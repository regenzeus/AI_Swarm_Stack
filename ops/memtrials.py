#!/usr/bin/env python3
"""The memory stack's trials with answer keys (docs/MEMORY-STACK.md, MEM-47). Structural changes of the memory agent (splits,
archives, moves out of long-term memory, skill publishes) run only while the last results pass (gate()).

  coverage     eval/trials/memstack.yaml: a fixture vault and tasks; each case names what its opening must give, what must be
               a pointer and what it must never give (another agent's journal, a private wiki). No model, no network.
  continuity   the live stack: every mission with a journal entry and a wiki gets its opening built for its own title; it must
               hold the mission's working state or last entry and a page of its own wiki. Passes at PASS_CONTINUITY.
  recall       the live long-term memory, in its own bank (trial-memstack, never the owner's): facts are retained, one is corrected
               later; a recall of each must find the planted fact, and the corrected one's newer text.
  exam         the coding exam's arms stack and stack+notes (ops/replay.py) are run by hand; their result is kept with these.

  python3 ops/memtrials.py coverage | continuity | recall | all | gate
Results: /srv/ai/missions/memory/trials.json (each trial's last 10 runs)."""
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "eval/trials/memstack.yaml"
DIR = Path(os.environ.get("MEMSTACK_DIR", "/srv/ai/missions/memory"))
RESULTS = DIR / "trials.json"
PASS_CONTINUITY = 0.8          # share of missions whose opening holds their own state and wiki
# limit: waits, a trial result older than this keeps the memory agent's structural changes waiting until the trials run again
MAX_AGE_DAYS = 14
BANK = "trial-memstack"


def now_iso():
    import datetime as dt
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def load():
    try:
        return json.loads(RESULTS.read_text())
    except (OSError, ValueError):
        return {}


def keep(name, res):
    DIR.mkdir(parents=True, exist_ok=True)
    d = load()
    d[name] = (d.get(name) or [])[-9:] + [{"at": now_iso(), "t": time.time(), **res}]  # cap: rotate (a trial's last 10 results)
    RESULTS.write_text(json.dumps(d, indent=1, ensure_ascii=False))
    return res


# ---------- coverage: the fill and the access rules on a fixture (no model, no network) ----------
def local_search(vault):
    """A stand-in for qmd over the fixture vault: pages ranked by how many of the query's words they hold."""
    import memstack as MS

    def search(query, n=30, mode="search"):
        q = MS.words(query)
        hits = []
        for p in sorted(vault.rglob("*.md")):
            rel = p.relative_to(vault).as_posix()
            text = p.read_text()
            s = len(q & MS.words(text))
            if s:
                hits.append((-s, rel, text))
        hits.sort()
        return [{"path": rel, "title": Path(rel).stem, "snippet": text[:300], "rank": i, "qmd": rel.split("/")[0]}  # cap: parse (a snippet for ranking)
                for i, (_, rel, text) in enumerate(hits[:n])]  # cap: top (a search's hits)
    return search


def build_fixture(fx, vault):
    import yaml
    for f in fx.get("files") or []:
        p = vault / f["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        meta = f.get("meta")
        p.write_text((f"---\n{yaml.safe_dump(meta, sort_keys=False)}---\n" if meta else "") + f["text"])


def coverage(fixture=FIXTURE):
    import yaml
    import memstack as MS
    fx = yaml.safe_load(Path(fixture).read_text())
    tmp = Path(tempfile.mkdtemp(prefix="memtrial-"))
    old = (MS.VAULT, MS.qmd_search, MS.DIR, MS.private_roots, MS.settings)
    conf = MS.settings()
    import journal as J
    jv = J.VAULT                                     # restored in finally: an error left it on the removed folder (review SWM-R17)
    try:
        build_fixture(fx, tmp)
        MS.VAULT, MS.DIR = tmp, tmp / "_state"
        MS.qmd_search = local_search(tmp)
        MS.private_roots = lambda: set(fx.get("private") or [])
        MS.settings = lambda: {**conf, **(fx.get("settings") or {})}
        J.VAULT = tmp
        cases, failed = [], []
        for c in fx["cases"]:
            text = MS.opening(c["agent"], kind=c.get("kind", "task"), task=c["task"], subs=c["subs"], budget=c.get("budget"), own=c.get("own"), tools=False)
            given = set(re.findall(r"\((vault:[^ ,)]+)", text))
            pointed = set(re.findall(r"^- (vault:[^:]+\.md[^:]*):", text, re.M))
            miss = [r for r in c.get("given") or [] if r not in given]
            nopoint = [r for r in c.get("pointer") or [] if r not in pointed and r not in given]
            leaked = [r for r in c.get("never") or [] if r in given or r in pointed]
            ok = not miss and not nopoint and not leaked
            cases.append({"id": c["id"], "ok": ok, "missing": miss, "not_pointed": nopoint, "leaked": leaked})
            if not ok:
                failed.append(c["id"])
    finally:
        J.VAULT = jv
        MS.VAULT, MS.qmd_search, MS.DIR, MS.private_roots, MS.settings = old
        shutil.rmtree(tmp, ignore_errors=True)
    return keep("coverage", {"passed": not failed, "cases": len(cases), "failed": failed, "detail": cases})


# ---------- continuity: the live missions ----------
GIVEN = re.compile(r"^#### .*\(((?:vault|agent|code|world|owner|howto|swarm|lesson)[^\s,)]*)", re.M)


def given_refs(text):
    """The refs an opening gave whole (its #### items), never those it only names as not given or offers."""
    return set(GIVEN.findall(text or ""))


def continuity(missions=None, build=None):
    """Each mission's opening for its own title holds its state or last journal entry and a page of its own wiki: given,
    not only named in the list of what did not fit, and a page, not the wiki's index (review MEM-R19)."""
    import memstack as MS
    import journal as J
    if missions is None:
        import missions as MI
        missions = [m for m in MI.load_missions().values() if m.get("status") != "archived"]
        import mission_extras as X
        root = X.wiki_root
    else:
        root = lambda m: m["wiki"]
    build = build or (lambda m: MS.opening(f"mission:{m['slug']}", kind="mission", task=m["title"], card="desk" if m.get("type") == "briefing" else "mission",
                                           own=root(m), tools=False))
    rows = []
    for m in missions:
        jid = f"mission-{m['slug']}"
        doc = J.load(f"mission:{m['slug']}")
        wiki = root(m)
        if not doc["entries"] and not doc.get("state") or not (MS.VAULT / wiki).is_dir():
            continue
        given = given_refs(build(m))
        has_state = any(r.startswith(f"vault:agents/{jid}/MEMORY.md") for r in given)     # its state, or a run's entry (#…)
        has_wiki = any(r.startswith(f"vault:{wiki}/") and not r.endswith("/index.md") for r in given)
        rows.append({"mission": m["slug"], "state": has_state, "wiki": has_wiki})
    share = sum(1 for r in rows if r["state"] and r["wiki"]) / len(rows) if rows else 0.0
    return keep("continuity", {"passed": bool(rows) and share >= PASS_CONTINUITY, "missions": len(rows), "share": round(share, 3), "detail": rows})


# ---------- recall: the live long-term memory, in its own bank ----------
# Planted in the trial's own bank, never the owner's. They name the owner because the retain mission keeps only facts about
# him: the trial goes through the same gatekeeper as a chat. None of them is true.
RECALL_FACTS = [
    {"t": "2026-01-10T10:00:00Z", "text": "In a chat the owner said he prefers tea to coffee in the morning."},
    {"t": "2026-01-11T10:00:00Z", "text": "The owner said his bike is a green gravel bike he bought in 2025."},
    {"t": "2026-01-12T10:00:00Z", "text": "The owner said he works from home on Fridays."},
    {"t": "2026-03-01T10:00:00Z", "text": "The owner said he now works from home on Mondays instead of Fridays."},
]
RECALL_ASK = [("What does the owner drink in the morning?", "tea"), ("What bike does the owner have?", "gravel"),
              ("Which day does the owner work from home?", "monday")]


def trial_post(path, body, timeout=180, method="POST"):
    """A call to Hindsight's trial bank (through Hermes' container: Hindsight is only on memnet). Never the owner's bank."""
    import subprocess
    code = ("import json,sys,urllib.request as u\n"
            "d=None if sys.argv[2]=='null' else sys.argv[2].encode()\n"
            "r=u.Request('http://hindsight:8888/v1/default/banks/" + BANK + "/'+sys.argv[1], data=d, method=sys.argv[4], headers={'Content-Type':'application/json'})\n"
            "print(u.urlopen(r,timeout=int(sys.argv[3])).read().decode() or '{}')")
    p = subprocess.run(["docker", "exec", "aistack-hermes-1", "/opt/hermes/.venv/bin/python", "-c", code, path, json.dumps(body), str(timeout), method],
                       capture_output=True, text=True, timeout=timeout + 30)
    return json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else None


def recall(post=None, wait=300):
    """Retains the planted facts into the trial bank, waits for Hindsight to process them, and asks."""
    if post is None:
        trial_post("memories", None, method="DELETE")    # the trial bank starts empty each time: its facts never pile up
    post = post or trial_post
    post("memories", {"items": [{"content": f["text"], "timestamp": f["t"], "context": "memory stack trial"} for f in RECALL_FACTS], "async": False})
    t0, rows = time.time(), []
    while time.time() - t0 < wait:
        rows = []
        for q, want in RECALL_ASK:
            r = post("memories/recall", {"query": q, "budget": "mid", "max_tokens": 400}) or {}
            texts = " ".join(str(x.get("text") or "") for x in (r.get("results") or [])[:3]).lower()  # cap: top (the recall's best three)
            rows.append({"q": q, "want": want, "ok": want in texts})
        if all(r["ok"] for r in rows):
            break
        time.sleep(20)
    return keep("recall", {"passed": all(r["ok"] for r in rows), "detail": rows})


# ---------- the gate ----------
def gate(now=None):
    """-> (open, why). Open when coverage passed and continuity passed in their last runs within MAX_AGE_DAYS; recall, when run,
    must have passed too."""
    now = now or time.time()
    d = load()
    need = ["coverage", "continuity"] + (["recall"] if d.get("recall") else [])
    for n in need:
        runs = d.get(n) or []
        if not runs:
            return False, f"the {n} trial has not run yet"
        last = runs[-1]
        if now - float(last.get("t") or 0) > MAX_AGE_DAYS * 86400:
            return False, f"the {n} trial last ran more than {MAX_AGE_DAYS} days ago"
        if not last.get("passed"):
            return False, f"the {n} trial failed on {last['at'][:10]}"
    return True, "the memory trials passed: " + ", ".join(f"{n} {d[n][-1]['at'][:10]}" for n in need)


def main(argv):
    sys.path.insert(0, str(ROOT / "ops"))
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd in ("coverage", "continuity", "recall"):
        r = globals()[cmd]()
        print(json.dumps(r, indent=1))
        return 0 if r["passed"] else 1
    if cmd == "all":
        rs = [coverage(), continuity(), recall()]
        print(json.dumps(rs, indent=1))
        return 0 if all(r["passed"] for r in rs) else 1
    if cmd == "gate":
        print(gate())
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

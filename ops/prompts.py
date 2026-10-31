"""Agent prompts as files (MEM-11, DEC-33): one file per agent, prompts/<owner>.md, named by its card (the card's
`prompts` field), by a service of config/agents.yaml (journal, wikis, eval) or `shared` for the templates several
cards use. Each prompt is a section of its file, used verbatim ({name} is a fill, {{ }} a literal brace).

text(owner, name)    the prompt as a Prompt: a str that keeps its ref "owner/NAME@sha" through .format()
version(owner)       the file's sha, in each run's manifest (registry.hash_of includes it in the card hash)
record(prompt)       puts the ref of a prompt about to be sent into the current run's record
case(prompt, out)    keeps a direct model call's fills and answer as a replay case (CASES, the last KEEP per prompt)
check()              the build gate (ops/check.sh): every prompt's sha has its baseline or a passed replay in REPLAYS
replay(owner, name)  replays the cases with the last approved text and the changed one on the agent's model, a judge
                     compares each pair, and the result is recorded; it passes when the new text is valid as often and
                     the judge prefers the old answer no more often than the new one
  python3 ops/prompts.py check | list | render <owner> <name> [fill=value ...] | replay <owner> <name> | keep <cases.jsonl>
The desk's and the research scout's containers read prompts/ through a read-only mount (MEM-13) with the same section
format; they log each version, and the desk hands its calls back as cases (/out/prompt-cases.jsonl, an alert's JSON).
"""
import datetime as dt
import hashlib
import json
import os
import random
import re
import string
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "prompts"
REPLAYS = DIR / "replays.json"
FIXTURES = DIR / "cases"                       # committed cases for a prompt no live run has used yet
CASES = Path(os.environ.get("PROMPT_CASES", "/srv/ai/state/prompt-cases"))
KEEP = 12                                      # live cases kept per prompt (the newest)  # cap: store
REPLAY_CASES = 6                               # cases one replay uses  # cap: list
MIN_CASES = 3                                  # fewer, and one judgement decides: a coin toss for a small wording change
FILL_CHARS = 20000                             # one fill or answer kept in a case  # cap: store
SECTION = re.compile(r"^<!-- prompt: ([A-Z][A-Z0-9_]*)\b([^\n]*)-->\n(.*?)\n<!-- end -->$", re.M | re.S)
META = re.compile(r"\b(I can't|I cannot|I can’t|as an AI|please provide)\b", re.I)
_cache = {}


class Prompt(str):
    """A prompt's text that knows where it came from; .format() keeps the ref and remembers the fills."""
    ref = ""
    fills = None

    def format(self, *a, **k):
        p = Prompt(str.format(self, *a, **k))
        p.ref, p.fills = self.ref, k
        return p


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()[:12]  # cap: id


def parse(text):
    """{NAME: text} of one prompt file."""
    return {m.group(1): m.group(3) for m in SECTION.finditer(text)}


def raw(owner, name):
    """True for a prompt sent as written (a SOUL text, or one whose braces are literal JSON): it is never filled."""
    m = next((m for m in SECTION.finditer((DIR / f"{owner}.md").read_text()) if m.group(1) == name), None)
    return bool(m and "· raw:" in m.group(2))


def sections(owner, root=None):
    f = (root or DIR) / f"{owner}.md"
    key = (str(f), f.stat().st_mtime)
    if key not in _cache:
        _cache[key] = parse(f.read_text())
    return _cache[key]


def text(owner, name):
    t = sections(owner)[name]
    p = Prompt(t)
    p.ref = f"{owner}/{name}@{sha(t)}"
    return p


def version(owner):
    f = DIR / f"{owner}.md"
    return sha(f.read_text()) if f.exists() else None


def owners():
    return sorted(f.stem for f in DIR.glob("*.md") if f.stem != "AGENTS")


def fills_of(t):
    return sorted({n for _, n, _, _ in string.Formatter().parse(t) if n})


def fill(owner, name, t, fills):
    return t if raw(owner, name) else t.format(**fills)


# ---------- what a run records ----------
def record(prompt):
    """The prompt's ref in the current run's record (MEM-11: every run records the version it used)."""
    ref = getattr(prompt, "ref", "")
    if ref:
        try:
            import runtime as RTM
            RTM.stage("Prompt", ref)
        except Exception:
            pass
    return ref


def case(prompt, out, model=None):
    """A direct model call's fills and answer, kept as a replay case for its prompt (owner-only file, newest KEEP)."""
    ref, fills = getattr(prompt, "ref", ""), getattr(prompt, "fills", None)
    if ref and fills is not None:
        add_case(ref, fills, out, model=model)


def add_case(ref, fills, out, at=None, model=None):
    """Keep one case (also one a container handed over: the desk's, ops/desk.sh `keep`); the same call is kept once."""
    if not ref or not str(out or "").strip():
        return
    try:
        owner, name = ref.split("@")[0].split("/")
        CASES.mkdir(parents=True, exist_ok=True)
        f = CASES / f"{owner}.{name}.jsonl"
        rows = f.read_text().splitlines() if f.exists() else []
        at = at or time.time()
        if any(json.loads(r).get("at") == at and json.loads(r).get("ref") == ref for r in rows if r.strip()):
            return
        rows.append(json.dumps({"at": at, "ref": ref, "model": model, "fills": {k: str(v)[:FILL_CHARS] for k, v in fills.items()},  # cap: store
                                "out": str(out)[:FILL_CHARS]}, ensure_ascii=False))  # cap: store
        f.write_text("\n".join(rows[-KEEP:]) + "\n")
        os.chmod(f, 0o600)
    except Exception:
        pass                                         # a case is a help for later, never a reason to fail the run


# ---------- the build gate ----------
def load_replays(root=None):
    f = (root or ROOT) / "prompts" / "replays.json"
    return json.loads(f.read_text()) if f.exists() else {}


def check(root=None):
    """Problems: a prompt whose current text has no baseline (its first record only) and no passed replay."""
    base = (root or ROOT) / "prompts"
    rec, out = load_replays(root), []
    for f in sorted(base.glob("*.md")):
        if f.stem == "AGENTS":
            continue
        secs = parse(f.read_text())
        if not secs:
            out.append(f"prompts/{f.name}: no <!-- prompt: NAME --> sections")
        for name, t in secs.items():
            key, s = f"{f.stem}/{name}", sha(t)
            rs = rec.get(key) or []
            ok = any(r.get("sha") == s and (r.get("passed") or (r.get("baseline") and i == 0)) for i, r in enumerate(rs))
            if not ok:
                out.append(f"{key}: its text ({s}) changed without a passed replay: run python3 ops/prompts.py replay {f.stem} {name}")
    for key in rec:
        owner, name = key.split("/")
        if not (base / f"{owner}.md").exists() or name not in parse((base / f"{owner}.md").read_text()):
            out.append(f"prompts/replays.json: {key} has no prompt any more")
    return out


# ---------- replay ----------
def approved(owner, name, rec):
    """The last approved text of a prompt (baseline or passed replay), from the git history of its file."""
    good = {r["sha"] for r in rec.get(f"{owner}/{name}") or [] if r.get("passed") or r.get("baseline")}
    revs = subprocess.run(["git", "log", "--format=%H", "--", f"prompts/{owner}.md"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    for c in revs:
        old = subprocess.run(["git", "show", f"{c}:prompts/{owner}.md"], cwd=ROOT, capture_output=True, text=True).stdout
        t = parse(old).get(name)
        if t is not None and sha(t) in good:
            return t
    return None


def cases_of(owner, name):
    rows = []
    f = CASES / f"{owner}.{name}.jsonl"
    if f.exists():
        rows += [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
    fx = FIXTURES / f"{owner}.{name}.json"
    if fx.exists():
        rows += json.loads(fx.read_text())
    return rows[-REPLAY_CASES:]


def model_of(owner):
    import registry as REG
    card = next((c for c in REG.load().get("agents") or [] if c.get("id") == owner), None)
    m = (card or {}).get("model")
    return m if m and m != "none" else "gpt-sub-fast"   # a service or shared template: the fast model


def valid(answer, wants_json):
    if not str(answer or "").strip() or META.search(str(answer)[:400]):  # cap: parse
        return False
    if wants_json:
        m = re.search(r"\{.*\}", str(answer), re.S)
        try:
            return isinstance(json.loads(m.group(0)), dict) if m else False
        except ValueError:
            return False
    return True


def replay(owner, name, ask=None, judge_ask=None, now=None):
    """Replay a changed prompt on its cases and record the result in prompts/replays.json; returns the record."""
    import evals as E
    rec = load_replays()
    new = sections(owner)[name]
    old = approved(owner, name, rec)
    if old is None:
        raise SystemExit(f"{owner}/{name} has no approved text to compare with")
    cases = cases_of(owner, name)
    if len(cases) < MIN_CASES:
        raise SystemExit(f"{owner}/{name}: {len(cases) or 'no'} case{'' if len(cases) == 1 else 's'} to replay, it needs {MIN_CASES}; live runs record "
                         f"them ({CASES}), or add prompts/cases/{owner}.{name}.json")
    need = set() if raw(owner, name) else set(fills_of(new)) - set(cases[0]["fills"])
    if need:
        raise SystemExit(f"{owner}/{name}: the new text needs fills the cases lack: {', '.join(sorted(need))}")
    card = {"id": owner, "model": cases[-1].get("model") or model_of(owner)}      # the model the calls used, else the card's
    ask = ask or (lambda t: E.ask(card, t, ref=f"{owner}/{name}"))
    judge_ask = judge_ask or (lambda t: E.ask({"id": "eval", "model": "gpt-sub"}, t, ref=f"judge {owner}/{name}"))
    wants_json = "JSON" in new or "JSON" in old
    score = {"valid": [0, 0], "judge": {"new": 0, "old": 0, "equal": 0}, "cases": len(cases)}
    rnd = random.Random(sha(new))
    for c in cases:
        task = fill(owner, name, new, c["fills"])
        a_old, a_new = ask(fill(owner, name, old, c["fills"])), ask(task)
        score["valid"][0] += valid(a_old, wants_json)
        score["valid"][1] += valid(a_new, wants_json)
        flip = rnd.random() < 0.5
        first, second = (a_new, a_old) if flip else (a_old, a_new)
        v = re.search(r"\{.*\}", str(judge_ask(text("eval", "JUDGE").format(task=task[:12000], a=str(first)[:8000],  # cap: prompt
                                                                               b=str(second)[:8000]))), re.S)  # cap: prompt
        try:
            better = json.loads(v.group(0)).get("better") if v else "equal"
        except ValueError:
            better = "equal"
        if better in ("A", "B"):
            score["judge"]["new" if (better == "A") == flip else "old"] += 1
        else:
            score["judge"]["equal"] += 1
    passed = score["valid"][1] >= score["valid"][0] and score["judge"]["old"] <= score["judge"]["new"]
    r = {"sha": sha(new), "from": sha(old), "at": dt.date.fromtimestamp(now or time.time()).isoformat(), "model": card["model"],
         **score, "passed": passed}
    rec.setdefault(f"{owner}/{name}", []).append(r)
    REPLAYS.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n")
    return r


def main(argv):
    sys.path.insert(0, str(Path(__file__).parent))
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "check":
        bad = check()
        n = sum(len(parse((DIR / f"{o}.md").read_text())) for o in owners())
        print(f"   {n} prompts in {len(owners())} files, {len(bad)} problems")
        for b in bad:
            print("  ", b)
        return 1 if bad else 0
    if cmd == "list":
        for o in owners():
            for name, t in sections(o).items():
                print(f"{o}/{name}@{sha(t)}  " + ("raw" if raw(o, name) else f"fills: {', '.join(fills_of(t)) or '-'}"))
        return 0
    if cmd == "render":
        fills = dict(a.split("=", 1) for a in argv[4:])
        sys.stdout.write(fill(argv[2], argv[3], text(argv[2], argv[3]), fills))
        return 0
    if cmd == "keep":                                # ops/desk.sh: the cases a desk run wrote to its /out
        f = Path(argv[2])
        rows = [json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.exists() else []
        for r in rows:
            add_case(r.get("ref"), r.get("fills") or {}, r.get("out"), at=r.get("at"), model=r.get("model"))
        print(f"   {len(rows)} prompt case{'' if len(rows) == 1 else 's'} kept from {f}")
        return 0
    if cmd == "replay":
        r = replay(argv[2], argv[3])
        print(json.dumps(r))
        return 0 if r["passed"] else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

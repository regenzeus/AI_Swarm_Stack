"""Wikis: a short summary for every wiki, and deleting a mission's or topic's wiki.

summaries  every 30 min the runner looks at every wiki (the vault wiki, topic and mission wikis); one whose pages changed
           gets a fresh 2-3 sentence summary from one small model call (at most 3 per pass, at most every 6 hours per
           wiki; a wiki without a summary gets one at once). Kept in public/wiki-summaries.json for the app.
delete     wiki_delete (from the app only, never from the AI phone or an MCP tool) removes a mission's or topic's wiki
           from the vault in one git commit, so it can be restored from the vault history. The mission keeps running
           but stops compiling a wiki (wiki_off in MISSION.md). The vault wiki itself cannot be deleted.
"""
import json
import textcap as TC                              # visible caps (AGENTS.md, truncation)
import os
import re
import subprocess
import threading
import time
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md

M = None                                         # ops/missions.py (set by missions.main)
ACTIONS = {"wiki_delete"}
ROOT = re.compile(r"^(missions|topics|repos)/[A-Za-z0-9][A-Za-z0-9._-]{0,99}/wiki$")
EVERY = 6 * 3600                                 # a changed wiki is summarised again at most this often
PER_PASS = 3
V = 2                                            # summaries written by an older version are written again
META = re.compile(r"\b(I'll|I will|I can't|I cannot|I can’t|I’ll|please provide|let me|I need)\b", re.I)   # the model talked about the task

SUMMARY = P.text("wikis", "SUMMARY")


def store():
    return M.PUBLIC / "wiki-summaries.json"


def load():
    try:
        return json.loads(store().read_text())
    except Exception:
        return {}


def save(d):
    tmp = store().with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    tmp.replace(store())


def roots():
    """[(root, title)] of every wiki that exists in the vault."""
    out = [("wiki", "Vault wiki")]
    for m in M.load_missions().values():
        r = M.X.wiki_root(m)
        if not m.get("wiki_off") and (M.VAULT / r).is_dir() and r not in {x for x, _ in out}:
            out.append((r, m["title"]))
    for d in sorted((M.VAULT / "repos").glob("*/wiki")) if (M.VAULT / "repos").is_dir() else ():   # CHG-08: one wiki per repository
        out.append((str(d.relative_to(M.VAULT)), f"{d.parent.name} (repository)"))
    try:                                         # a briefing task's topic without a mission of its own (TSK-22)
        c = M.db()
        for row in c.execute("select title, spec from tasks where door='plan' and status <> 'cancelled' and json_extract(spec, '$.topic') is not null"):
            r = f"topics/{json.loads(row['spec'])['topic']}/wiki"
            if (M.VAULT / r).is_dir() and r not in {x for x, _ in out}:
                out.append((r, row["title"]))
        c.close()
    except Exception as e:                       # the missions' wikis are listed all the same; logged
        M.log(f"wikis: the tasks' topics not read: {type(e).__name__}: {e}")
    return out


def pages_of(root):
    """[(title, one line about it)] of a wiki's pages, and its change signature. The line is the page's front-matter
    summary, or the start of its text (the curator's vault wiki pages have no summary field)."""
    files = [f for f in sorted((M.VAULT / root).rglob("*.md")) if f.name != "index.md"]
    out = []
    for f in files:
        try:
            meta, body = M.split_front(f.read_text(errors="replace"))
            meta = meta if isinstance(meta, dict) else {}
        except Exception as e:  # one unreadable page must not stop the summary of its wiki
            M.log(f"wiki page {f} skipped: {e}")
            continue
        line = str(meta.get("summary") or "").strip()
        if not line:
            text = " ".join(x.strip() for x in body.splitlines() if x.strip() and not x.lstrip().startswith(("#", "---", "|")))
            line = TC.cut(re.sub(r"\[\[([^\]|]+\|)?([^\]]+)\]\]", r"\2", text), 220)  # cap: prompt
        out.append((str(meta.get("title") or f.stem.replace("-", " ")), line))
    sig = f"{len(files)}:{int(max((f.stat().st_mtime for f in files), default=0))}"
    return out, sig


def summarize(root, title):
    pages, sig = pages_of(root)
    if not pages:
        return None, sig
    lines = TC.cut("\n".join(f"- {t}: {s}" if s else f"- {t}" for t, s in pages), 7000)  # cap: prompt
    text = M.ask_text(SUMMARY.format(title=title, n=len(pages), pages=lines), os.environ["VK_WIKIS"], model="gpt-sub-fast", timeout=180)
    text = re.sub(r"\s+", " ", re.sub(r"[*_#`>]", "", text)).strip()
    if META.search(text) or len(text) < 40:
        raise ValueError(f"not a summary: {text}")
    return TC.cut(text, 700), sig  # cap: untrusted


def sweep(now=None):
    """One pass: summarise wikis that have none, or whose pages changed (at most every 6 h). Returns the roots done."""
    now = now or time.time()
    d, done = load(), []
    live = roots()
    for root, title in live:
        # limit: paces, wiki summaries a pass; the rest the next pass
        if len(done) >= PER_PASS:
            break
        try:
            _, sig = pages_of(root)
        except Exception as e:
            M.log(f"wiki summary {root} failed: {e}")
            continue
        cur = d.get(root) or {}
        if cur.get("v") == V and (cur.get("sig") == sig or now - cur.get("at", 0) < EVERY):
            continue
        try:
            text, sig = summarize(root, title)
        except Exception as e:
            M.log(f"wiki summary {root} failed: {e}")
            continue
        if text:
            d[root] = {"summary": text, "sig": sig, "at": now, "pages": len(pages_of(root)[0]), "v": V}
            done.append(root)
    for gone in set(d) - {r for r, _ in live}:
        d.pop(gone)
    save(d)
    return done


def worker():
    M.stop.wait(120)
    while not M.stop.is_set():
        try:
            done = sweep()
            if done:
                M.log(f"wiki summaries written: {', '.join(done)}")
        except Exception as e:
            M.log(f"wiki summaries failed: {e}")
        try:                                     # MEM-03: every wiki is in the Ledger, owned by its one writer
            import swarm_client as SW
            for root, title in roots():
                SW.wiki_artifact(root, title)
        except Exception as e:
            M.log(f"wikis in the Ledger: {type(e).__name__}: {e}")
        M.stop.wait(1800)


def handle(req):
    root = str(req.get("root", "")).strip().strip("/")
    if root == "wiki":
        raise ValueError("the vault wiki is the core of your knowledge and cannot be deleted here")
    if not ROOT.match(root):
        raise ValueError("only a mission's or topic's wiki can be deleted")
    d = M.VAULT / root
    if not d.is_dir():
        raise ValueError("no such wiki")
    n = len([f for f in d.rglob("*.md") if f.name != "index.md"])
    owner = next((m for m in M.load_missions().values() if M.X.wiki_root(m) == root), None)
    git = lambda *a: subprocess.run(["git", *a], cwd=M.VAULT, capture_output=True, text=True, timeout=60)
    git("add", "--", root)                            # everything in history first: nothing is lost for good
    git("commit", "-qm", f"wiki: {root} before deleting it", "-m", M.J.CO)
    git("rm", "-rq", "--", root)
    if d.exists():                                    # only ignored or empty leftovers remain
        subprocess.run(["rm", "-rf", "--", str(d)], timeout=60)
    paths = []
    if owner:
        owner["wiki_off"] = True                      # it keeps running, but no new wiki grows back
        M.save_mission(owner)
        paths.append(f"missions/{owner['slug']}")
    M.vault_commit(paths, f"wiki: delete {root} ({n} pages; restorable from this commit's parent)")
    head = git("rev-parse", "--short", "HEAD").stdout.strip()
    s = load()
    s.pop(root, None)
    save(s)
    threading.Thread(target=M.reindex, daemon=True).start()
    title = owner["title"] if owner else root
    M.event("wiki", owner["slug"] if owner else "", f"Wiki deleted ({n} pages); restorable from vault commit {head}", title=title)
    return {"deleted": root, "pages": n, "commit": head,
            "detail": f"Deleted {n} pages. The agent keeps running but no longer builds a wiki. Restorable from vault commit {head}."}

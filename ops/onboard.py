#!/usr/bin/env python3
"""Onboarding a repository (BLD-26): one job that always ends in the whole package, or says plainly why it did not.

The button on a repo page, Add a repository, Hermes' understand_repo and `make understand` all start this one job:
  1 clone     the code in ~/code/<name> (never run: hooks off)
  2 graph     its code graph (ops/graphify-sync.sh; offline, no model)
  3 facts     where it breaks, what changes together, who knows it, how healthy it is (ops/repofacts.py; sealed, no model)
  4 map       its code map as fixed steps (ops/ua_map_in.py in a throwaway container that sees only this repo: the plugin's
              scan, batches and tree-sitter structure, then nodes and edges; no model, no agent that could take a shortcut)
  5 explain   every file and function explained from the code (ops/ua_enrich.py, one batch per model call), the viewer's corrections saved
  6 search    a readable digest in the search index, so Hermes can answer about the code (ops/ua_digest.py, qmd)
  7 analysis  a written analysis by Claude Code, read-only: what it is, how the stack could use it, risks, a verdict
  8 wiki      the repository's wiki, seeded from all of that (ops/repowiki.py, CHG-08): what every code agent starts from

Nothing about a repository's size stops it. What it cannot do now it waits for and then does by itself: a usage limit,
the PC's memory, the gateway being away, another repository's turn. Each step's progress is saved in
/srv/ai/state/onboard/<name>.json, which the repo page and repos_overview read, so a crash, a deploy or a restart of the
PC loses nothing: the runner's watchdog (tick) starts the job again and it goes on at the first unfinished step. A step
that fails is tried ATTEMPTS times; then the job stops with the reason and a Try again that goes on from there. The
owner gets one message when it ends, either way, and one when it has to wait for a usage limit or waits long for anything.

Every step has a quality gate and a record (DEC-48): what it made in numbers, when it last ran, how long, which model, how
many calls and tokens. A step whose result is hollow (a map without edges, files left unexplained, an analysis whose
file:line claims do not resolve) is weak, shown as weak, never as done; the repo page's checklist shows all of it, and
each step can run again on its own. Third-party code is data: it is never built, installed or run, and text in it cannot steer anything but its own map. Third-party
programs do run on it, sealed: CodeLore and repowise (images/repointel), no network, no secrets, on a throwaway copy, never the clone.

  python3 ops/onboard.py run <https url | name>     the job itself, in the foreground (make understand; needs VK_CODE)
  python3 ops/onboard.py start <https url | name>   start or resume it in its own systemd unit
  python3 ops/onboard.py all                        start every repository whose package is not complete
"""
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md
import textcap as TC                              # visible caps (AGENTS.md, truncation)
import deployment as DEPLOY                        # this deployment's hosts and paths (deployments/<name>/deployment.env)
import repofacts as RF                             # a repository's facts (BLD-27)
import runtime as RTM                              # each step is a run in the record (DEC-48)

STACK = Path(__file__).resolve().parent.parent
CODE = Path(os.environ.get("ONBOARD_CODE", DEPLOY.CODE_DIR))
STATE = Path(os.environ.get("ONBOARD_STATE", "/srv/ai/state/onboard"))
DOCS = Path(os.environ.get("ONBOARD_DOCS", "/srv/ai/code-docs"))
LOGS = Path(os.environ.get("ONBOARD_LOGS", "/srv/ai/state"))
GRAPHS = Path(os.environ.get("ONBOARD_GRAPHS", "/srv/ai/state/graphify"))
MISSIONS = Path(os.environ.get("MISSIONS_HOME", "/srv/ai/missions"))
VAULT = Path(os.environ.get("ONBOARD_VAULT", "/srv/vault"))
LITELLM = os.environ.get("LITELLM_URL", "http://127.0.0.1:4000/v1/chat/completions")
APP = DEPLOY.MC_URL
IMAGE = "aistack/opencode:1.19.4-ua1"
QMD = "aistack-qmd-1"

STEPS = (("clone", "Copy of the code"), ("graph", "Code graph"), ("facts", "Facts from its history"), ("map", "Code map"), ("explain", "Every file explained"),
         ("search", "Search index"), ("analysis", "Written analysis"), ("wiki", "The repository's wiki"), ("card", "Card for coding agents"))
TITLE = dict(STEPS)
ACTIVE = ("queued", "running", "waiting")
ATTEMPTS = 3            # limit: stops, a step that failed this often names its reason and waits for the owner's Try again (BLD-26)
RESTARTS = 5            # limit: stops, a job that died this often without finishing a step says so instead of looping (BLD-26)
BACKOFF = (60, 300)     # s before a failed step's second and third try
POLL = 15 * 60          # s between looks while waiting for a usage limit or the gateway
LONG_WAIT = 30 * 60     # s of waiting (for memory, say) before the owner hears why it takes so long
NEED_GB = 1.0           # limit: waits, the PC's available memory before the code map's container starts (= conductor NEED_GB opencode)
MAP_TIMEOUT = 4 * 3600  # limit: stops, one code map run that hangs (717 files take 30 s without a model): counts as a failed try
ENRICH_TIMEOUT = 4 * 3600   # limit: stops, one explanation pass that hangs: counts as a failed try
CLONE_TIMEOUT = 30 * 60     # limit: stops, one clone that hangs: counts as a failed try
QMD_TIMEOUT = 30 * 60       # limit: stops, one search index update that hangs: counts as a failed try
GRAPH_WAIT = 15 * 60        # limit: stops, the code graph tool not done by then: counts as a failed try
SEEN_WAIT = 5 * 60          # limit: stops, the runner not taking the Claude request by then: counts as a failed try
URL = re.compile(r"https://(?P<host>[A-Za-z0-9.-]+)(?::\d+)?/(?:[\w.-]+/)*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*?)(?:\.git)?/?")
LOCAL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
INTERNAL = re.compile(r"^(localhost|\d+\.\d+\.\d+\.\d+|.*\.(local|lan|internal|localhost|test|ts\.net))$", re.I)


class Wait(Exception):
    """Not now, and not a failure: no try is used. The step runs again after `seconds`."""

    def __init__(self, note, seconds=POLL, idle=True, tell=False):
        super().__init__(note)
        self.note, self.seconds, self.idle, self.tell = note, seconds, idle, tell


class Stop(Exception):
    """A failure no retry can mend: the job stops at once with this reason."""


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def working(st, sid, note):
    """A wait is over and the work itself starts: the page says so, not what it waited for."""
    st["steps"][sid].update(status="running", note=note)
    st["status"] = "running"
    st.pop("waiting_since", None)
    save(st)


def pause(seconds):
    time.sleep(seconds)


def env():
    return {**os.environ, "DOCKER_HOST": os.environ.get("DOCKER_HOST", DEPLOY.DOCKER_SOCKET), "GIT_TERMINAL_PROMPT": "0"}


def sh(*cmd, timeout=600, check=True, input=None):
    """A command's output; a failure raises with its last lines."""
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env(), input=input)
    if check and p.returncode:
        raise RuntimeError(TC.tail((p.stderr or p.stdout or f"exit {p.returncode}").strip(), 1500))  # cap: store
    return p


# ---------- which repository ----------
def parse(arg):
    """(name, url or None) of a https git URL on a public host, or the name of a repository in ~/code."""
    arg = str(arg or "").strip()
    m = URL.fullmatch(arg)
    if m:
        if INTERNAL.match(m["host"]):
            raise ValueError(f"{m['host']} is not a public address: only public https repositories can be studied")
        return m["name"], arg
    if LOCAL_NAME.fullmatch(arg) and (CODE / arg / ".git").exists():
        return arg, None
    known = load(arg) if LOCAL_NAME.fullmatch(arg) else None
    if known and known.get("url"):                     # its job was started with an address and has not copied it yet
        return arg, known["url"]
    if arg.startswith("http"):
        raise ValueError(f"{arg} is not an https git URL like https://github.com/owner/name")
    raise ValueError("give an https git URL (like https://github.com/owner/name) or the name of a repository in ~/code")


def same_repo(a, b):
    norm = lambda u: re.sub(r"\.git/?$", "", re.sub(r"//[^/@]+@", "//", str(u or ""))).rstrip("/").lower()
    return norm(a) == norm(b)


def origin(name):
    return sh("git", "-C", str(CODE / name), "remote", "get-url", "origin", check=False).stdout.strip()


# ---------- the job's record ----------
def path(name):
    return STATE / f"{name}.json"


def load(name):
    try:
        return json.loads(path(name).read_text())
    except (OSError, ValueError):
        return None


def save(st):
    st["updated"] = now()
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = path(st["repo"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False))
    tmp.replace(path(st["repo"]))


def kg_of(name):
    return CODE / name / ".ua" / "knowledge-graph.json"


def valid_map(name):
    try:
        return bool(json.loads(kg_of(name).read_text()).get("nodes"))
    except (OSError, ValueError, AttributeError):
        return False


def map_report(name):
    try:
        return json.loads((kg_of(name).parent / "intermediate" / "map-report.json").read_text())
    except (OSError, ValueError):
        return {}


def map_quality(name):
    """DEC-48: the code map in numbers, and whether it is a map or a hollow list: nodes, edges, symbols. A repository
    whose scan found no code (web pages, documents) has no edges to expect."""
    try:
        g = json.loads(kg_of(name).read_text())
    except (OSError, ValueError):
        return {"ok": False, "text": "no code map", "n": {}}
    nodes, edges = g.get("nodes") or [], g.get("edges") or []
    symbols = sum(1 for n in nodes if "lineRange" in n)
    code = sum(1 for n in nodes if n.get("type") == "file")
    n = {"nodes": len(nodes), "edges": len(edges), "symbols": symbols, "code_files": code}
    if not nodes:
        return {"ok": False, "text": "hollow: an empty map", "n": n}
    if not edges and code:
        return {"ok": False, "text": f"hollow: {len(nodes):,} nodes and no edges between them", "n": n}
    return {"ok": True, "text": f"{len(nodes):,} nodes · {len(edges):,} edges · {symbols:,} symbols" + ("" if code else " · no code files, only documents"), "n": n}


def unexplained(name):
    """Files of the code map without an explanation: (how many, of how many, their paths)."""
    import ua_enrich as U
    try:
        g = json.loads(kg_of(name).read_text())
    except (OSError, ValueError):
        return 0, 0, []
    files = [n for n in g.get("nodes", []) if n.get("filePath") and "lineRange" not in n
             and n.get("type") not in ("function", "class", "method", "interface")]
    bad = [n["filePath"] for n in files if U.is_placeholder(n.get("summary"))]
    return len(bad), len(files), bad


def graphed(repo):
    """Its code graph, or the tool's word that it has no code to read (web pages, documents)."""
    return (repo / "graphify-out" / "graph.json").exists() or (repo / "graphify-out" / ".no-code").exists()


FILELINE = re.compile(r"\b([\w./-]+\.[A-Za-z]{1,6}):(\d+)\b")
MODEL_OF = {"explain": "gpt-sub-fast", "analysis": "claude-code", "wiki": "claude-code"}   # which model a step's work ran on (none: a program)
def claim_resolves(repo, path, line):
    """A file:line claim holds when the file exists and has that line. A short name ("app.py") counts when exactly one file
    of the repository ends with it, as a reader would find it; two candidates are ambiguous and do not count."""
    f = repo / path
    if not f.is_file():
        tail = "/" + path.lstrip("./")
        hits = [x for x in _files_of(repo) if ("/" + x).endswith(tail)]
        if len(hits) != 1:
            return False
        f = repo / hits[0]
    try:
        with f.open("rb") as fh:
            return 1 <= line <= sum(1 for _ in fh) + 1
    except OSError:
        return False


def _files_of(repo):
    out = sh("git", "-C", str(repo), "ls-tree", "-r", "--name-only", "HEAD", check=False, timeout=60).stdout
    return [x for x in out.splitlines() if x]


_quality = {}                                      # (step, repo) -> (asked at, result): status() is read on every state write


def quality_of(sid, name):
    """DEC-48: one step's result in numbers and whether it is good enough: {ok, text, n}. Cached a minute."""
    hit = _quality.get((sid, name))
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    q = _quality_of(sid, name)
    _quality[(sid, name)] = (time.time(), q)
    return q


WIKI_STALE = re.compile(r"^reverify:", re.M)       # a page the wiki's recheck marked: the code it cites changed (repowiki.reverify)


def _quality_of(sid, name):
    repo = CODE / name
    if sid == "clone":
        if not (repo / ".git").exists():
            return {"ok": False, "text": "no copy of the code", "n": {}}
        sha = sh("git", "-C", str(repo), "rev-parse", "--short", "HEAD", check=False, timeout=60).stdout.strip()
        files = map_report(name).get("files")         # the scan's count, once the map ran; never a limit (BLD-26)
        return {"ok": True, "text": (f"{files:,} files " if files else "") + f"at {sha}", "n": {"files": files}}
    if sid == "graph":
        if (repo / "graphify-out" / ".no-code").exists():
            return {"ok": True, "text": "no code to graph: web pages or documents", "n": {}}
        try:
            g = json.loads((repo / "graphify-out" / "graph.json").read_text())
        except (OSError, ValueError):
            return {"ok": False, "text": "no code graph", "n": {}}
        nodes, links = g.get("nodes") or [], g.get("links") or []
        own = sum(1 for n in nodes if n.get("source_file"))
        ok = bool(nodes) and bool(links)
        return {"ok": ok, "text": f"{len(nodes):,} nodes · {len(links):,} links · {own:,} in the repository's own files" if ok else "hollow: a graph without links",
                "n": {"nodes": len(nodes), "links": len(links), "own": own}}
    if sid == "facts":
        made, unknown = RF.state_of(name)              # what could not be found out is said (QA-26), not a weak step
        return {"ok": bool(made), "text": unknown or ("facts from its history" if made else "no facts yet"), "n": {}}
    if sid == "map":
        return map_quality(name)
    if sid == "explain":
        missing, total, _ = unexplained(name)
        if not total:
            return {"ok": False, "text": "no code map to explain", "n": {}}
        ok = missing <= total * 0.05
        return {"ok": ok, "text": f"{total - missing:,} of {total:,} files explained" + ("" if ok else f": {missing:,} still hollow"), "n": {"files": total, "explained": total - missing}}
    if sid == "search":
        ok = (DOCS / f"{name}.md").exists()
        return {"ok": ok, "text": "digest in the search index" if ok else "not in the search index", "n": {}}
    if sid == "analysis":
        f = DOCS / f"{name}.analysis.md"
        if not f.exists():
            return {"ok": False, "text": "no written analysis", "n": {}}
        text = f.read_text(errors="replace")
        sections = len(re.findall(r"^## ", text, re.M))
        claims = [(p, int(l)) for p, l in FILELINE.findall(text) if not p.endswith((".md", ".analysis"))]
        resolve = sum(1 for p, l in claims if claim_resolves(repo, p, l))
        ok = len(text) >= 2000 and sections >= 4 and (not claims or resolve >= len(claims) * 0.6)
        n = {"chars": len(text), "sections": sections, "claims": len(claims), "resolve": resolve}
        return {"ok": ok, "text": f"{sections} sections · {resolve} of {len(claims)} file:line claims resolve" + ("" if ok else " · too thin to work from"), "n": n}
    if sid == "wiki":
        pages = len(list((VAULT / "repos" / name / "wiki").glob("*.md"))) if (VAULT / "repos" / name / "wiki").is_dir() else 0
        stale = sum(1 for f in (VAULT / "repos" / name / "wiki").glob("*.md") if WIKI_STALE.search(f.read_text(errors="replace")[:3000])) if pages else 0  # cap: parse (the front matter)
        return {"ok": pages >= 3, "text": (f"{pages} pages" + (f" · {stale} to check: the code they cite changed" if stale else "")) if pages else "no wiki yet",
                "n": {"pages": pages, "stale": stale}}
    if sid == "card":
        import repocard as RC
        lines, _ = RC.lines_of(name)
        kinds = {}
        for x in lines:
            kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
        ok = RC.load(name) is not None                 # made from the steps before it, which have their own gates
        words = {"command": "commands", "rule": "rules", "fragile": "fragile areas", "module": "parts", "start": "starting points"}
        text = " · ".join(f"{n} {words[k]}" for k, n in kinds.items()) if lines else "no card yet"
        if lines and not kinds.get("command"):
            text += " · no commands known yet (a change learns them)"
        return {"ok": ok, "text": text, "n": kinds}
    return {"ok": True, "text": "", "n": {}}


def usage_of(sid, name):
    """What a step's work cost: {model, calls, tokens} where a model ran, else {}."""
    if sid == "explain":
        try:
            e = json.loads((LOGS / f"ua-enrich-{name}.json").read_text())
            return {"model": MODEL_OF[sid], "calls": e.get("calls"), "tokens": e.get("tokens")}
        except (OSError, ValueError):
            return {"model": MODEL_OF[sid]}
    return {"model": MODEL_OF[sid]} if sid in MODEL_OF else {}


def host_of(url):
    """The host of a URL or an scp-like git address, without a user part: ssh://git@host:7999/P/r.git and git@host:P/r.git -> host.
    An ssh alias (forgejo:owner/repo) has none: "" (the owner's own, as before)."""
    u = str(url or "")
    m = re.match(r"^[a-z][a-z0-9+.-]*://(?:[^/@]+@)?\[?([^/:\]]+)", u, re.I) or re.match(r"^[^/@:]+@([^/:]+):(?!//)", u)
    return m.group(1).lower() if m else ""


def own_forges(values=None):
    """The hosts whose repositories are the owner's own work: Forgejo, the deployment's forge (FORGE_URL) and the hosts it
    names in OWN_FORGES (comma separated)."""
    v = values if values is not None else DEPLOY.VALUES
    hosts = {str(getattr(DEPLOY, "FORGEJO_HOST", "") or "").lower(), host_of(v.get("FORGE_URL"))}
    hosts |= {h.strip().lower() for h in str(v.get("OWN_FORGES") or "").split(",")}
    return {h for h in hosts if h}


def kind_of(url_or_origin, values=None):
    """What a repository is to the owner, when not said: their own work on their forge, PC or tailnet, or on a forge the
    deployment names as its own; else something to evaluate."""
    u = str(url_or_origin or "")
    host = host_of(u)
    if not u or not host or INTERNAL.match(host) or host in own_forges(values):
        return "own"
    return "evaluate"


LEAVE = re.compile(r"(?i)\bplease (grant|give|allow|approve|confirm)\b|\bgrant (me )?(the )?permission\b"
                   r"|\b(I|we) (need|require|would need)\b[^.\n]{0,40}\b(permission|approval)\b|\b(may|can|shall) I (proceed|continue)\b")


def asks_leave(answer):
    """A short answer that asks for permission instead of giving the analysis (a work site, 9 Nov 2026: a model that waited
    for a tool it was not given answered "please grant permission", and onboarding took that as the guide)."""
    a = str(answer or "")
    return len(a) < 3000 and bool(LEAVE.search(a))


def package(name):
    """What of the package this repository has, from what is on disk: {step: bool}."""
    repo = CODE / name
    made, unknown = RF.state_of(name)
    return {"clone": (repo / ".git").exists(), "graph": graphed(repo), "facts": made and not unknown, "map": valid_map(name),
            "explain": valid_map(name) and not unexplained(name)[0], "search": (DOCS / f"{name}.md").exists(),
            "analysis": (DOCS / f"{name}.analysis.md").exists(), "wiki": (VAULT / "repos" / name / "wiki" / "conventions.md").exists(),
            "card": (VAULT / "repos" / name / "card.json").exists()}


RECORD = ("ended", "seconds", "model", "calls", "tokens", "sha")
CODE_STEPS = ("clone", "graph", "facts", "map", "explain", "search")   # these follow the code; the analysis shows its age
UPDATE_STEPS = CODE_STEPS + ("wiki", "card")       # Update: the code-made steps, the wiki checked against the changed code, the card made again
NO_MODEL = "no model (a program)"
MODEL_WORD = {"claude-code": "Claude Code"}
_behind = {}                                       # (repo, sha, head) -> commits behind; status() runs on every state write


def head_of(name):
    return sh("git", "-C", str(CODE / name), "rev-parse", "HEAD", check=False, timeout=60).stdout.strip()


def behind(name, sha, head=None):
    """How many commits the repository's copy has after `sha` (None: unknown)."""
    if not sha:
        return None
    head = head or head_of(name)
    if not head:
        return None
    if head.startswith(sha):
        return 0
    key = (name, sha, head)
    if key not in _behind:
        out = sh("git", "-C", str(CODE / name), "rev-list", "--count", f"{sha}..{head}", check=False, timeout=60).stdout.strip()
        _behind[key] = int(out) if out.isdigit() else None
    return _behind[key]


def _mtime(p):
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(p.stat().st_mtime))
    except OSError:
        return None


_known = {}                                        # (step, repo) -> (read at, record): the map file is large and status() runs often


def known_record(sid, name):
    hit = _known.get((sid, name))
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    rec = _known_record(sid, name)
    _known[(sid, name)] = (time.time(), rec)
    return rec


def _known_record(sid, name):
    """A step's record read from what it left (for a run before records existed): when, the commit it was made at, model, calls, tokens."""
    repo = CODE / name
    if sid == "clone":
        return {"ended": _mtime(repo / ".git" / "FETCH_HEAD") or _mtime(repo / ".git" / "HEAD"), "model": NO_MODEL, "sha": head_of(name)[:12]}
    if sid == "graph":
        try:
            sha = (GRAPHS / f"{name}.head").read_text().strip()[:12]
        except OSError:
            sha = None
        return {"ended": _mtime(repo / "graphify-out" / "graph.json"), "model": NO_MODEL, "sha": sha}
    if sid == "facts":
        try:
            sha = str(json.loads(RF.path(name).read_text()).get("commit") or "")[:12] or None
        except (OSError, ValueError):
            sha = None
        return {"ended": _mtime(RF.path(name)), "model": NO_MODEL, "sha": sha}
    try:
        kg = json.loads(kg_of(name).read_text())
    except (OSError, ValueError):
        kg = {}
    map_sha = str((kg.get("project") or {}).get("gitCommitHash") or "")[:12] or None
    if sid == "map":
        rep = map_report(name)
        return {"ended": str((kg.get("project") or {}).get("analyzedAt") or "")[:19] or _mtime(kg_of(name)), "sha": map_sha,
                "model": NO_MODEL if rep else "an agent on gpt-sub-fast (the old way)", "seconds": rep.get("seconds")}
    if sid == "explain":
        try:
            e = json.loads((LOGS / f"ua-enrich-{name}.json").read_text())
        except (OSError, ValueError):
            e = {}
        return {"ended": e.get("finished") or e.get("updated"), "model": "gpt-sub-fast", "calls": e.get("calls"), "tokens": e.get("tokens"), "sha": map_sha}
    if sid == "search":
        return {"ended": _mtime(DOCS / f"{name}.md"), "model": NO_MODEL, "sha": map_sha}
    if sid == "analysis":
        f = DOCS / f"{name}.analysis.md"
        head = f.read_text(errors="replace")[:600] if f.exists() else ""   # cap: parse (the header holds the commit and the task)
        m, t = re.search(r"Commit ([0-9a-f]{7,40})", head), re.search(r"Claude task #(\d+)", head)
        task = task_of(int(t.group(1))) if t else None
        return {"ended": _mtime(f), "model": "Claude Code", "tokens": (task or {}).get("tokens"), "sha": m.group(1) if m else None,
                "task": int(t.group(1)) if t else None}
    if sid == "card":
        try:
            c = json.loads((VAULT / "repos" / name / "card.json").read_text())
        except (OSError, ValueError):
            c = {}
        return {"ended": c.get("made"), "model": NO_MODEL, "sha": c.get("commit")}
    if sid == "wiki":
        pages = list((VAULT / "repos" / name / "wiki").glob("*.md")) if (VAULT / "repos" / name / "wiki").is_dir() else []
        newest = max(pages, key=lambda p: p.stat().st_mtime) if pages else None
        return {"ended": _mtime(newest) if newest else None, "model": "the Scribe (Claude Code)"}
    return {}


def step_row(k, t, rec, state, name, live=False, head=None, kind=None):
    """One step for the page: its state, note, quality (DEC-48) and record: when it ran, which model, calls, tokens, the commit
    it was made at and how many commits the code has moved on since. A run from before records is read from what it left."""
    q = rec.get("quality") if isinstance(rec.get("quality"), dict) else None
    if state in ("done", "weak") and (not q or not live):     # a finished job's steps are judged as they are now, not as they were
        q = quality_of(k, name)
    if state == "done" and q and not q.get("ok"):
        state = "weak"
    out = {f: rec.get(f) for f in RECORD}
    if state in ("done", "weak") and not (out.get("ended") and out.get("model") and out.get("sha")):
        out = {**{f: v for f, v in known_record(k, name).items() if f in RECORD + ("task",)}, **{f: v for f, v in out.items() if v not in (None, "")}}
    out["model"] = MODEL_WORD.get(out.get("model"), out.get("model"))
    quality = (q or {}).get("text", "")
    if k == "analysis" and quality and kind:
        quality = ("a guide to your own code · " if kind == "own" else "a review of an outside project · ") + quality
    n = behind(name, out.get("sha"), head) if k != "clone" and state in ("done", "weak") else None
    return {"id": k, "title": t, "state": state, "note": rec.get("note", ""), **out, "behind": n, "quality": quality, "ok": (q or {}).get("ok")}


def status(name, pkg=None):
    """What the repo page and repos_overview show: {status, step, index, total, steps, why, since, kind}. status: done (the
    whole package, no weak step), incomplete (parts missing or weak, no job), queued, running, waiting, failed. Each
    step carries its record: when it last ran, how long, which model, calls and tokens, and its quality in words."""
    st, total = load(name), len(STEPS)
    recs = (st or {}).get("steps") or {}
    kind = (st or {}).get("kind") or kind_of(origin(name) if (CODE / name).exists() else "")
    head = head_of(name) if (CODE / name / ".git").exists() else ""
    if st and st.get("status") in ACTIVE + ("failed",):
        steps = [step_row(k, t, recs.get(k, {}), recs.get(k, {}).get("status", "pending"), name, live=True, head=head, kind=kind) for k, t in STEPS]
        i = next((n for n, (k, _) in enumerate(STEPS, 1) if k == st.get("step")), 1)
        return {"status": st["status"], "step": st.get("step"), "index": i, "total": total, "steps": steps, "why": st.get("why", ""),
                "since": st.get("started"), "kind": kind, "head": head[:12], "behind": behind_of(steps)}
    pkg = package(name) if pkg is None else pkg
    notes = {"explain": recs.get("explain", {}).get("note", ""), "facts": RF.state_of(name)[1]}    # what could not be found out says so (QA-26)
    steps = [step_row(k, t, {**recs.get(k, {}), "note": notes.get(k) or recs.get(k, {}).get("note", "")}, "done" if pkg.get(k) else "pending", name, head=head, kind=kind)
             for k, t in STEPS]
    done = all(s["state"] == "done" for s in steps)
    return {"status": "done" if done else "incomplete", "step": None, "index": sum(s["state"] in ("done", "weak") for s in steps), "total": total,
            "steps": steps, "why": "", "since": st.get("finished") if st else None, "kind": kind, "head": head[:12], "behind": behind_of(steps)}


def behind_of(steps):
    """How far the code-made steps are behind the code: the most any of them is (None: unknown)."""
    ns = [s.get("behind") for s in steps if s["id"] in CODE_STEPS and s.get("behind") is not None]
    return max(ns) if ns else None



def begin(name, url, source="app", redo=False, kind=None, step=None, update=False):
    """A new or resumed record: what the disk already has stays done; a weak step is done again; on redo the analysis is made
    anew from the code map on; `step` does that step and every one after it again. The repository's kind (the owner's own
    work, or something to evaluate) is kept from the last record unless given."""
    old = load(name) or {}
    pkg = package(name)
    for k, _ in STEPS:                                 # DEC-48: hollow never counts as done
        if pkg.get(k) and not quality_of(k, name)["ok"]:
            pkg[k] = False
    if redo:
        pkg.update(facts=False, map=False, explain=False, search=False, analysis=False)   # the wiki keeps what it learned
    fresh = []
    if update:                                         # Update: the steps that follow the code, from the latest commit; the map keeps what is unchanged
        fresh = list(UPDATE_STEPS)
    if step in TITLE:                                  # Run again: that step and every one after it, done again for real
        fresh = [k for k, _ in STEPS[[k for k, _ in STEPS].index(step):]]
    for k in fresh:
        pkg[k] = False
    kept = {k: v for k, v in (old.get("steps") or {}).items() if isinstance(v, dict)}
    st = {"repo": name, "url": url, "source": source, "status": "queued", "step": None, "redo": bool(redo), "attempts": {}, "restarts": 0, "fresh": fresh,
          "started": now(), "milestone": now(), "why": "", "task": None, "kind": kind or old.get("kind") or kind_of(url or (origin(name) if (CODE / name).exists() else "")),
          "steps": {k: ({**kept.get(k, {}), "status": "done"} if pkg.get(k) else {"status": "pending", "note": ""}) for k, _ in STEPS}}
    save(st)
    return st


# ---------- the steps ----------
def step_clone(st):
    name, url, repo = st["repo"], st.get("url"), CODE / st["repo"]
    if (repo / ".git").exists():
        if url and not same_repo(origin(name), url):
            raise Stop(f"another repository called {name} is already here, from {origin(name)}: remove it first")
        if "clone" in (st.get("fresh") or []) and name != "ai-stack" and origin(name):   # ai-stack's copy is kept current by graphify-sync
            was = head_of(name)[:12]
            sh("git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", "fetch", "-q", "origin", timeout=CLONE_TIMEOUT)
            up = sh("git", "-C", str(repo), "rev-parse", "@{u}", check=False).stdout.strip() or sh("git", "-C", str(repo), "rev-parse", "origin/HEAD", check=False).stdout.strip()
            if up:                                     # the stack's copy is read, never edited: it follows its origin exactly
                sh("git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", "reset", "-q", "--hard", up)
            now_ = head_of(name)[:12]
            return f"updated from {was} to {now_}" if now_ != was else "already at the latest commit"
        return ""
    if not url:
        raise Stop(f"{name} is not in ~/code, and no address was given to copy it from")
    tmp = CODE / ".cloning" / name
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    sh("git", "-c", "core.hooksPath=/dev/null", "clone", "-q", url, str(tmp), timeout=CLONE_TIMEOUT)    # its whole history: the facts read it
    tmp.replace(repo)                                      # a half-done clone never looks like a repository
    return ""


def graph_sync():
    sh("bash", str(STACK / "ops/graphify-sync.sh"), timeout=GRAPH_WAIT, check=False)


def step_graph(st):
    name, repo = st["repo"], CODE / st["repo"]
    head = sh("git", "-C", str(repo), "rev-parse", "HEAD").stdout.strip()
    t0 = time.time()
    while time.time() - t0 < GRAPH_WAIT:
        graph_sync()                                       # at once, not at the timer's next minute; it takes its own lock
        if graphed(repo) and (GRAPHS / f"{name}.head").exists() and (GRAPHS / f"{name}.head").read_text().strip() == head:
            return "" if (repo / "graphify-out" / "graph.json").exists() else "It has no code the graph tool reads."
        failed = GRAPHS / f"{name}.failed"
        if failed.exists() and failed.read_text().strip() == head:
            failed.unlink()                                # so that the next try builds it again
            raise RuntimeError(f"the code graph tool failed at commit {head[:12]} (journal: graphify-sync)")
        pause(15)
    raise RuntimeError(f"no code graph after {GRAPH_WAIT // 60} minutes (journal: graphify-sync)")


def step_facts(st):
    """BLD-27: no model. A tool that fails leaves the other's results and its name in the note; only no result at all is a failed try."""
    name = st["repo"]
    gb = free_gb()
    if gb < RF.NEED_GB:
        raise Wait(f"waits for memory: {gb:.1f} GB available on the PC, it starts at {RF.NEED_GB:.1f}", seconds=120)
    working(st, "facts", "CodeLore and repowise are reading a throwaway copy")
    doc = RF.build(name)
    if RF.nothing(doc):
        raise RuntimeError(f"neither tool could run. {RF.gaps(doc)}")
    return RF.gaps(doc)


def gateway():
    """None when ChatGPT answers through the gateway; else a Wait for what is in the way. A refused key cannot mend itself."""
    key = os.environ.get("VK_CODE")
    if not key:
        raise Stop("VK_CODE is not set: the job runs through make understand")
    body = json.dumps({"model": "gpt-sub-fast", "messages": [{"role": "user", "content": "Say ok."}]}).encode()
    req = urllib.request.Request(LITELLM, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            r.read()
        return None
    except urllib.error.HTTPError as e:
        detail = TC.cut(e.read().decode(errors="replace"), 500)  # cap: untrusted
        if e.code == 429 or re.search(r"usage.?limit|rate.?limit|quota|cooldown|no deployments", detail, re.I):
            return Wait("waits for the ChatGPT usage limit, then goes on by itself", tell=True)
        if e.code in (401, 403):
            raise Stop(f"the gateway refused the key: {detail}")
        return Wait(f"waits for the model gateway (HTTP {e.code})")
    except (OSError, ValueError) as e:
        return Wait(f"waits for the model gateway ({type(e).__name__})")


def free_gb():
    import conductor as CD
    return CD.free_gb()


def ready_for_memory(need_gb):
    """The code map's container needs room, not a model."""
    gb = free_gb()
    if gb is not None and gb < need_gb:
        raise Wait(f"waits for memory: {gb:.1f} GB available on the PC, it starts at {need_gb:.1f}", seconds=120)


def ready_for_model(need_gb=0):
    w = gateway()
    if w:
        raise w
    gb = free_gb()
    if gb < need_gb:
        raise Wait(f"waits for memory: {gb:.1f} GB available on the PC, it starts at {need_gb:.1f}", seconds=120)


def run_map(name, attempt, log):
    """The code map as fixed steps (ops/ua_map_in.py) in a throwaway container that sees only this repo and no network:
    no model, no agent. Its exit code alone says little: step_map reads the map's quality."""
    repo = CODE / name
    sh("docker", "rm", "-f", f"understand-{name}", check=False, timeout=120)
    memory = "2g" if not attempt else "4g"             # killed for memory the first time: more room for the next
    with log.open("a") as f:
        f.write(f"\n===== {now()} try {attempt + 1}\n")
        f.flush()
        try:
            subprocess.run(["docker", "run", "--rm", "--network", "none", "--memory", memory, "--name", f"understand-{name}", "-e", "HOME=/root",
                            "-v", f"{repo}:/work/{name}", "-v", f"{STACK / 'ops/ua_map_in.py'}:/ua_map_in.py:ro", "-w", f"/work/{name}",
                            "--entrypoint", "python3", IMAGE, "/ua_map_in.py", f"/work/{name}"],
                           stdout=f, stderr=subprocess.STDOUT, timeout=MAP_TIMEOUT, env=env())
        finally:
            sh("docker", "rm", "-f", f"understand-{name}", check=False, timeout=120)


def step_map(st):
    name, repo = st["repo"], CODE / st["repo"]
    kg, prev = kg_of(name), kg_of(name).with_name("knowledge-graph.previous.json")
    (repo / ".ua").mkdir(parents=True, exist_ok=True)
    excl = repo / ".git" / "info" / "exclude"
    if excl.parent.exists() and ".ua/" not in (excl.read_text().split() if excl.exists() else []):
        with excl.open("a") as f:
            f.write(".ua/\n")
    ignore = repo / ".ua" / ".understandignore"        # Graphify's own output in the clone is not the project
    if "graphify-out/" not in (ignore.read_text().split() if ignore.exists() else []):
        with ignore.open("a") as f:
            f.write("graphify-out/\n")
    if st.get("redo") or "map" in (st.get("fresh") or []):   # made anew: only what this run writes counts as its result; the earlier map, set aside, lends its unchanged explanations
        if kg.exists():
            kg.replace(prev)
        kg.with_name("knowledge-graph.fallback.json").unlink(missing_ok=True)
        (LOGS / f"ua-enrich-{name}.json").unlink(missing_ok=True)
        st["redo"] = False
        save(st)
    elif map_quality(name)["ok"]:                      # it was written just before a crash
        return ""
    ready_for_memory(NEED_GB)
    working(st, "map", "Understand Anything is reading the code")
    log = LOGS / f"understand-{name}.log"
    run_map(name, st["attempts"].get("map", 0), log)
    q = map_quality(name)
    if not q["ok"]:                                    # DEC-48: a hollow map is a failed try, never "done"; the run's last words say why
        words = TC.tail(log.read_text(errors="replace"), 800) if log.exists() else ""  # cap: store
        raise RuntimeError(f"map {q['text']}" + (f": {words}" if words.strip() else f"; log: {log}"))
    kg_of(name).with_name("knowledge-graph.previous.json").unlink(missing_ok=True)
    return ""


def run_enrich(name):
    log = LOGS / f"understand-{name}.log"
    with log.open("a") as f:
        return subprocess.run([sys.executable, str(STACK / "ops/ua_enrich.py"), str(CODE / name), name], stdout=f, stderr=subprocess.STDOUT,
                              timeout=ENRICH_TIMEOUT, env=env()).returncode


def run_fix(name):
    """The viewer's own corrections, saved, so it opens without an "auto-corrections" banner."""
    return sh("docker", "run", "--rm", "--network", "none", "-v", f"{CODE / name / '.ua'}:/ua", "-v", f"{STACK / 'ops/ua_fix.mjs'}:/ua_fix.mjs:ro",
              "--entrypoint", "node", IMAGE, "/ua_fix.mjs", check=False, timeout=600).returncode


def step_explain(st):
    name = st["repo"]
    ready_for_model()
    working(st, "explain", "explaining the files, one batch after the other")
    rc = run_enrich(name)
    if rc == 75:
        raise Wait("waits for the ChatGPT usage limit, then goes on where it stopped", tell=True)
    if rc:
        raise RuntimeError(f"the explanations stopped (exit {rc}); log: {LOGS / f'understand-{name}.log'}")
    missing, total, paths = unexplained(name)
    if missing and st["attempts"].get("explain", 0) < ATTEMPTS - 1:
        raise RuntimeError(f"{missing} of {total} files still have no explanation")
    note = ""
    if missing:                                        # said, not hidden: the page keeps offering to finish them
        note = f"{missing} of {total} files have no explanation: " + ", ".join(TC.more(paths, 8, "more"))  # cap: list (the code map's page shows every file)
    if run_fix(name):
        note = (note + " " if note else "") + "The viewer may show its own corrections banner."
    return note


def qmd_index():
    """The digest searchable by its words now (qmd update); its embeddings, for search by meaning, go on in the search
    container on their own (overnight 9 Nov 2026: embedding sympy's 4.4 MB digest on the CPU outlasted the step's 30 minutes
    twice and would have stopped the onboarding before its guide, wiki and card)."""
    sh("docker", "exec", QMD, "qmd", "update", timeout=QMD_TIMEOUT)
    sh("docker", "exec", "-d", QMD, "sh", "-c", "qmd embed >/dev/null 2>&1", timeout=60)


def qmd_has(doc):
    listed = sh("docker", "exec", QMD, "qmd", "ls", "code-docs", timeout=120).stdout
    plain = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    return plain(doc) in plain(listed)


def write_doc(path_, text):
    DOCS.mkdir(parents=True, exist_ok=True)
    tmp = path_.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(path_)


def step_search(st):
    name = st["repo"]
    made = sh(sys.executable, str(STACK / "ops/ua_digest.py"), str(kg_of(name)), name, timeout=300).stdout
    if not made.strip():
        raise RuntimeError("the digest came out empty")
    write_doc(DOCS / f"{name}.md", made)
    qmd_index()
    if not qmd_has(f"{name}.md"):
        raise RuntimeError(f"the search index does not list {name}.md after the update")
    return ""


def submit(req):
    """A request through the runner's inbox, as the app sends one; -> its answer."""
    rid = "onboard-" + hashlib.sha1(f"{req}{time.time()}".encode()).hexdigest()[:16]  # cap: id
    tmp = MISSIONS / "inbox" / f"{rid}.tmp"
    tmp.write_text(json.dumps(req, ensure_ascii=False))
    tmp.replace(tmp.with_suffix(".json"))
    res = MISSIONS / "public" / "results" / f"{rid}.json"
    t0 = time.time()
    while time.time() - t0 < SEEN_WAIT:
        if res.exists():
            return json.loads(res.read_text())
        pause(3)
    raise RuntimeError(f"the runner did not take the request within {SEEN_WAIT // 60} minutes")


def task_of(tid):
    try:
        return json.loads((MISSIONS / "claude" / f"{tid}.json").read_text())
    except (OSError, ValueError):
        return None


def about_the_stack():
    return (STACK / "README.md").read_text(errors="replace").split("## Documents")[0]


STRUCTURAL = {"calls", "inherits", "implements", "contains", "imports", "imports_from", "method", "defines", "uses"}   # what holds code together; not a type mention
MODULES_CHARS = 30000                                  # cap: prompt (the module list the engineer's guide is written from)


def modules_text(name):
    """The repository's own structure for the guide's writer: each package with its files and its most connected classes and
    functions (by the structural links, not by type mentions), and the code map's layer descriptions where they exist."""
    repo = CODE / name
    try:
        g = json.loads((repo / "graphify-out" / "graph.json").read_text())
    except (OSError, ValueError):
        return "(no code graph yet)"
    deg = {}
    for ln in g.get("links") or []:
        if ln.get("relation") in STRUCTURAL:
            for k in ("source", "target"):
                deg[ln[k]] = deg.get(ln[k], 0) + 1
    packs = {}
    for n in g.get("nodes") or []:
        f = str(n.get("source_file") or "")
        if not f:
            continue
        parts = f.split("/")
        pack = "/".join(parts[:-1][:3]) or "(root)"
        p = packs.setdefault(pack, {"files": set(), "symbols": []})
        p["files"].add(f)
        if n.get("_callable") or n.get("_callable_class"):
            p["symbols"].append((deg.get(n["id"], 0), str(n.get("label") or n["id"]), f, str(n.get("source_location") or "")))
    lines = []
    try:                                               # the layers first: short, and on a large repository the package list
        kg = json.loads(kg_of(name).read_text())        # alone outgrew the cap and cut them off (sympy's guide, 9 Nov 2026)
        import ua_enrich as U
        desc = [f"- {l.get('name')}: {l.get('description')}" for l in kg.get("layers") or [] if not U.is_placeholder(l.get("description"))]
        if desc:
            lines += ["# What the code map says about each layer", *desc, ""]
    except (OSError, ValueError, ImportError):
        pass
    lines += [f"# {name}: packages, their files and their most connected classes and functions (largest first)", ""]
    for pack, p in sorted(packs.items(), key=lambda kv: -len(kv[1]["files"])):
        top = sorted(p["symbols"], key=lambda x: (-x[0], x[1]))[:8]  # cap: top (the most connected per package; the graph has every one)
        lines.append(f"- {pack}: {len(p['files'])} files" + (": " + ", ".join(f"{lbl} ({f}:{loc.lstrip('L')})" if loc else f"{lbl} ({f})" for _, lbl, f, loc in top) if top else ""))
    return TC.cut("\n".join(lines), MODULES_CHARS, f"the smaller packages; every one is in graphify-out/graph.json ({len(packs)} packages)")  # cap: prompt


def guide_titles():
    """The section titles the guide's and the analysis's prompts ask for, read from the prompts themselves (one source)."""
    out = []
    for name in ("ONBOARD_GUIDE", "ONBOARD_ANALYSIS"):
        out += re.findall(r"^## (.+?)\s*$", str(P.text("shared", name)), re.M)
    return list(dict.fromkeys(out))


def _key(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


HEADING_DRESS = re.compile(r"^(?:\*\*|__)?\s*(?:(?:\d+|[A-Za-z])\s*[.)]|(?:\d+|[A-Z])\s+[—–-])?\s*(.*?)\s*(?:\*\*|__)?\s*:?\s*(?:\*\*|__)?\s*$")


def headings_fixed(text, titles=None):
    """BLD-39: a line that is one of the asked section titles, written as plain text ("Module map", "**3. Module map:**"),
    becomes its "## Title" heading; everything else stays as it is. -> (text, how many lines were made headings). A work
    site, 9 Nov 2026: 7 of 10 good guides had no "##" line, so the check failed them and the card and wiki read nothing."""
    canon = {_key(t): t for t in (titles if titles is not None else guide_titles())}
    out, fixed = [], 0
    for line in str(text).split("\n"):
        m = HEADING_DRESS.match(line.strip()) if line.strip() and not line.lstrip().startswith("#") else None
        title = canon.get(_key(m.group(1))) if m else None
        if title:
            out.append(f"## {title}")
            fixed += 1
        else:
            out.append(line)
    return "\n".join(out), fixed


def fix_headings(names=None):
    """The written guides and analyses on disk, their plain-text section titles made headings, once, without a model;
    each one repaired gets its card and its guide's wiki pages made again. -> {name: lines fixed}."""
    done = {}
    for f in sorted(DOCS.glob("*.analysis.md")):
        name = f.name[:-len(".analysis.md")]
        if names and name not in names:
            continue
        text, n = headings_fixed(f.read_text(errors="replace"))
        if n:
            write_doc(f, text)
            done[name] = n
            try:
                import repocard as RC
                RC.make(name)
                sh(sys.executable, str(STACK / "ops/repowiki.py"), "feed", name, timeout=1200, check=False)
            except Exception as e:                         # the guide is fixed; the card is made again by onboarding's next pass
                print(f"{name}: the card was not made again: {type(e).__name__}: {e}", flush=True)
    return done


def step_analysis(st):
    name = st["repo"]
    if not st.get("task"):
        origin_ = re.sub(r"//[^/@]+@", "//", origin(name)) or "(none)"
        if st.get("kind", "own") == "own":            # DEC-48: the owner's own work gets the engineer's guide, written from its structure
            question, context = P.text("shared", "ONBOARD_GUIDE").format(name=name, origin=origin_), modules_text(name)
        else:
            question, context = P.text("shared", "ONBOARD_ANALYSIS").format(name=name, origin=origin_), about_the_stack()
        r = submit({"action": "claude_task", "mode": "study", "repo": name, "question": question, "context": context,
                    "source": f"onboard:{name}"})
        if not r.get("ok"):
            raise RuntimeError(f"Claude Code did not take it: {r.get('error')}")
        st["task"] = r["id"]
        save(st)
    t = task_of(st["task"]) or {}
    state = t.get("status")
    if state == "waiting":
        raise Wait(f"Claude task #{st['task']} waits for the Claude usage limit, then goes on by itself", seconds=300, tell=True)
    if state in ("queued", "running", None):
        raise Wait(f"Claude task #{st['task']} is reading the code", seconds=20, idle=False)
    if state != "done" or len(str(t.get("answer") or "")) < 200 or asks_leave(t.get("answer")):
        tid, st["task"] = st["task"], None             # the next try asks anew
        save(st)
        raise RuntimeError(f"Claude task #{tid} ended without an analysis: {TC.tail(str(t.get('error') or 'no answer'), 800)}")  # cap: store
    sha = sh("git", "-C", str(CODE / name), "rev-parse", "--short", "HEAD", check=False).stdout.strip()
    answer, fixed = headings_fixed(t["answer"])          # BLD-39: the asked titles as headings, whatever the model wrote
    if fixed:                                             # a warning in the job's log: the model drifting from the prompt shows
        print(f"onboard {name}: prompt adherence: the guide's model wrote {fixed} section titles without their ## heading; "
              "made headings", flush=True)
        st["note_headings"] = fixed
    write_doc(DOCS / f"{name}.analysis.md", f"# {name}: analysis\n\nCommit {sha}, {now()[:10]}, by [Claude task #{st['task']}](#/live/claude-task:{st['task']}).\n\n{answer}\n")
    qmd_index()
    if not qmd_has(f"{name}.analysis.md"):
        raise RuntimeError(f"the search index does not list {name}.analysis.md after the update")
    return ""


def step_wiki(st):
    """CHG-08: the first version of the repository's wiki; a redo keeps what the wiki has learned. DEC-49: onboarding's own
    pages (a page per part of the code, a page per section of the guide) are made again every time."""
    name = st["repo"]
    try:
        sh(sys.executable, str(STACK / "ops/repowiki.py"), "feed", name, timeout=600)
    except Exception as e:                             # the Scribe's wiki stands without them; the next Update tries again
        print(f"onboard: the wiki pages of {name} from onboarding: {type(e).__name__}: {e}", flush=True)
    if (VAULT / "repos" / name / "wiki" / "conventions.md").exists():
        if "wiki" in (st.get("fresh") or []):         # asked again: checked against the code as it is now; what changes learned stays
            working(st, "wiki", "the wiki's pages are checked against the changed code")
            out = sh(sys.executable, str(STACK / "ops/repowiki.py"), "reverify", name, timeout=1200).stdout
            try:
                marked = len(json.loads(out or "{}"))
            except ValueError:
                marked = 0
            return (f"{marked} page{'' if marked == 1 else 's'} cite code that changed: marked for the Scribe" if marked
                    else "every page still matches the code") + f" at {head_of(name)[:7]}"
        return "the wiki stays: it holds what earlier changes learned"
    ready_for_model()
    working(st, "wiki", "the Scribe writes its first version")
    sh(sys.executable, str(STACK / "ops/repowiki.py"), "seed", name, timeout=1200)
    return ""


def step_card(st):
    """DEC-49: the card for coding agents, from what the steps before made; no model. The owner's pins and strikes stay."""
    import repocard as RC
    c = RC.make(st["repo"])
    try:                                               # the node panel shows what a coder is told on first reading a file
        import memstack as MS
        write_doc(DOCS / f"{st['repo']}.notes.json", json.dumps(MS.file_notes(st["repo"]), ensure_ascii=False))
    except Exception as e:                             # the card stands without them; the app says no note
        print(f"onboard: the file notes of {st['repo']}: {type(e).__name__}: {e}", flush=True)
    kinds = {}
    for x in c["lines"]:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    words = {"command": ("command", "commands"), "rule": ("rule", "rules"), "fragile": ("fragile area", "fragile areas"),
             "module": ("part", "parts"), "start": ("starting point", "starting points")}
    return ", ".join(f"{n} {words[k][n != 1]}" for k, n in kinds.items()) + " (the card gives the first of each)" if kinds else "nothing to say yet"


STEP_FN = {"clone": step_clone, "graph": step_graph, "facts": step_facts, "map": step_map, "explain": step_explain, "search": step_search, "analysis": step_analysis, "wiki": step_wiki,
           "card": step_card}


# ---------- the message ----------
def tell(st, text, key):
    try:
        import notify as N
        N.send(text, "result", by="stack", title="Code", buttons=[[("🔍 Open it", f"{APP}/#/repo/{st['repo']}")]], push_on=True, event_kind="code",
               key=f"onboard:{st['repo']}:{st['started']}:{key}")
    except Exception as e:                                 # the job's result stays on the page either way
        print(f"message not sent: {type(e).__name__}: {e}", file=sys.stderr, flush=True)


def fail(st, sid, why):
    if sid == "map":                                       # a failed new analysis: the last good map stays
        prev = kg_of(st["repo"]).with_name("knowledge-graph.previous.json")
        if prev.exists() and not kg_of(st["repo"]).exists():
            prev.replace(kg_of(st["repo"]))
    st["steps"][sid].update(status="failed", note="", ended=now())
    st.update(status="failed", step=sid, why=str(why), finished=now(), milestone=now())
    save(st)
    print(f"onboarding {st['repo']} stopped at {sid}: {why}", flush=True)
    tell(st, f"Onboarding {st['repo']} stopped at “{TITLE[sid]}”: {TC.fit(str(why), 1500)}\nTry again on its page goes on from there.", "failed")  # cap: api


def finish(st):
    st.update(status="done", step=None, why="", finished=now(), milestone=now())
    save(st)
    gaps = " ".join(x for x in (st["steps"][k].get("note", "") for k in ("facts", "explain")) if x)
    print(f"onboarding {st['repo']}: the whole package is done", flush=True)
    tell(st, f"{st['repo']} is onboarded: code graph, facts from its history, code map, every file explained, search index, a written analysis and its wiki."
         + (f"\nOne gap: {gaps}" if gaps else ""), "done")


def do_step(st, sid):
    """One step until it is done or the job stops. -> True when done. The step is a run in the record (DEC-48), and its
    record (when, how long, which model, calls, tokens, quality) stays on the state for the page."""
    s = st["steps"][sid]
    run = f"onboard:{st['repo']}:{sid}:{time.strftime('%Y%m%d-%H%M%S')}"
    st.update(step=sid, status="running")
    s.update(status="running", started=now(), note="", run=run)
    for f in RECORD + ("quality",):
        s.pop(f, None)
    save(st)
    RTM.start(run, "onboard", f"Onboarding {st['repo']}: {TITLE[sid]}", ref=f"onboard:{st['repo']}")
    t0 = time.time()
    while True:
        try:
            note = STEP_FN[sid](st)
            _quality.pop((sid, st["repo"]), None)
            q, use = quality_of(sid, st["repo"]), usage_of(sid, st["repo"])
            s.update(status="done", note=note or "", ended=now(), seconds=round(time.time() - t0), quality=q, sha=head_of(st["repo"])[:12],
                     **({"model": NO_MODEL} if sid in ("clone", "graph", "facts", "map", "search", "card") else {}), **use)
            st["attempts"].pop(sid, None)
            st.update(status="running", restarts=0, milestone=now())
            save(st)
            if use.get("tokens"):
                RTM.emit(run, "llm", agent="onboard", title=use.get("model") or "", data={"tokens": {"in": int(use["tokens"]), "out": 0}})
            RTM.end(run, "onboard", "done", detail=q["text"], seconds=time.time() - t0)
            print(f"onboarding {st['repo']}: {sid} done ({q['text']})", flush=True)
            return True
        except Wait as w:
            s["note"], s["status"] = w.note, "waiting" if w.idle else "running"
            st["status"] = "waiting" if w.idle else "running"
            save(st)
            if w.idle:
                st.setdefault("waiting_since", time.time())
            if w.tell or (w.idle and time.time() - st["waiting_since"] > LONG_WAIT):
                tell(st, f"Onboarding {st['repo']} {w.note}.", "waiting")
            save(st)
            pause(w.seconds)
        except Stop as e:
            fail(st, sid, str(e))
            RTM.end(run, "onboard", "failed", detail=str(e), seconds=time.time() - t0)
            return False
        except Exception as e:
            why = f"{type(e).__name__}: {e}" if not isinstance(e, RuntimeError) else str(e)
            tries = st["attempts"].get(sid, 0) + 1
            st["attempts"][sid] = tries
            if tries >= ATTEMPTS:
                fail(st, sid, why)
                RTM.end(run, "onboard", "failed", detail=why, seconds=time.time() - t0)
                return False
            s["note"] = f"try {tries} of {ATTEMPTS} failed, the next follows: {TC.cut(why, 300)}"  # cap: preview
            s["status"] = "running"
            save(st)
            print(f"onboarding {st['repo']}: {sid}: {why}", flush=True)
            pause(BACKOFF[tries - 1])


LIGHT_STEPS = {"card"}   # no model and next to no memory: such a job does not wait for another repository's turn


def take_turn(st):
    """One repository at a time (memory and the usage limit are shared); the lock goes with the process if it dies."""
    STATE.mkdir(parents=True, exist_ok=True)
    f = (STATE / ".turn").open("a+")
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            f.seek(0)
            who = f.read().strip() or "another repository"
            st.update(status="queued", why=f"waits for {who}")
            save(st)
            pause(20)
    f.seek(0)
    f.truncate()
    f.write(st["repo"])
    f.flush()
    st["why"] = ""
    return f


def run(arg, source="make"):
    name, url = parse(arg)
    STATE.mkdir(parents=True, exist_ok=True)
    mine = (STATE / f".{name}.lock").open("a")
    try:
        fcntl.flock(mine, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"{name}: its onboarding is already running", flush=True)
        return 0
    st = load(name)
    if not st or st.get("status") not in ACTIVE:
        st = begin(name, url, source, redo=all(package(name).values()))
    if url:
        st["url"] = url
    pending = {sid for sid, _ in STEPS if st["steps"][sid]["status"] != "done"}
    turn = None if pending <= LIGHT_STEPS else take_turn(st)   # overnight 8 Nov: a 2-second card waited hours behind sympy
    try:
        for sid, _ in STEPS:
            if st["steps"][sid]["status"] != "done" and not do_step(st, sid):
                return 1
        finish(st)
        return 0
    finally:
        if turn:
            turn.close()


# ---------- the runner's side ----------
def unit(name):
    return f"onboard-{name}"


def unit_active(name):
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit(name) + ".service"], timeout=30).returncode == 0


def launch(name):
    """The job in its own unit: it outlives the runner, and a deploy restarting the runner does not touch it."""
    p = subprocess.run(["systemd-run", "--user", "--collect", "--unit", unit(name), "-p", f"WorkingDirectory={STACK}",
                        "make", "understand", f"REPO={name}"], capture_output=True, text=True, timeout=30)
    if p.returncode:
        raise ValueError(f"the onboarding job did not start: {TC.tail((p.stderr or p.stdout).strip(), 800)}")  # cap: store


def start(arg, source="app", kind=None, step=None, update=False):
    """Start the job, or say it is running. Whatever is missing, failed or weak is what it does; a complete package is made
    anew; `step` does that step and the ones after it again; `kind` (own | evaluate) is kept on the repository."""
    name, url = parse(arg)
    st = load(name)
    if kind not in (None, "own", "evaluate"):
        raise ValueError("a repository is 'own' (your own work) or 'evaluate' (something to look at)")
    if step is not None and step not in TITLE:
        raise ValueError(f"no onboarding step called {step}")
    if st and st.get("status") in ACTIVE and unit_active(name):
        return {"repo": name, "already": True, "onboard": status(name)}
    if url and (CODE / name / ".git").exists() and not same_repo(origin(name), url):
        raise ValueError(f"another repository called {name} is already here, from {origin(name)}: remove it first")
    if not st or st.get("status") not in ACTIVE:
        whole = all(package(name).values()) and all(quality_of(k, name)["ok"] for k, _ in STEPS)
        begin(name, url, source, redo=whole and not step and not update, kind=kind, step=step, update=update)
    launch(name)
    return {"repo": name, "already": False, "onboard": status(name)}


def tick():
    """The watchdog, every minute from the runner: a job that should be running and is not (a crash, the PC restarted) is
    started again and goes on at its first unfinished step."""
    STATE.mkdir(parents=True, exist_ok=True)
    for f in STATE.glob("*.json"):
        name = f.stem
        st = load(name)
        if not st or st.get("status") not in ACTIVE or unit_active(name):
            continue
        st["restarts"] = st.get("restarts", 0) + 1
        if st["restarts"] > RESTARTS:
            fail(st, st.get("step") or "clone", f"the job stopped {RESTARTS} times without finishing a step; see journalctl --user -u {unit(name)}")
            continue
        save(st)
        print(f"onboarding {name}: the job was not running, starting it again ({st['restarts']})", flush=True)
        try:
            launch(name)
        except Exception as e:
            print(str(e), flush=True)


def active():
    """Names of the jobs at work: the Code tab lists a repository as soon as its clone is there."""
    out = []
    for f in STATE.glob("*.json") if STATE.exists() else ():
        st = load(f.stem)
        if st and st.get("status") in ACTIVE:
            out.append(f.stem)
    return out


def last_milestone():
    """The latest step finished by any job: the Code tab refreshes what it knows from disk after one."""
    best = ""
    for f in STATE.glob("*.json") if STATE.exists() else ():
        st = load(f.stem)
        best = max(best, (st or {}).get("milestone") or "")
    return best


def forget(name):
    """The repository is being removed: its job stops and its records go."""
    for cmd in (["systemctl", "--user", "stop", unit(name) + ".service"], ["docker", "rm", "-f", f"understand-{name}"]):
        try:
            subprocess.run(cmd, capture_output=True, timeout=120, env=env())
        except (OSError, subprocess.SubprocessError) as e:      # nothing there to stop: the records still go
            print(f"{cmd[0]}: {type(e).__name__}", file=sys.stderr, flush=True)
    for p in (path(name), STATE / f".{name}.lock", DOCS / f"{name}.analysis.md", LOGS / f"ua-enrich-{name}.json", LOGS / f"understand-{name}.log"):
        p.unlink(missing_ok=True)
    RF.forget(name)
    if (VAULT / "repos" / name).is_dir():                  # the vault's history keeps it (SN-09)
        shutil.rmtree(VAULT / "repos" / name, ignore_errors=True)


def main(argv):
    if len(argv) == 3 and argv[1] == "run":
        return run(argv[2])
    if len(argv) == 3 and argv[1] == "start":
        r = start(argv[2], "make")
        print(f"{r['repo']}: " + ("already running" if r["already"] else "started"))
        return 0
    if len(argv) >= 2 and argv[1] == "fix-headings":    # BLD-39: repair the guides on disk once, without a model
        for name, n in fix_headings(argv[2:] or None).items():
            print(f"{name}: {n} section titles made headings")
        return 0
    if len(argv) == 2 and argv[1] == "all":
        for d in sorted(CODE.iterdir()):
            if (d / ".git").exists() and status(d.name)["status"] != "done":
                print(d.name, start(d.name, "make")["already"] and "already running" or "started")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

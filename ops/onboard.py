#!/usr/bin/env python3
"""Onboarding a repository (BLD-26): one job that always ends in the whole package, or says plainly why it did not.

The button on a repo page, Add a repository, Hermes' understand_repo and `make understand` all start this one job:
  1 clone     the code in ~/code/<name> (never run: hooks off)
  2 graph     its code graph (ops/graphify-sync.sh; offline, no model)
  3 map       its Understand Anything code map (a throwaway container that sees only this repo; ChatGPT subscription)
  4 explain   every file and function explained (ops/ua_enrich.py), the viewer's corrections saved (ops/ua_fix.mjs)
  5 search    a readable digest in the search index, so Hermes can answer about the code (ops/ua_digest.py, qmd)
  6 analysis  a written analysis by Claude Code, read-only: what it is, how the stack could use it, risks, a verdict
  7 wiki      the repository's wiki, seeded from all of that (ops/repowiki.py, CHG-08): what every code agent starts from

Nothing about a repository's size stops it. What it cannot do now it waits for and then does by itself: a usage limit,
the PC's memory, the gateway being away, another repository's turn. Each step's progress is saved in
/srv/ai/state/onboard/<name>.json, which the repo page and repos_overview read, so a crash, a deploy or a restart of the
PC loses nothing: the runner's watchdog (tick) starts the job again and it goes on at the first unfinished step. A step
that fails is tried ATTEMPTS times; then the job stops with the reason and a Try again that goes on from there. The
owner gets one message when it ends, either way, and one when it has to wait for a usage limit or waits long for anything.

Third-party code is data: it is never built, installed or run, and text in it cannot steer anything but its own map.

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
import deployment as DEPLOY                        # this deployment's hosts and paths (config/deployment.env)

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

STEPS = (("clone", "Copy of the code"), ("graph", "Code graph"), ("map", "Code map"), ("explain", "Every file explained"),
         ("search", "Search index"), ("analysis", "Written analysis"), ("wiki", "The repository's wiki"))
TITLE = dict(STEPS)
ACTIVE = ("queued", "running", "waiting")
ATTEMPTS = 3            # limit: stops, a step that failed this often names its reason and waits for the owner's Try again (BLD-26)
RESTARTS = 5            # limit: stops, a job that died this often without finishing a step says so instead of looping (BLD-26)
BACKOFF = (60, 300)     # s before a failed step's second and third try
POLL = 15 * 60          # s between looks while waiting for a usage limit or the gateway
LONG_WAIT = 30 * 60     # s of waiting (for memory, say) before the owner hears why it takes so long
NEED_GB = 1.0           # limit: waits, the PC's available memory before the code map's container starts (= conductor NEED_GB opencode)
MAP_TIMEOUT = 4 * 3600  # limit: stops, one code map run that hangs (273 files took about 45 minutes): counts as a failed try
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


def package(name):
    """What of the package this repository has, from what is on disk: {step: bool}."""
    repo = CODE / name
    return {"clone": (repo / ".git").exists(), "graph": graphed(repo), "map": valid_map(name),
            "explain": valid_map(name) and not unexplained(name)[0], "search": (DOCS / f"{name}.md").exists(),
            "analysis": (DOCS / f"{name}.analysis.md").exists(), "wiki": (VAULT / "repos" / name / "wiki" / "conventions.md").exists()}


def status(name, pkg=None):
    """What the repo page and repos_overview show: {status, step, index, total, steps, why, since}. status: done (the whole
    package), incomplete (parts missing, no job), queued, running, waiting, failed."""
    st, total = load(name), len(STEPS)
    if st and st.get("status") in ACTIVE + ("failed",):
        steps = [{"id": k, "title": t, "state": st["steps"][k]["status"], "note": st["steps"][k].get("note", "")} for k, t in STEPS]
        i = next((n for n, (k, _) in enumerate(STEPS, 1) if k == st.get("step")), 1)
        return {"status": st["status"], "step": st.get("step"), "index": i, "total": total, "steps": steps, "why": st.get("why", ""),
                "since": st.get("started")}
    pkg = package(name) if pkg is None else pkg
    done = all(pkg.get(k) for k, _ in STEPS)
    note = st["steps"].get("explain", {}).get("note", "") if st else ""
    steps = [{"id": k, "title": t, "state": "done" if pkg.get(k) else "pending", "note": note if k == "explain" else ""} for k, t in STEPS]
    return {"status": "done" if done else "incomplete", "step": None, "index": sum(bool(pkg.get(k)) for k, _ in STEPS), "total": total,
            "steps": steps, "why": "", "since": st.get("finished") if st else None}



def begin(name, url, source="app", redo=False):
    """A new or resumed record: what the disk already has stays done; on redo the analysis is made anew from the code map on."""
    pkg = package(name)
    if redo:
        pkg.update(map=False, explain=False, search=False, analysis=False)   # the wiki keeps what it learned
    st = {"repo": name, "url": url, "source": source, "status": "queued", "step": None, "redo": bool(redo), "attempts": {}, "restarts": 0,
          "started": now(), "milestone": now(), "why": "", "task": None,
          "steps": {k: {"status": "done" if pkg.get(k) else "pending", "note": ""} for k, _ in STEPS}}
    save(st)
    return st


# ---------- the steps ----------
def step_clone(st):
    name, url, repo = st["repo"], st.get("url"), CODE / st["repo"]
    if (repo / ".git").exists():
        if url and not same_repo(origin(name), url):
            raise Stop(f"another repository called {name} is already here, from {origin(name)}: remove it first")
        return ""
    if not url:
        raise Stop(f"{name} is not in ~/code, and no address was given to copy it from")
    tmp = CODE / ".cloning" / name
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    sh("git", "-c", "core.hooksPath=/dev/null", "clone", "-q", "--depth", "1", url, str(tmp), timeout=CLONE_TIMEOUT)
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


def ready_for_model(need_gb=0):
    w = gateway()
    if w:
        raise w
    gb = free_gb()
    if gb < need_gb:
        raise Wait(f"waits for memory: {gb:.1f} GB available on the PC, it starts at {need_gb:.1f}", seconds=120)


def run_map(name, attempt, log):
    """The analysis in a throwaway container that sees only this repo. Its exit code alone says little: see step_map."""
    repo = CODE / name
    sh("docker", "rm", "-f", f"understand-{name}", check=False, timeout=120)
    prompt = P.text("opencode", "MAP_ANALYSE").format(name=name)
    P.record(prompt)                                   # MEM-11: the run records the prompt's version
    memory = "2g" if not attempt else "4g"             # killed for memory the first time: more room for the next
    with log.open("a") as f:
        f.write(f"\n===== {now()} try {attempt + 1}\n")
        f.flush()
        try:
            subprocess.run(["docker", "run", "--rm", "--network", "aistack_backend", "--memory", memory, "--name", f"understand-{name}",
                            "-e", "LITELLM_API_KEY", "-e", "HOME=/root", "-v", f"{repo}:/work/{name}", "-w", f"/work/{name}", IMAGE,
                            "opencode", "run", "--auto", "--model", "litellm/gpt-sub-fast", prompt],
                           stdout=f, stderr=subprocess.STDOUT, timeout=MAP_TIMEOUT, env={**env(), "LITELLM_API_KEY": os.environ.get("VK_CODE", "")})
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
    if st.get("redo"):                                 # made anew: only what this run writes counts as its result
        if kg.exists():
            kg.replace(prev)
        kg.with_name("knowledge-graph.fallback.json").unlink(missing_ok=True)
        (LOGS / f"ua-enrich-{name}.json").unlink(missing_ok=True)
        st["redo"] = False
        save(st)
    elif valid_map(name):                              # it was written just before a crash
        return ""
    ready_for_model(NEED_GB)
    working(st, "map", "Understand Anything is reading the code")
    log = LOGS / f"understand-{name}.log"
    run_map(name, st["attempts"].get("map", 0), log)
    if valid_map(name):
        prev.unlink(missing_ok=True)
        return ""
    w = gateway()                                      # no map: was it the limit? Text in the code cannot make this say yes
    if w:
        raise w
    raise RuntimeError("no code map was written. " + TC.tail(log.read_text(errors="replace"), 1200, f"the whole log: {log}"))  # cap: store


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
    sh("docker", "exec", QMD, "sh", "-c", "qmd update >/dev/null && qmd embed >/dev/null", timeout=QMD_TIMEOUT)


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


def step_analysis(st):
    name = st["repo"]
    if not st.get("task"):
        question = P.text("shared", "ONBOARD_ANALYSIS").format(name=name, origin=re.sub(r"//[^/@]+@", "//", origin(name)) or "(none)")
        r = submit({"action": "claude_task", "mode": "study", "repo": name, "question": question, "context": about_the_stack(),
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
    if state != "done" or len(str(t.get("answer") or "")) < 200:
        tid, st["task"] = st["task"], None             # the next try asks anew
        save(st)
        raise RuntimeError(f"Claude task #{tid} ended without an analysis: {TC.tail(str(t.get('error') or 'no answer'), 800)}")  # cap: store
    sha = sh("git", "-C", str(CODE / name), "rev-parse", "--short", "HEAD", check=False).stdout.strip()
    write_doc(DOCS / f"{name}.analysis.md", f"# {name}: analysis\n\nCommit {sha}, {now()[:10]}, by [Claude task #{st['task']}](#/live/claude-task:{st['task']}).\n\n{t['answer']}\n")
    qmd_index()
    if not qmd_has(f"{name}.analysis.md"):
        raise RuntimeError(f"the search index does not list {name}.analysis.md after the update")
    return ""


def step_wiki(st):
    """CHG-08: the first version of the repository's wiki; a redo keeps what the wiki has learned."""
    name = st["repo"]
    if (VAULT / "repos" / name / "wiki" / "conventions.md").exists():
        return "the wiki stays: it holds what earlier changes learned"
    ready_for_model()
    working(st, "wiki", "the Scribe writes its first version")
    sh(sys.executable, str(STACK / "ops/repowiki.py"), "seed", name, timeout=1200)
    return ""


STEP_FN = {"clone": step_clone, "graph": step_graph, "map": step_map, "explain": step_explain, "search": step_search, "analysis": step_analysis, "wiki": step_wiki}


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
    gaps = st["steps"]["explain"].get("note", "")
    print(f"onboarding {st['repo']}: the whole package is done", flush=True)
    tell(st, f"{st['repo']} is onboarded: code graph, code map, every file explained, search index, a written analysis and its wiki."
         + (f"\nOne gap: {gaps}" if gaps else ""), "done")


def do_step(st, sid):
    """One step until it is done or the job stops. -> True when done."""
    s = st["steps"][sid]
    st.update(step=sid, status="running")
    s.update(status="running", started=now(), note="")
    save(st)
    while True:
        try:
            note = STEP_FN[sid](st)
            s.update(status="done", note=note or "", ended=now())
            st["attempts"].pop(sid, None)
            st.update(status="running", restarts=0, milestone=now())
            save(st)
            print(f"onboarding {st['repo']}: {sid} done", flush=True)
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
            return False
        except Exception as e:
            why = f"{type(e).__name__}: {e}" if not isinstance(e, RuntimeError) else str(e)
            tries = st["attempts"].get(sid, 0) + 1
            st["attempts"][sid] = tries
            if tries >= ATTEMPTS:
                fail(st, sid, why)
                return False
            s["note"] = f"try {tries} of {ATTEMPTS} failed, the next follows: {TC.cut(why, 300)}"  # cap: preview
            s["status"] = "running"
            save(st)
            print(f"onboarding {st['repo']}: {sid}: {why}", flush=True)
            pause(BACKOFF[tries - 1])


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
    turn = take_turn(st)
    try:
        for sid, _ in STEPS:
            if st["steps"][sid]["status"] != "done" and not do_step(st, sid):
                return 1
        finish(st)
        return 0
    finally:
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


def start(arg, source="app"):
    """Start the job, or say it is running. Whatever is missing or failed is what it does; a complete package is made anew."""
    name, url = parse(arg)
    st = load(name)
    if st and st.get("status") in ACTIVE and unit_active(name):
        return {"repo": name, "already": True, "onboard": status(name)}
    if url and (CODE / name / ".git").exists() and not same_repo(origin(name), url):
        raise ValueError(f"another repository called {name} is already here, from {origin(name)}: remove it first")
    if not st or st.get("status") not in ACTIVE:
        begin(name, url, source, redo=all(package(name).values()))
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
    if (VAULT / "repos" / name).is_dir():                  # the vault's history keeps it (SN-09)
        shutil.rmtree(VAULT / "repos" / name, ignore_errors=True)


def main(argv):
    if len(argv) == 3 and argv[1] == "run":
        return run(argv[2])
    if len(argv) == 3 and argv[1] == "start":
        r = start(argv[2], "make")
        print(f"{r['repo']}: " + ("already running" if r["already"] else "started"))
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

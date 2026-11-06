"""Code repositories for Mission Control's Code tab (ops/missions.py sets M to itself and routes the repo_* / codemap
requests here; builds.py does the building).

  repos      -> every repo the stack knows: ai-stack and ~/code/*, with whether the builder may change it (its origin is
                Forgejo), its code graph (Graphify, ~/code/<repo>/graphify-out/graph.json), its code map (Understand
                Anything, <repo>/.ua/), its digest for search (/srv/ai/code-docs/<repo>.md) and its last commit
  codemap    -> show one repo in the code map viewer (ops/understand-dashboard.sh; behind the tailnet gate, no token)
  repo_create, repo_buildable -> need a Forgejo token (FORGEJO_TOKEN, made once by the owner): a new private repo on
                Forgejo cloned to ~/code, or a studied GitHub repo moved to Forgejo so the builder can change it
Studying a repo is ops/onboard.py (the "understand" action in ops/missions.py): the whole package, shown step by step.
ai-stack itself is studied through a read-only mirror clone in ~/code/ai-stack (kept current by ops/graphify-sync.sh).
"""
import json, os, re, subprocess, time
from pathlib import Path
from textcap import tail                    # visible caps and input limits (AGENTS.md, truncation)
import textcap as TC
import onboard as O

M = B = None
CODE = Path.home() / "code"
STACK = Path.home() / "ai-stack"
DOCS = Path("/srv/ai/code-docs")
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,99}$")   # as GitHub allows: a studied repository must stay removable
_cache = {"t": 0, "data": []}


def token():
    return os.environ.get("FORGEJO_TOKEN") or os.environ.get("FORGEJO_PR_TOKEN") or ""


def git(path, *args):
    p = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=600)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(args[:2])}: {tail((p.stderr or p.stdout).strip(), 4000)}")  # cap: store
    return p.stdout.strip()


def clean_url(u):
    return re.sub(r"//[^/@]+@", "//", u or "")          # never show credentials embedded in a URL


def one(name):
    live = STACK if name == "ai-stack" else CODE / name
    study = CODE / name                                      # where graph, code map and the mirror of ai-stack live
    graph = study / "graphify-out" / "graph.json"
    info = {"name": name, "buildable": name in B.repos(), "source": clean_url(B.origin(name)), "graph": None,
            "codemap": (study / ".ua" / "knowledge-graph.json").exists(), "digest": (DOCS / f"{name}.md").exists(), "last": None}
    try:                                                     # ops/ua_enrich.py: how much of the code map is explained
        e = json.loads(Path(f"/srv/ai/state/ua-enrich-{name}.json").read_text())
        info["explained"] = {k: e.get(k) for k in ("status", "files", "explained", "updated")}
    except Exception:
        pass
    try:
        g = json.loads(graph.read_text())
        info["graph"] = {"nodes": len(g.get("nodes", [])), "links": len(g.get("links", [])),
                         "communities": len({n.get("community") for n in g.get("nodes", [])}), "built": int(graph.stat().st_mtime)}
    except Exception:
        pass
    try:
        sha, ts, subject = git(live, "log", "-1", "--format=%h%x09%cI%x09%s").split("\t", 2)
        info["last"] = {"sha": sha, "ts": ts, "subject": subject}
        info["files"] = len(git(live, "ls-files").splitlines())
    except Exception:
        pass
    info["no_code"] = (study / "graphify-out" / ".no-code").exists()      # only web pages or documents: nothing to graph
    info["package"] = O.package(name)                        # what it has on disk; the job's own record is laid over it (state)
    return info


def repos(force=False):
    stale = _cache.get("milestone") != O.last_milestone()     # a job finished a step: what is on disk changed
    arrived = any(n not in {r["name"] for r in _cache["data"]} and (CODE / n / ".git").exists() for n in O.active())
    if force or stale or arrived or time.time() - _cache["t"] > 120:
        _cache["milestone"] = O.last_milestone()
        names = ["ai-stack"] + sorted(d.name for d in CODE.iterdir() if (d / ".git").exists() and d.name != "ai-stack") if CODE.exists() else ["ai-stack"]
        _cache.update(t=time.time(), data=[one(n) for n in names], codemap=codemap_repo())
    return _cache["data"]


def codemap_repo():
    """Which repo the code map viewer shows now (it shows one at a time)."""
    p = subprocess.run(["docker", "inspect", "-f", "{{range .Mounts}}{{.Source}} {{end}}", "aistack-ua-viewer"], capture_output=True, text=True)
    m = re.search(r"/code/([^/\s]+)", p.stdout)
    return m[1] if m else None


def forgejo_owner():
    return (B.forgejo("GET", "/user") or {}).get("login")


def handle(req, c):
    a = req["action"]
    if a == "codemap":
        name = str(req.get("repo", ""))
        if not (CODE / name / ".ua" / "knowledge-graph.json").exists():
            raise ValueError(f"{name} has no code map yet: analyse it first")
        p = subprocess.run([str(STACK / "ops/understand-dashboard.sh"), name], capture_output=True, text=True, timeout=120)
        if p.returncode:
            raise ValueError(f"code map did not start: {tail((p.stderr or p.stdout).strip(), 4000)}")  # cap: store
        _cache["codemap"] = name
        return {"repo": name}
    if a == "repo_remove":
        return remove(str(req.get("repo", "")), c)
    if a not in ("repo_create", "repo_buildable"):
        raise ValueError("unknown repo action")
    if not token():
        raise ValueError("this needs a Forgejo token once: see 'Connect Forgejo' in the Code tab")
    owner = forgejo_owner()
    if a == "repo_create":
        name = str(req.get("name", "")).strip().lower()
        if not NAME.match(name) or (CODE / name).exists() or name == "ai-stack":
            raise ValueError("give a new name: lowercase letters, digits, . _ - (2-41 characters)")
        desc = TC.fit(re.sub(r"\s+", " ", str(req.get("description", ""))).strip(), 200)  # cap: api
        B.forgejo("POST", "/user/repos", {"name": name, "description": desc, "private": True, "auto_init": True,
                                          "default_branch": "main", "readme": "Default"})
        subprocess.run(["git", "clone", "-q", f"forgejo:{owner}/{name}.git", str(CODE / name)], check=True, capture_output=True, timeout=300)
        (CODE / name / "AGENTS.md").write_text(f"# {name}\n\n{desc or 'A new repository.'}\n\nRules for coding agents working here: keep "
                                               "changes small, add tests with every behaviour change, and keep this file current.\n")
        git(CODE / name, "add", "AGENTS.md")
        git(CODE / name, "commit", "-qm", "Add AGENTS.md for coding agents")
        git(CODE / name, "push", "-q", "origin", "HEAD")
        M.event("code", "", f"New repository {name} on Forgejo: the builder can work on it", title="Code")
        repos(force=True)
        return {"repo": name}
    name = str(req.get("repo", ""))
    path = CODE / name
    if not (path / ".git").exists() or name == "ai-stack" or name in B.repos():
        raise ValueError("give a studied repository in ~/code that is not on Forgejo yet")
    B.forgejo("POST", "/user/repos", {"name": name, "private": True, "description": f"from {clean_url(B.origin(name))}"})
    if git(path, "rev-parse", "--is-shallow-repository") == "true":
        git(path, "fetch", "-q", "--unshallow")
    git(path, "remote", "rename", "origin", "upstream")
    git(path, "remote", "add", "origin", f"forgejo:{owner}/{name}.git")
    git(path, "push", "-q", "-u", "origin", "HEAD:main")
    M.event("code", "", f"{name} is now on Forgejo: the builder can work on it (the original stays as 'upstream')", title="Code")
    repos(force=True)
    return {"repo": name}


def remove(name, c):
    """Take a repository out of the stack: its clone in ~/code (with graph and code map), its digest, the builder's
    workbench copy and its graph state. Never ai-stack, never while a build of it runs, and never anything on Forgejo:
    a repo that lives there stays there (delete it in Forgejo yourself if you want it gone)."""
    path = CODE / name
    if not NAME.match(name.lower()) or name == "ai-stack" or not (path / ".git").exists() or path.resolve().parent != CODE.resolve():
        raise ValueError("give a repository from the Code tab (ai-stack itself cannot be removed)")
    busy = c.execute("select id from builds where repo=? and status in ('queued','working','checking','recheck','approved','deploying')",
                     (name,)).fetchone() if c else None
    if busy:
        raise ValueError(f"build #{busy[0]} of {name} is still running; wait for it or reject it first")
    on_forgejo = name in B.repos()
    if _cache.get("codemap") == name:
        subprocess.run(["docker", "rm", "-f", "aistack-ua-viewer", "aistack-ua-viewer-port"], capture_output=True)
        _cache["codemap"] = None
    for p in (path, B.WB / name):
        if p.exists():
            # files written by containers can belong to other uids: let the builder (container root) clear its copy first
            if p == B.WB / name:
                subprocess.run(["docker", "exec", "-u", "0", B.BUILDER, "rm", "-rf", f"/work/{name}"], capture_output=True, timeout=300)
            subprocess.run(["rm", "-rf", str(p)], check=False, timeout=300)
    O.forget(name)                                           # its job, its records and its analysis
    for p in (DOCS / f"{name}.md", Path("/srv/ai/state/graphify") / f"{name}.head"):
        p.unlink(missing_ok=True)
    if path.exists():
        raise ValueError(f"could not remove everything in {path}; some files belong to another user")
    M.event("code", "", f"{name} removed from the stack" + (" (it stays on Forgejo)" if on_forgejo else ""), title="Code")
    repos(force=True)
    return {"removed": name, "still_on_forgejo": on_forgejo}


def state():
    rows = [{**r, "onboard": O.status(r["name"], r.get("package"))} for r in repos()]     # live, every state write
    return {"code": {"repos": rows, "codemap": _cache.get("codemap"), "forgejo_token": bool(token())}}

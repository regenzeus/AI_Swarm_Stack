"""Packs (GEN-21, GEN-32, docs/AI-STACK.md): a domain kept outside the stack's repository, pinned by commit and
approved per commit before it runs.

A pack is a Claude Code plugin folder plus what only the stack knows:
    .claude-plugin/plugin.json   its name (the pack's name), version, description
    agents/<name>.md             agents, Claude Code's subagent format          -> named <pack>:<name>
    skills/<name>/SKILL.md       skills                                        -> named <pack>:<name>
    .mcp.json                    MCP servers its agents may use
    stack.yaml                   each agent's harness and model alias
    jobs/<file>.json             job kinds of the worker protocol (ops/winjobs.py) -> named <pack>.<kind>
    workflows/<name>.json        n8n workflows, as n8n exports them             -> named <pack>/<name>
    exams/<set>.yaml             cases with their known outcome

The deployment lists its packs in packs.txt beside its deployment.env, one per line: name, source (a git URL or a
folder holding a git repository), commit. Each commit is checked out once, read-only, under CACHE/<name>@<commit>.

Trust: a commit runs only once the owner approved it (one decision in the queue, with the manifest, the prompts, the
commands and the diff from the commit that runs now; a security floor, it always asks). Until then the last approved
commit of that pack keeps running; a pack never approved does not run. A refused commit stays refused. Job kinds are
still copied to each worker and approved there by their hash, so a command never runs on the pack's word alone.

Names: a pack's name is letters, digits and dashes; a pack named like a core agent or another pack is refused with the
reason, and so is a pack whose manifest names another pack. Everything it brings is namespaced by its name, so packs
cannot clash with each other or with the core; a workflow's webhooks listen under item/<pack>/ or <pack>/ only. A
workflow may not use n8n's command node: commands run only at places, approved by their hash (GEN-22, WFL-03). A
deployment whose n8n loads only listed nodes (N8N_NODES_INCLUDE, read by the data guard: dataguard.n8n_nodes(), WFL-17)
refuses a workflow with any other node, with the reason (GEN-42).

In n8n (GEN-43, ops/n8n_sync.py sync_packs): the running commit's workflows are imported, each under an id made from its
name, published or not as its file says; an approval or a refusal syncs at once, a deploy too. An edit on the canvas is
a proposal, never what runs: it goes to the pack's own repository as a branch (ai/canvas-<date>) and, where the pack's
forge allows, a draft pull request (propose), and the approved version is imported again. It runs once a commit with
it is approved.

    entries(path)        packs.txt -> [{name, source, commit}]
    load()               -> {"packs": [active pack], "pending": [decision], "refused": [{name, commit, why}]}
    view(loaded)         the same for the app's state: no folders or file paths
    approve(name, commit, who) / refuse(name, commit, who, why)   a refusal also withdraws that commit's approval
    plugin_args(pack)    Claude Code's arguments for a step of one of its agents
    handle(req)          the app's actions: pack_approve, pack_refuse (each syncs n8n)
    propose(pack, files) canvas edits -> a branch and a draft pull request in the pack's repository
"""
import datetime as dt
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import textcap as TC  # noqa: E402
import winjobs as WJ  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
NAME = re.compile(r"[a-z][a-z0-9-]{1,30}")
HEX = re.compile(r"[0-9a-f]{7,40}")
DIFF_CHARS = 60000              # cap: preview, the diff shown with a decision; the whole is in the pack's repository
GIT_S = 300                     # limit: stops, a clone or fetch of a pack that takes longer fails with the reason
NO_NODES = ("n8n-nodes-base.executeCommand", "n8n-nodes-base.localFileTrigger")   # off in the stack's n8n (WFL-03)
WEBHOOK = "n8n-nodes-base.webhook"


def _deployment():
    import deployment as D
    return D.chosen()


def n8n_nodes(values=None):
    """The node types the deployment's n8n loads, as a set, from the data guard's one reading of it
    (dataguard.n8n_nodes: N8N_NODES_INCLUDE, handed to n8n as NODES_INCLUDE), or None: n8n loads its nodes less
    NO_NODES. A line that is no JSON list of node types -> ValueError with the data guard's reason."""
    try:
        import dataguard as DG
        got = DG.n8n_nodes(values)
    except SystemExit as e:                          # the data guard's refusal (or no data.yaml), as a pack's problem
        raise ValueError(str(e)) from None
    return None if got is None else set(got)


def packs_txt():
    return Path(os.environ.get("AISTACK_PACKS_TXT") or _deployment() / "packs.txt")


def cache():
    return Path(os.environ.get("AISTACK_PACKS") or Path.home() / ".local/share/aistack/packs")


def approvals_path():
    return Path(os.environ.get("AISTACK_PACK_APPROVALS") or "/srv/ai/state/pack-approvals.json")


def entries(path=None):
    path = Path(path or packs_txt())
    out = []
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            parts = line.split()
            out.append({"name": parts[0], "source": parts[1] if len(parts) > 1 else "", "commit": parts[2] if len(parts) > 2 else ""})
    return out


def core_names():
    """What a pack may not be named: the core's agents and the core's own names. home is the stack's own item
    workflows' (their webhooks item/home/<name>, n8n/workflows/item-home-<name>.json); item and run are n8n's webhook
    roots (item/<pack>/<name>, run/<file>), which a pack's own namespace <pack>/ would otherwise cover."""
    try:
        reg = yaml.safe_load((ROOT / "config/agents.yaml").read_text()) or {}
    except OSError:
        reg = {}
    return {str(a.get("id")) for a in reg.get("agents") or []} | {"core", "home", "stack", "item", "run"}


# ---------- approvals ----------
def _approvals(path=None):
    p = Path(path or approvals_path())
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _write(d, path=None):
    p = Path(path or approvals_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, sort_keys=True))
    tmp.replace(p)


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def approve(name, commit, who, path=None):
    d = _approvals(path)
    rec = d.setdefault(name, {"approved": [], "refused": []})
    if not any(a["commit"] == commit for a in rec["approved"]):
        rec["approved"].append({"commit": commit, "who": who, "at": _now()})
    rec["refused"] = [r for r in rec["refused"] if r["commit"] != commit]
    _write(d, path)


def refuse(name, commit, who, why="", path=None):
    """A refusal also withdraws the commit's approval: its workflows leave n8n, and the pack's last other approved
    commit runs, if any."""
    d = _approvals(path)
    rec = d.setdefault(name, {"approved": [], "refused": []})
    rec["approved"] = [a for a in rec["approved"] if a["commit"] != commit]
    if not any(r["commit"] == commit for r in rec["refused"]):
        rec["refused"].append({"commit": commit, "who": who, "at": _now(), "why": TC.cut(str(why or ""), 300)})   # cap: store
    _write(d, path)


# ---------- git ----------
def _git(*args, cwd=None):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=GIT_S)
    if p.returncode:
        raise ValueError(f"git {args[0]}: {TC.cut((p.stderr or p.stdout).strip(), 300)}")   # cap: preview
    return p.stdout


def _bare(e, base):
    """The pack's repository, fetched into the cache (a bare clone), with its commit there."""
    bare = base / f"{e['name']}.git"
    src = e["source"]
    if src and not re.match(r"^[a-z]+://|^[\w.-]+@[\w.-]+:", src):
        src = str(Path(src).expanduser().resolve())
    if not bare.is_dir():
        base.mkdir(parents=True, exist_ok=True)
        _git("clone", "--quiet", "--bare", src, str(bare))
    try:
        _git("rev-parse", "--verify", "--quiet", f"{e['commit']}^{{commit}}", cwd=bare)
    except ValueError:
        _git("fetch", "--quiet", src, "+refs/heads/*:refs/heads/*", cwd=bare)
    return bare


def checkout(e, base=None):
    """-> (the full commit, its read-only folder). Refuses a commit that is no commit of the source."""
    base = Path(base or cache())
    if not HEX.fullmatch(e.get("commit") or ""):
        raise ValueError(f"pack {e['name']}: the commit is 7 to 40 hex digits, not {e.get('commit')!r}")
    bare = _bare(e, base)
    try:
        full = _git("rev-parse", "--verify", "--quiet", f"{e['commit']}^{{commit}}", cwd=bare).strip()
    except ValueError:
        raise ValueError(f"pack {e['name']}: commit {e['commit']} is not in {e['source']}") from None
    folder = base / f"{e['name']}@{full}"
    if not folder.is_dir():
        tmp = Path(tempfile.mkdtemp(prefix=f"{e['name']}-", dir=base))
        arch = subprocess.run(["git", "archive", full], cwd=bare, capture_output=True, timeout=GIT_S)
        if arch.returncode:
            raise ValueError(f"pack {e['name']}: git archive: {TC.cut(arch.stderr.decode(errors='replace'), 300)}")   # cap: preview
        subprocess.run(["tar", "-x", "-C", str(tmp)], input=arch.stdout, check=True, timeout=GIT_S)
        for p in [tmp, *tmp.rglob("*")]:                 # read-only: what runs is what was approved
            p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        tmp.rename(folder)
    return full, folder


_diffs = {}


def diff(e, old, new, base=None):
    if (e["name"], old, new) not in _diffs:
        _diffs[(e["name"], old, new)] = _diff(e, old, new, base)
    return _diffs[(e["name"], old, new)]


def _diff(e, old, new, base=None):
    """What changed from the commit that runs now to the new one (or the whole tree, for a pack's first commit)."""
    bare = _bare(e, Path(base or cache()))
    if old:
        text = _git("diff", "--stat", "--patch", old, new, cwd=bare)
    else:
        text = _git("show", "--stat", "--patch", "--format=%H %s", new, cwd=bare)
    return TC.cut(text, DIFF_CHARS)                    # cap: preview, the whole diff is in the pack's repository


# ---------- what a pack brings ----------
def _front(text):
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    try:
        return yaml.safe_load(m.group(1)) or {}, m.group(2)
    except yaml.YAMLError:
        return {}, m.group(2)


def _flow_problems(name, nodes, allow):
    """What keeps a pack's workflow out of n8n: a node n8n leaves off, a node off the deployment's allowlist, a webhook
    outside the pack's namespace."""
    types = {str(n.get("type")) for n in nodes if isinstance(n, dict)}
    banned = sorted(types & set(NO_NODES))
    if banned:
        return f"it uses {', '.join(banned)}, which the stack's n8n leaves off; a command runs at a place"
    off = sorted(types - allow) if allow is not None else []
    if off:
        return f"it uses {', '.join(off)}, which this deployment's n8n does not load (N8N_NODES_INCLUDE in its deployment.env)"
    paths = sorted(str((n.get("parameters") or {}).get("path") or "") for n in nodes if isinstance(n, dict) and n.get("type") == WEBHOOK)
    outside = [p for p in paths if not p.startswith((f"item/{name}/", f"{name}/"))]
    if outside:
        return f"its webhook path {outside[0]!r} is outside the pack's namespace (item/{name}/... or {name}/...)"
    return ""


def read(name, commit, folder, allow="deployment"):
    """A pack's contents, each named in its namespace, and what is wrong with it. allow: the node types the
    deployment's n8n loads (None: all but NO_NODES)."""
    folder = Path(folder)
    problems = []
    if allow == "deployment":
        try:
            allow = n8n_nodes()
        except ValueError as e:                      # no workflow of the pack loads until the deployment's list is right
            allow = frozenset()
            problems.append(f"workflows: {e}")
    try:
        man = json.loads((folder / ".claude-plugin/plugin.json").read_text())
    except (OSError, ValueError) as e:
        man = {}
        problems.append(f"no Claude Code manifest (.claude-plugin/plugin.json): {type(e).__name__}")
    if man and man.get("name") != name:
        problems.append(f"its manifest names it {man.get('name')!r}, and packs.txt names it {name!r}")
    try:
        st = yaml.safe_load((folder / "stack.yaml").read_text()) or {}
    except OSError:
        st = {}
    agents = []
    for f in sorted((folder / "agents").glob("*.md")):
        front, body = _front(f.read_text(encoding="utf-8"))
        cfg = (st.get("agents") or {}).get(f.stem) or {}
        agents.append({"id": f"{name}:{f.stem}", "name": str(front.get("name") or f.stem), "purpose": str(front.get("description") or ""),
                       "harness": str(cfg.get("harness") or "claude-code"), "model": str(cfg.get("model") or ""), "prompt": body.strip(),
                       "pack": name})
    skills = [{"id": f"{name}:{f.parent.name}", "purpose": str(_front(f.read_text(encoding="utf-8"))[0].get("description") or "")}
              for f in sorted((folder / "skills").glob("*/SKILL.md"))]
    jobs = []
    for f in sorted((folder / "jobs").glob("*.json")):
        try:
            k = json.loads(f.read_text())
        except ValueError as e:
            problems.append(f"jobs/{f.name}: not JSON ({e})")
            continue
        bad = WJ.kind_problems(k)
        if not str(k.get("kind") or "").startswith(f"{name}."):
            bad.append(f"its kind is named {name}.<something>, not {k.get('kind')!r}")
        problems += [f"jobs/{f.name}: {b}" for b in bad]
        jobs.append({"kind": k.get("kind"), "about": k.get("about", ""), "file": str(f), "sha256": WJ.digest(f), "spec": k})
    workflows = []
    for f in sorted((folder / "workflows").glob("*.json")):
        try:
            w = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            problems.append(f"workflows/{f.name}: not JSON ({e})")
            continue
        nodes = w.get("nodes") if isinstance(w, dict) else None
        if not isinstance(nodes, list) or not isinstance(w.get("connections"), dict):
            problems.append(f"workflows/{f.name}: not an n8n workflow (it has no nodes and connections)")
            continue
        wname = str(w.get("name") or "")
        if not wname.startswith(f"{name}/"):
            problems.append(f"workflows/{f.name}: a pack's workflow is named {name}/<something>, not {wname!r}")
            continue
        bad = _flow_problems(name, nodes, allow)
        if bad:
            problems.append(f"workflows/{f.name}: {bad}")
            continue
        workflows.append({"name": wname, "path": str(f), "nodes": len(nodes), "active": bool(w.get("active"))})
    try:
        mcp = sorted((json.loads((folder / ".mcp.json").read_text()).get("mcpServers") or {}))
    except (OSError, ValueError):
        mcp = []
    exams = sorted(f.stem for f in (folder / "exams").glob("*.yaml"))
    return {"name": name, "commit": commit, "dir": str(folder), "version": str(man.get("version") or ""),
            "about": str(man.get("description") or ""), "agents": agents, "skills": skills, "jobs": jobs,
            "workflows": workflows, "mcp": mcp, "exams": exams, "problems": problems}


def load(txt=None, base=None, approvals=None):
    """The deployment's packs: those that run (each at its approved commit), the commits waiting for the owner, and
    what is refused with its reason."""
    core, seen = core_names(), set()
    packs, pending, refused = [], [], []
    rec = _approvals(approvals)
    for e in entries(txt):
        name = e["name"]
        why = ("its name is letters, digits and dashes, starting with a letter" if not NAME.fullmatch(name)
               else "a core agent or a name of the core has that name" if name in core
               else "another pack in packs.txt has that name" if name in seen else "")
        if why:
            refused.append({"name": name, "commit": e.get("commit", ""), "why": f"pack {name}: {why}"})
            continue
        seen.add(name)
        try:
            full, folder = checkout(e, base)
        except (ValueError, OSError, subprocess.SubprocessError) as x:
            refused.append({"name": name, "commit": e.get("commit", ""), "why": str(x)})
            continue
        r = rec.get(name) or {}
        ok = [a["commit"] for a in r.get("approved") or []]
        no = {x["commit"]: x for x in r.get("refused") or []}
        runs = full if full in ok else (ok[-1] if ok else "")
        if full not in ok:
            if full in no:
                refused.append({"name": name, "commit": full, "why": f"pack {name}: commit {full[:12]} was refused by {no[full]['who']}"
                                + (f": {no[full]['why']}" if no[full].get("why") else "")})
            else:
                p = read(name, full, folder)
                pending.append({"name": name, "commit": full, "runs": runs, "version": p["version"], "about": p["about"],
                                "agents": [{"id": a["id"], "purpose": a["purpose"], "prompt": a["prompt"]} for a in p["agents"]],
                                "jobs": [{"kind": j["kind"], "about": j["about"], "spec": j["spec"]} for j in p["jobs"]],
                                "workflows": [w["name"] for w in p["workflows"]], "skills": [s["id"] for s in p["skills"]],
                                "problems": p["problems"], "diff": diff(e, runs, full, base)})
        if runs:
            try:
                _, rf = checkout({**e, "commit": runs}, base)
                packs.append({**read(name, runs, rf), "source": e["source"]})
            except (ValueError, OSError, subprocess.SubprocessError) as x:
                refused.append({"name": name, "commit": runs, "why": str(x)})
    return {"packs": packs, "pending": pending, "refused": refused}


def view(loaded=None):
    """What the app shows (the Stack page's Packs and trackers): each running pack with what it brings, each commit
    waiting for the owner with everything needed to decide it, and what is refused with why. No folders or file paths."""
    L = loaded or load()
    run = [{**{k: p[k] for k in ("name", "commit", "version", "about", "mcp", "exams", "problems")},
            "agents": [{k: a[k] for k in ("id", "purpose", "harness", "model", "prompt")} for a in p["agents"]],
            "skills": [s["id"] for s in p["skills"]], "jobs": [{k: j[k] for k in ("kind", "about", "spec")} for j in p["jobs"]],
            "workflows": [w["name"] for w in p["workflows"]]} for p in L["packs"]]
    return {"packs": run, "pending": L["pending"], "refused": L["refused"]}


def cards(packs=None):
    """The running packs' agents as cards a step may name (<pack>:<agent>): harness, model and the agent's own prompt."""
    return {a["id"]: {"id": a["id"], "harness": a["harness"] or "claude-code", "model": a["model"], "prompt": a["prompt"], "pack": p["name"]}
            for p in (load()["packs"] if packs is None else packs) for a in p["agents"]}


def decisions(make, loaded=None):
    """The queue's items (ops/decisions.py): one per pack commit waiting for the owner, a security floor."""
    for p in (loaded or load())["pending"]:
        short = p["commit"][:12]
        what = (f"Run pack {p['name']} at {short}?" if not p["runs"] else f"Update pack {p['name']} from {p['runs'][:12]} to {short}?")
        n = lambda xs, one: f"{len(xs)} {one}{'' if len(xs) == 1 else 's'}"   # noqa: E731
        why = (", ".join(n(p[k], w) for k, w in (("agents", "agent"), ("jobs", "command"), ("workflows", "workflow"), ("skills", "skill")) if p[k])
               + (f"; problems: {'; '.join(p['problems'])}" if p["problems"] else "") + (f"; {p['about']}" if p["about"] else ""))
        yield make(f"pack:{p['name']}@{short}", "pack-commit", what, why, f"#/system?tab=connections&pack={p['name']}",
                   unanswered=f"commit {p['runs'][:12]} keeps running" if p["runs"] else "the pack does not run",
                   answers=[{"label": "Look and decide", "href": f"#/system?tab=connections&pack={p['name']}"}])


def egress_hosts():
    """The deployment's egress list (egress.txt beside its deployment.env), or None: a deployment without one (home)
    limits no host."""
    p = Path(os.environ.get("AISTACK_EGRESS") or _deployment() / "egress.txt")
    if not p.is_file():
        return None
    return {x.split("#", 1)[0].strip().lower() for x in p.read_text().splitlines() if x.split("#", 1)[0].strip()}


def grants(pack, agent, egress="deployment"):
    """What a step of the pack's agent may use (GEN-30): exactly the MCP servers and tools its stack.yaml grants. A
    server on a host the egress list does not name is dropped, with the reason."""
    from urllib.parse import urlparse
    egress = egress_hosts() if egress == "deployment" else egress
    name = agent.split(":", 1)[-1]
    try:
        cfg = (yaml.safe_load((Path(pack["dir"]) / "stack.yaml").read_text()) or {}).get("agents", {}).get(name) or {}
    except OSError:
        cfg = {}
    try:
        servers = json.loads((Path(pack["dir"]) / ".mcp.json").read_text()).get("mcpServers") or {}
    except (OSError, ValueError):
        servers = {}
    keep, dropped = {}, []
    for s in cfg.get("mcp") or []:
        spec = servers.get(s)
        if spec is None:
            dropped.append(f"{s}: no such server in the pack's .mcp.json")
            continue
        host = (urlparse(spec.get("url", "")).hostname or "").lower()
        if host and egress is not None and host not in egress:
            dropped.append(f"{s}: its host {host} is not on this deployment's egress list")
            continue
        keep[s] = {k: v for k, v in spec.items() if k != "description"}
    tools = [str(t) for t in cfg.get("tools") or []] + [f"mcp__{s}" for s in keep]
    return {"mcp": {"mcpServers": keep}, "tools": tools, "dropped": dropped}


def plugin_args(pack, agent=None, egress="deployment"):
    """Claude Code's arguments for a step of one of the pack's agents: the pack is its plugin folder, and the step gets
    exactly its grants (no other MCP server, no other tool)."""
    args = ["--plugin-dir", str(pack["dir"])]
    if agent:
        g = grants(pack, agent, egress)
        args += ["--strict-mcp-config", "--mcp-config", json.dumps(g["mcp"]), "--allowedTools", ",".join(g["tools"])]
    return args


def sync_n8n():
    """n8n made to hold the running commits' workflows (ops/n8n_sync.py sync_packs). -> what changed, in lines."""
    import n8n_sync as NS
    return NS.sync_packs(load())


def handle(req, approvals=None):
    """The queue's answers. Each one syncs n8n at once (an approved commit's workflows arrive, a refused one's go); when
    n8n cannot be reached the decision still stands and the next deploy syncs it."""
    a = req.get("action")
    name, commit, who = str(req.get("name") or ""), str(req.get("commit") or ""), str(req.get("who") or "owner")
    if not NAME.fullmatch(name) or not HEX.fullmatch(commit):
        return {"ok": False, "error": "name a pack and its commit"}
    if a == "pack_approve":
        approve(name, commit, who, approvals)
        out = {"ok": True, "approved": commit}
    elif a == "pack_refuse":
        refuse(name, commit, who, req.get("why"), approvals)
        out = {"ok": True, "refused": commit}
    else:
        return {"ok": False, "error": f"unknown pack action {a}"}
    try:
        out["n8n"] = sync_n8n()
    except Exception as x:                           # n8n down or a pack's repository away: the decision stands, a deploy syncs
        out["n8n"] = [f"n8n not synced yet: {type(x).__name__}: {TC.cut(str(x), 300)}"]   # cap: preview, the reason
    return out


# ---------- canvas edits go back to the pack ----------
def propose(pack, files, forge=None, when=None):
    """Canvas edits of a running pack's workflows -> a branch ai/canvas-<date> in the pack's own repository (never the
    stack's), from the commit that runs (or on top of that day's branch), and a draft pull request into the pack's main
    branch where its forge knows the repository and holds a token. files: {path in the pack: text}.
    -> {"branch", "commit", "pr"}; nothing runs from it until a commit with it is approved."""
    day = (when or dt.datetime.now()).strftime("%Y-%m-%d")
    branch = f"ai/canvas-{day}"
    bare = cache() / f"{pack['name']}.git"
    src = pack["source"]
    if src and not re.match(r"^[a-z]+://|^[\w.-]+@[\w.-]+:", src):
        src = str(Path(src).expanduser().resolve())
    target = _git("symbolic-ref", "--short", "HEAD", cwd=bare).strip() or "main"
    with tempfile.TemporaryDirectory(prefix=f"{pack['name']}-canvas-") as tmp:
        _git("clone", "--quiet", "--no-checkout", str(bare), tmp)
        try:
            _git("fetch", "--quiet", src, f"refs/heads/{branch}", cwd=tmp)
            start = "FETCH_HEAD"                     # that day's branch exists: the edit goes on top of it
        except ValueError:
            start = pack["commit"]
        _git("checkout", "--quiet", "-B", branch, start, cwd=tmp)
        for rel, text in sorted(files.items()):
            p = Path(tmp) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        _git("add", "--", *sorted(files), cwd=tmp)
        if not _git("status", "--porcelain", cwd=tmp).strip():
            return {"branch": branch, "commit": "", "pr": None}
        names = ", ".join(sorted(Path(r).stem for r in files))
        _git("-c", "user.name=AI Stack", "-c", "user.email=ai-stack@localhost", "commit", "--quiet", "-m",
             f"Canvas edit of {names}\n\nMade on n8n's canvas; it runs once a commit with it is approved.", cwd=tmp)
        head = _git("rev-parse", "HEAD", cwd=tmp).strip()
        _git("push", "--quiet", src, f"{branch}:refs/heads/{branch}", cwd=tmp)
    pr = None
    if forge is None:
        import forge as F
        forge = F.FORGE
    if forge.repo_of(pack["source"]):
        try:
            pr = forge.open_pr(pack["source"], branch, target, f"Canvas edit of {names}",
                               "Made on n8n's canvas in the AI Stack. It runs once a commit with it is approved.", draft=True)
        except Exception as x:                       # the branch is there; the pull request can be opened by hand
            pr = {"error": f"{type(x).__name__}: {TC.cut(str(x), 300)}"}   # cap: preview, the forge's reason
    return {"branch": branch, "commit": head, "pr": pr}

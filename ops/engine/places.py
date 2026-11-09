"""Places and pools (GEN-22, GEN-28, docs/AI-STACK.md §7 and §10): where a Command block's job runs, and how many
activities run at once.

A place is a worker of the worker protocol (ops/winjobs.py) behind a Temporal task queue of its own (place-<name>):
    wsl        the stack's own worker, a thread of the runner, as the stack's user (the root is under /srv/ai/state)
    wsl-host   the same protocol on the WSL host, run as the Linux user the deployment names as the owner of its tools
               and repositories (ops/fakeworker.py made real by a unit the owner sets up once: ops/wslhost-setup.sh)
    windows    the Windows worker, pull-only (ops/winworker.py's folders)
A job runs only when its kind is approved at that place, by the hash of its file: a pack's job kinds are copied to each
place's jobs.d, and the owner approves each there (Needs you, class command, a security floor). Per-change values are
the kind's typed parameters, checked by the stack before the request and by the worker again.

The deployment's places.yaml and pools.yaml beside its deployment.env:
    places: {wsl-host: {root: /home/aiworker/worker, user: aiworker}}
    pools: {tool: 2, claude: 4}

    place(name)                -> Place: submit(kind, values, files, spec), state(rid), wait(rid, ...)
    pools()                    -> {name: size}: each a task queue whose worker runs at most that many activities
    queues()                   -> the engine's task queues with their sizes: the defaults, the pools and the places
    sync_jobs(packs)           copies the running packs' job kinds to every local place's jobs.d
    decisions(make) / handle   a job kind waiting for its approval at a place; the owner's approval
"""
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import winjobs as WJ  # noqa: E402

LOCAL = ("wsl", "wsl-host")
PLACES = (*LOCAL, "windows")
PLACE_SLOTS = 2                 # limit: paces, jobs a place's queue hands out at once; the worker runs them one lock at a time
ALIVE_S = 60                    # a worker writes its status every 10 s; older than this, it is not running
LEASE_S = 60                    # a claim whose heartbeat is older than this was lost with its worker
PICKUP_S = 300                  # limit: stops, a request no worker took within this is given up as not picked up


def _deployment():
    import deployment as D
    return D.chosen()


def _yaml(env, name):
    p = Path(os.environ.get(env) or _deployment() / name)
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


def config():
    d = (_yaml("AISTACK_PLACES", "places.yaml").get("places") or {})
    base = Path(os.environ.get("AISTACK_PLACE_ROOT") or "/srv/ai/state/places")
    out = {"wsl": {"root": str(base / "wsl")}}
    for name, cfg in d.items():
        if name in PLACES:
            out[name] = {**out.get(name, {}), **(cfg or {})}
    return out


def pools():
    return {str(k): int(v) for k, v in (_yaml("AISTACK_POOLS", "pools.yaml").get("pools") or {}).items()}


def queues(defaults):
    """The engine's task queues: its own, each pool at its size, each place at PLACE_SLOTS."""
    return {**defaults, **pools(), **{f"place-{p}": PLACE_SLOTS for p in config()}}


class Refused(Exception):
    pass


class Place:
    """The stack's side of one worker: requests into its inbox, answers from its outbox, its status."""

    def __init__(self, name, requests, answers):
        self.name, self.requests, self.answers = name, Path(requests), Path(answers)

    def status(self):
        try:
            st = json.loads((self.answers / "status.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
        return st if time.time() - float(st.get("ts") or 0) < ALIVE_S else None

    def submit(self, kind, values, files=None, spec=None):
        st = self.status()
        if not st:
            raise Refused(f"the {self.name} worker is not answering (it writes its status every 10 seconds)")
        k = (st.get("kinds") or {}).get(kind)
        if not k:
            raise Refused(f"no job kind {kind} at {self.name} (there: {', '.join(sorted(st.get('kinds') or {})) or 'none'})")
        if not k.get("approved"):                                  # the worker's own reason names Windows' script: here it is the queue
            raise Refused(f"the job kind {kind} is not approved at {self.name}: the owner approves it in Needs you" if self.name in LOCAL
                          else k.get("why") or f"the job kind {kind} is not approved at {self.name}")
        if spec is not None:
            ok, why = WJ.check_values(spec, values, None, {})
            if why:
                raise Refused(f"{kind}: {why}")
        rid = uuid.uuid4().hex[:12]                                   # cap: id
        tmp = self.requests / f".tmp-{rid}"
        tmp.mkdir(parents=True)
        for name, text in (files or {}).items():
            (tmp / name).write_text(text, encoding="utf-8")
        (tmp / "request.json").write_text(json.dumps({"id": rid, "kind": kind, "values": values, "at": int(time.time())}), encoding="utf-8")
        os.replace(tmp, self.requests / rid)                          # the worker sees the whole request or none of it
        return rid

    def state(self, rid, submitted=None, now=None):
        now = now or time.time()
        try:
            return json.loads((self.answers / rid / "result.json").read_text())
        except (OSError, ValueError):
            pass
        try:
            claim = json.loads((self.answers / rid / "claimed.json").read_text())
        except (OSError, ValueError):
            claim = None
        if claim:
            if now - float(claim.get("beat") or 0) > LEASE_S:
                return {"id": rid, "status": "lost", "error": f"the {self.name} worker stopped answering while it ran the job"}
            return {"id": rid, "status": "running"}
        if submitted and now - submitted > PICKUP_S:
            return {"id": rid, "status": "not picked up", "error": f"no {self.name} worker took the request within {PICKUP_S // 60} minutes"}
        return {"id": rid, "status": "queued"}

    def artifacts(self, rid):
        d = self.answers / rid / "artifacts"
        return sorted(p for p in d.iterdir() if p.is_file()) if d.is_dir() else []


def place(name, cfg=None):
    cfg = cfg or config()
    if name == "windows":
        import winworker as WW
        return Place("windows", WW.REQUESTS, WW.ANSWERS)
    if name not in cfg:
        raise Refused(f"no place {name!r} in this deployment (places: {', '.join(sorted(cfg))})")
    root = Path(cfg[name]["root"])
    return Place(name, root / "inbox", root / "outbox")


def run_job(name, kind, values, files=None, spec=None, beat=lambda: None, poll=2, timeout=None, sleep=time.sleep):
    """A Command block's job at its place, to its end: {status, error, steps, artifacts: [paths], rid}."""
    p = place(name)
    rid = p.submit(kind, values, files, spec)
    t0 = time.time()
    while True:
        st = p.state(rid, submitted=t0)
        if st["status"] in ("done", "failed", "refused", "lost", "not picked up"):
            return {**st, "rid": rid, "artifacts": p.artifacts(rid)}
        if timeout and time.time() - t0 > timeout:
            return {"id": rid, "rid": rid, "status": "failed", "error": f"no result within {timeout // 60} minutes", "artifacts": []}
        beat()
        sleep(poll)


# ---------- job kinds at each place: copied from the packs, approved by the owner ----------
def sync_jobs(packs, cfg=None):
    """Copies each running pack's job kinds into every local place's jobs.d (approved there separately)."""
    cfg = cfg or config()
    for name in LOCAL:
        if name not in cfg:
            continue
        jobs = Path(cfg[name]["root"]) / "jobs.d"
        jobs.mkdir(parents=True, exist_ok=True)
        for pk in packs or ():
            for j in pk["jobs"]:
                dest = jobs / f"{j['kind']}.json"
                if not dest.is_file() or WJ.digest(dest) != j["sha256"]:
                    shutil.copyfile(j["file"], dest)


def _kinds(name, cfg):
    root = Path(cfg[name]["root"])
    kinds = WJ.load_kinds(root / "jobs.d") if (root / "jobs.d").is_dir() else {}
    try:
        appr = json.loads((root / "approved.json").read_text())
    except (OSError, ValueError):
        appr = {}
    return root, kinds, appr


def decisions(make, cfg=None):
    cfg = cfg or config()
    for name in LOCAL:
        if name not in cfg:
            continue
        _, kinds, appr = _kinds(name, cfg)
        for kind, (k, sha, probs) in sorted(kinds.items()):
            if appr.get(kind) == sha or probs:
                continue
            what = f"Approve the command {kind} at {name}?" if kind not in appr else f"Approve the changed command {kind} at {name}?"
            yield make(f"command:{name}:{kind}:{sha[:12]}", "command", what,
                       f"{k.get('about', '')}; runs: {' && '.join(' '.join(s) for s in k.get('steps') or [])}", "#/packs",
                       unanswered=f"{kind} does not run at {name}",
                       answers=[{"label": "Approve", "act": {"action": "command_approve", "place": name, "kind": kind, "sha": sha}}])


def handle(req, cfg=None):
    cfg = cfg or config()
    name, kind, sha = str(req.get("place") or ""), str(req.get("kind") or ""), str(req.get("sha") or "")
    if name not in LOCAL or name not in cfg:
        return {"ok": False, "error": f"commands are approved here for {', '.join(LOCAL)}; Windows approves on Windows (worker-approve.ps1)"}
    root, kinds, appr = _kinds(name, cfg)
    if kind not in kinds or kinds[kind][1] != sha:
        return {"ok": False, "error": f"the command {kind} at {name} is not the one you saw: it changed, look again"}
    appr[kind] = sha
    (root / "approved.json").write_text(json.dumps(appr, indent=1, sort_keys=True))
    return {"ok": True, "approved": kind}


def worker_loop(stop, cfg=None):
    """The wsl place's worker: a thread of the runner, the protocol's rules (ops/fakeworker.py), as the stack's user."""
    import fakeworker as FK
    cfg = cfg or config()
    w = FK.Worker(cfg["wsl"]["root"])
    for d in ("inbox", "outbox", "jobs.d", "repos", "scratch"):
        (Path(cfg["wsl"]["root"]) / d).mkdir(parents=True, exist_ok=True)
    while not stop.is_set():
        if not w.once():
            stop.wait(2)


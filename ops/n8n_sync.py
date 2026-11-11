#!/usr/bin/env python3
"""WFL-08: the deployment's workflows live in git (n8n/workflows/*.json); n8n holds a copy.

    python3 ops/n8n_sync.py import            the deployment's workflows of the repository into n8n, each active or not as
                                              its file says, and the running packs' (a deploy runs this when n8n/workflows/,
                                              compose or deployments/ changed)
    python3 ops/n8n_sync.py packs             only the running packs' workflows (an approval in the queue does this too)
    python3 ops/n8n_sync.py export [dir]      n8n's workflows as one file each, made stable for git (default: n8n/workflows);
                                              a pack's workflow goes to the pack's own repository instead, never into git here
    python3 ops/n8n_sync.py list              what n8n holds

A change made on the canvas reaches git by `export` in a session's worktree and the landing path, like any other change.
A workflow the runner made or switched off for a task since the last export (ops/n8n_jobs.py, its own folder) is the
newer word: an import publishes or unpublishes it as that word says, so a deploy never switches a cancelled task back on.
Uses n8n's own command line inside its container (import:workflow, export:workflow), which the free edition has.

Every Webhook trigger takes only a call with the runner's header (SEC-27, ops/n8n_gen.py hook_auth): the stack's files in
git carry it, a pack's workflow and an export get it here, and every import writes n8n's credential for it first from the
secret N8N_HOOK_TOKEN (sops; `make trust-keys` makes it once). Without the secret an import stops before it changes
anything, so a deploy that lacks it fails and rolls back instead of leaving webhooks that nothing can call.

Which of the repository's workflows a deployment runs (PLT-38): those its deployments/<name>/workflows.yaml names, and
the tracker poller and the item workflows its trackers.yaml implies (ops/deployment.py workflow_names). The rest are
not imported, and one imported earlier that the deployment no longer runs is unpublished (a run of it that waits still
finishes). An export adds a workflow made on the canvas to that list, so the next import keeps it.

A pack's workflows (GEN-43, ops/domain/packs.py): the running commit's files, each under the id pack_id(<pack>/<name>)
whatever the file says, so a pack can never overwrite a workflow of the stack's or of another pack. What runs is the
approved commit's version: a canvas edit is sent to the pack's repository as a proposal (packs.propose) and the
approved version is imported again. A new commit replaces its workflows in place: a run waiting in the old version
finishes on the version it started with (n8n resumes from the copy it keeps with each execution; docs/N8N-MIGRATION.md
§11). A pack refused or removed has its workflows unpublished; its waiting runs still finish.
"""
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from textcap import tail

R = Path(__file__).resolve().parent.parent
REPO = R / "n8n/workflows"
CONTAINER = "aistack-n8n-1"
CHOSEN = "/home/node/.n8n/chosen"                 # inside n8n: the deployment's files of /workflows, for one import
VOLATILE = ("createdAt", "updatedAt", "versionId", "activeVersionId", "triggerCount", "shared", "tags", "pinData",
            "staticData", "meta", "isArchived", "versionCounter", "activeVersion", "parentFolder", "description")
PACK = "pack"                                     # a pack's workflow ids start with it; the stack's start with "ais"
HOOKED = ("n8n-nodes-base.webhook", "n8n-nodes-base.wait", "n8n-nodes-base.formTrigger", "CUSTOM.aistackStep")


def n8n(*args, run=subprocess.run):
    return run(["docker", "exec", "-u", "node", CONTAINER, "n8n", *args], capture_output=True, text=True, timeout=300)


def stable(wf):
    """A workflow as git keeps it: no timestamps or version ids, keys sorted, so a canvas change is a readable diff."""
    out = {k: v for k, v in wf.items() if k not in VOLATILE}
    out["nodes"] = sorted(out.get("nodes", []), key=lambda n: n.get("name", ""))
    return out


def hook_credential(run=subprocess.run, token=None):
    """SEC-27: n8n's Header Auth credential of the runner's webhooks (ops/n8n_gen.py HOOK_CRED), written from the secret
    N8N_HOOK_TOKEN through n8n's own import (it encrypts it with N8N_ENCRYPTION_KEY); the secret goes in on stdin into
    n8n's /tmp (memory) and is removed. -> "" or why not."""
    import n8n_gen as G
    token = os.environ.get("N8N_HOOK_TOKEN", "") if token is None else token
    if not token:
        return "no N8N_HOOK_TOKEN in the environment (make trust-keys stores one in the secrets, SEC-27)"
    cred = [{**G.HOOK_CRED, "type": "httpHeaderAuth", "data": {"name": G.HOOK_HEADER, "value": token}}]
    p = run(["docker", "exec", "-i", "-u", "node", CONTAINER, "sh", "-c",
             "umask 077 && cat > /tmp/hook.json && n8n import:credentials --input=/tmp/hook.json; s=$?; rm -f /tmp/hook.json; exit $s"],
            input=json.dumps(cred), capture_output=True, text=True, timeout=300)
    return "" if p.returncode == 0 else f"n8n did not take the webhooks' credential: {tail((p.stderr or p.stdout).strip(), 300)}"   # cap: preview, n8n's reason


def import_chosen(files, run=subprocess.run):
    """The deployment's files of the repository's folder (mounted at /workflows) into n8n, unpublished: copied into a
    folder of their own inside the container, so n8n's folder import takes exactly these."""
    names = " ".join(shlex.quote(f) for f in files)
    return run(["docker", "exec", "-u", "node", CONTAINER, "sh", "-c",
                f"rm -rf {CHOSEN} && mkdir -p {CHOSEN} && cd /workflows && cp {names} {CHOSEN}/ && "
                f"n8n import:workflow --separate --input={CHOSEN}; s=$?; rm -rf {CHOSEN}; exit $s"],
               capture_output=True, text=True, timeout=300)


def active_ids(run=subprocess.run):
    """The ids of the workflows n8n has published, or None when n8n does not say."""
    p = n8n("list:workflow", "--active=true", "--onlyId", run=run)
    return None if p.returncode else {x.strip() for x in p.stdout.split() if x.strip()}


def import_all(repo=REPO, run=subprocess.run, made=None, names=None):
    """Imports the deployment's files (PLT-38, deployments/<name>/workflows.yaml; n8n imports them unpublished),
    publishes the ones whose file says active and unpublishes the others (n8n 2.x activates only through publish in
    single-server mode), unpublishes a workflow of the repository it published earlier that the deployment no longer
    runs, then restarts n8n so its server loads them. The runner's newer word on a workflow (ops/n8n_jobs.py) decides
    over the repository's file."""
    import n8n_jobs as NJ
    if why := hook_credential(run=run):
        print(f"nothing imported: {why}")
        return 1
    made = made or NJ.MADE
    names = NJ.chosen(repo) if names is None else names
    mine = NJ.workflows(repo, made, names)
    files = sorted(w["file"] for w in mine.values() if not w["made"])
    if files:
        p = import_chosen(files, run=run)
        print(tail((p.stdout + p.stderr).strip(), 2000))     # cap: preview, the tail of n8n's own report; the journal keeps the rest
        if p.returncode:
            return p.returncode
    bad = 0
    for _, w in sorted(mine.items(), key=lambda x: x[1]["file"]):
        wf = w["wf"]
        q = n8n("publish:workflow" if wf.get("active") else "unpublish:workflow", f"--id={wf['id']}", run=run)
        print(f"{'published' if wf.get('active') else 'unpublished'} {wf['name']}" if not q.returncode else
              f"{wf['name']}: {tail((q.stderr or q.stdout).strip(), 300)}")   # cap: preview, n8n's reason; the journal has it all
        bad += q.returncode != 0
    live = active_ids(run=run)
    for wid, w in sorted(NJ.workflows(repo, made, ["*"]).items(), key=lambda x: x[1]["file"]):
        if wid not in mine and (live is None or wid in live):     # n8n did not say: unpublished anyway, harmless when it has none
            q = n8n("unpublish:workflow", f"--id={wid}", run=run)
            if not q.returncode:
                print(f"unpublished {w['wf'].get('name')}: this deployment does not run it (its workflows.yaml)")
            bad += q.returncode != 0 and live is not None
    try:
        from domain import packs as PK
        for line in sync_packs(PK.load(), run=run, restart=False):
            print(line)
    except Exception as e:                       # a pack's repository away: the stack's own workflows still go in
        print(f"packs not synced: {type(e).__name__}: {tail(str(e), 300)}")   # cap: preview, the reason
    run(["docker", "restart", CONTAINER], capture_output=True, text=True, timeout=180)
    return 1 if bad else 0


def put(path, run=subprocess.run, text=None):
    """One workflow file of this machine (or its text) into n8n, imported unpublished (ops/n8n_switch.py publishes it)."""
    return run(["docker", "exec", "-i", "-u", "node", CONTAINER, "sh", "-c",
                "cat > /home/node/.n8n/put.json && n8n import:workflow --input=/home/node/.n8n/put.json; s=$?; "
                "rm -f /home/node/.n8n/put.json; exit $s"], input=Path(path).read_text() if text is None else text,
               capture_output=True, text=True, timeout=300)


def get(wid, run=subprocess.run):
    """n8n's copy of one workflow, or None when n8n has none by that id."""
    p = run(["docker", "exec", "-u", "node", CONTAINER, "sh", "-c",
             f"n8n export:workflow --id={wid} --output=/home/node/.n8n/get.json >/dev/null 2>&1 && cat /home/node/.n8n/get.json; "
             "s=$?; rm -f /home/node/.n8n/get.json; exit $s"], capture_output=True, text=True, timeout=300)
    if p.returncode or not p.stdout.strip():
        return None
    got = json.loads(p.stdout)
    return (got[0] if got else None) if isinstance(got, list) else got


# ---------- a pack's workflows (GEN-43) ----------
def pack_id(name):
    """A pack workflow's n8n id (16 letters and digits) from its name <pack>/<name>: the same on every import."""
    return PACK + hashlib.sha1(name.encode()).hexdigest()[:16 - len(PACK)]


def is_pack(wf, packs=()):
    """A workflow of a pack: by its id, or (one made on the canvas) by a name under a running pack's name."""
    wid, name = str(wf.get("id") or ""), str(wf.get("name") or "")
    return (wid.startswith(PACK) and len(wid) == 16) or any(name.startswith(f"{p}/") for p in packs)


def prepared(path):
    """A pack's workflow file as n8n gets it: the id from its name, node ids and webhook ids derived from the id and each
    node's name (a pack names none of them, so it can take no id of the stack's)."""
    import n8n_gen as G
    wf = G.hook_auth(json.loads(Path(path).read_text(encoding="utf-8")))     # SEC-27: a pack's webhooks too
    w = pack_id(wf["name"])
    nodes = []
    for n in wf["nodes"]:
        n = {**n, "id": G.node_id(w, n["name"])}
        if n.get("type") in HOOKED or "webhookId" in n:
            n["webhookId"] = G.node_id(w, n["name"] + "/hook")
        nodes.append(n)
    return {**wf, "id": w, "active": bool(wf.get("active")), "nodes": nodes, "settings": wf.get("settings") or {"executionOrder": "v1"}}


def shape(wf):
    """What a canvas edit changes: the nodes (name, type, version, parameters, switched off) and the connections."""
    nodes = sorted(({k: n.get(k) for k in ("name", "type", "typeVersion", "parameters", "disabled")} for n in wf.get("nodes") or []),
                   key=lambda n: str(n["name"]))
    return json.dumps({"nodes": nodes, "connections": wf.get("connections") or {}}, sort_keys=True)


def for_pack(wf):
    """n8n's copy as the pack keeps it: stable, without the ids the stack derives."""
    out = {k: v for k, v in stable(wf).items() if k != "id"}
    out["nodes"] = [{k: v for k, v in n.items() if k not in ("id", "webhookId")} for n in out["nodes"]]
    return json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def pack_state_path():
    return Path(os.environ.get("AISTACK_PACK_FLOWS") or "/srv/ai/state/pack-workflows.json")


def _pack_state():
    try:
        return json.loads(pack_state_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_pack_state(st):
    p = pack_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1, sort_keys=True))
    tmp.replace(p)


def _flows(pack):
    """{name: (file name in the pack, prepared workflow)} of a pack read by packs.read."""
    return {w["name"]: (Path(w["path"]).name, prepared(w["path"])) for w in pack["workflows"]}


def _flows_at(pack, commit):
    """The pack's workflows at an earlier commit, from its read-only checkout in the cache (what n8n got then)."""
    folder = Path(pack["dir"]).parent / f"{pack['name']}@{commit}"
    out = {}
    for f in sorted((folder / "workflows").glob("*.json")) if folder.is_dir() else []:
        try:
            out[json.loads(f.read_text(encoding="utf-8"))["name"]] = (f.name, prepared(f))
        except (ValueError, KeyError, TypeError):
            continue
    return out


def _propose(pack, edits, st, propose):
    """Canvas edits not sent yet -> one proposal to the pack's repository. -> lines."""
    key = hashlib.sha1("".join(sorted(shape(wf) for _, wf in edits.values())).encode()).hexdigest()
    if key in st.get("proposed", []):
        return []
    try:
        got = propose(pack, {f"workflows/{file}": for_pack(wf) for file, wf in edits.values()})
    except Exception as e:                       # the pack's repository away: said, and tried again on the next sync
        return [f"{pack['name']}: canvas edit of {', '.join(sorted(edits))} not sent: {type(e).__name__}: {tail(str(e), 300)}"]   # cap: preview
    st["proposed"] = (st.get("proposed") or [])[-19:] + [key]   # cap: list, the last 20 proposals are enough to skip a repeat
    pr = got.get("pr") or {}
    return [f"{pack['name']}: canvas edit of {', '.join(sorted(edits))} sent to the pack's repository as {got['branch']}"
            + (f", draft pull request {pr.get('url')}" if pr.get("url") else "")]


def sync_packs(loaded, run=subprocess.run, restart=True, propose=None):
    """n8n holds exactly the running packs' workflows at their approved commits (loaded: packs.load()). A workflow n8n
    lacks, or holds at another commit, is imported; one edited on the canvas is first sent to the pack's repository as a
    proposal (propose, default packs.propose), then imported again as approved; each is published or not as its file
    says. A workflow of a pack that no longer runs (refused, removed, or the file gone) is unpublished. One restart at
    the end when anything changed (restart=False: the caller restarts). -> what changed, in lines."""
    if propose is None:
        from domain import packs as PK
        propose = PK.propose
    state, out, changed = _pack_state(), [], False
    running = {p["name"]: p for p in loaded.get("packs") or []}
    for name, p in sorted(running.items()):
        st = state.get(name) or {}
        want = _flows(p)
        then = want if st.get("commit") == p["commit"] else _flows_at(p, st["commit"]) if st.get("commit") else {}
        edits = {}
        for wname, (file, wf) in sorted(want.items()):
            have = get(wf["id"], run=run)
            base = then.get(wname)                   # what n8n was given last time; a difference is an edit on the canvas
            if have and base and shape(have) != shape(base[1]):
                edits[wname] = (base[0], have)
            if have and shape(have) == shape(wf):
                if bool(have.get("active")) == wf["active"]:
                    continue
            else:
                q = put(None, run=run, text=json.dumps(wf))
                if q.returncode:
                    out.append(f"{wname}: n8n refused it: {tail((q.stderr or q.stdout).strip(), 300)}")   # cap: preview
                    continue
                out.append(f"{wname}: imported at {p['commit'][:12]}")
            q = n8n("publish:workflow" if wf["active"] else "unpublish:workflow", f"--id={wf['id']}", run=run)
            changed = True
            if q.returncode:
                out.append(f"{wname}: n8n refused to {'publish' if wf['active'] else 'unpublish'} it")
        if edits:
            out += _propose(p, edits, st, propose)
        for wid in sorted(set((st.get("ids") or {}).values()) - {wf["id"] for _, wf in want.values()}):
            n8n("unpublish:workflow", f"--id={wid}", run=run)
            out.append(f"{name}: workflow {wid} is no longer in the pack, unpublished")
            changed = True
        state[name] = {"commit": p["commit"], "ids": {w: wf["id"] for w, (_, wf) in want.items()}, "proposed": st.get("proposed") or []}
    for name in sorted(set(state) - set(running)):
        for wid in sorted((state[name].get("ids") or {}).values()):
            n8n("unpublish:workflow", f"--id={wid}", run=run)
        out.append(f"{name}: the pack no longer runs, its workflows are unpublished (runs that wait still finish)")
        del state[name]
        changed = True
    if changed or out:
        _save_pack_state(state)
    if changed and restart:
        run(["docker", "restart", CONTAINER], capture_output=True, text=True, timeout=180)
    return out


def file_name(wf):
    """The workflow's file in git, from its name: "Crew: Health doctor" -> crew-health-doctor.json."""
    import re
    return re.sub(r"-+", "-", "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in wf["name"].lower())).strip("-") + ".json"


def write_stable(files, dest, packs=()):
    """n8n's exported files -> one stable file per workflow of the stack's in dest. A pack's workflow (is_pack) is left
    out: it belongs to the pack's own repository (export_packs). -> the names written."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    names = []
    import n8n_gen as G
    for f in sorted(files):
        wf = G.hook_auth(stable(json.loads(Path(f).read_text())))   # SEC-27: a webhook made on the canvas gets the runner's header
        if is_pack(wf, packs):
            continue
        (dest / file_name(wf)).write_text(json.dumps(wf, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        names.append(file_name(wf))
    return names


def export_packs(files, loaded, propose=None):
    """The packs' workflows among n8n's exported files -> a proposal to each pack's own repository where the canvas
    changed one (never the stack's repository); what runs stays the approved version until a commit with the edit is
    approved. A new workflow made on the canvas under a pack's name goes too. -> lines."""
    if propose is None:
        from domain import packs as PK
        propose = PK.propose
    running = {p["name"]: p for p in loaded.get("packs") or []}
    state, out, by_pack = _pack_state(), [], {}
    for f in sorted(files):
        wf = json.loads(Path(f).read_text())
        if not is_pack(wf, running):
            continue
        name = str(wf.get("name") or "")
        p = running.get(name.split("/", 1)[0])
        if not p:
            out.append(f"{name}: no running pack has this workflow, left in n8n")
            continue
        mine = _flows(p).get(name)
        if mine and shape(mine[1]) == shape(wf):
            continue
        by_pack.setdefault(p["name"], {})[name] = (mine[0] if mine else f"{name.split('/', 1)[1]}.json".replace("/", "-"), wf)
    for pname, edits in sorted(by_pack.items()):
        st = state.setdefault(pname, {"commit": running[pname]["commit"], "ids": {}, "proposed": []})
        out += _propose(running[pname], edits, st, propose)
    if by_pack:
        _save_pack_state(state)
    return out


def export_all(dest=REPO, run=subprocess.run, loaded=None, propose=None):
    """n8n's workflows: the stack's into git (dest), each pack's to its own repository as a proposal."""
    p = run(["docker", "exec", "-u", "node", CONTAINER, "sh", "-c",
             "rm -rf /home/node/.n8n/export && n8n export:workflow --all --separate --output=/home/node/.n8n/export/"],
            capture_output=True, text=True, timeout=300)
    if p.returncode:
        print(p.stderr.strip())
        return p.returncode
    if loaded is None:
        from domain import packs as PK
        loaded = PK.load()
    with tempfile.TemporaryDirectory() as tmp:
        run(["docker", "cp", f"{CONTAINER}:/home/node/.n8n/export/.", tmp], check=True, capture_output=True, timeout=120)
        files = sorted(Path(tmp).glob("*.json"))
        for n in write_stable(files, dest, [p["name"] for p in loaded.get("packs") or []]):
            print(f"exported {n}")
            if Path(dest).resolve() == REPO.resolve():
                import deployment as DEPLOY
                if DEPLOY.add_workflow(n):           # PLT-38: made on the canvas here, so this deployment runs it
                    print(f"{n} added to {DEPLOY.FOLDER / 'workflows.yaml'}")
        for line in export_packs(files, loaded, propose):
            print(line)
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "list"
    if cmd == "import":
        return import_all()
    if cmd == "packs":
        from domain import packs as PK
        if why := hook_credential():
            print(f"nothing synced: {why}")
            return 1
        for line in sync_packs(PK.load()) or ["the packs' workflows in n8n are as approved"]:
            print(line)
        return 0
    if cmd == "export":
        return export_all(argv[2] if len(argv) > 2 else REPO)
    p = n8n("list:workflow")
    print(p.stdout.strip() or p.stderr.strip())
    return p.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv))

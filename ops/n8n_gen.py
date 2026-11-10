#!/usr/bin/env python3
"""WFL-09: the workflow of a scheduled job: a Schedule trigger, a Run now trigger and one AI Stack step, inactive until
its switch (ops/n8n_switch.py). n8n starts every scheduled job of the stack; this makes a new one's workflow.

    python3 ops/n8n_gen.py crew <job> '<cron>'   write n8n/workflows/crew-<name>.json for a crew job of ops/crew.py
                                                 (an existing file stays as it is) and list it in this deployment's
                                                 workflows.yaml (PLT-38)
    python3 ops/n8n_gen.py chain '<name>' '<cron>' crew:<job>=<title> agent:<card>=<title> ...
                                                 write n8n/workflows/<name>.json: the steps in that order, each waiting
                                                 for the one before (an existing file stays as it is), listed in this
                                                 deployment's workflows.yaml; the tax desk's is one (TAX-08)
    python3 ops/n8n_gen.py --run-now             Run now for every crew-* and task-* file that lacks it (its id,
                                                 "active" and canvas changes kept)

A workflow is a Schedule trigger, a Run now Webhook (WFL-13: POST <n8n>/webhook/run/<file stem>) and one AI Stack step
(WFL-06), which goes through the step service and waits. A task's workflow is made by the runner when the task gets
its schedule (ops/n8n_jobs.py). What systemd still starts, and why, is in ops/systemd/AGENTS.md.
"""
import hashlib
import json
import sys
import uuid
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "ops"))
OUT = R / "n8n/workflows"


def settings(cron):
    """A job that runs every few minutes keeps only its failed runs in n8n's history (a sync every minute would be
    43,000 runs a month); the others keep every run (pruned after 30 days, WFL-04)."""
    s = {"executionOrder": "v1", "timezone": "Europe/Berlin"}
    if cron.split()[0] == "*" or cron.split()[0].startswith("*/"):
        s["saveDataSuccessExecution"] = "none"
    return s


def wid(kind, key):
    return ("ais" + kind[0] + hashlib.sha1(f"{kind}:{key}".encode()).hexdigest())[:16]


def node_id(w, n):
    return str(uuid.UUID(hashlib.md5(f"{w}:{n}".encode()).hexdigest()))


STEP = "CUSTOM.aistackStep"                           # the stack's own node (n8n/custom, WFL-06)


RUN_NOW = "Run now"


def run_now(wf, stem):
    """WFL-13: a second trigger, a Webhook "Run now" (POST <n8n>/webhook/run/<stem>), on the same AI Stack step, so the
    job can be started on demand through n8n. Its ids come from the workflow's id, so a regeneration or an import
    never makes a second one. Adds it once; -> the workflow."""
    if any(n["name"] == RUN_NOW for n in wf["nodes"]):
        return wf
    step = next(n for n in wf["nodes"] if n["type"] == STEP)
    w = wf["id"]
    wf["nodes"].append({"id": node_id(w, RUN_NOW), "name": RUN_NOW, "notes": "Starts the job now, as its schedule would (POST).",
                        "parameters": {"httpMethod": "POST", "options": {}, "path": f"run/{stem}"},
                        "position": [0, 160], "type": "n8n-nodes-base.webhook", "typeVersion": 2, "webhookId": node_id(w, RUN_NOW + "/hook")})
    wf["connections"][RUN_NOW] = {"main": [[{"index": 0, "node": step["name"], "type": "main"}]]}
    return wf


def workflow(kind, key, name, cron, params, note):
    """A Schedule trigger, a Run now trigger and one AI Stack step, which sends the step and waits for its answer."""
    import n8n_sync as NS
    w = wid(kind, key)
    trig, step = f"On its schedule ({cron})", name
    return run_now({
        "active": False, "id": w, "name": name, "settings": settings(cron),
        "connections": {trig: {"main": [[{"index": 0, "node": step, "type": "main"}]]}},
        "nodes": [
            {"id": node_id(w, trig), "name": trig, "parameters": {"rule": {"interval": [{"expression": cron, "field": "cronExpression"}]}},
             "position": [0, 0], "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2},
            {"id": node_id(w, step), "name": step, "notes": note, "parameters": {**params, "title": name},
             "position": [260, 0], "type": STEP, "typeVersion": 1, "webhookId": node_id(w, step + "/hook")}]},
        NS.file_name({"name": name})[:-len(".json")])


def add_run_now(out=None):
    """Every generated workflow in git (crew-*, task-*) gets its Run now trigger; everything else in the file stays (its
    id, its "active", canvas changes). -> the files changed."""
    changed = []
    for p in sorted(Path(out or OUT).glob("*.json")):
        if not p.name.startswith(("crew-", "task-")):
            continue
        wf = json.loads(p.read_text())
        if any(n["name"] == RUN_NOW for n in wf["nodes"]):
            continue
        p.write_text(json.dumps(run_now(wf, p.stem), indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        changed.append(p.name)
    return changed


def crew(job, cron, out=None, folder=None):
    """A crew job's workflow, inactive, in n8n/workflows (as an export names it), and its name added to the deployment's
    workflows.yaml (folder, default this deployment's), so its switch may publish it. -> the file, or None when it exists."""
    import crew as CR
    import n8n_jobs as NJ
    import n8n_sync as NS
    ag = CR.BY_ID.get(job)
    if not ag or not ag.get("unit"):
        raise SystemExit(f"no crew job {job!r} with a unit in ops/crew.py")
    if not NJ.parse(cron):
        raise SystemExit(f"not a five-field cron expression: {cron!r}")
    wf = workflow("crew", job, f"Crew: {ag.get('name') or job}", cron, {"kind": "crew", "job": job},
                  f"The crew job {job} ({ag['unit']}.service), as Run now starts it (WFL-05).")
    p = Path(out or OUT) / NS.file_name(wf)
    if p.exists():
        return None
    p.write_text(json.dumps(wf, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    if out is None or folder is not None:            # PLT-38: made for this deployment, so its workflows.yaml lists it
        import deployment as DEPLOY
        DEPLOY.add_workflow(p, folder)
    return p


def chain(name, cron, steps, out=None, folder=None):
    """A workflow of AI Stack steps in a row (crew jobs and agent steps), behind a Schedule and a Run now trigger,
    inactive until its switch, in n8n/workflows and listed in the deployment's workflows.yaml (folder, default this
    deployment's). steps: ["crew:<job>=<title>" | "agent:<card>=<title>"]; an agent step's brief is its card's purpose.
    -> the file, or None when it exists."""
    import crew as CR
    import n8n_jobs as NJ
    import n8n_sync as NS
    import registry as REG
    if not NJ.parse(cron):
        raise SystemExit(f"not a five-field cron expression: {cron!r}")
    cards = {c["id"]: c for c in REG.load().get("agents") or []}
    nodes = []
    for spec in steps:
        kind, _, rest = spec.partition(":")
        ref, _, title = rest.partition("=")
        if not title:
            raise SystemExit(f"a step needs its title: {spec!r} (crew:<job>=<title> or agent:<card>=<title>)")
        if kind == "crew" and (CR.BY_ID.get(ref) or {}).get("unit"):
            nodes.append((title, {"kind": "crew", "job": ref}, f"The crew job {ref} ({CR.BY_ID[ref]['unit']}.service), waited for."))
        elif kind == "agent" and ref in cards:
            nodes.append((title, {"kind": "agent", "agent": ref, "brief": cards[ref]["purpose"]},
                          f"The agent {ref} ({cards[ref]['harness']}, {cards[ref]['model']}) through the step service."))
        else:
            raise SystemExit(f"no crew job with a unit or agent card for {spec!r}")
    w = wid("chain", name)
    trig = f"On its schedule ({cron})"
    wf = {"active": False, "id": w, "name": name, "settings": settings(cron), "connections": {}, "nodes": [
        {"id": node_id(w, trig), "name": trig, "parameters": {"rule": {"interval": [{"expression": cron, "field": "cronExpression"}]}},
         "position": [0, 0], "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2}]}
    before = trig
    for i, (title, params, note) in enumerate(nodes):
        wf["nodes"].append({"id": node_id(w, title), "name": title, "notes": note, "parameters": {**params, "title": title},
                            "position": [260 * (i + 1), 0], "type": STEP, "typeVersion": 1, "webhookId": node_id(w, title + "/hook")})
        wf["connections"][before] = {"main": [[{"index": 0, "node": title, "type": "main"}]]}
        before = title
    wf = run_now(wf, NS.file_name(wf)[:-len(".json")])
    p = Path(out or OUT) / NS.file_name(wf)
    if p.exists():
        return None
    p.write_text(json.dumps(wf, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    if out is None or folder is not None:            # PLT-38: made for this deployment, so its workflows.yaml lists it
        import deployment as DEPLOY
        DEPLOY.add_workflow(p, folder)
    return p


def main(argv):
    if argv[1:2] == ["--run-now"]:
        for name in add_run_now():
            print(f"Run now added to {name}")
        return 0
    if len(argv) == 4 and argv[1] == "crew":
        p = crew(argv[2], argv[3])
        print(f"wrote {p.relative_to(R)}, listed in this deployment's workflows.yaml (inactive: ops/n8n_switch.py "
              f"{p.relative_to(R)} on)" if p else "it has a workflow already")
        return 0
    if len(argv) >= 5 and argv[1] == "chain":
        p = chain(argv[2], argv[3], argv[4:])
        print(f"wrote {p.relative_to(R)}, listed in this deployment's workflows.yaml (inactive: ops/n8n_switch.py "
              f"{p.relative_to(R)} on)" if p else "it has a workflow already")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

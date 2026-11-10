#!/usr/bin/env python3
"""WFL-09: switch one scheduled job on n8n on or off. On: its workflow is published and n8n starts the job on its
schedule. Off: unpublished; nothing starts it on a schedule (Run now on its page still does). n8n is the one scheduler,
so there is no other schedule to hand the job back to.

    python3 ops/n8n_switch.py <workflow file> on|off
    python3 ops/n8n_switch.py status                 every workflow of this deployment: on or off, the repository's or
                                                     the runner's word

Only a workflow the deployment runs (PLT-38, deployments/<name>/workflows.yaml) is switched on; switching off works on
any.

The file's "active" is set to match, so the file says what runs; for n8n/workflows/ land it like any change (the live
checkout is never edited). n8n reloads after a switch (a restart, about 30 s; a waiting run survives it).
"""
import json
import subprocess
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "ops"))
import n8n_sync as NS


def switch(path, on, run=subprocess.run):
    path = Path(path)
    wf = json.loads(path.read_text())
    if on and path.resolve().parent == NS.REPO.resolve():   # PLT-38: only a workflow this deployment runs is published
        import deployment as DEPLOY
        if not DEPLOY.runs_workflow(path):
            raise RuntimeError(f"{path.name} is not one of this deployment's workflows: add {path.stem} to "
                               f"{DEPLOY.FOLDER / 'workflows.yaml'} first")
    q = NS.n8n("publish:workflow" if on else "unpublish:workflow", f"--id={wf['id']}", run=run)
    if q.returncode:                                 # an error, never SystemExit: the runner calls this from its threads
        raise RuntimeError(f"n8n refused: {(q.stderr or q.stdout).strip()}")
    wf["active"] = on
    path.write_text(json.dumps(wf, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    run(["docker", "restart", NS.CONTAINER], capture_output=True, text=True, timeout=180)
    return f"{wf['name']}: {'on, n8n starts it on its schedule' if on else 'off, nothing starts it on a schedule'}"


def main(argv):
    if len(argv) == 2 and argv[1] == "status":
        import n8n_jobs as NJ
        mine = NJ.workflows()
        for wid, w in sorted(mine.items(), key=lambda x: x[1]["file"]):
            print(f"{'on ' if w['wf'].get('active') else 'off'}  {w['file']}  {w['wf'].get('name')}" + ("  (the runner's word)" if w["made"] else ""))
        left = len(NJ.workflows(names=["*"])) - len(mine)
        if left:
            print(f"({left} more in n8n/workflows/ that this deployment does not run)")
        return 0
    if len(argv) != 3 or argv[2] not in ("on", "off"):
        print(__doc__)
        return 2
    try:
        print(switch(argv[1], argv[2] == "on"))
    except RuntimeError as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

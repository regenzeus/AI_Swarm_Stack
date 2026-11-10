#!/usr/bin/env python3
"""WFL-08: the deployment's workflows live in git (n8n/workflows/*.json); n8n holds a copy.

    python3 ops/n8n_sync.py import            the repository's workflows into n8n, each active or not as its file says
                                              (a deploy runs this when n8n/workflows/ or compose changed)
    python3 ops/n8n_sync.py export [dir]      n8n's workflows as one file each, made stable for git (default: n8n/workflows)
    python3 ops/n8n_sync.py list              what n8n holds

A change made on the canvas reaches git by `export` in a session's worktree and the landing path, like any other change.
A workflow the runner made or switched off for a task since the last export (ops/n8n_jobs.py, its own folder) is the
newer word: an import publishes or unpublishes it as that word says, so a deploy never switches a cancelled task back on.
Uses n8n's own command line inside its container (import:workflow, export:workflow), which the free edition has.
"""
import json
import subprocess
import sys
from pathlib import Path

from textcap import tail

R = Path(__file__).resolve().parent.parent
REPO = R / "n8n/workflows"
CONTAINER = "aistack-n8n-1"
VOLATILE = ("createdAt", "updatedAt", "versionId", "activeVersionId", "triggerCount", "shared", "tags", "pinData",
            "staticData", "meta", "isArchived", "versionCounter", "activeVersion", "parentFolder", "description")


def n8n(*args, run=subprocess.run):
    return run(["docker", "exec", "-u", "node", CONTAINER, "n8n", *args], capture_output=True, text=True, timeout=300)


def stable(wf):
    """A workflow as git keeps it: no timestamps or version ids, keys sorted, so a canvas change is a readable diff."""
    out = {k: v for k, v in wf.items() if k not in VOLATILE}
    out["nodes"] = sorted(out.get("nodes", []), key=lambda n: n.get("name", ""))
    return out


def import_all(repo=REPO, run=subprocess.run, made=None):
    """Imports every file (n8n imports them unpublished), publishes the ones whose file says active and unpublishes the
    others (n8n 2.x activates only through publish in single-server mode), then restarts n8n so its server loads them.
    The runner's newer word on a workflow (ops/n8n_jobs.py) decides over the repository's file."""
    import n8n_jobs as NJ
    p = n8n("import:workflow", "--separate", "--input=/workflows", run=run)
    print(tail((p.stdout + p.stderr).strip(), 2000))     # cap: preview, the tail of n8n's own report; the journal keeps the rest
    if p.returncode:
        return p.returncode
    bad = 0
    for _, w in sorted(NJ.workflows(repo, made or NJ.MADE).items(), key=lambda x: x[1]["file"]):
        wf = w["wf"]
        q = n8n("publish:workflow" if wf.get("active") else "unpublish:workflow", f"--id={wf['id']}", run=run)
        print(f"{'published' if wf.get('active') else 'unpublished'} {wf['name']}" if not q.returncode else
              f"{wf['name']}: {tail((q.stderr or q.stdout).strip(), 300)}")   # cap: preview, n8n's reason; the journal has it all
        bad += q.returncode != 0
    run(["docker", "restart", CONTAINER], capture_output=True, text=True, timeout=180)
    return 1 if bad else 0


def put(path, run=subprocess.run):
    """One workflow file of this machine into n8n, imported unpublished (ops/n8n_switch.py publishes it)."""
    return run(["docker", "exec", "-i", "-u", "node", CONTAINER, "sh", "-c",
                "cat > /home/node/.n8n/put.json && n8n import:workflow --input=/home/node/.n8n/put.json; s=$?; "
                "rm -f /home/node/.n8n/put.json; exit $s"], input=Path(path).read_text(), capture_output=True, text=True, timeout=300)


def file_name(wf):
    """The workflow's file in git, from its name: "Crew: Health doctor" -> crew-health-doctor.json."""
    import re
    return re.sub(r"-+", "-", "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in wf["name"].lower())).strip("-") + ".json"


def write_stable(files, dest):
    """n8n's exported files -> one stable file per workflow in dest. -> the names written."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    names = []
    for f in sorted(files):
        wf = stable(json.loads(Path(f).read_text()))
        (dest / file_name(wf)).write_text(json.dumps(wf, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        names.append(file_name(wf))
    return names


def export_all(dest=REPO, run=subprocess.run):
    import tempfile
    p = run(["docker", "exec", "-u", "node", CONTAINER, "sh", "-c",
             "rm -rf /home/node/.n8n/export && n8n export:workflow --all --separate --output=/home/node/.n8n/export/"],
            capture_output=True, text=True, timeout=300)
    if p.returncode:
        print(p.stderr.strip())
        return p.returncode
    with tempfile.TemporaryDirectory() as tmp:
        run(["docker", "cp", f"{CONTAINER}:/home/node/.n8n/export/.", tmp], check=True, capture_output=True, timeout=120)
        for n in write_stable(Path(tmp).glob("*.json"), dest):
            print(f"exported {n}")
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "list"
    if cmd == "import":
        return import_all()
    if cmd == "export":
        return export_all(argv[2] if len(argv) > 2 else REPO)
    p = n8n("list:workflow")
    print(p.stdout.strip() or p.stderr.strip())
    return p.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv))

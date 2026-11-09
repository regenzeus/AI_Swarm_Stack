#!/usr/bin/env python3
"""Temporal's upgrades are the update path's job (GEN-39, docs/AI-STACK.md §12), never a manual step.

Temporal requires its server to move one minor version at a time, each with its schema first. When an update moves the
pinned server (versions.env TEMPORAL_IMAGE), the path is:
  1. snapshot Temporal's two databases on this machine (pg_dump into /srv/ai/state/temporal-snapshots; the backup
     leaves temporal* out on a customer-class deployment, so it never leaves the machine there);
  2. for each minor version from the old to the new, in order: the schema with that version's temporal-sql-tool, then
     that version's server, then a check: the server answers and the replay test passes against the pinned runner;
  3. any failing step restores the snapshot and starts the old server again, and says which step failed.
The minor versions and their images are in config/temporal/steps.yaml (each pinned by digest, as versions.env pins).

    plan(old, new, table)                         -> the minor versions to step through, in order
    run(old, new, table, snapshot, restore, schema, server, check)   -> what happened
    python3 ops/temporal_upgrade.py plan <old> <new>
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STEPS = ROOT / "config/temporal/steps.yaml"
VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def _v(text):
    m = VERSION.search(str(text))
    if not m:
        raise ValueError(f"{text!r} names no Temporal version")
    return tuple(int(x) for x in m.groups())


def table(path=STEPS):
    """{version: {"server": image, "admin": image}} of every minor version the update path may step through."""
    return {str(k): v for k, v in (yaml.safe_load(Path(path).read_text()) or {}).get("versions", {}).items()}


def plan(old, new, versions):
    """The versions to step through from old to new: the newest patch of each minor version after old's, up to new."""
    o, n = _v(old), _v(new)
    if n < o:
        raise ValueError(f"Temporal does not go back ({old} to {new}): restore a snapshot instead")
    if n[0] != o[0]:
        raise ValueError(f"a major version ({old} to {new}) is not a step the update path takes on its own")
    out = []
    for minor in range(o[1] + (0 if n[1] == o[1] else 1), n[1] + 1):
        have = sorted((_v(k), k) for k in versions if _v(k)[:2] == (o[0], minor))   # cap: parse, the major and minor of a version, not a cut
        if minor == n[1]:
            have = [h for h in have if h[0] <= n]
        if not have:
            raise ValueError(f"no pinned image for Temporal {o[0]}.{minor} in {STEPS.name}: a minor version may not be skipped")
        if have[-1][0] > o:
            out.append(have[-1][1])
    return out


def run(old, new, versions, snapshot, restore, schema, server, check):
    """Steps the engine from old to new; any failure restores the snapshot and the old server."""
    try:
        steps = plan(old, new, versions)
    except ValueError as e:
        return {"ok": False, "why": str(e), "done": []}
    if not steps:
        return {"ok": True, "why": f"Temporal stays at {old}", "done": []}
    snap = snapshot()
    done = []
    for v in steps:
        for what, fn in (("schema", schema), ("server", server), ("check", check)):
            try:
                ok = fn(v, versions[v])
            except Exception as e:                     # a step that raises is a step that failed, with its reason
                ok, why = False, f"{type(e).__name__}: {e}"
            else:
                why = "" if ok else "it said no"
            if not ok:
                restore(snap)
                server(old, versions.get(old, {}))
                return {"ok": False, "why": f"Temporal {v}: the {what} step failed ({why}); restored the snapshot, back at {old}", "done": done}
            done.append(f"{v} {what}")
    return {"ok": True, "why": f"Temporal moved from {old} to {new} through {', '.join(steps)}", "done": done}


def pinned(text):
    """The Temporal version a versions.env names."""
    m = re.search(r"^TEMPORAL_IMAGE=temporalio/server:(\S+?)@", text, re.M)
    return m.group(1) if m else ""


def real(repo, compose, snapshots=Path("/srv/ai/state/temporal-snapshots")):
    """The steps on this machine, through the deployment's compose (deploy.py's COMPOSE), with the secrets in the
    environment as the update runs (sops exec-env)."""
    import os
    import subprocess
    import time

    def sh(*args, env=None, inp=None, out=None):
        return subprocess.run(args, cwd=repo, env={**os.environ, **(env or {})}, input=inp, stdout=out, capture_output=out is None,
                              timeout=1800).returncode == 0

    def snapshot():
        d = snapshots / time.strftime("%Y%m%d-%H%M%S")
        d.mkdir(parents=True, exist_ok=True)
        for db in ("temporal", "temporal_visibility"):
            with (d / f"{db}.dump").open("wb") as f:
                if not sh(*compose, "exec", "-T", "postgres", "pg_dump", "-U", "litellm", "-Fc", db, out=f):
                    raise RuntimeError(f"the snapshot of {db} failed: nothing was changed")
        return d

    def restore(d):
        for db in ("temporal", "temporal_visibility"):
            sh(*compose, "exec", "-T", "postgres", "pg_restore", "-U", "litellm", "--clean", "--if-exists", "-d", db,
               inp=(d / f"{db}.dump").read_bytes())

    def schema(v, imgs):
        return sh(*compose, "run", "--rm", "temporal-schema", env={"TEMPORAL_ADMIN_IMAGE": imgs["admin"]})

    def server(v, imgs):
        return sh(*compose, "up", "-d", "--no-deps", "temporal", env={"TEMPORAL_IMAGE": imgs.get("server", "")}) if imgs else False

    def check(v, imgs):
        for _ in range(40):                                # its health check: the namespace API answers
            p = subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", "aistack-temporal-1"], capture_output=True, text=True)
            if p.stdout.strip() == "healthy":
                return True
            time.sleep(5)
        return False
    return dict(snapshot=snapshot, restore=restore, schema=schema, server=server, check=check)


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == "plan":
        print(" -> ".join(plan(a[1], a[2], table())) or "nothing to do")
        sys.exit(0)
    sys.exit(__doc__)

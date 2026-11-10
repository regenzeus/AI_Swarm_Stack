"""Artifacts (GEN-29, docs/AI-STACK.md): the files a step makes, kept by their SHA-256 under the deployment's artifact
folder, with one record naming the task, step, run and commit that made them, their data class and when they may go.
A run passes only their ids (artifact:<sha>), never their bytes. A file may be attached to a tracker item or a pull
request through a tracker write of kind attach (its body names the artifact).

    put(path, task, step, run, commit, data_class)   -> {"id": "artifact:<sha>", ...}: the record (one per file and maker)
    path_of(id)                                      the file of an artifact
    records(id)                                      who made it
    prune(now)                                       removes what is past the deployment's retention
"""
import datetime as dt
import hashlib
import json
import os
import shutil
from pathlib import Path

RETAIN_DAYS = 90                # limit: drops, an artifact past this many days is removed (the deployment may say otherwise: ARTIFACT_DAYS)


def root():
    return Path(os.environ.get("AISTACK_ARTIFACTS") or "/srv/ai/artifacts")


def _index():
    return root() / "index.jsonl"


def _days():
    return int(os.environ.get("ARTIFACT_DAYS") or RETAIN_DAYS)


def put(path, task="", step="", run="", commit="", data_class="private", now=None):
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    sha = h.hexdigest()
    dest = root() / sha[:2] / sha
    if not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        shutil.copyfile(path, tmp)
        tmp.replace(dest)
    now = now or dt.datetime.now(dt.timezone.utc)
    rec = {"id": f"artifact:{sha}", "sha256": sha, "name": path.name, "bytes": dest.stat().st_size, "task": task, "step": step,
           "run": run, "commit": commit, "data_class": data_class, "at": now.isoformat(timespec="seconds"),
           "until": (now + dt.timedelta(days=_days())).isoformat(timespec="seconds")}
    with _index().open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def _all():
    try:
        return [json.loads(x) for x in _index().read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError:
        return []


def records(aid):
    sha = str(aid).removeprefix("artifact:")
    return [r for r in _all() if r["sha256"] == sha]


def path_of(aid):
    sha = str(aid).removeprefix("artifact:")
    p = root() / sha[:2] / sha
    return p if p.is_file() else None


def prune(now=None):
    """Removes each artifact whose every record is past its retention; keeps the others' records."""
    now = (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds")
    recs = _all()
    keep = {r["sha256"] for r in recs if r["until"] > now}
    gone = {r["sha256"] for r in recs} - keep
    for sha in gone:
        p = root() / sha[:2] / sha
        if p.is_file():
            p.unlink()
    tmp = _index().with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in recs if r["sha256"] in keep), encoding="utf-8")
    tmp.replace(_index())
    return sorted(gone)

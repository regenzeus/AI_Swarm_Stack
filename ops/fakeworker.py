#!/usr/bin/env python3
"""The Windows worker's protocol in plain Python (GEN-11, docs/PLATFORM.md §6): the stack's tests and CI run it in place of
ops/windows/worker.ps1, over the same folder layout and by the same rules (ops/winjobs.py). Not for real work: it runs
as whoever starts it, with none of the account separation that is the real worker's boundary.

    python3 ops/fakeworker.py <root> [--once]      root holds inbox/, outbox/, jobs.d/, approved.json, repos/, scratch/

The worker's side of the protocol:
  inbox/<id>/request.json     {id, kind, values, at} and the request's files (a patch)   (the broker's copy of the stack's)
  outbox/<id>/claimed.json    {id, at, beat}: the lease; beat is refreshed every BEAT_S seconds while the job runs
  outbox/<id>/progress.jsonl  one line per step: {at, step, of, exit}
  outbox/<id>/result.json     {id, kind, status: done|failed|refused, error, steps: [{n, exit, seconds}], artifacts, ended}
  outbox/<id>/artifacts/      the files the kind collects, and log.txt
  outbox/status.json          {ts, kinds: {kind: {approved, why, sha, retry, lock}}, busy: {lock: id}}"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import winjobs as WJ  # noqa: E402

BEAT_S = 10
STALE_S = 3600                 # limit: refuses, a request older than this was left from before a sleep: nobody waits for it
# limit: drops, a job's log past this comes back as its end, with a marker saying how much was cut
LOG_MAX = 200_000
# limit: drops, artifacts past this many MB are not copied back; the result names them as left out
ARTIFACTS_MB = 50


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class Worker:
    MINUTE_S = 60                                        # a test makes a job's minutes shorter

    def __init__(self, root, beat_s=BEAT_S):
        self.root = Path(root)
        self.inbox, self.outbox, self.jobs = self.root / "inbox", self.root / "outbox", self.root / "jobs.d"
        self.repos, self.scratch = self.root / "repos", self.root / "scratch"
        self.beat_s = beat_s
        self.busy = {}

    def approvals(self):
        try:
            return json.loads((self.root / "approved.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}

    def names(self):
        """The names a 'name' parameter may take: the entries of each folder of the worker's root."""
        return {d.name: {e.name for e in d.iterdir()} for d in self.root.iterdir() if d.is_dir()}

    def status(self):
        kinds, appr = WJ.load_kinds(self.jobs), self.approvals()
        save(self.outbox / "status.json", {
            "ts": int(time.time()),
            "kinds": {n: {"approved": WJ.approved(n, kinds, appr) is None, "why": WJ.approved(n, kinds, appr), "sha": sha,
                          "retry": bool(k.get("retry")), "lock": k.get("lock") or n} for n, (k, sha, _p) in kinds.items()},
            "busy": dict(self.busy)})

    def take(self):
        """The oldest request of the inbox that has no answer folder yet, or None. The worker may only read the inbox (the
        broker writes and empties it), so an answer folder is what marks a request as taken."""
        if not self.inbox.is_dir():
            return None
        for d in sorted((d for d in self.inbox.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime):
            if WJ.ID.fullmatch(d.name) and not (self.outbox / d.name).exists():
                return d
        return None

    def refuse(self, rid, kind, why):
        save(self.outbox / rid / "result.json", {"id": rid, "kind": kind, "status": "refused", "error": why, "steps": [], "artifacts": [],
                                                  "ended": int(time.time())})

    def run(self, req_dir):
        rid = req_dir.name
        try:
            req = json.loads((req_dir / "request.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return self.refuse(rid, None, "the request could not be read")
        kind_name = str(req.get("kind") or "")
        if req.get("id") != rid:
            return self.refuse(rid, kind_name, "the request's id is not its folder's")
        if time.time() - float(req.get("at") or 0) > STALE_S:
            return self.refuse(rid, kind_name, "the request waited over an hour, so it was dropped")
        kinds = WJ.load_kinds(self.jobs)
        why = WJ.approved(kind_name, kinds, self.approvals())
        if why:
            return self.refuse(rid, kind_name, why)
        k = kinds[kind_name][0]
        values, why = WJ.check_values(k, req.get("values") or {}, req_dir, self.names())
        if why:
            return self.refuse(rid, kind_name, why)
        if "patch" in (k.get("params") or {}):
            why = WJ.check_patch(k, (req_dir / values["patch"]).read_text(encoding="utf-8", errors="replace"))
            if why:
                return self.refuse(rid, kind_name, why)
        out = self.outbox / rid
        scratch = self.scratch / rid
        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir(parents=True)
        lock = k.get("lock") or kind_name
        self.busy[lock] = rid
        stop = threading.Event()
        save(out / "claimed.json", {"id": rid, "at": int(time.time()), "beat": time.time()})

        def beat():
            while not stop.wait(self.beat_s):
                save(out / "claimed.json", {"id": rid, "at": int(time.time()), "beat": time.time()})
        threading.Thread(target=beat, daemon=True).start()
        builtins = {"scratch": str(scratch), "repos": str(self.repos), "out": str(out / "artifacts"),
                    "patch": str((req_dir / values["patch"]).resolve()) if "patch" in values else ""}
        steps, log, status, error = [], [], "done", None
        deadline = time.time() + self.MINUTE_S * k["minutes"]
        for n, step in enumerate(k["steps"], 1):
            args = WJ.fill(step, {p: v for p, v in values.items() if p != "patch"}, builtins)
            t0 = time.time()
            try:
                p = subprocess.run(args, cwd=scratch, capture_output=True, text=True, timeout=max(1, deadline - time.time()))
                code, said = p.returncode, p.stdout + p.stderr
            except subprocess.TimeoutExpired:
                code, said = None, ""
                status, error = "failed", f"step {n} ({step[0]}) stopped at the job's time limit of {k['minutes']} minutes"
            except OSError as e:
                code, said = None, ""
                status, error = "failed", f"step {n}: {step[0]} could not be started ({e.strerror})"
            log.append(f"$ step {n}: {step[0]}\n{said}")
            steps.append({"n": n, "exit": code, "seconds": round(time.time() - t0, 1)})
            with (out / "progress.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": int(time.time()), "step": n, "of": len(k["steps"]), "exit": code}) + "\n")
            if status == "failed":
                break
            if code != 0:
                status, error = "failed", f"step {n} ({step[0]}) exited with {code}"
                break
        stop.set()
        arts = out / "artifacts"
        arts.mkdir(parents=True, exist_ok=True)
        text = "\n".join(log)
        if len(text) > LOG_MAX:                              # cap: store (the end is what explains a failure)
            text = f"[… the first {len(text) - LOG_MAX:,} characters of the log were cut]\n" + text[-LOG_MAX:]
        (arts / "log.txt").write_text(text, encoding="utf-8")
        names, left, size = ["log.txt"], [], 0
        for f in WJ.collect_matches(scratch, k.get("collect") or []):
            size += f.stat().st_size
            if size > ARTIFACTS_MB * 1024 * 1024:            # limit: drops, as ARTIFACTS_MB above (named in left_out)
                left.append(f.relative_to(scratch).as_posix())
                continue
            dest = arts / f.relative_to(scratch).as_posix().replace("/", "__")
            shutil.copyfile(f, dest)
            names.append(dest.name)
        self.busy.pop(lock, None)
        shutil.rmtree(scratch, ignore_errors=True)
        save(out / "result.json", {"id": rid, "kind": kind_name, "status": status, "error": error, "steps": steps, "artifacts": names,
                                   "left_out": left, "ended": int(time.time())})

    def once(self):
        self.status()
        d = self.take()
        if d:
            (self.outbox / d.name).mkdir(parents=True, exist_ok=True)      # taken, before anything else happens
            self.run(d)
            self.status()
        return d is not None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    w = Worker(sys.argv[1])
    if "--once" in sys.argv:
        w.once()
    else:
        while True:
            if not w.once():
                time.sleep(2)

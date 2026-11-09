"""PLT-21: the runner's growing files are pruned once a day: event lines, run logs, and build logs and diffs older than
90 days. Run summaries stay for good (the runs table, task_occ, the run record's summaries, the vault's reports);
the app prunes its own uploads and the run record's events (images/mission-control/server.py rt_housekeeping).
  python3 ops/prune.py     one pass now, with the counts"""
import datetime as dt
import json
import threading
import time
from pathlib import Path

KEEP_S = 90 * 86400
BUILD_FILES = (".log", ".diff", ".steps", ".files", ".context.json")   # a build's own logs; its row stays
M = None                                             # ops/missions.py, set by its main()


def old_files(folder, now, suffixes=None):
    """Files under folder last written more than KEEP_S ago (only these suffixes when given)."""
    d = Path(folder)
    if not d.is_dir():
        return []
    return [f for f in d.rglob("*") if f.is_file() and now - f.stat().st_mtime > KEEP_S and (not suffixes or f.name.endswith(suffixes))]


def events(path, now, lock):
    """Drop event lines older than KEEP_S from events.jsonl, under the writer's own lock (missions.event appends there);
    a line that cannot be read stays. -> lines dropped."""
    p = Path(path)
    if not p.exists():
        return 0
    cut = dt.datetime.fromtimestamp(now - KEEP_S).astimezone()
    with lock:
        keep, dropped = [], 0
        for ln in p.read_text().splitlines():
            try:
                old = dt.datetime.fromisoformat(json.loads(ln)["ts"]) < cut
            except (ValueError, KeyError, TypeError):
                old = False
            dropped += old
            if not old:
                keep.append(ln)
        if dropped:
            tmp = p.with_suffix(".jsonl.tmp")
            tmp.write_text("".join(x + "\n" for x in keep))
            tmp.replace(p)
    return dropped


def run(now=None, public=None, runlogs=None, builds=None, lock=None):
    """One pass. -> {events, run_logs, build_files}."""
    now = now or time.time()
    out = {"events": events((public or M.PUBLIC) / "events.jsonl", now, lock or M.EVENTS_LOCK)}
    for key, files in (("run_logs", old_files(runlogs or M.RUNLOGS, now)), ("build_files", old_files(builds or Path("/srv/ai/missions/builds"), now, BUILD_FILES))):
        for f in files:
            f.unlink()
        out[key] = len(files)
    return out


def worker():
    while not M.stop.is_set():
        try:
            n = run()
            if any(n.values()):
                M.log(f"prune: older than 90 days: {n['events']} event lines, {n['run_logs']} run logs, {n['build_files']} build files")
        except Exception as e:                       # logged; tried again tomorrow
            M.log(f"prune: {type(e).__name__}: {e}")
        M.stop.wait(86400)


def start():
    threading.Thread(target=worker, daemon=True, name="prune").start()


if __name__ == "__main__":
    import missions
    M = missions
    print(run())

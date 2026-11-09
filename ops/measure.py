#!/usr/bin/env python3
"""A measured change (GEN-17, docs/PLATFORM.md §8): one real change request, done by one coder and by the stack's loop on
the same commit, side by side: tests passed, tokens, builds, minutes, and what memory gave and what of it was used.

    python3 ops/measure.py run <repo> <case> [arm ...]     the arms one after another (default: one-coder stack), then the report
    python3 ops/measure.py report <repo> [--since "YYYY-MM-DD HH:MM"] [--case N]

A case is one of ops/replay.py's (a real commit with its tests; `ops/replay.py pick` and `check` make them), so the change
is a real one with a program for its judge. On a metered gateway the tokens are money: this is the number to decide by."""
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = Path("/srv/ai/trials/runs")
MEMORY = Path("/srv/ai/missions/memory/runs.jsonl")
DEFAULT_ARMS = ("one-coder", "stack")


def memory_of(task, log):
    """What the memory stack gave the task's openings (the intake and every step), what could be measured and what was used."""
    g = m = u = n = 0
    for r in log:
        run = str(r.get("run", ""))
        if run.startswith((f"task:{task}:", f"task-intake:{task}-")):
            g, m, u, n = g + (r.get("chars") or 0), m + (r.get("measurable_chars") or 0), u + (r.get("used_chars") or 0), n + 1
    return {"given": g, "measurable": m, "used": u, "openings": n}


def runs(repo, since="", case=None, runs_dir=None, memory=None):
    """-> one row per run of the repository's replay exam (newest last)."""
    log = []
    mem = Path(memory or MEMORY)
    for ln in mem.read_text(encoding="utf-8").splitlines() if mem.is_file() else []:
        try:
            log.append(json.loads(ln))
        except ValueError:
            pass
    out = []
    for f in sorted(Path(runs_dir or RUNS).glob(f"replay-{repo}-*/result.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        m = re.match(rf"replay-{re.escape(repo)}-(\d+)-", f.parent.name)
        n = int(m.group(1)) if m else None
        if (r.get("started_at") or "") < since or (case is not None and n != case):
            continue
        s, mt = r.get("score") or {}, r.get("metrics") or {}
        out.append({"start": r.get("started_at"), "case": n, "arm": r.get("arm"), "version": r.get("version"),
                    "passed": s.get("passed"), "total": s.get("total"), "tokens": mt.get("tokens") or 0,
                    "builds": len(r.get("builds") or []), "minutes": mt.get("minutes"), **memory_of(r.get("task"), log)})
    return sorted(out, key=lambda x: x["start"] or "")


def report(rows):
    """Markdown: each run, then each case and arm with medians."""
    lines = ["| Started | Case | Arm | Version | Tests | Tokens | Builds | Minutes | Memory given | Used of measurable |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for x in rows:
        share = f"{x['used'] / x['measurable']:.0%}" if x["measurable"] else "–"
        lines.append(f"| {x['start']} | {x['case']} | {x['arm']} | {x['version']} | {x['passed']} of {x['total']} | {x['tokens']:,} | "
                     f"{x['builds']} | {x['minutes']} | {x['given']:,} | {share} |")
    groups = {}
    for x in rows:
        groups.setdefault((x["case"], x["arm"]), []).append(x)
    lines += ["", "| Case | Arm | Runs | Every test passed | Median tokens | Median builds | Median minutes |", "|---|---|---|---|---|---|---|"]
    for (c, a), xs in sorted(groups.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1] or "")):
        full = sum(1 for x in xs if x["passed"] is not None and x["passed"] == x["total"])
        med = lambda k: statistics.median(x[k] or 0 for x in xs)
        lines.append(f"| {c} | {a} | {len(xs)} | {full} of {len(xs)} | {med('tokens'):,.0f} | {med('builds'):g} | {med('minutes'):g} |")
    return "\n".join(lines)


def run(repo, case, arms=DEFAULT_ARMS, call=subprocess.run):
    """The arms one after another on the same case (each a whole replay run), then the report of that case."""
    for arm in arms:
        print(f"== {repo} case {case}: {arm}", flush=True)
        call([sys.executable, str(ROOT / "ops/replay.py"), "run", repo, str(case), arm], check=False)
    return report(runs(repo, case=case))


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == "run":
        print(run(a[1], int(a[2]), tuple(a[3:]) or DEFAULT_ARMS))
    elif len(a) >= 2 and a[0] == "report":
        since = a[a.index("--since") + 1] if "--since" in a else ""
        case = int(a[a.index("--case") + 1]) if "--case" in a else None
        print(report(runs(a[1], since=since, case=case)))
    else:
        sys.exit(__doc__)

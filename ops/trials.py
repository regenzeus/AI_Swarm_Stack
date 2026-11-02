#!/usr/bin/env python3
"""Trials (phase 10a, docs/SWARM-TRIALS.md): a task the owner could type, given through the real front door, scored by
a program against an answer key no agent can reach, audited for the clean room, and reported.

  python3 ops/trials.py check NAME   the answer key scores its own reference solution fully (a key that cannot is wrong)
  python3 ops/trials.py run NAME     one run: a fresh repository with the specification, the task through intake as
                                     the owner would give it, watched to its end or its budget, scored, audited, reported
  python3 ops/trials.py follow NAME RUN TASK   pick up a run whose harness stopped (its task goes on meanwhile)
  python3 ops/trials.py rescore NAME RUN       score a recorded run again with today's key, recount its tokens (kept: before)
  make trial NAME=…                  the same run in the background (a transient systemd unit); make trial-check NAME=…

A trial is eval/trials/<name>.yaml (the task, what is forbidden, the budget); its answer key is
/srv/ai/private/trials/<key>/ (inputs/ for the agents, score.py and its vectors, reference/ to prove the key, the
upstream code for the similarity check), which no container mounts. Each run keeps its delivered code, score and audit
in /srv/ai/trials/runs/<run>/, its report in the vault (trials/<name>/<run>.md) and a copy of its result in eval/results.
"""
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import time
import tokenize
import uuid
import textcap as TC                              # visible caps (AGENTS.md, truncation)
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ops"))
TRIALS = ROOT / "eval/trials"
KEYS = Path("/srv/ai/private/trials")                # answer keys: /srv/ai/private is in no container
RUNS = Path("/srv/ai/trials/runs")
PUBLIC = Path("/srv/ai/missions/public")              # the app's scoreboard reads public/trials.json (TRL-09)
HOME = Path("/srv/ai/missions")
INBOX, RESULTS, DB, RT_DB, BUILD_LOGS = HOME / "inbox", HOME / "public/results", HOME / "missions.sqlite", HOME / "app/runtime.db", HOME / "builds"
CODE, VAULT = Path.home() / "code", Path("/srv/vault")
IMAGE = "python:3.12-slim"                          # the scorer's sandbox: no network, read-only, nobody, 512 MB
SANDBOX = ["docker", "run", "--rm", "--network", "none", "--memory", "512m", "--cpus", "1", "--read-only", "-u", "65534"]
UNATTENDED = "Decide it yourself from the specification in the repository's spec/ folder: this is an unattended trial."
END = ("done", "failed", "cancelled")


# ---------- the trial's definition ----------
def load(name, root=TRIALS):
    """eval/trials/<name>.yaml, checked: ValueError says what is wrong."""
    f = root / f"{name}.yaml"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}", name) or not f.is_file():
        raise ValueError(f"no trial called {name!r} in {root}")
    t = yaml.safe_load(f.read_text()) or {}
    errs = [k for k in ("name", "title", "task", "key", "forbidden", "budget") if not t.get(k)]
    if errs:
        raise ValueError(f"{f.name}: missing {', '.join(errs)}")
    if t["name"] != name:
        raise ValueError(f"{f.name}: its name is {t['name']!r}")
    if len(str(t["task"])) < 40:
        raise ValueError(f"{f.name}: the task must say what to build, in the owner's words")
    fb = t["forbidden"]
    try:
        t["_urls"] = [re.compile(x) for x in fb.get("urls") or []]
        t["_commands"] = [re.compile(x) for x in fb.get("commands") or []]
    except re.error as e:
        raise ValueError(f"{f.name}: a forbidden pattern does not compile: {e}") from None
    b = t["budget"]
    if not (0 < float(b.get("hours", 0)) <= 24):
        raise ValueError(f"{f.name}: budget.hours must be between 0 and 24")
    t.setdefault("flag_similarity", 0.3)
    t.setdefault("effort", "standard")
    return t


def key_dir(t):
    return KEYS / t["key"]


# ---------- the answer key and its scorer ----------
def score(code, key, run=subprocess.run, timeout=300):
    """The key's score.py over the delivered code, in the sandbox. -> {cases, error, passed, total, areas}."""
    p = run([*SANDBOX, "-v", f"{code}:/code:ro", "-v", f"{key}:/key:ro", IMAGE, "python3", "/key/score.py", "/code"],
            capture_output=True, text=True, timeout=timeout)
    try:
        d = json.loads(p.stdout)
    except ValueError:
        d = {"cases": [], "error": f"the scorer gave no result (exit {p.returncode}): {TC.tail(p.stderr or p.stdout, 400)}"}  # cap: preview
    return summarise(d)


def summarise(d):
    cases = d.get("cases") or []
    areas = {}
    for c in cases:
        a = areas.setdefault(c["area"], [0, 0])
        a[0] += bool(c["ok"])
        a[1] += 1
    return {**d, "passed": sum(bool(c["ok"]) for c in cases), "total": len(cases), "areas": areas}


def check(t, run=subprocess.run):
    """The key scores its own reference solution fully, else the key or the scorer is wrong."""
    k = key_dir(t)
    s = score(k / "reference", k, run=run)
    if s["error"] or not s["total"] or s["passed"] != s["total"]:
        bad = [c["id"] for c in s["cases"] if not c["ok"]][:5]   # cap: preview
        raise RuntimeError(f"the answer key of {t['name']} does not pass its own reference: {s['error'] or bad}")
    return s


# ---------- the clean-room audit ----------
def tool_inputs(log_text):
    """What a builder's agent did (its tool calls' inputs) from a build's .steps file or its Claude Code stream: the
    commands it ran and the files it wrote, not the prompt it was given (which names what is forbidden)."""
    out = []
    try:
        for e in json.loads(log_text):                   # a .steps file: [{kind, tool, text}]
            if e.get("kind") == "call":
                out.append(str(e.get("text") or ""))
        return out
    except (ValueError, TypeError, AttributeError):
        pass
    for line in log_text.splitlines():                   # a stream-json log: assistant messages with tool_use blocks
        try:
            m = json.loads(line)
        except ValueError:
            continue
        for b in ((m.get("message") or {}).get("content") or []) if isinstance(m, dict) else []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                out.append(json.dumps(b.get("input"), ensure_ascii=False))
    return out


def audit(t, sources):
    """sources: [(where, kind, text)], kind "url" (a page an agent read), "action" (a tool call's input) or "code"
    (a delivered file). -> {ok, forbidden: [{where, pattern, excerpt}]}."""
    hits = []
    for where, kind, text in sources:
        pats = t["_urls"] if kind == "url" else t["_commands"]
        for p in pats:
            m = p.search(text or "")
            if m:
                a = max(0, m.start() - 60)
                hits.append({"where": where, "pattern": p.pattern, "excerpt": text[a:m.end() + 60]})   # cap: preview
    return {"ok": not hits, "forbidden": hits}


def fingerprints(src, k=12):
    """Winnowed hashes of normalised Python tokens (names, strings and numbers stand for their kind, as in MOSS and
    JPlag): renaming and reformatting do not hide copied code."""
    toks = []
    try:
        for tk in tokenize.generate_tokens(io.StringIO(src).readline):
            if tk.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING):
                continue
            toks.append("N" if tk.type == tokenize.NAME and not __import__("keyword").iskeyword(tk.string) else
                        "S" if tk.type == tokenize.STRING else "0" if tk.type == tokenize.NUMBER else tk.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return set()
    grams = [int(hashlib.blake2b(" ".join(toks[i:i + k]).encode(), digest_size=6).hexdigest(), 16) for i in range(len(toks) - k + 1)]
    w = 4
    return {min(grams[i:i + w]) for i in range(max(0, len(grams) - w + 1))} or set(grams)


def py_files(d):
    return [f for f in sorted(Path(d).rglob("*.py")) if not any(x in f.parts for x in (".git", "tests", "test", ".venv"))
            and not f.name.startswith("test_")]


def similarity(code, reference):
    """The share of the delivered code's fingerprints found in the reference implementation (0 to 1), and the files
    that share most."""
    ref = set()
    for f in py_files(reference):
        ref |= fingerprints(f.read_text(errors="replace"))
    rows, mine = [], set()
    for f in py_files(code):
        fp = fingerprints(f.read_text(errors="replace"))
        mine |= fp
        if fp:
            rows.append({"file": str(f.relative_to(code)), "share": round(len(fp & ref) / len(fp), 3)})
    return {"share": round(len(mine & ref) / len(mine), 3) if mine else 0.0, "files": sorted(rows, key=lambda r: -r["share"])[:5]}   # cap: list


# ---------- talking to the runner like the app does ----------
def request(req, wait=120):
    """An owner's request through the runner's inbox (as the app sends it); its answer."""
    rid = "trial" + uuid.uuid4().hex[:12]
    tmp = INBOX / f".{rid}.tmp"
    tmp.write_text(json.dumps({**req, "source": req.get("source") or "trial"}, ensure_ascii=False))
    tmp.rename(INBOX / f"{rid}.json")
    end = time.time() + wait
    while time.time() < end:
        f = RESULTS / f"{rid}.json"
        if f.exists():
            r = json.loads(f.read_text())
            if not r.get("ok", True):
                raise RuntimeError(f"{req['action']}: {r.get('error')}")
            return r["result"] if isinstance(r.get("result"), dict) else {k: v for k, v in r.items() if k != "ok"}   # {"ok", "task": 88} or {"ok", "result": …}
        time.sleep(1)
    raise RuntimeError(f"{req['action']}: the runner did not answer in {wait} s")


def db():
    import sqlite3
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def git(path, *args, timeout=120):
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=timeout, check=True).stdout


# ---------- one run ----------
def make_repo(t, run_id):
    """A fresh repository for the run on Forgejo (push-to-create), holding the specification and, for a trace (T2,
    code: true), the implementation to trace in code/."""
    repo = f"trial-{run_id}"
    d = CODE / repo
    d.mkdir(parents=True)
    shutil.copytree(key_dir(t) / "inputs", d / "spec")
    if t.get("code"):
        shutil.copytree(key_dir(t) / "code", d / "code")
    (d / "README.md").write_text(f"# {t['title']}\n\nA trial workspace (docs/SWARM-TRIALS.md in ai-stack). The specification is in spec/"
                                 + (", the implementation in code/" if t.get("code") else "") + ".\n\n"
                                 f"## The task\n\n{t['task'].strip()}\n")
    (d / ".gitignore").write_text("__pycache__/\n*.pyc\n.venv/\n.pytest_cache/\n")
    git(d, "init", "-q", "-b", "main")
    git(d, "add", "-A")
    git(d, "-c", "user.name=AI stack trials", "-c", "user.email=trials@stack.local", "commit", "-q", "-m", f"Trial {run_id}: the specification")
    git(d, "remote", "add", "origin", f"forgejo:regenzeus/{repo}.git")
    git(d, "push", "-q", "-u", "origin", "main", timeout=180)
    return repo


def build_ids(c, tid, repo=None):
    """The task's builds: every build in the trial's own repository (a failed step's next attempt is a new build, and
    the step keeps only the newest), else its plan's build steps, or the build it became given straight to the builder."""
    if repo:
        got = [r["id"] for r in c.execute("select id from builds where repo=? order by id", (repo,))]
        if got:
            return got
    row = c.execute("select door, ref from tasks where id=?", (tid,)).fetchone()
    if row and row["door"] == "build" and str(row["ref"] or "").isdigit():
        return [int(row["ref"])]
    out = []
    for r in c.execute("select resume from task_steps where task=? order by occ, idx", (tid,)):
        try:
            b = json.loads(r["resume"] or "{}").get("build")
        except ValueError:
            b = None
        if b:
            out.append(int(b))
    return out


def tree(tid, rt_db=RT_DB):
    """The runtime record's runs of the task, its steps and whatever they started."""
    import sqlite3
    if not Path(rt_db).exists():
        return []
    c = sqlite3.connect(f"file:{rt_db}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    seen = {r["run"] for r in c.execute("select run from runs where run like ? or run like ?", (f"task:{tid}", f"task:{tid}%"))}
    new = set(seen)
    while new:
        q = ",".join("?" * len(new))
        new = {r["run"] for r in c.execute(f"select run from runs where ref in ({q})", tuple(new))} - seen
        seen |= new
    rows = [dict(r) for r in c.execute(f"select * from runs where run in ({','.join('?' * len(seen))})", tuple(seen))] if seen else []
    calls = [dict(r) for r in c.execute(f"select run, title, detail from events where kind='call' and run in ({','.join('?' * len(seen))})", tuple(seen))] if seen else []
    return rows, calls


def watch(t, tid, started, poll=30, log=print):
    """Until the task ends or the budget does; an intake question is answered with UNATTENDED (and counted)."""
    asked, deadline = 0, started + float(t["budget"]["hours"]) * 3600
    while True:
        with db() as c:
            row = dict(c.execute("select * from tasks where id=?", (tid,)).fetchone())
        st = row["status"]
        if st in END or (st == "scheduled" and row.get("door") == "plan"):
            return row, asked, False
        if row.get("door") == "build" and str(row.get("ref") or "").isdigit():      # given straight to the builder: its
            with db() as c:                                                          # build at review is the delivery
                b = c.execute("select status from builds where id=?", (int(row["ref"]),)).fetchone()
            if b and b["status"] in ("review", "failed", "rejected", "cancelled"):
                return row, asked, False
        if time.time() > deadline:
            return row, asked, True
        if st == "needs_answer":
            qs = json.loads(row.get("questions") or "[]")
            asked += len(qs)
            log(f"intake asked {len(qs)} question(s); answered for the unattended trial")
            request({"action": "task_answer", "id": tid, "answers": [UNATTENDED] * len(qs)})
        elif st == "waiting_approval":
            request({"action": "task_approve", "id": tid})
        time.sleep(poll)


def deliverable(c, repo, bids, dest):
    """What the trial scores and audits, archived into dest: its repository's main when the stages' builds were merged
    there (TRL-05), else the last build's branch head."""
    merged = [r for r in (c.execute("select * from builds where id=?", (b,)).fetchone() for b in bids) if r and r["status"] == "merged"]
    if merged:
        git(CODE / repo, "fetch", "-q", "origin", "main", timeout=180)
        dest.mkdir(parents=True, exist_ok=True)
        data = subprocess.run(["git", "-C", str(CODE / repo), "archive", "origin/main"], capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(dest)], input=data, check=True)
        last = dict(merged[-1])
        return {**last, "status": "merged", "head": git(CODE / repo, "rev-parse", "origin/main").strip(), "branch": "main"}
    for bid in reversed(bids):
        b = c.execute("select * from builds where id=?", (bid,)).fetchone()
        if b and b["head"] and b["branch"]:
            git(CODE / repo, "fetch", "-q", "origin", b["branch"], timeout=180)
            dest.mkdir(parents=True, exist_ok=True)
            data = subprocess.run(["git", "-C", str(CODE / repo), "archive", b["head"]], capture_output=True, check=True).stdout
            subprocess.run(["tar", "-x", "-C", str(dest)], input=data, check=True)
            return dict(b)
    return None


def answered(c, tid, opened, dest):
    """A research exam's deliverable (TRL-16): the task's answer as answer.md and the pages its agents opened as
    opened.txt, so the key checks each claim and that each cited page was read. -> {"id": task} or None."""
    row = c.execute("select result from tasks where id=?", (tid,)).fetchone()
    f = VAULT / str((row or {"result": ""})["result"] or "")
    if not row or not str(row["result"] or "").startswith("tasks/") or not f.is_file():
        return None
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "answer.md").write_text(f.read_text(errors="replace"))
    (dest / "opened.txt").write_text("\n".join(sorted(set(opened))) + "\n")
    return {"id": tid, "status": "answered"}


def report(t, r):
    """The run's report, for the owner (the vault) and for the scoreboard (the JSON is the record)."""
    s, a, sim, m = r["score"], r["audit"], r["similarity"], r["metrics"]
    pct = (100 * s["passed"] / s["total"]) if s["total"] else 0
    lines = [f"# Trial: {t['title']}", "", f"Run {r['run']} · {r['started_at']} · task #{r['task']} · repository {r['repo']}", "",
             "## Outcome", "",
             f"**{s['passed']} of {s['total']} answer-key cases passed ({pct:.0f}%)**" + (f": {s['error']}" if s.get("error") else "") +
             (" · stopped at its budget" if r["over_budget"] else ""), ""]
    if s["areas"]:
        lines += ["| Area | Passed |", "|---|---|"] + [f"| {k} | {v[0]} of {v[1]} |" for k, v in sorted(s["areas"].items())] + [""]
    fails = [c for c in s.get("cases") or [] if not c["ok"]]
    if fails:
        lines += [f"Failed cases ({len(fails)}):", ""] + [f"- {c['id']}: {c['detail']}" for c in fails[:40]]   # cap: list (all of them are in the run's result.json)
        lines += [f"- … and {len(fails) - 40} more, in {r['dir']}/result.json" if len(fails) > 40 else "", ""]
    rev = s.get("review") or []
    if rev:                                              # TRL-13: the key is a reading of the code, not all of it
        lines += [f"Gaps beyond the answer key, for review ({len(rev)}): unscored; each may be a real defect the key does not know yet.", ""]
        lines += [f"- {g['id']}: {g.get('why') or ''}" for g in rev[:60]]   # cap: list (all of them are in the run's result.json)
        lines += [f"- … and {len(rev) - 60} more, in {r['dir']}/result.json" if len(rev) > 60 else "", ""]
    if r.get("rescored"):
        b = r["rescored"]
        lines += [f"Rescored {b['at']} with the key and code of {b['version']}: before, {b['before']['passed']} of {b['before']['total']}"
                  f" and {b['before']['tokens']:,} tokens.", ""]
    lines += ["## Clean room", "",
              "No forbidden read or action found." if a["ok"] else f"**{len(a['forbidden'])} forbidden reads or actions:**",
              *[f"- {h['where']}: `{h['pattern']}`: …{h['excerpt']}…" for h in a["forbidden"]],
              f"Similarity to the upstream implementation: {sim['share']:.0%} of the delivered code's fingerprints"
              + (f" (**above {t['flag_similarity']:.0%}: look at it**)" if sim["share"] > t["flag_similarity"] else ""), ""]
    lines += ["## How it went", "",
              f"- Task: {m['status']}{' · ' + m['error'] if m.get('error') else ''}; judged {m.get('verdict') or 'not yet'} by the model judge"
              + (" (**it disagrees with the answer key**)" if m.get("verdict") in ("not met", "partly") and s["total"] and s["passed"] == s["total"]
                 or m.get("verdict") == "met" and s["total"] and s["passed"] < s["total"] else ""),
              f"- Time: {m['minutes']} min of a {t['budget']['hours']} h budget",
              f"- Plan: {m['steps']} step(s): " + "; ".join(m["plan"]),
              f"- Builds: {', '.join('#' + str(b) for b in r['builds']) or 'none'}" + (f" · the scored one #{r['build']['id']} ({r['build']['status']}, {r['build'].get('attempts') or 1} attempt(s))" if r.get("build") else ""),
              f"- Model calls recorded: {m['calls']} · tokens {m['tokens']:,} (the builder's own: {m['builder_tokens']:,}) of a {t['budget'].get('tokens', 0):,} budget",
              f"- Questions the intake asked (answered for the unattended trial): {r['asked']}", ""]
    return "\n".join(x for x in lines if x is not None)


# ---------- the scoreboard (TRL-09) ----------
def board_row(r):
    """One run as the scoreboard shows it: its score per area, the clean room, the cost and how it went."""
    s, m = r.get("score") or {}, r.get("metrics") or {}
    return {"trial": r["trial"], "run": r["run"], "started": r.get("started_at"), "version": r.get("version"), "task": r.get("task"),
            "passed": s.get("passed", 0), "total": s.get("total", 0), "areas": s.get("areas") or {}, "error": s.get("error"),
            "clean": (r.get("audit") or {}).get("ok"), "forbidden": len((r.get("audit") or {}).get("forbidden") or []),
            "similarity": (r.get("similarity") or {}).get("share"), "minutes": m.get("minutes"), "tokens": m.get("tokens"),
            "builder_tokens": m.get("builder_tokens"), "steps": m.get("steps"), "asked": r.get("asked"), "over_budget": r.get("over_budget"),
            "verdict": m.get("verdict"), "attempts": (r.get("build") or {}).get("attempts"), "builds": len(r.get("builds") or []),
            "review": len(s.get("review") or []), "rescored": (r.get("rescored") or {}).get("at"),
            "report": f"trials/{r['trial']}/{r['run']}.md"}


def publish(runs=RUNS, out=PUBLIC, log=print):
    """Every trial run side by side, oldest first, with the trials' titles: public/trials.json for the app."""
    rows = []
    for f in sorted(Path(runs).glob("*/result.json")):
        try:
            row = board_row(json.loads(f.read_text()))
            m = Path(out) / "maps" / f"{row['task']}.1.json"          # the run's swarm map: how the agents worked together
            n = json.loads(m.read_text()).get("numbers") or {} if row["task"] and m.exists() else {}
            rows.append({**row, "agents": n.get("agents"), "parallel": n.get("parallel"), "read": n.get("read"), "cited": n.get("cited")})
        except (ValueError, KeyError) as e:              # a broken record is left out and named
            log(f"trials: {f}: not on the scoreboard: {type(e).__name__}: {e}")
    titles = {p.stem: (yaml.safe_load(p.read_text()) or {}).get("title") or p.stem for p in TRIALS.glob("*.yaml")}
    rows.sort(key=lambda x: x["started"] or "")
    tmp = Path(out) / "trials.json.tmp"
    tmp.write_text(json.dumps({"trials": titles, "runs": rows}, ensure_ascii=False))
    tmp.replace(Path(out) / "trials.json")
    return rows


def model_calls(runs, rt_db=None):
    """(calls, tokens) of the runs' own model calls in the run record, each call once (FND-101: a run's summary is taken
    when it ends, so a parent that ended before its build holds part of it, and adding summaries counts some twice)."""
    import sqlite3
    names = [r["run"] for r in runs]
    if not names or not Path(rt_db or RT_DB).exists():
        return 0, 0
    c = sqlite3.connect(f"file:{rt_db or RT_DB}?mode=ro", uri=True, timeout=10)
    rows = c.execute(f"select data from events where kind='llm' and run in ({','.join('?' * len(names))})", names).fetchall()
    c.close()
    tokens = 0
    for (data,) in rows:
        try:
            tok = json.loads(data or "{}").get("tokens") or {}
        except ValueError:
            tok = {}
        tokens += int(tok.get("in") or 0) + int(tok.get("out") or 0)
    return len(rows), tokens


def metrics(c, tid, bids, rt, rt_db=None):
    row = dict(c.execute("select * from tasks where id=?", (tid,)).fetchone())
    steps = [dict(s) for s in c.execute("select idx, title, agent, status from task_steps where task=? order by occ, idx", (tid,))]
    runs, _ = rt
    inside = {r["run"] for r in runs}
    calls, tokens = model_calls(runs, rt_db)
    btok = sum((c.execute("select tokens from builds where id=?", (b,)).fetchone() or {"tokens": 0})["tokens"] or 0 for b in bids)
    tokens += sum((c.execute("select tokens from builds where id=?", (b,)).fetchone() or {"tokens": 0})["tokens"] or 0
                  for b in bids if not any(x.startswith(f"build:{b}:") for x in inside))   # a build outside the trace
    import datetime as dt
    mins = round((dt.datetime.fromisoformat(row["updated"]) - dt.datetime.fromisoformat(row["created"])).total_seconds() / 60)
    return {"status": row["status"], "error": row.get("error"), "verdict": row.get("verdict"), "minutes": mins, "steps": len(steps),
            "plan": [f"{s['idx']} {s['agent']}: {s['title']} ({s['status']})" for s in steps], "calls": calls, "tokens": tokens, "builder_tokens": btok}


def run(name, log=print):
    t = load(name)
    check(t)                                             # a key that cannot score its own reference proves nothing
    run_id = f"{name}-{time.strftime('%Y%m%d-%H%M')}"
    d = RUNS / run_id
    d.mkdir(parents=True)
    research = t.get("kind") == "research"              # TRL-16: an exam answered from the web, no repository
    repo = "" if research else make_repo(t, run_id)
    log(f"{run_id}: " + ("a research exam" if research else f"repository {repo} with the specification") + "; giving the task")
    started = time.time()
    res = request({"action": "task_create", "text": t["task"].strip(), "kind": "research" if research else "coding", **({} if research else {"repo": repo}),
                   "effort": t["effort"], "budget": t["budget"], **({"done": t["done"]} if t.get("done") else {}), "source": f"trial:{name}"})
    tid = int(res["task"])
    return follow(t, run_id, repo, tid, started, log)


def follow(t, run_id, repo, tid, started, log=print):
    """Watch the run's task to its end or its budget, then score, audit and report it (also for a run whose harness
    stopped: python3 ops/trials.py follow NAME RUN TASK)."""
    name, d = t["name"], RUNS / run_id
    log(f"{run_id}: task #{tid}; watching it (budget {t['budget']['hours']} h)")
    row, asked, over = watch(t, tid, started, log=log)
    if over:
        request({"action": "task_cancel", "id": tid})
        log(f"{run_id}: the budget ran out; task #{tid} cancelled")
    for _ in range(40):                                  # the model judge reads the result after the task ends: its verdict
        with db() as c:                                  # goes in the report beside the answer key's (FND-92)
            o = c.execute("select verdict from task_occ where task=? order by occ desc limit 1", (tid,)).fetchone()
        if over or (o and o["verdict"]):
            break
        time.sleep(15)
    with db() as c:
        research = t.get("kind") == "research"
        bids = [] if research else build_ids(c, tid, repo)
        opened = [r["uri"] for r in c.execute(
            "select a.uri from prov p join artifacts a on a.id = p.artifact where p.task=? and a.uri like 'http%'", (tid,))]
        b = answered(c, tid, opened, d / "code") if research else deliverable(c, repo, bids, d / "code")
        rt = tree(tid) or ([], [])
        s = score(d / "code", key_dir(t)) if b else summarise({"cases": [], "error": "no answer delivered" if research else "no build delivered code"})
        srcs = [(f"task #{tid}: a page read", "url", u) for u in opened]
        m = metrics(c, tid, bids, rt)
    for bid in bids:
        for ext in ("steps", "log"):
            f = BUILD_LOGS / f"{bid}.{ext}"
            if f.exists():
                srcs += [(f"build #{bid} ({ext})", "action", x) for x in tool_inputs(f.read_text(errors="replace"))]
    srcs += [(f"run {e['run']}: {e['title']}", "action", f"{e['title']} {e['detail'] or ''}") for e in rt[1]]
    if b:
        srcs += [(f"delivered {f.relative_to(d / 'code')}", "code", f.read_text(errors="replace")) for f in sorted((d / "code").rglob("*"))
                 if f.is_file() and f.suffix in (".py", ".toml", ".txt", ".cfg") and "spec" not in f.relative_to(d / "code").parts]
    a = audit(t, srcs)
    sim = similarity(d / "code", key_dir(t) / t["similar_to"]) if b and t.get("similar_to") else {"share": 0.0, "files": []}
    r = {"trial": name, "run": run_id, "dir": str(d), "repo": repo, "task": tid, "started_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(started)),
         "version": git(ROOT, "rev-parse", "--short", "HEAD").strip(),
         "over_budget": over, "asked": asked, "builds": bids, "build": b and {k: b[k] for k in ("id", "status", "branch", "head", "attempts") if k in b},
         "score": s, "audit": a, "similarity": sim, "metrics": m}
    (d / "result.json").write_text(json.dumps(r, indent=1, ensure_ascii=False))
    (ROOT / "eval/results" / f"{time.strftime('%Y%m%d-%H%M%S')}-trial-{name}.json").write_text(json.dumps({k: v for k, v in r.items() if k != "score"} | {"score": {k: v for k, v in s.items() if k != "cases"}}, indent=1))
    rel = f"trials/{name}/{run_id}.md"
    (VAULT / rel).parent.mkdir(parents=True, exist_ok=True)
    (VAULT / rel).write_text(report(t, r))
    for act in ([{"action": "build_reject", "id": b["id"]}] if b and b.get("status") == "review" else []) + ([{"action": "repo_remove", "repo": repo}] if repo else []):
        try:                                             # scored and archived: the build leaves Needs you, the clone the Code tab
            request(act, wait=300)
        except RuntimeError as e:
            log(f"{run_id}: {e}")
    try:
        import notify as N
        import mission_extras as X                     # the app's address (MC_URL), kept where the app's links are made
        pct = f"{100 * s['passed'] / s['total']:.0f}%" if s["total"] else "no score"
        N.send(f"Trial {t['title']}: {s['passed']} of {s['total']} cases ({pct}), clean room {'ok' if a['ok'] else 'BROKEN'}, "
               f"similarity {sim['share']:.0%}, {m['minutes']} min", "result", title="Trials", push_on=True, event_kind="task",
               buttons=[[("📄 The report", f"{X.APP}/#/read?path={rel}")]])
    except Exception as e:                               # the report is in the vault either way
        log(f"{run_id}: not notified: {type(e).__name__}: {e}")
    try:
        publish(log=log)
    except OSError as e:                                 # the run's record is in its folder either way
        log(f"{run_id}: scoreboard not written: {e}")
    log(f"{run_id}: {s['passed']}/{s['total']} · clean room {'ok' if a['ok'] else 'broken'} · similarity {sim['share']:.0%} · report {rel}")
    return r


def rescore(name, run_id, now=None):
    """A recorded run scored again with the key as it is now (a reviewed gap added, a scorer fixed) and its tokens
    counted again from the run record; the record keeps what it said before (TRL-13). -> the new record."""
    t, d = load(name), RUNS / run_id
    r = json.loads((d / "result.json").read_text())
    before = (r.get("rescored") or {}).get("before") or {          # a second rescore keeps what the run first said
        "passed": r["score"].get("passed"), "total": r["score"].get("total"), "tokens": (r.get("metrics") or {}).get("tokens") or 0}
    r["score"] = score(d / "code", key_dir(t)) if (d / "code").exists() else r["score"]
    if r.get("task"):
        with db() as c:
            r["metrics"] = {**r["metrics"], **{k: v for k, v in metrics(c, r["task"], r.get("builds") or [], tree(r["task"]) or ([], [])).items()
                                               if k in ("calls", "tokens", "builder_tokens")}}
    r["rescored"] = {"at": time.strftime("%Y-%m-%d %H:%M", time.localtime(now)), "version": git(ROOT, "rev-parse", "--short", "HEAD").strip(),
                     "before": before}
    (d / "result.json").write_text(json.dumps(r, indent=1, ensure_ascii=False))
    rel = VAULT / f"trials/{name}/{run_id}.md"
    rel.parent.mkdir(parents=True, exist_ok=True)
    rel.write_text(report(t, r))
    return r


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "follow":            # a run already under way: NAME RUN TASK
        import datetime as dt
        tr, rid, task = load(sys.argv[2]), sys.argv[3], int(sys.argv[4])
        with db() as c:
            created = c.execute("select created from tasks where id=?", (task,)).fetchone()["created"]
        follow(tr, rid, f"trial-{rid}", task, dt.datetime.fromisoformat(created).timestamp())
        sys.exit(0)
    if len(sys.argv) == 4 and sys.argv[1] == "rescore":
        r = rescore(sys.argv[2], sys.argv[3])
        print(f"{sys.argv[3]}: {r['score']['passed']} of {r['score']['total']} (before {r['rescored']['before']['passed']} of "
              f"{r['rescored']['before']['total']}), {r['metrics']['tokens']:,} tokens; {len(r['score'].get('review') or [])} gaps for review")
        publish()
        sys.exit(0)
    if sys.argv[1:] == ["publish"]:
        print(f"{len(publish())} runs on the scoreboard")
        sys.exit(0)
    if len(sys.argv) != 3 or sys.argv[1] not in ("check", "run"):
        sys.exit(__doc__)
    if sys.argv[1] == "check":
        s = check(load(sys.argv[2]))
        print(f"{sys.argv[2]}: the answer key scores its reference {s['passed']} of {s['total']}: " + ", ".join(f"{k} {v[0]}/{v[1]}" for k, v in sorted(s["areas"].items())))
    else:
        run(sys.argv[2])

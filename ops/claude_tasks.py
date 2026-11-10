"""Claude tasks: Hermes delegates a question to Claude Code (headless, on the owner's Claude subscription), read-only.

Hermes thinks on ChatGPT through LiteLLM (the Max plan has no API access); for code questions, reviews, analysing code
or long documents and hard reasoning it calls the MCP tool claude_task (Mission Control, server "claude"), which drops
a request here. The runner works through them one at a time:
  - a throwaway snapshot of the repo's main branch (or a folder with the text Hermes passed) in the builder sandbox,
    /srv/ai/workbench/.claude-tasks/<id> = /work/.claude-tasks/<id>: the live repos and the builder's branches are
    never touched, and the snapshot is deleted afterwards;
  - `claude -p` in aistack-builder-1 (same pinned Claude Code, Serena, proxy and sandbox as the builder); the token
    is passed per run (docker exec -e), never stored in the container;
  - mode "ask": Read, Grep, Glob and Serena's read-only tools; mode "study": the same with more time, for onboarding a
    repository; mode "analyse": also Bash (tests, linters) in the copy.
    Never Edit/Write, no web: changes go through build_assign as before.
Evidence: a task may ask for read-only evidence (`evidence`: mission:<slug>, run:<runtime ref>, crew:<agent id>,
minutes:<N>), gathered by the Health doctor's code (ops/doctor.py: run record or mission timeline, runner journal,
docker logs, the gateway's failed calls; secrets redacted) when the task starts and put next to the question as
evidence.md, so "why did X fail?" is answered from the logs, not guessed.
Steps (tool calls, results, Claude's thinking) are read live from the stream-json output into
/srv/ai/missions/claude/<id>.json, which the app and claude_task_result read. A usage limit makes the task wait and
retry at the reset (the limit is shared with the owner's Claude sessions and the builder).
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import runtime as RTM
from textcap import STORE, cut, limit, tail                    # visible caps and input limits (AGENTS.md, truncation)
import textcap as TC
import modelpolicy as MP                          # the Claude CLI's access under this deployment's model policy (GEN-05)
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md

M = None                                   # ops/missions.py, set by its main()
B = None                                   # ops/builds.py (repos, claude_ready, claude_result, SERENA_FOR_CLAUDE)
OUT = Path("/srv/ai/missions/claude")
TMP = Path("/srv/ai/workbench/.claude-tasks")
MAX_WAITS = 16                             # limit: stops (a task waits at most this many times for Claude's usage limit, then fails with the reason)
MODES = {
    "ask": {"tools": "Read,Grep,Glob,mcp__serena__find_symbol,mcp__serena__find_referencing_symbols,mcp__serena__get_symbols_overview,"
                     "mcp__serena__find_declaration,mcp__serena__find_implementations,mcp__serena__search_for_pattern,{graph}",
            "turns": 40, "timeout": 15 * 60},
    "study": {"tools": "Read,Grep,Glob,mcp__serena__find_symbol,mcp__serena__find_referencing_symbols,mcp__serena__get_symbols_overview,"
                       "mcp__serena__find_declaration,mcp__serena__find_implementations,mcp__serena__search_for_pattern,{graph}",
              "turns": 80, "timeout": 30 * 60},     # onboarding's analysis: as long as "analyse", but third-party code is never run (BLD-18)
    "analyse": {"tools": "Read,Grep,Glob,Bash,mcp__serena__find_symbol,mcp__serena__find_referencing_symbols,mcp__serena__get_symbols_overview,"
                         "mcp__serena__find_declaration,mcp__serena__find_implementations,mcp__serena__search_for_pattern,"
                         "mcp__serena__get_diagnostics_for_file,{graph}",
                "turns": 80, "timeout": 30 * 60},
}
GRAPH = ("mcp__memory__memorypublic-search,mcp__memory__memorypublic-open,mcp__memory__memorypublic-subscribe,"
         "mcp__memory__memorypublic-note")   # MEM-28, MEM-30: the memory tool without the owner's facts (the builder's key)
for _m in MODES.values():                  # Serena's server text says to read its manual first: a model that obeys must be
    _m["tools"] = _m["tools"].format(graph=GRAPH) + ",mcp__serena__initial_instructions"   # able to (read-only; a work site, 9 Nov 2026)
NEVER = "Edit,Write,NotebookEdit,WebFetch,WebSearch,mcp__serena__replace_symbol_body,mcp__serena__insert_after_symbol," \
        "mcp__serena__insert_before_symbol,mcp__serena__rename_symbol,mcp__serena__safe_delete_symbol,mcp__serena__replace_content," \
        "mcp__serena__replace_in_files"
PROMPT = P.text("shared", "CLAUDE_TASK")


def table(c):
    c.execute("""create table if not exists claude_tasks (id integer primary key, question text, repo text, mode text, context text,
                 status text, answer text, error text, created text, started text, ended text, turns integer, tokens integer,
                 cached integer, retry_at text, source text)""")
    cols = {r[1] for r in c.execute("pragma table_info(claude_tasks)")}
    if "evidence" not in cols:
        c.execute("alter table claude_tasks add column evidence text")
    if "waits" not in cols:
        c.execute("alter table claude_tasks add column waits integer")
    if "ref" not in cols:                                 # TSK-48: a commit to copy instead of main, and history to bring
        c.execute("alter table claude_tasks add column ref text")
        c.execute("alter table claude_tasks add column history integer")


def put(c, tid, **kw):
    c.execute(f"update claude_tasks set {', '.join(k + '=?' for k in kw)} where id=?", (*kw.values(), tid))
    c.commit()


def handle(req, c):
    table(c)
    q = limit(str(req.get("question", "")).strip(), 20000, "the question")
    mode = str(req.get("mode") or "ask")
    repo = str(req.get("repo") or "").strip()
    if len(q) < 10:
        raise ValueError("ask a real question (at least a sentence)")
    if mode not in MODES:
        raise ValueError(f"mode must be one of: {', '.join(MODES)}")
    if repo and repo not in all_repos():
        raise ValueError(f"repo must be one of: {', '.join(all_repos())} (or none, to ask about the text you pass)")
    ev = limit(str(req.get("evidence") or "").strip(), 4000, "the evidence references")
    if ev:
        import doctor as D
        bad = [x for x in ev.split(",") if x.strip() and not D.EVIDENCE_REF.match(x.strip())]
        if bad:
            raise ValueError(f"evidence: {bad[0].strip()!r} is not mission:<slug>, run:<ref>, crew:<agent id> or minutes:<N>")
    ref, history = str(req.get("ref") or "").strip(), req.get("history")
    if ref and (not repo or not REF.fullmatch(ref)):
        raise ValueError("ref names a commit, tag or branch of the task's repository (letters, digits and . _ / -)")
    try:
        history = int(history or 0)
    except (TypeError, ValueError):
        raise ValueError("history is a number of commits")
    if history < 0 or history > HISTORY_MAX or (history and not repo):   # limit: refuses, HISTORY_MAX commits of history at most
        raise ValueError(f"history is 0 to {HISTORY_MAX} commits of the task's repository")
    if not B.claude_ready():
        raise ValueError("Claude Code is not connected (Code tab → Connect Claude Code)")
    cur = c.execute("insert into claude_tasks (question, repo, mode, context, status, created, source, evidence, ref, history) values (?,?,?,?,?,?,?,?,?,?)",
                    (q, repo, mode, limit(str(req.get("context") or ""), 200000, "the context"), "queued", M.now().isoformat(timespec="seconds"),
                     str(req.get("source") or ""), ev or None, ref or None, history or None))
    c.commit()
    tid = cur.lastrowid
    write(c, tid, [])
    M.event("claude", "", f"Claude task #{tid} queued ({mode}{', ' + repo if repo else ''}): {cut(q, 300, 'the whole question is on its page')}", title="Claude Code")  # cap: preview
    return {"id": tid}


def all_repos():
    """Buildable repos plus the studied ones in ~/code (read-only questions need no Forgejo)."""
    names = set(B.repos())
    names |= {p.name for p in B.CODE.iterdir() if (p / ".git").exists()} if B.CODE.exists() else set()
    return sorted(names)


def gather(spec):
    """The evidence a task asked for (ops/doctor.py's read-only gathering, redacted)."""
    import crew
    import doctor as D
    D.C, D.M = crew, M
    crew.M = crew.M or M
    return D.evidence_for(spec)


REF = re.compile(r"[0-9A-Za-z][\w./-]{0,99}")
HISTORY_MAX = 500        # limit: refuses, commits of history a task's copy may bring (a review of recent work, not the whole past)
TAG_FAMILIES = 5         # limit: drops, tag families past these get no tag on a task's copy (a project uses one or two)


def one_commit(dest, src, ref):
    """The copy as one commit of its own with the newest release tag of each family before it: a project that asks git for its
    version imports and installs (overnight 8 Nov 2026: sympy in a plain copy made the scribe write a version shim); the
    history stays out of reach. Never fails the task: a copy without it is what it was before."""
    try:
        for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["-c", "user.name=AI stack trials", "-c", "user.email=trials@stack.local",
                                                                   "commit", "-q", "--no-verify", "-m", "The repository as it stands"]):
            subprocess.run(["git", "-C", str(dest), *args], check=True, capture_output=True, timeout=600)
        out = subprocess.run(["git", "-C", str(src), "tag", "--merged", ref, "--sort=-creatordate"], capture_output=True, text=True, timeout=120).stdout
        newest = {}
        for t in out.split():
            newest.setdefault(re.match(r"^\D*", t).group(0), t)
        for t in list(newest.values())[:TAG_FAMILIES]:  # cap: top (TAG_FAMILIES, newest families first)
            subprocess.run(["git", "-C", str(dest), "tag", t], capture_output=True, timeout=60)
        subprocess.run(["chmod", "-R", "a+rwX", str(dest / ".git")], capture_output=True, timeout=120)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"claude task copy of {src.name}: no commit of its own ({type(e).__name__}: {e})", flush=True)


def with_history(dest, src, sha, n):
    """The copy as the last n commits up to sha (a shallow fetch: git log and git show work, nothing older is there, and it
    has no remote). TSK-48: a work site, 9 Nov 2026, could not ask "review the last pull requests" of a one-commit copy."""
    up = "git -c uploadpack.allowAnySHA1InWant=true upload-pack"
    for args in (["init", "-q", "-b", "main"], ["fetch", "-q", f"--depth={int(n)}", f"--upload-pack={up}", f"file://{src}", sha],
                 ["checkout", "-q", "-B", "main", "FETCH_HEAD"]):
        subprocess.run(["git", "-C", str(dest), *args], check=True, capture_output=True, timeout=1800)
    subprocess.run(["chmod", "-R", "a+rwX", str(dest / ".git")], capture_output=True, timeout=120)


def snapshot(tid, repo, context, evidence="", ref=None, history=0):
    """A throwaway copy for this task (the repo's main branch or the commit asked for, with the history asked for, or the
    passed text); returns its path inside the sandbox."""
    base = TMP / str(tid)
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    if repo:
        src = B.WB / repo if (B.WB / repo / ".git").exists() else B.CODE / repo
        ref = "HEAD"
        if src == B.WB / repo:
            subprocess.run(["git", "-C", str(src), "fetch", "-q", "origin"], capture_output=True, timeout=120)
            ref = f"origin/{B.default_branch(src)}"
        if want := (ref_asked := (ref or "").strip()):    # TSK-48: a commit, tag or branch instead of main
            got = subprocess.run(["git", "-C", str(src), "rev-parse", "--verify", "-q", f"{want}^{{commit}}"], capture_output=True, text=True, timeout=60)
            if got.returncode:
                raise RuntimeError(f"{repo} has no commit {ref_asked!r}")
            ref = got.stdout.strip()
        dest = base / repo
        dest.mkdir()
        if history:
            sha = subprocess.run(["git", "-C", str(src), "rev-parse", "--verify", f"{ref}^{{commit}}"], capture_output=True, text=True, timeout=60).stdout.strip()
            with_history(dest, src, sha, history)
            if context:
                (dest / ".claude-task-context.md").write_text(context)
            if evidence:
                (dest / ".claude-task-evidence.md").write_text(evidence)
            return f"/work/.claude-tasks/{tid}/{repo}"
        arch = subprocess.run(["git", "-C", str(src), "archive", ref], capture_output=True, timeout=300)
        if arch.returncode:
            raise RuntimeError(f"could not copy {repo}: {tail(arch.stderr.decode(errors='replace'), 4000)}")  # cap: store
        subprocess.run(["tar", "-x", "-C", str(dest)], input=arch.stdout, capture_output=True, timeout=300, check=True)
        one_commit(dest, src, ref)
        if context:
            (dest / ".claude-task-context.md").write_text(context)
        if evidence:
            (dest / ".claude-task-evidence.md").write_text(evidence)
        return f"/work/.claude-tasks/{tid}/{repo}"
    (base / "context.md").write_text(context or "(no text passed)")
    if evidence:
        (base / "evidence.md").write_text(evidence)
    return f"/work/.claude-tasks/{tid}"


def steps_of(lines):
    """stream-json lines → steps the app shows (with Claude's thinking) and the running token count."""
    out, names, tokens = [], {}, {"in": 0, "out": 0, "cached": 0}
    for ts, ln in lines:
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if e.get("type") == "assistant":
            u = (e.get("message") or {}).get("usage") or {}
            tokens["in"] += int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0)
            tokens["cached"] += int(u.get("cache_read_input_tokens") or 0)
            tokens["out"] += int(u.get("output_tokens") or 0)
        for part in ((e.get("message") or {}).get("content") or []) if e.get("type") in ("assistant", "user") else []:
            if not isinstance(part, dict):
                continue
            t = part.get("type")
            if t == "thinking" and (part.get("thinking") or "").strip():
                out.append({"ts": ts, "kind": "think", "title": "Thinking", "detail": cut(part["thinking"], STORE)})  # cap: store
            elif t == "tool_use":
                names[part.get("id")] = part.get("name")
                out.append({"ts": ts, "kind": "call", "title": part.get("name") or "tool", "detail": cut(json.dumps(part.get("input", {})), STORE)})  # cap: store
            elif t == "tool_result":
                body = part.get("content")
                text = body if isinstance(body, str) else " ".join(x.get("text", "") for x in body or [] if isinstance(x, dict))
                out.append({"ts": ts, "kind": "error" if part.get("is_error") else "result", "title": names.get(part.get("tool_use_id")) or "result",
                            "detail": cut(text, STORE)})  # cap: store
            elif t == "text" and (part.get("text") or "").strip():
                out.append({"ts": ts, "kind": "say", "title": "Says", "detail": cut(part["text"], STORE)})  # cap: store
    return out, tokens


def write(c, tid, steps, tokens=None):
    r = dict(c.execute("select * from claude_tasks where id=?", (tid,)).fetchone())
    r.pop("context", None)
    t0 = time.mktime(time.strptime(r["started"][:19], "%Y-%m-%dT%H:%M:%S")) if r.get("started") else None
    import observe as O
    doc = {**r, "steps": [{**s, "t": round(s["ts"] - t0, 1) if t0 else 0} for s in steps], "live_tokens": tokens or {},
           "files": O.files_of(steps), "detail": O.stats_of(steps)}
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / f".{tid}.tmp"
    tmp.write_text(json.dumps(doc, ensure_ascii=False))
    tmp.replace(OUT / f"{tid}.json")


def run(c, t):
    tid, mode = t["id"], t["mode"] or "ask"
    cfg = MODES[mode]
    put(c, tid, status="running", started=M.now().isoformat(timespec="seconds"), error=None)
    lines = []
    try:
        ev = gather(t["evidence"]) if t.get("evidence") else ""
        cwd = snapshot(tid, t["repo"], t["context"], ev, t.get("ref"), t.get("history") or 0)
        if t["repo"]:
            what = f"a copy at {t['ref']}" if t.get("ref") else "a copy of its main branch"
            what += f", with its last {t['history']} commits: git log and git show work" if t.get("history") else ""
            where = (f"The repository {t['repo']} is in the current directory ({what})."
                     + (" The owner's notes for this question are in .claude-task-context.md." if t["context"] else "")
                     + (" The evidence asked for (run records, logs, failed gateway calls; secrets redacted) is in"
                        " .claude-task-evidence.md: base the answer on it and quote the lines that show the cause." if ev else ""))
        else:
            where = ("The text to work on is in context.md in the current directory."
                     + (" The evidence asked for (run records, logs, failed gateway calls; secrets redacted) is in evidence.md:"
                        " base the answer on it and quote the lines that show the cause." if ev else ""))
        prompt = PROMPT.format(question=t["question"], where=where)
        P.record(prompt)                                  # MEM-11: the run records the prompt's version
        if t["repo"]:                                     # MEM-31: what the stack knows about this repository, for this question
            import memstack as MS
            prompt = MS.opening("claude-task", kind="task", task=t["question"], subs=[f"code:{t['repo']}", "howto:lessons/code"], repo=t["repo"],
                                run=f"claude-task:{tid}") + prompt
        box = {"where": "a throwaway copy of " + (t["repo"] or "the text Hermes passed"), "can": cfg["tools"], "never": NEVER,
               "network": "none beyond the model"}
        cmd = ["docker", "exec", "-u", "hermes", *MP.claude_args(), "-e", "MAX_THINKING_TOKENS=8000", "-w", cwd,
               "-e", f"AISTACK_REF=claude-task:{tid}", "-e", "AISTACK_AGENT=claude-task", "-e", f"AISTACK_TITLE={t['question'][:150]}",  # cap: id
               "-e", "AISTACK_BOX=" + json.dumps(box), B.BUILDER,
               "timeout", str(cfg["timeout"]), "claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
               # limit: stops, a Claude task past its mode's turns and time (MODES) is reported as stopped
               "--max-turns", str(cfg["turns"]), "--allowedTools", cfg["tools"], "--disallowedTools", NEVER,
               "--mcp-config", B.SERENA_FOR_CLAUDE, "--strict-mcp-config", "--settings", "/config/claude-hooks/claude-runtime-settings.json"]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env={**os.environ})
        last = 0
        cancelled = False
        for ln in p.stdout:                                   # live steps while it works
            lines.append((time.time(), ln.strip()))
            if time.time() - last > 3:
                last = time.time()
                write(c, tid, *steps_of(lines))
                cancelled = (c.execute("select status from claude_tasks where id=?", (tid,)).fetchone() or ["?"])[0] == "cancelled"
            if M.stop.is_set() or cancelled:
                p.kill()
                break
        p.wait(timeout=60)
        if cancelled:                                     # its change was cancelled: it stops, and says so (cancel_for)
            put(c, tid, ended=M.now().isoformat(timespec="seconds"))
            write(c, tid, *steps_of(lines))
            M.log(f"Claude task #{tid} stopped: its task was cancelled")
            return
        if M.stop.is_set():                               # the runner stops (a deploy): the task was cut off, not failed;
            put(c, tid, status="queued", started=None, error=None)   # it is asked again after the restart (31 Oct 2026)
            M.log(f"Claude task #{tid} cut off by the runner stopping: queued again")
            return
        log = "\n".join(ln for _, ln in lines)
        res = B.claude_result(log)
        steps, tokens = steps_of(lines)
        waits = ((t["waits"] if "waits" in t.keys() else 0) or 0) + 1
        if res["limit_reset"] and waits > MAX_WAITS:      # review RUN-R3: a task that kept hitting a "limit" retried forever
            put(c, tid, status="failed", error=f"Claude stayed at its usage limit through {MAX_WAITS} waits; ask again when it has reset",
                ended=M.now().isoformat(timespec="seconds"))
            M.event("claude", "", f"Claude task #{tid} stopped: still at the usage limit after {MAX_WAITS} waits", push=True, title="Claude Code")
        elif res["limit_reset"]:
            retry = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(res["limit_reset"] + 120))
            put(c, tid, status="waiting", retry_at=retry, waits=waits, error="Claude usage limit: it continues by itself after the reset")
            M.event("claude", "", f"Claude task #{tid} waits for the Claude usage limit (until {retry[11:16]})", title="Claude Code")
        elif res["text"]:
            put(c, tid, status="done", answer=cut(res["text"], 200000), ended=M.now().isoformat(timespec="seconds"), turns=res["turns"],  # cap: store
                tokens=res["tokens"], cached=res["cached"])
            M.event("claude", "", f"Claude task #{tid} answered ({res['turns']} turns)", title="Claude Code")
        else:
            put(c, tid, status="failed", ended=M.now().isoformat(timespec="seconds"),
                error=(f"stopped at {res['stopped']} after {res['turns']} turns; " if res.get("stopped") else "")
                + (re.sub(r"\s+", " ", tail(log, 4000)) or "no answer").strip())  # cap: store
        write(c, tid, steps, tokens)
    except Exception as e:
        put(c, tid, status="failed", ended=M.now().isoformat(timespec="seconds"), error=f"{type(e).__name__}: {str(e)}")
        write(c, tid, *steps_of(lines))
    finally:
        shutil.rmtree(TMP / str(tid), ignore_errors=True)


def cancel(c, tid, why="cancelled by the owner"):
    """claude_cancel (TSK-46): a queued or waiting Claude task never starts; a running one stops at its next live update
    (a work site, 9 Nov 2026: a question sent by mistake could not be withdrawn). -> {"id", "cancelled": bool}."""
    table(c)
    n = c.execute("update claude_tasks set status='cancelled', error=? where id=? and status in ('queued', 'waiting', 'running')",
                  (why, int(tid))).rowcount
    c.commit()
    if n:
        M.event("claude", "", f"Claude task #{tid} cancelled", title="Claude Code")
    return {"id": int(tid), "cancelled": bool(n)}


PARALLEL = 1            # limit: paces, Claude tasks side by side unless the deployment says CLAUDE_PARALLEL (home: one subscription)
PARALLEL_MAX = 4        # limit: paces, at most this many whatever the deployment says


def parallel(values=None):
    """How many Claude tasks run side by side: the deployment's CLAUDE_PARALLEL (a work site, 9 Nov 2026: nine questions
    took hours in a row on a gateway that could take several)."""
    import deployment as DEPLOY
    try:
        return max(1, min(PARALLEL_MAX, int((values if values is not None else DEPLOY.VALUES).get("CLAUDE_PARALLEL"))))
    except (TypeError, ValueError):
        return PARALLEL


def claim(c):
    """The next Claude task to run, claimed so that no other worker takes it, or None."""
    now = M.now().isoformat(timespec="seconds")[:19]
    for t in c.execute("select * from claude_tasks where status='queued' or (status='waiting' and julianday(retry_at) <= julianday(?)) "
                       "order by id limit 8", (now,)).fetchall():  # cap: top (the next few: one of them is claimed, the rest wait their turn)
        if c.execute("update claude_tasks set status='running' where id=? and status=?", (t["id"], t["status"])).rowcount:
            c.commit()
            return t
    return None


def cancel_for(c, task):
    """The Claude tasks a task's steps started stop with it (overnight 8 Nov 2026: an exam change was cancelled, its scribe's
    Claude task was asked again after a restart and ran on for half an hour). A running one stops at its next live update.
    -> how many."""
    table(c)
    n = c.execute("update claude_tasks set status='cancelled', error='its task was cancelled' where source like ? and status in "
                  "('queued', 'waiting', 'running')", (f"task:{int(task)}:%",)).rowcount
    c.commit()
    return n


def state(c):
    table(c)
    rows = [dict(r) for r in c.execute("select id, question, repo, mode, status, answer, error, created, started, ended, turns, tokens, "
                                       "cached, retry_at, source, evidence from claude_tasks order by id desc limit 15")]  # cap: list (the 15 newest on the board; each has its own page)
    for r in rows:
        r["question"] = TC.cut((r["question"] or ""), 300)  # cap: preview
        r["answer"] = TC.cut((r["answer"] or ""), 400)  # cap: preview
    return {"claude_tasks": rows}


def yield_answer(repo, question, answer, tid):
    """MEM-37: an answer about a repository goes through the memory's rubric into that repository's wiki. Never fails a task."""
    try:
        import memwrite as MW
        MW.M = MW.M or M
        MW.yield_answer(repo, question, answer, tid)
    except Exception as e:
        M.log(f"claude task #{tid}: its answer was not yielded to memory: {type(e).__name__}: {e}")


def worker():
    """The Claude task workers: CLAUDE_PARALLEL of them (TSK-46), each claiming its task."""
    c = M.db()
    table(c)
    c.execute("update claude_tasks set status='queued' where status='running'")   # cut off by a restart: try again
    c.commit()
    for _ in range(parallel() - 1):
        threading.Thread(target=work, daemon=True).start()
    work(c)


def work(c=None):
    c = c or M.db()
    while not M.stop.is_set():
        try:
            t = claim(c)
            if t:
                rid = f"claude-task:{t['id']}"
                RTM.start(rid, "claude-task", f"Claude task #{t['id']}: {t['question'][:150]}", data={"manifest": {"agent": "claude-task", "mode": t["mode"], "repo": t["repo"]}},  # cap: id
                          ref=t["source"] or None, detail=cut(t["question"], STORE))       # who asked (crew:doctor) and the whole question  # cap: store
                t0 = time.time()
                try:
                    run(c, dict(t))
                finally:
                    st = c.execute("select status, error, answer from claude_tasks where id=?", (t["id"],)).fetchone()
                    RTM.end(rid, "claude-task", {"done": "done", "waiting": "limit", "cancelled": "stopped"}.get(st["status"] if st else "", "failed"),
                            ((st["error"] if st else "") or ""), time.time() - t0)
                    if st and st["status"] == "done" and t["repo"] and st["answer"]:     # MEM-37: what it found about the repository
                        threading.Thread(target=yield_answer, args=(t["repo"], t["question"], st["answer"], t["id"]), daemon=True).start()
                continue
        except Exception as e:
            M.log(f"claude tasks: {type(e).__name__}: {e}")
        M.rest(c, "claude tasks", 5)

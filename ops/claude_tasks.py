"""Claude tasks: Hermes delegates a question to Claude Code (headless, on the owner's Claude subscription), read-only.

Hermes thinks on ChatGPT through LiteLLM (the Max plan has no API access); for code questions, reviews, analysing code
or long documents and hard reasoning it calls the MCP tool claude_task (Mission Control, server "claude"), which drops
a request here. The runner works through them one at a time:
  - a throwaway snapshot of the repo's main branch (or a folder with the text Hermes passed) in the builder sandbox,
    /srv/ai/workbench/.claude-tasks/<id> = /work/.claude-tasks/<id>: the live repos and the builder's branches are
    never touched, and the snapshot is deleted afterwards;
  - `claude -p` in aistack-builder-1 (same pinned Claude Code, Serena, proxy and sandbox as the builder); the token
    is passed per run (docker exec -e), never stored in the container;
  - mode "ask": Read, Grep, Glob and Serena's read-only tools; mode "analyse": also Bash (tests, linters) in the copy.
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
import time
from pathlib import Path

import runtime as RTM
from textcap import STORE, cut, limit, tail                    # visible caps and input limits (AGENTS.md, truncation)
import textcap as TC
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md

M = None                                   # ops/missions.py, set by its main()
B = None                                   # ops/builds.py (repos, claude_ready, claude_result, SERENA_FOR_CLAUDE)
OUT = Path("/srv/ai/missions/claude")
TMP = Path("/srv/ai/workbench/.claude-tasks")
MODES = {
    "ask": {"tools": "Read,Grep,Glob,mcp__serena__find_symbol,mcp__serena__find_referencing_symbols,mcp__serena__get_symbols_overview,"
                     "mcp__serena__find_declaration,mcp__serena__find_implementations,mcp__serena__search_for_pattern,{graph}",
            "turns": 40, "timeout": 15 * 60},
    "analyse": {"tools": "Read,Grep,Glob,Bash,mcp__serena__find_symbol,mcp__serena__find_referencing_symbols,mcp__serena__get_symbols_overview,"
                         "mcp__serena__find_declaration,mcp__serena__find_implementations,mcp__serena__search_for_pattern,"
                         "mcp__serena__get_diagnostics_for_file,{graph}",
                "turns": 80, "timeout": 30 * 60},
}
GRAPH = ("mcp__graph__graphify-query_graph,mcp__graph__graphify-get_node,mcp__graph__graphify-get_neighbors,"
         "mcp__graph__graphify-god_nodes,mcp__graph__graphify-shortest_path,mcp__graph__graphify-graph_stats")   # the code graph, read-only
for _m in MODES.values():
    _m["tools"] = _m["tools"].format(graph=GRAPH)
NEVER = "Edit,Write,NotebookEdit,WebFetch,WebSearch,mcp__serena__replace_symbol_body,mcp__serena__insert_after_symbol," \
        "mcp__serena__insert_before_symbol,mcp__serena__rename_symbol,mcp__serena__safe_delete_symbol,mcp__serena__replace_content," \
        "mcp__serena__replace_in_files"
PROMPT = P.text("shared", "CLAUDE_TASK")


def table(c):
    c.execute("""create table if not exists claude_tasks (id integer primary key, question text, repo text, mode text, context text,
                 status text, answer text, error text, created text, started text, ended text, turns integer, tokens integer,
                 cached integer, retry_at text, source text)""")
    if "evidence" not in {r[1] for r in c.execute("pragma table_info(claude_tasks)")}:
        c.execute("alter table claude_tasks add column evidence text")


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
    if not B.claude_ready():
        raise ValueError("Claude Code is not connected (Code tab → Connect Claude Code)")
    cur = c.execute("insert into claude_tasks (question, repo, mode, context, status, created, source, evidence) values (?,?,?,?,?,?,?,?)",
                    (q, repo, mode, limit(str(req.get("context") or ""), 200000, "the context"), "queued", M.now().isoformat(timespec="seconds"),
                     str(req.get("source") or ""), ev or None))
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


def snapshot(tid, repo, context, evidence=""):
    """A throwaway copy for this task (the repo's main branch, or the passed text); returns its path inside the sandbox."""
    base = TMP / str(tid)
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    if repo:
        src = B.WB / repo if (B.WB / repo / ".git").exists() else B.CODE / repo
        ref = "HEAD"
        if src == B.WB / repo:
            subprocess.run(["git", "-C", str(src), "fetch", "-q", "origin"], capture_output=True, timeout=120)
            ref = f"origin/{B.default_branch(src)}"
        dest = base / repo
        dest.mkdir()
        arch = subprocess.run(["git", "-C", str(src), "archive", ref], capture_output=True, timeout=300)
        if arch.returncode:
            raise RuntimeError(f"could not copy {repo}: {tail(arch.stderr.decode(errors='replace'), 4000)}")  # cap: store
        subprocess.run(["tar", "-x", "-C", str(dest)], input=arch.stdout, capture_output=True, timeout=300, check=True)
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
        cwd = snapshot(tid, t["repo"], t["context"], ev)
        if t["repo"]:
            where = (f"The repository {t['repo']} is in the current directory (a copy of its main branch)."
                     + (" The owner's notes for this question are in .claude-task-context.md." if t["context"] else "")
                     + (" The evidence asked for (run records, logs, failed gateway calls; secrets redacted) is in"
                        " .claude-task-evidence.md: base the answer on it and quote the lines that show the cause." if ev else ""))
        else:
            where = ("The text to work on is in context.md in the current directory."
                     + (" The evidence asked for (run records, logs, failed gateway calls; secrets redacted) is in evidence.md:"
                        " base the answer on it and quote the lines that show the cause." if ev else ""))
        prompt = PROMPT.format(question=t["question"], where=where)
        P.record(prompt)                                  # MEM-11: the run records the prompt's version
        box = {"where": "a throwaway copy of " + (t["repo"] or "the text Hermes passed"), "can": cfg["tools"], "never": NEVER,
               "network": "none beyond the model"}
        cmd = ["docker", "exec", "-u", "hermes", "-e", "CLAUDE_CODE_OAUTH_TOKEN", "-e", "MAX_THINKING_TOKENS=8000", "-w", cwd,
               "-e", f"AISTACK_REF=claude-task:{tid}", "-e", "AISTACK_AGENT=claude-task", "-e", f"AISTACK_TITLE={t['question'][:150]}",  # cap: id
               "-e", "AISTACK_BOX=" + json.dumps(box), B.BUILDER,
               "timeout", str(cfg["timeout"]), "claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--max-turns", str(cfg["turns"]), "--allowedTools", cfg["tools"], "--disallowedTools", NEVER,
               "--mcp-config", B.SERENA_FOR_CLAUDE, "--strict-mcp-config", "--settings", "/config/claude-hooks/claude-runtime-settings.json"]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env={**os.environ})
        last = 0
        for ln in p.stdout:                                   # live steps while it works
            lines.append((time.time(), ln.strip()))
            if time.time() - last > 3:
                last = time.time()
                write(c, tid, *steps_of(lines))
            if M.stop.is_set():
                p.kill()
                break
        p.wait(timeout=60)
        if M.stop.is_set():                               # the runner stops (a deploy): the task was cut off, not failed;
            put(c, tid, status="queued", started=None, error=None)   # it is asked again after the restart (31 Oct 2026)
            M.log(f"Claude task #{tid} cut off by the runner stopping: queued again")
            return
        log = "\n".join(ln for _, ln in lines)
        res = B.claude_result(log)
        steps, tokens = steps_of(lines)
        if res["limit_reset"]:
            retry = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(res["limit_reset"] + 120))
            put(c, tid, status="waiting", retry_at=retry, error="Claude usage limit: it continues by itself after the reset")
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


def state(c):
    table(c)
    rows = [dict(r) for r in c.execute("select id, question, repo, mode, status, answer, error, created, started, ended, turns, tokens, "
                                       "cached, retry_at, source, evidence from claude_tasks order by id desc limit 15")]  # cap: list (the 15 newest on the board; each has its own page)
    for r in rows:
        r["question"] = TC.cut((r["question"] or ""), 300)  # cap: preview
        r["answer"] = TC.cut((r["answer"] or ""), 400)  # cap: preview
    return {"claude_tasks": rows}


def worker():
    c = M.db()
    table(c)
    c.execute("update claude_tasks set status='queued' where status='running'")   # cut off by a restart: try again
    c.commit()
    while not M.stop.is_set():
        try:
            t = c.execute("select * from claude_tasks where status='queued' or (status='waiting' and retry_at <= ?) order by id limit 1",
                          (M.now().isoformat(timespec="seconds")[:19],)).fetchone()
            if t:
                rid = f"claude-task:{t['id']}"
                RTM.start(rid, "claude-task", f"Claude task #{t['id']}: {t['question'][:150]}", data={"manifest": {"agent": "claude-task", "mode": t["mode"], "repo": t["repo"]}},  # cap: id
                          ref=t["source"] or None, detail=cut(t["question"], STORE))       # who asked (crew:doctor) and the whole question  # cap: store
                t0 = time.time()
                try:
                    run(c, dict(t))
                finally:
                    st = c.execute("select status, error from claude_tasks where id=?", (t["id"],)).fetchone()
                    RTM.end(rid, "claude-task", {"done": "done", "waiting": "limit"}.get(st["status"] if st else "", "failed"),
                            ((st["error"] if st else "") or ""), time.time() - t0)
                continue
        except Exception as e:
            M.log(f"claude tasks: {type(e).__name__}: {e}")
        M.stop.wait(5)

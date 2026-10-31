"""The Health doctor (crew): reviews the open issues of the Agent health board with their evidence and proposes how
to fix them. It changes nothing (no code, no config) and acknowledges nothing: the owner decides.

  1. the open issues: state.json -> health (missions, crew agents, live runs from the runtime record)
  2. evidence per issue, secrets redacted: the run's record (runtime.db) or the mission's timeline, the runner's
     journal, docker logs and the gateway's failed calls (LiteLLM spend logs) around the run, and where the detector
     that raised the issue lives in the code
  3. one Claude task (ops/claude_tasks.py, read-only on a copy of ai-stack main; the evidence is its context): per
     issue a class (real fault, expected, noise, external), the cause (file:line, log line), a fix and a confidence
  4. real faults -> a build proposal (Code -> The stack suggests); noise and expected -> a proposal to tune the
     detector, and the finding says the issue can be acknowledged; external -> explained, nothing to build

  python3 ops/crew.py doctor     (crew-doctor.service: every 6 hours, Run now, and crew.call_doctor after a new alert)
If the Claude task has to wait for a usage limit, the doctor ends cleanly and reads the answer on its next run.
"""
import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path
from textcap import cut, tail                    # visible caps and input limits (AGENTS.md, truncation)
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md

C = M = None                                   # ops/crew.py and ops/missions.py (set by crew.run)
RTDB = Path("/srv/ai/missions/app/runtime.db")
WAIT_S = 50 * 60                               # how long one run waits for its Claude task (the queue is one at a time)
PER_ISSUE = 16000                              # evidence characters per issue
MAX_ISSUES = 12
CLASSES = ("real", "expected", "noise", "external")
ERRORISH = re.compile(r"error|exception|traceback|fail|timeout|timed out|limit|refused|denied|forbidden|\b4[02]\d\b|\b5\d\d\b|stall|kill", re.I)
OBS, RR = "images/mission-control/obs_core.py", "images/mission-control/runrecord.py"
DETECTORS = {                                  # where each kind of issue is decided: the first stop for "is the detector wrong?"
    "partial-read": f"{OBS} problems() (TRUNC)", "tool-error": f"{OBS} problems() (kind error)",
    "unknown-tool": f"{OBS} problems() (UNKNOWN)", "empty-args": f"{OBS} problems()", "bad-args": f"{OBS} problems()",
    "repeat": f"{OBS} problems()", "no-end": f"{OBS} problems()",
    "stalled": f"{RR} watchdog_once() (STALL_S, WAIT_S) and open_problems()", "limit": f"{RR} open_problems(); {OBS} LIMIT and judge()",
    "failed": f"{RR} open_problems(); {OBS} judge()", "limit-long": "ops/crew.py mission_health() (the queue's waiting runs)", "drift": f"{RR} open_problems() (manifest drift)",
    "failing": f"{OBS} judge()", "overdue": f"{OBS} judge(); ops/crew.py interval_of()", "slow": f"{OBS} judge()",
    "tokens": f"{OBS} judge()", "loop": f"{OBS} judge() (warnings)",
}

SECRET_RES = [
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "sk-[redacted]"),
    (re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{4,}"), "[redacted jwt]"),
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"), "[redacted bot token]"),
    (re.compile(r"\b(?:ghp|gho|github_pat|glpat|xox[abpr])[-_][A-Za-z0-9_-]{16,}"), "[redacted token]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[redacted key]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1[redacted]"),
    (re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|token|secret|password|passwd|authorization|cookie|oauth)[\"']?\s*[:=]\s*[\"']?)"
                r"[^\s\"',;}{]{6,}"), r"\1[redacted]"),
    (re.compile(r"\b[0-9a-f]{40,}\b"), "[redacted hex]"),
]


def redact(text, env=None):
    """Secrets out of evidence: the values of secret-looking environment variables, then known token shapes."""
    s = str(text or "")
    for k, v in (os.environ if env is None else env).items():
        if v and len(v) >= 8 and re.search(r"KEY|TOKEN|SECRET|PASSWORD|PASS\b|COOKIE|CREDENTIAL", k) and v in s:
            s = s.replace(v, f"[redacted {k}]")
    for rx, rep in SECRET_RES:
        s = rx.sub(rep, s)
    return s


# ---------- 1. the issues ----------
def issues_of(health, skip=frozenset(), limit=MAX_ISSUES):
    """The board's open issues (acknowledged ones are in each item's "acked", not here), alerts first, without those an
    open proposal already covers (skip: keys and "kind:<issue>") -> [{id, key, name, kind, item, slug, run, issue, text, severity}]."""
    out = []
    for it in (health or {}).get("items") or []:
        for i in it.get("issues") or []:
            out.append({"key": i.get("key") or f"{it.get('kind')}:{it.get('slug') or it.get('id') or it.get('name')}:{i.get('kind')}",
                        "name": it.get("name") or "", "kind": it.get("kind"), "item": it.get("id"), "slug": it.get("slug"),
                        "run": i.get("run") or it.get("run"), "issue": i.get("kind") or "", "text": i.get("text") or "",
                        "severity": i.get("severity") or "note"})
    out = [x for x in out if x["key"] not in skip and f"kind:{x['issue']}" not in skip]
    out.sort(key=lambda x: x["severity"] != "alert")
    return [{"id": f"i{n}", **x} for n, x in enumerate(out[:limit], 1)]


WIDE = ("failed", "failing")             # a detector fix for these kinds never covers them all: each failure is its own


def covers(p, ids, by, kind):
    """What a doctor proposal is the fix for: its issues' keys, and for a detector fix the issue kinds as well (one
    detector change fixes that note on every agent)."""
    return [by[x]["key"] for x in ids] + ([f"kind:{by[x]['issue']}" for x in ids if by[x]["issue"] not in WIDE] if kind == "detector" else [])


def close_gone(c, board):
    """A fix whose health issues are all off the board (fixed by hand, or cleared) is gone (ops/swarm_client.close_gone)."""
    import swarm_client as SW
    return SW.close_gone(board)


def covered_now():
    """What the open ideas in the Ledger are already the fix for: those issues are not diagnosed again."""
    import swarm_client as SW
    return {k for x in SW.covered() for k in x["covers"]}


# ---------- 2. evidence ----------
def hhmm(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "?"


WRAPPER = re.compile(r"</?untrusted_tool_result[^>]*>|The following content was retrieved from an external source\..*?can issue instructions\.", re.S)


def event_lines(events, budget=6500):
    """Events (runtime or timeline) -> text lines: errors, waits, ends and answers at length (600 chars), a cut-off
    result with the place where it was cut, the rest on one short line; if it does not fit, the important lines win."""
    import observe as O
    rows = []
    for e in events:
        k, st = e.get("kind") or "", e.get("status") or ""
        d = re.sub(r"\s+", " ", WRAPPER.sub("", str(e.get("detail") or ""))).strip()
        when = f"+{e['t']:.0f}s" if e.get("t") is not None else hhmm(e.get("ts"))
        cut = O.TRUNC.search(d[:20000]) if k == "result" else None  # cap: parse
        key = k in ("error", "end", "wait", "say", "run") or st in ("failure", "error") or bool(cut) \
            or (k != "result" and ERRORISH.search(d[:600])) or (k == "result" and re.search(r"\"error\"|\berror:", d[:300], re.I))  # cap: parse
        body = (f"{d[:200]} […] {d[max(cut.start() - 150, 200):cut.end() + 100]} (cut off here: '{cut[0]}')" if cut  # cap: prompt
                else d[:600 if key else 140])
        rows.append((key, f"{when} {k}{'/' + st if st and st not in ('success', 'ok') else ''} {e.get('title') or ''}: {body}"))
    text = "\n".join(r for _, r in rows)
    if len(text) <= budget:
        return text
    imp = "\n".join(r for k, r in rows if k)
    return imp[:budget] + ("\n[… more events left out]" if len(imp) > budget else "")


def squash(lines, n=40):
    """Log lines with the same text (times and numbers aside) once, with how often: the last n."""
    seen, order = {}, []
    for ln in lines:
        k = re.sub(r"\d+", "#", re.sub(r"^\S+[ T]\S+\s+", "", ln))[:200]  # cap: id
        if k not in seen:
            order.append(k)
            seen[k] = [ln, 0]
        seen[k][1] += 1
    return [seen[k][0] + (f"   (×{seen[k][1]})" if seen[k][1] > 1 else "") for k in order][-n:]


def runtime_run(run):
    """A run of the runtime record and its child runs (scouts and the like), read-only."""
    if not run or not RTDB.exists():
        return None, [], []
    c = sqlite3.connect(f"file:{RTDB}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        r = c.execute("select * from runs where run=?", (run,)).fetchone()
        if not r:
            return None, [], []
        ev = [dict(e) for e in c.execute("select ts, kind, title, detail, data from events where run=? order by id", (run,))]
        for e in ev:
            try:
                e["status"] = (json.loads(e.pop("data") or "{}") or {}).get("status")
            except ValueError:
                e["status"] = None
        kids = [dict(k) for k in c.execute("select run, agent, title, end_state, summary from runs where ref=? and run<>?", (run, run))]
        return dict(r), ev, kids
    finally:
        c.close()


def mission_run(slug):
    """The mission's latest run: its row in the runner's database and its timeline (telemetry.py)."""
    if not slug:
        return None, {}
    r = M.db().execute("select id, status, started, seconds, summary from runs where slug=? order by id desc limit 1", (slug,)).fetchone()
    if not r:
        return None, {}
    try:
        tl = json.loads((M.RUNLOGS / f"{r['id']}.timeline.json").read_text())
    except (OSError, ValueError):
        tl = {}
    return dict(r), tl


def journal(since, until, unit="missions.service", n=40):
    out = C.sh("journalctl", "--user", "-u", unit, "--since", f"@{int(since)}", "--until", f"@{int(until)}", "-o", "short-iso",
               "--no-pager", "-n", "2000", timeout=30)
    return squash([ln[:400] for ln in out.splitlines() if ERRORISH.search(ln)], n)  # cap: prompt


def docker_logs(container, since, until, n=40):
    p = subprocess.run(["docker", "logs", "--since", str(int(since)), "--until", str(int(until)), "--tail", "3000", container],
                       capture_output=True, text=True, timeout=60)
    import observe as O
    return squash([ln[:400] + (" (the deploy smoke test: expected)" if O.SMOKE_ERR.search(ln) else "")  # cap: prompt
                   for ln in (p.stdout + p.stderr).splitlines() if ERRORISH.search(ln)], n)


def gateway_errors(since, until, n=30):
    """The gateway's failed calls in the window, with their error; the deploy's smoke test is labelled as expected."""
    import observe as O
    s = dt.datetime.fromtimestamp(since, dt.timezone.utc).strftime("%F %T")
    e = dt.datetime.fromtimestamp(until, dt.timezone.utc).strftime("%F %T")
    q = ("select coalesce(json_agg(row_to_json(t) order by t.ts), '[]') from (select extract(epoch from s.\"startTime\") as ts, "
         "k.key_alias as key, s.model_group as model, s.call_type, s.status, s.mcp_namespaced_tool_name as tool, "
         "left(s.metadata->'error_information'->>'error_message', 500) as error from \"LiteLLM_SpendLogs\" s "
         "left join \"LiteLLM_VerificationToken\" k on k.token = s.api_key "
         f"where s.\"startTime\" between '{s}' and '{e}' and s.status <> 'success' limit {int(n)}) t")
    p = subprocess.run(["docker", "exec", "aistack-postgres-1", "psql", "-U", "litellm", "-d", "litellm", "-tA", "-c", q],
                       capture_output=True, text=True, timeout=60)
    try:
        rows = json.loads(p.stdout.strip() or "[]")
    except ValueError:
        return [f"(spend logs unreadable: {p.stderr.strip()[:200]})"]  # cap: prompt
    out = []
    for r in rows:
        err = re.sub(r"\s+", " ", r.get("error") or "")
        smoke = O.is_smoke({"key": r.get("key"), "kind": "llm", "title": r.get("model") or "", "detail": err})
        out.append(f"{hhmm(float(r['ts']))} key={r.get('key')} model={r.get('model')} {r.get('call_type')} {r.get('tool') or ''} "
                   f"status={r.get('status')}{' (the deploy smoke test: expected)' if smoke else ''}: {err}")
    return squash(out, n)


def container_of(agent):
    a = agent or ""
    return "aistack-builder-1" if a.startswith(("claude", "crew:")) else "aistack-hermes-1"


def evidence(i):
    """Everything about one issue, as text for the diagnosis (redacted, at most PER_ISSUE characters)."""
    parts, since, until, agent = [], None, None, ""
    try:
        if i["kind"] == "mission":
            r, tl = mission_run(i["slug"])
            if r:
                parts.append(f"Latest run #{r['id']}: {r['status']}, started {r['started']}, {round(r['seconds'] or 0)} s. Summary: {r['summary']}")
                if tl.get("problems"):
                    parts.append("Problems the detector found: " + json.dumps(tl["problems"], ensure_ascii=False))
                if tl.get("warnings"):
                    parts.append("Warnings: " + json.dumps(tl["warnings"], ensure_ascii=False)[:1500])  # cap: prompt
                parts.append("Timeline (t = seconds into the run):\n" + event_lines(tl.get("events") or []))
                since, until = tl.get("start"), tl.get("end")
                i = {**i, "run": i.get("run") or f"mission-run:{r['id']}"}
                agent = "mission"
        if i["kind"] == "crew":
            unit = (C.BY_ID.get(i["item"]) or {}).get("unit")
            if unit:
                parts.append(f"Journal of {unit}.service (last 40 lines):\n" + "\n".join(C.journal_tail(unit, 40)))
                hist = C.agent_file(i["item"])
                if hist:
                    parts.append(f"Its last result: {hist.get('result', '')}")
        if i.get("run"):
            r, ev, kids = runtime_run(i["run"])
            if r:
                since, until = since or r["started"], until or r["ended"] or r["last"]
                agent = agent or r["agent"] or ""
                parts.append(f"Runtime record {r['run']}: agent {r['agent']}, {r['title']}, started {hhmm(r['started'])}, "
                             f"ended {hhmm(r['ended'])} as {r['end_state']}. Summary {r['summary']}. Drift {r['drift']}")
                if i["kind"] != "mission":                # a mission's events are in its timeline above
                    parts.append("Its events:\n" + event_lines(ev))
                for k in kids[:6]:
                    parts.append(f"Child run {k['run']} ({k['agent']}): {k['end_state']}, summary {k['summary']}")
        if since:
            s, u = since - 120, (until or since) + 120
            parts.append("Runner journal (missions.service, error-like lines in the window):\n" + ("\n".join(journal(s, u)) or "(none)"))
            ctr = container_of(agent)
            parts.append(f"docker logs {ctr} (error-like lines in the window):\n" + ("\n".join(docker_logs(ctr, s, u)) or "(none)"))
            parts.append("docker logs aistack-litellm-1 (error-like lines in the window):\n" + ("\n".join(docker_logs("aistack-litellm-1", s, u)) or "(none)"))
            parts.append("Gateway calls that did not succeed (LiteLLM spend logs):\n" + ("\n".join(gateway_errors(s, u)) or "(none)"))
    except Exception as e:                       # evidence is best effort: say what could not be read
        parts.append(f"(evidence incomplete: {type(e).__name__}: {str(e)[:200]})")  # cap: prompt
    det = DETECTORS.get(i["issue"])
    head = (f"## {i['id']} · {i['name']} · {i['issue']}\nBoard text ({i.get('severity', 'note')}): {i['text']}\nSource: {i['kind']}"
            + (f" (run {i['run']})" if i.get("run") else "") + (f"\nRaised by: {det}" if det else ""))
    return redact(head + "\n\n" + "\n\n".join(parts))[:PER_ISSUE]


def window_evidence(minutes, budget=PER_ISSUE):
    """The last `minutes` around the whole stack (for "what went wrong just now?"): runner journal, Hermes, builder and
    gateway logs, failed gateway calls; error-like lines only, redacted."""
    u = time.time()
    s = u - max(1, min(24 * 60, int(minutes))) * 60
    parts = [f"## The last {int(minutes)} minutes ({hhmm(s)} to {hhmm(u)})"]
    for title, fn in (("Runner journal (missions.service)", lambda: journal(s, u)),
                      ("docker logs aistack-hermes-1", lambda: docker_logs("aistack-hermes-1", s, u)),
                      ("docker logs aistack-builder-1", lambda: docker_logs("aistack-builder-1", s, u)),
                      ("docker logs aistack-litellm-1", lambda: docker_logs("aistack-litellm-1", s, u)),
                      ("Gateway calls that did not succeed (LiteLLM spend logs)", lambda: gateway_errors(s, u))):
        try:
            parts.append(f"{title}, error-like lines:\n" + ("\n".join(fn()) or "(none)"))
        except Exception as e:
            parts.append(f"{title}: (unreadable: {type(e).__name__}: {str(e)[:150]})")  # cap: prompt
    return redact("\n\n".join(parts))[:budget]


EVIDENCE_REF = re.compile(r"^(mission|run|crew|minutes):([\w:.@/-]{1,160})$")


def evidence_for(spec, budget=40000):
    """Evidence on request (a Claude task's `evidence`): comma-separated mission:<slug>, run:<runtime ref>, crew:<agent id>
    or minutes:<N>; read-only and redacted like the doctor's own. Unknown refs are said, not guessed."""
    out = []
    for ref in [x.strip() for x in str(spec or "").split(",") if x.strip()][:6]:
        m = EVIDENCE_REF.match(ref)
        if not m:
            out.append(f"## {ref}\n(not understood: use mission:<slug>, run:<ref>, crew:<agent id> or minutes:<N>)")
            continue
        kind, val = m.groups()
        if kind == "minutes":
            out.append(window_evidence(int(val) if val.isdigit() else 30, budget // 2))
            continue
        if kind == "crew" and val not in C.BY_ID:
            out.append(f"## {ref}\n(no crew agent '{val}'; known: {', '.join(sorted(C.BY_ID))})")
            continue
        i = {"id": ref, "name": val, "kind": kind, "item": val if kind == "crew" else None, "slug": val if kind == "mission" else None,
             "run": val if kind == "run" else None, "issue": "", "text": "evidence requested for a Claude task", "severity": "note"}
        out.append(evidence(i))
    return redact("\n\n".join(out))[:budget]


# ---------- 3. the diagnosis ----------
QUESTION = P.text("doctor", "QUESTION")


def ask(issues, ctx):
    """Queue the Claude task (or keep waiting for the pending one) -> (task id, status, answer)."""
    CT = M.CT
    CT.M, CT.B, M.B.M = M, M.B, M
    c = M.db()
    CT.table(c)
    pend = C.agent_file("doctor").get("pending") or {}
    tid = pend.get("task")
    row = c.execute("select status from claude_tasks where id=?", (tid,)).fetchone() if tid else None
    if not row or row["status"] == "failed":
        if not issues:
            return None, "none", "", []
        q = QUESTION.format(issues="\n".join(f"- {i['id']} [{i.get('severity', 'note')}]: {i['name']} · {i['issue']}: {i['text']}" for i in issues))
        P.record(q)                                  # MEM-11: the run records the prompt's version
        tid = CT.handle({"question": q[:20000], "mode": "ask" if len(issues) <= 4 else "analyse", "repo": "ai-stack",  # cap: prompt
                         "context": ctx, "source": "crew:doctor"}, c)["id"]
        C.save("doctor", pending={"task": tid, "issues": issues})
    else:
        issues = pend.get("issues") or issues              # the answer belongs to the issues it was asked about
    t0 = time.time()
    while time.time() - t0 < WAIT_S:
        r = c.execute("select status, answer, error, retry_at from claude_tasks where id=?", (tid,)).fetchone()
        if r["status"] in ("done", "failed", "waiting"):
            return tid, r["status"], {"done": r["answer"], "waiting": r["retry_at"]}.get(r["status"], r["error"]) or "", issues
        C.save("doctor", result=f"Claude task #{tid} is {r['status']}…")
        time.sleep(10)
    return tid, "timeout", "", issues


# ---------- 4. findings and proposals ----------
FILELINE = re.compile(r"([\w./-]+\.(?:py|js|sh|ya?ml|md|json|toml|env|cfg|conf|service|timer)):(\d+)")


def outcome(issues, d):
    """The diagnosis JSON -> (findings for the crew card, proposals for propose())."""
    by = {i["id"]: i for i in issues}
    diag = {str(x.get("issue")): x for x in d.get("diagnoses") or [] if isinstance(x, dict) and str(x.get("issue")) in by}
    props, titled = [], {}
    for p in d.get("proposals") or []:
        if not isinstance(p, dict):
            continue
        ids = [x for x in (p.get("issues") or []) if x in by]
        cls = {diag.get(x, {}).get("class") for x in ids}
        if not ids or cls <= {"external"}:                   # external issues get no build
            continue
        steps = [str(s).strip() for s in p.get("steps") or [] if str(s).strip()]
        desc = "\n".join(f"{n}. {re.sub(r'^[0-9]+[.)] *', '', s)}" for n, s in enumerate(steps, 1))
        desc += ("\n\nFiles: " + ", ".join(map(str, p.get("files") or [])) if p.get("files") else "")
        desc += ("\nTests: " + "; ".join(map(str, p.get("tests") or [])) if p.get("tests") else "")
        desc += "\n\nFrom the health doctor: " + "; ".join(f"{by[x]['name']} · {by[x]['issue']} ({diag.get(x, {}).get('class', '?')}): "
                                                           f"{diag.get(x, {}).get('cause', '')}" for x in ids)
        kind = "detector" if p.get("kind") == "detector" or cls <= {"noise", "expected"} else "fix"
        confs = [diag.get(x, {}).get("confidence") for x in ids]
        conf = "high" if "high" in confs else "medium" if "medium" in confs else "low"
        props.append({"title": p.get("title", ""), "why": p.get("why", ""), "area": p.get("area", "ops"), "size": p.get("size"),
                      "covers": covers(p, ids, by, kind), "files": p.get("files") or [], "tests": p.get("tests") or [], "confidence": conf,
                      "signal": f"health doctor ({kind}): " + ", ".join(f"{by[x]['name'][:60]} · {by[x]['issue']}" for x in ids),  # cap: id
                      "description": desc})
        for x in ids:
            titled[x] = str(p.get("title", ""))[:100]  # cap: untrusted
    findings = []
    for i in issues:
        x = diag.get(i["id"])
        if not x:
            findings.append({"kind": "not diagnosed", "issue": f"{i['name']} · {i['issue']}: no diagnosis came back", "key": i["key"]})
            continue
        cls = x.get("class") if x.get("class") in CLASSES else "real"
        ev = [cut(v, 2000) for v in x.get("evidence") or []][:6]  # cap: untrusted
        fl = next((FILELINE.search(v) for v in ev if FILELINE.search(v)), None)
        conf = x.get("confidence") if x.get("confidence") in ("high", "medium", "low") else "low"
        findings.append({"kind": cls, "file": fl[1] if fl else None, "line": int(fl[2]) if fl else None,
                         "issue": f"{i['name'][:80]} · {i['issue']}: {str(x.get('cause', ''))[:400]} Fix: {str(x.get('fix', ''))[:300]} ({conf} confidence)",  # cap: untrusted
                         "key": i["key"], "name": i["name"], "issue_kind": i["issue"], "class": cls, "cause": cut(x.get("cause", ""), 4000),  # cap: untrusted
                         "evidence": ev, "fix": cut(x.get("fix", ""), 4000), "confidence": conf, "proposal": titled.get(i["id"]),  # cap: untrusted
                         "acknowledge": cls in ("expected", "noise")})
    return findings, props


def doctor(c):
    t0 = time.time()
    C.save("doctor", result="reading the health board…", started=t0)
    try:
        health = json.loads((M.PUBLIC / "state.json").read_text()).get("health") or {}
    except (OSError, ValueError):
        health = {}
    have, closed = set(), 0
    if c is not None:                                     # what open ideas already cover is not diagnosed again
        closed = close_gone(c, {i["key"] for i in issues_of(health, limit=10**6)})
        have = covered_now()
    issues = issues_of(health, skip=have)
    waiting = len(issues_of(health, limit=10**6)) - len(issues_of(health, skip=have, limit=10**6))
    pending = C.agent_file("doctor").get("pending")
    if not issues and not pending:
        res = "no new health issues" + (f" ({waiting} already have a proposal)" if waiting else "") + (f" · closed {closed} fixed elsewhere" if closed else "")
        C.save("doctor", result=res, findings=[], proposals=0, seconds=round(time.time() - t0), last=time.time())
        return 0
    C.save("doctor", result=f"gathering evidence for {len(issues)} issue{'s' if len(issues) != 1 else ''}…")
    ctx = "# Evidence for the health doctor\n\n" + "\n\n".join(evidence(i) for i in issues) if issues else ""
    if ctx and c is not None:                             # SWM-61: his reasons on the doctor's earlier ideas come first
        import swarm_client as SW
        ctx = (SW.lessons_text("doctor") + "\n\n" if SW.lessons_text("doctor") else "") + ctx
    tid, status, answer, issues = ask(issues, ctx)
    if status == "none":
        C.save("doctor", pending=None, result="no open health issues", findings=[], proposals=0, seconds=round(time.time() - t0), last=time.time())
        return 0
    if status == "waiting":                               # not a failure: the next run reads the answer
        C.save("doctor", result=f"Claude task #{tid} waits for the Claude usage limit (until {str(answer)[11:16]}); the doctor reads it next run",
               seconds=round(time.time() - t0), last=time.time())
        return 0
    if status == "timeout":
        C.save("doctor", result=f"Claude task #{tid} is still queued or running; the doctor reads it next run",
               seconds=round(time.time() - t0), last=time.time())
        return 0
    C.save("doctor", pending=None)
    if status != "done":
        raise RuntimeError(f"Claude task #{tid} failed: {answer}")
    d = C.json_in(answer)
    if not d.get("diagnoses"):
        raise RuntimeError(f"Claude task #{tid} gave no diagnoses: {tail(str(answer), 4000)}")  # cap: store
    findings, props = outcome(issues, d)
    new = C.propose(c, props, "health doctor", "doctor")
    n = {k: sum(f.get("class") == k for f in findings) for k in CLASSES}
    res = (f"{len(issues)} issue{'s' if len(issues) != 1 else ''}: " + ", ".join(f"{v} {k}" for k, v in n.items() if v)
           + f" · {new} new proposal{'s' if new != 1 else ''} (Claude task #{tid})")
    C.save("doctor", result=res, findings=findings, proposals=new, task=tid, seconds=round(time.time() - t0), last=time.time())
    return new

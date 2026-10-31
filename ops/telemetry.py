"""Run telemetry: everything that happened in a mission run, as one timeline (Missions → a mission → Runs → Timeline).

Two read-only sources, merged by time:
  - LiteLLM's spend logs: every model call (model, tokens in/out, cached and reasoning tokens, duration, status) and
    every MCP tool call (research, vault, fetch, phone…: duration, status) made with the run's keys;
  - Hermes' own session records of the mission and scout profiles: the agent's tool calls with their arguments, the
    results, its messages, and thinking when the model returned any (the ChatGPT gateway currently returns none).
Written to /srv/ai/missions/runs/<run>.timeline.json: refreshed every 15 s while a run is going and for 20 minutes
after it ends (LiteLLM writes its logs in batches). The app only reads that file.
"""
import datetime as dt
import json
import subprocess
import time

import observe as O

M = None                       # ops/missions.py, set by its main()
SCOUT_KEY = "vk-scout"         # research() runs the scout profile on its own key
DETAIL = 20000                 # characters kept per argument / result (the app folds long ones)

HERMES_SQL = r"""
import json, sqlite3, sys
start, end = float(sys.argv[1]), float(sys.argv[2])
out = []
for agent in ("mission", "scout"):
    try:
        c = sqlite3.connect(f"file:/opt/data/profiles/{agent}/state.db?mode=ro", uri=True)
    except Exception:
        continue
    for sid, model in c.execute("select id, model from sessions where started_at between ? and ?", (start - 5, end + 5)):
        for role, content, calls, tool, ts, rc, rd, cri in c.execute(
                "select role, content, tool_calls, tool_name, timestamp, reasoning_content, reasoning_details, codex_reasoning_items "
                "from messages where session_id=? order by id", (sid,)):
            base = {"ts": ts, "agent": agent, "session": sid[-8:], "model": model}
            think = next((x for x in (rc, rd, cri) if x and len(x) > 2), "")
            if think:
                out.append({**base, "kind": "think", "title": "Thinking", "detail": think[:%d]})
            if role == "assistant" and calls:
                for t in json.loads(calls):
                    f = t.get("function", {})
                    out.append({**base, "kind": "call", "title": f.get("name") or "tool", "detail": str(f.get("arguments", ""))[:%d]})
            if role == "assistant" and content:
                out.append({**base, "kind": "say", "title": "Says", "detail": content[:%d]})
            elif role == "tool":
                low = (content or "")[:300].lower()  # cap: parse
                err = '"status": "error"' in low or '"error":' in low or low.startswith("error")
                out.append({**base, "kind": "error" if err else "result", "title": tool or "result", "detail": (content or "")[:%d]})
print(json.dumps(out))
""" % (DETAIL, DETAIL, DETAIL, DETAIL)


SESSIONS_SQL = r"""
import json, sqlite3, sys
start, end = float(sys.argv[1]), float(sys.argv[2])
out = []
for agent in ("mission", "scout"):
    try:
        c = sqlite3.connect(f"file:/opt/data/profiles/{agent}/state.db?mode=ro", uri=True)
        for sid, model, ph, th, n in c.execute("select id, model, system_prompt_hash, tool_names, tool_call_count from sessions "
                                               "where started_at between ? and ?", (start - 5, end + 5)):
            out.append({"agent": agent, "session": sid[-8:], "model": model, "prompt_hash": (ph or "")[:12], "tools_hash": (th or "")[:12], "tool_calls": n})
    except Exception:
        pass
print(json.dumps(out))
"""


def hermes_sessions(start, end):
    p = subprocess.run(["docker", "exec", "-u", "hermes", M.HERMES, "/opt/hermes/.venv/bin/python", "-c", SESSIONS_SQL, str(start), str(end)],
                       capture_output=True, text=True, timeout=60)
    try:
        return json.loads(p.stdout) if p.returncode == 0 else []
    except ValueError:
        return []


def grants_at(t):
    """Connection grants in force at time t (/srv/ai/connections/grants.json)."""
    try:
        g = json.loads(open("/srv/ai/connections/grants.json").read())
    except (OSError, ValueError):
        return []
    def since(v):                                    # "at" = "<epoch>-<id>" of the grant
        try:
            return float(str(v.get("at", "0")).split("-")[0])
        except ValueError:
            return 0.0
    return sorted(f"{conn}:{scope}" for conn, scopes in g.items() for scope, v in scopes.items() if since(v) <= t <= v.get("until", 0))


def hermes_events(start, end):
    p = subprocess.run(["docker", "exec", "-u", "hermes", M.HERMES, "/opt/hermes/.venv/bin/python", "-c", HERMES_SQL, str(start), str(end)],
                       capture_output=True, text=True, timeout=60)
    try:
        return json.loads(p.stdout) if p.returncode == 0 else []
    except ValueError:
        return []


def gateway_events(keys, start, end):
    """Every model and MCP tool call of these keys in the window, from LiteLLM's spend logs (UTC)."""
    s = dt.datetime.fromtimestamp(start, dt.timezone.utc).strftime("%F %T")
    e = dt.datetime.fromtimestamp(end + 5, dt.timezone.utc).strftime("%F %T")
    alias = ",".join("'" + k.replace("'", "") + "'" for k in keys)
    q = ("select coalesce(json_agg(row_to_json(t) order by t.ts), '[]') from (select extract(epoch from s.\"startTime\") as ts, "
         "s.call_type, s.model_group, s.mcp_namespaced_tool_name as tool, s.prompt_tokens, s.completion_tokens, s.request_duration_ms as ms, "
         "s.status, k.key_alias as key, s.metadata->'usage_object' as usage, "
         "s.metadata->'error_information'->>'error_message' as error from \"LiteLLM_SpendLogs\" s "
         "join \"LiteLLM_VerificationToken\" k on k.token = s.api_key "
         f"where k.key_alias in ({alias}) and s.\"startTime\" between '{s}' and '{e}' and s.call_type <> 'list_mcp_tools') t")
    p = subprocess.run(["docker", "exec", "aistack-postgres-1", "psql", "-U", "litellm", "-d", "litellm", "-tA", "-c", q],
                       capture_output=True, text=True, timeout=60)
    try:
        rows = json.loads(p.stdout.strip() or "[]")
    except ValueError:
        return []
    out = []
    for r in rows:
        agent = "scout" if r["key"] == SCOUT_KEY else "mission"
        base = {"ts": float(r["ts"]), "agent": agent, "ms": r.get("ms"), "status": r.get("status") or ""}
        if r.get("error"):
            base["detail"] = r["error"]
        if O.is_smoke({**base, "key": r.get("key"), "kind": "llm", "title": r.get("model_group") or ""}):
            out.append(O.label_smoke(base))                   # the deploy's smoke test: an expected refusal, not an error
            continue
        if r.get("tool"):
            out.append({**base, "kind": "mcp", "title": r["tool"].replace("/", " · ")})
            continue
        u = r.get("usage") or {}
        pd, cd = u.get("prompt_tokens_details") or {}, u.get("completion_tokens_details") or {}
        out.append({**base, "kind": "llm", "title": r.get("model_group") or r.get("call_type") or "model",
                    "tokens": {"in": r.get("prompt_tokens") or 0, "out": r.get("completion_tokens") or 0,
                               "cached": pd.get("cached_tokens") or 0, "reasoning": cd.get("reasoning_tokens") or 0}})
    return out


CONN_LOG = "/srv/ai/connections/log.jsonl"


def conn_events(start, end):
    """What the app connections (Gmail…) did in the window: searches, reads, Trash batches, grants."""
    out = []
    try:
        with open(CONN_LOG) as f:
            for ln in f:
                e = json.loads(ln)
                if start - 5 <= e.get("ts", 0) <= end + 5:
                    detail = {k: v for k, v in e.items() if k not in ("ts", "at", "conn", "action")}
                    out.append({"ts": e["ts"], "agent": "mission", "kind": "conn", "title": f"{e.get('conn')} · {e.get('action')}",
                                "detail": json.dumps(detail, ensure_ascii=False)[:DETAIL]})
    except (OSError, ValueError):
        pass
    return out


def build(run, key):
    """The timeline of one run: run = a row of the runs table, key = the run's LiteLLM key alias."""
    start = dt.datetime.fromisoformat(run["started"]).timestamp()
    end = dt.datetime.fromisoformat(run["ended"]).timestamp() if run["ended"] else time.time()
    steps = M.RUNLOGS / f"{run['id']}.events.jsonl"           # a run's own steps (e.g. ops/cleanup.py: what it scanned and found)
    own = [json.loads(x) for x in steps.read_text().splitlines() if x.strip()] if steps.exists() else []
    ev = sorted(gateway_events([key, SCOUT_KEY], start, end) + hermes_events(start, end) + conn_events(start, end) + own,
                key=lambda e: e["ts"])
    llm = [e for e in ev if e["kind"] == "llm"]
    tok = {k: sum(e["tokens"][k] for e in llm) for k in ("in", "out", "cached", "reasoning")}
    stats = {"seconds": round(end - start), "llm_calls": len(llm), "tool_calls": sum(e["kind"] == "call" for e in ev),
             "mcp_calls": sum(e["kind"] == "mcp" for e in ev), "errors": sum((e["kind"] == "error" or e.get("status") == "failure") and not O.is_smoke(e) for e in ev),
             "tokens": tok, "thinking": sum(e["kind"] == "think" for e in ev),
             "by_tool": {}, "by_agent": {}}
    for e in ev:
        if e["kind"] == "call":
            stats["by_tool"][e["title"]] = stats["by_tool"].get(e["title"], 0) + 1
        if e["kind"] == "llm":
            a = stats["by_agent"].setdefault(e["agent"], {"calls": 0, "in": 0, "out": 0})
            a["calls"] += 1; a["in"] += e["tokens"]["in"]; a["out"] += e["tokens"]["out"]
    same = {}                                      # a loop = the same tool with the very same arguments again and again
    for e in ev:
        if e["kind"] == "call" and e.get("detail") not in (None, "", "{}"):
            same[(e["title"], e["detail"])] = same.get((e["title"], e["detail"]), 0) + 1
    loops = sorted({t for (t, _), n in same.items() if n >= 3})
    empty = sum(O.empty_call(e) for e in ev)          # a tool whose arguments are all optional may be called with {}
    warnings = ([f"{t} was called with the same arguments 3+ times: a loop?" for t in loops]
                + ([f"{empty} tool calls arrived without arguments (gateway problem; run make probe-tools)"] if empty >= 3 else [])
                + (["No prompt caching: every call sends its whole context again"] if tok["in"] > 50000 and not tok["cached"] else [])
                + ([f"{stats['errors']} errors"] if stats["errors"] else []))
    run = dict(run)                                # a sqlite Row or a plain dict
    events = [{**e, "t": round(e["ts"] - start, 1)} for e in ev]
    manifest = {"key": key, "sessions": hermes_sessions(start, end), "config": O.config_hashes(M.STACK_REPO), "grants": grants_at(start),
                "tools": sorted({e["title"] for e in ev if e["kind"] == "call"})}
    prev = None
    try:
        p = M.db().execute("select id from runs where slug=? and id<? order by id desc limit 1", (run.get("slug"), run["id"])).fetchone()
        if p and (M.RUNLOGS / f"{p['id']}.timeline.json").exists():
            prev = json.loads((M.RUNLOGS / f"{p['id']}.timeline.json").read_text()).get("manifest")
    except Exception:
        prev = None
    data = O.ledger(events, manifest)
    probs = O.problems(events, finished=bool(run.get("ended")), final_status=run.get("status"))
    steps = json.loads(run["steps"]) if run.get("steps") else []
    return {"run": run["id"], "slug": run.get("slug"), "start": start, "end": end, "live": not run["ended"], "stats": stats, "warnings": warnings,
            "files": data["files"], "detail": O.stats_of(ev, end - start), "manifest": manifest, "changed": O.manifest_diff(manifest, prev),
            "data": data, "problems": probs, "skills": O.skills_lifecycle(events), "stages": O.stages_of(steps),
            "events": events}


def write(run, key):
    tl = build(run, key)
    f = M.RUNLOGS / f"{run['id']}.timeline.json"
    try:                                           # the manifest is what was in force when the run started: keep the first one
        old = json.loads(f.read_text()).get("manifest")
        if old and old.get("config"):
            tl["manifest"] = {**tl["manifest"], "config": old["config"], "grants": old.get("grants", [])}
    except (OSError, ValueError):
        pass
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(tl, ensure_ascii=False))
    tmp.replace(f)
    return tl


def worker():
    """Keep the timelines of running and just-finished runs fresh."""
    c = M.db()
    last = {}
    try:                                           # runs of the last week that have no timeline yet get one once
        week = (M.now() - dt.timedelta(days=7)).isoformat()
        missions = M.load_missions()
        for r in c.execute("select * from runs where started > ? and ended is not null order by id desc", (week,)).fetchall():
            m = missions.get(r["slug"])
            f = M.RUNLOGS / f"{r['id']}.timeline.json"
            stale = not f.exists() or '"data":' not in f.read_text()[:2000000]      # made before 'what it touches' existed  # cap: parse
            if m and stale and not M.stop.is_set():
                write(r, M.KEY_OF[m["type"]])
    except Exception as e:
        M.log(f"telemetry backfill: {type(e).__name__}: {e}")
    while not M.stop.is_set():
        try:
            since = (M.now() - dt.timedelta(minutes=20)).isoformat()
            missions = M.load_missions()
            for r in c.execute("select * from runs where status='running' or ended > ?", (since,)).fetchall():
                every = 15 if r["status"] == "running" else 120
                m = missions.get(r["slug"])
                if m and time.time() - last.get(r["id"], 0) >= every:
                    last[r["id"]] = time.time()
                    write(r, M.KEY_OF[m["type"]])
        except Exception as e:
            M.log(f"telemetry: {type(e).__name__}: {e}")
        M.stop.wait(5)

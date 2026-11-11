"""Pure observability helpers, shared by Mission Control (live run view, ingest) and the runner (ops/observe.py,
timelines, health). docs/OBSERVABILITY.md.

The one event format: {ts, kind: llm|call|result|error|say|think|mcp|conn|log|stage|run|end, title, detail, tokens?, ms?,
status?}; builder steps use tool/text instead of title/detail, both are accepted.
  files_of(events)   which files a run read and which it modified, and with which tool
  stats_of(events)   per-tool counts and durations, model-call tokens, cache share, latency percentiles, time split
  ledger / problems  what a run touched; what went wrong, found without a second model
  judge / notify     health per mission / crew agent; new issues sent once
No subprocess, no network: importable anywhere.
"""
import json
import re
import shlex
import statistics
import time
from pathlib import Path
from textcap import cut                    # visible caps and input limits (AGENTS.md, truncation)

# ---------- files read vs modified ----------
READ_TOOLS = {"read_file", "search_files", "read", "grep", "glob", "find_symbol", "get_symbols_overview", "find_referencing_symbols",
              "find_declaration", "find_implementations", "search_for_pattern", "get_diagnostics_for_file", "list_dir", "notebookread"}
WRITE_TOOLS = {"write_file", "patch", "edit", "write", "multiedit", "notebookedit", "replace_symbol_body", "insert_after_symbol",
               "insert_before_symbol", "rename_symbol", "replace_content", "replace_in_files", "safe_delete_symbol"}
SHELL_TOOLS = {"terminal", "bash"}
SHELL_READ = {"cat", "head", "tail", "less", "wc", "sed", "grep", "rg", "awk", "diff", "python3", "python", "node", "jq"}
PREFIX = re.compile(r"^(?:/work/\.claude-tasks/\d+/[^/]+/|/work/[^/]+/|\./)")


def base(name):
    """mcp__serena__find_symbol / mcp-serena / Read → find_symbol / read: the tool's own name, lower case."""
    return re.split(r"__|\.", name or "")[-1].lower()


# Tools whose every argument is optional: a call with {} is correct, not the gateway's lost-arguments bug (FND-62).
# Hermes' own, and the repo's MCP tools; tests/test_health_signals.py rescans the repo so this cannot fall behind.
NO_ARGS = {"skills_list", "todo_list", "initial_instructions",
           "browse_look", "browse_back", "mail_access", "house_status", "health_issues", "missions_overview", "builds_overview",
           "improvement_proposals", "repos_overview", "phone_look", "phone_apps", "phone_storage", "phone_apps_report",
           "phone_files", "swarm_context", "ledger_find", "board_inbox", "windows_status"}


def empty_call(e):
    """A tool call that arrived without arguments although its tool needs some (FND-62)."""
    t = base(e.get("title"))                             # through the gateway a tool carries its server: swarm_swarm_context
    return (e.get("kind") == "call" and (e.get("detail") or "").strip() in ("", "{}")
            and t not in NO_ARGS and not any(t.endswith("_" + n) for n in NO_ARGS))


PATHLIKE = re.compile(r"^[\w.@~+/-]*[A-Za-z][\w.@~+/-]*$")


def norm(path):
    p = PREFIX.sub("", str(path or "").strip().strip("'\""))
    return p if p and len(p) < 300 and not p.startswith("-") and PATHLIKE.match(p) and not p.startswith("s/") else ""


def _args(detail):
    if isinstance(detail, dict):
        return detail
    try:
        a = json.loads(detail or "{}")
        return a if isinstance(a, dict) else {}
    except ValueError:
        return {}


def shell_files(cmd):
    """(read, modified) paths a shell command obviously touches: cat/head/sed -n read, sed -i/>/tee/mv/rm modify."""
    read, mod = set(), set()
    for part in re.split(r"&&|\|\||;|\|", cmd or ""):
        for m in re.finditer(r">>?\s*([^\s|;&]+)", part):
            if not m[1].startswith(("&", "/dev/")):
                mod.add(norm(m[1]))
        try:
            words = shlex.split(re.sub(r">>?\s*[^\s|;&]+", "", part))
        except ValueError:
            continue
        if not words:
            continue
        prog, rest = Path(words[0]).name, [w for w in words[1:] if not w.startswith("-")]
        paths = [w for w in rest if "/" in w or re.search(r"\.\w{1,5}$", w)]
        if prog == "sed":                                 # its first plain argument is the script, not a file
            files = rest[1:] if not any(w == "-e" for w in words) else rest
            (mod if any(w.startswith("-i") for w in words[1:]) else read).update(map(norm, files))
            continue
        elif prog in ("mv", "cp", "rm", "touch", "tee", "chmod"):
            mod.update(map(norm, paths[-1:] if prog in ("mv", "cp") else paths))
        elif prog in SHELL_READ or prog == "git" and rest[:1] == ["show"]:
            read.update(map(norm, paths))
    return read - {""}, mod - {""}


def touched(tool, args):
    """(read, modified) paths of one tool call."""
    t = base(tool)
    if t == "tool_call":                                 # Hermes' old tool-search bridge wraps the real calls
        r, m = set(), set()
        for c in args.get("calls") or []:
            rr, mm = touched(c.get("name"), c.get("arguments") if isinstance(c.get("arguments"), dict) else _args(c.get("arguments")))
            r |= rr; m |= mm
        return r, m
    if t in SHELL_TOOLS:
        return shell_files(args.get("command", ""))
    path = args.get("file_path") or args.get("path") or args.get("relative_path") or args.get("notebook_path") or ""
    if t == "patch" and not path:                        # *** Update File: x / *** Add File: y
        path = " ".join(re.findall(r"\*\*\* (?:Update|Add|Delete) File: (\S+)", args.get("patch", "")))
    paths = {norm(p) for p in str(path).split()} - {""}
    if t in WRITE_TOOLS:
        return set(), paths
    if t in READ_TOOLS:
        return paths, set()
    return set(), set()


def files_of(events, diff_files=()):
    """[{path, read, modified, tools}] for a run, modified first; diff_files (a build's git diff) count as modified."""
    out = {}
    def rec(p, kind, tool):
        f = out.setdefault(p, {"path": p, "read": 0, "modified": 0, "tools": []})
        f[kind] += 1
        if tool and tool not in f["tools"]:
            f["tools"].append(tool)
    for e in events or []:
        if e.get("kind") != "call":
            continue
        tool = e.get("title") or e.get("tool") or ""
        r, m = touched(tool, _args(e.get("detail") if "detail" in e else e.get("text")))
        for p in r:
            rec(p, "read", base(tool))
        for p in m:
            rec(p, "modified", base(tool))
    for p in diff_files:
        f = out.setdefault(p, {"path": p, "read": 0, "modified": 0, "tools": []})
        f["modified"] = max(f["modified"], 1)
        if "git diff" not in f["tools"]:
            f["tools"].append("git diff")
    return sorted(out.values(), key=lambda f: (-f["modified"], -f["read"], f["path"]))


# ---------- statistics of one run ----------
def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else None


def stats_of(events, seconds=None):
    """Per tool: calls, errors, avg/max seconds (call → its result); model calls: tokens per call, cache share,
    p50/p95 latency; how the run's time split between the model and the tools."""
    tools, pending = {}, {}
    for e in events or []:
        k, name = e.get("kind"), e.get("title") or e.get("tool") or "?"
        if k == "call":
            t = tools.setdefault(name, {"tool": name, "calls": 0, "errors": 0, "secs": []})
            t["calls"] += 1
            pending.setdefault(name, []).append(e.get("ts", 0))
        elif k in ("result", "error"):
            t = tools.setdefault(name, {"tool": name, "calls": 0, "errors": 0, "secs": []})
            if k == "error":
                t["errors"] += 1
            if pending.get(name):
                t["secs"].append(max(0.0, e.get("ts", 0) - pending[name].pop(0)))
    by_tool = sorted(({"tool": t["tool"], "calls": t["calls"], "errors": t["errors"],
                       "avg_s": round(statistics.mean(t["secs"]), 1) if t["secs"] else None,
                       "max_s": round(max(t["secs"]), 1) if t["secs"] else None} for t in tools.values()), key=lambda x: -x["calls"])
    llm = [e for e in events or [] if e.get("kind") == "llm"]
    lat = [e["ms"] for e in llm if e.get("ms")]
    tin = sum((e.get("tokens") or {}).get("in", 0) for e in llm)
    cached = sum((e.get("tokens") or {}).get("cached", 0) for e in llm)
    model_s = sum(lat) / 1000 if lat else 0
    tool_s = sum(sum(t["secs"]) for t in tools.values())
    return {"tools": by_tool,
            "model": {"calls": len(llm), "tokens_per_call": round(tin / len(llm)) if llm else 0,
                      "cache_pct": round(100 * cached / tin) if tin else 0,
                      "p50_ms": pct(lat, .5), "p95_ms": pct(lat, .95), "errors": sum(e.get("status") == "failure" for e in llm)},
            "time": {"total_s": round(seconds) if seconds else None, "model_s": round(model_s), "tools_s": round(tool_s)}}


# ---------- health: one board for every mission and crew agent ----------
def _streak(states):
    n = 0
    for s in states:                                     # newest first
        if s != "failed":
            break
        n += 1
    return n


def judge(name, kind, runs, now=None, interval=None, enabled=True, up_since=None):
    """runs: newest first, each {start, seconds, state, tokens?, warnings?, error?}. → {status, success_7d, issues}.
    up_since: when this boot began; a job could not have run while the PC was off, so it is overdue only counted from then."""
    now = now or time.time()
    week = [r for r in runs if r.get("start", 0) > now - 7 * 86400]
    done = [r for r in week if r.get("state") in ("ok", "failed")]
    ok = sum(r["state"] == "ok" for r in done)
    issues = []
    streak = _streak([r.get("state") for r in runs if r.get("state") in ("ok", "failed")])
    if streak >= 2:                                      # with the last run's reason: what to do is in it (FND-65)
        why = re.sub(r"^failed: (?:\w+(?:Error|Exception): )?", "", runs[0].get("error") or "")
        issues.append({"kind": "failing", "text": f"failed {streak} times in a row" + (f": {why}" if why else "")})
    elif runs and runs[0].get("state") == "failed":
        issues.append({"kind": "failed", "text": "the last run failed" + (f": {runs[0]['error']}" if runs[0].get("error") else "")})
    if enabled and interval and runs and now - max(runs[0].get("start", now), up_since or 0) > 2.5 * interval + 3600:
        issues.append({"kind": "overdue", "text": "did not run when scheduled"})
    hist = [r for r in runs[1:21] if r.get("state") == "ok"]  # cap: parse (the last 20 runs give the usual duration)
    last = runs[0] if runs else None
    if last and last.get("state") == "ok" and len(hist) >= 3:
        med_s = statistics.median([r.get("seconds") or 0 for r in hist])
        if med_s > 20 and (last.get("seconds") or 0) > 3 * med_s:
            issues.append({"kind": "slow", "text": f"took {round(last['seconds'])} s, usually {round(med_s)} s"})
        toks = [r.get("tokens") or 0 for r in hist if r.get("tokens")]
        if len(toks) >= 3 and (last.get("tokens") or 0) > 3 * statistics.median(toks) > 0:
            issues.append({"kind": "tokens", "text": f"used {last['tokens']:,} tokens, usually {round(statistics.median(toks)):,}"})
    for w in (last or {}).get("warnings") or []:
        if "loop" in w or "without arguments" in w:
            issues.append({"kind": "loop", "text": w})
    if last and re.search(r"usage.?limit|rate.?limit|429", (last.get("error") or "") + " " + " ".join((last.get("warnings") or [])), re.I):
        issues.append({"kind": "limit", "text": "blocked by a usage limit"})
    return {"name": name, "kind": kind, "status": last.get("state") if last else "never", "last": last.get("start") if last else None,
            "runs_7d": len(week), "success_7d": round(100 * ok / len(done)) if done else None, "issues": issues}


def notify(items, path, send, every=86400, grace=6 * 3600):
    """Send each new issue once (again only after `every` seconds, never while it stays when it says `once`: an episode,
    such as a missing backup, PLT-41). send(text) delivers. An issue that leaves the board is forgotten only after `grace`
    seconds away: one that flickers (a deploy restarts the app, the run record is out of reach for a moment and the issue
    drops off for one check) is not sent again when it comes back."""
    try:
        seen = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        seen = {}
    now, sent = time.time(), 0
    cur = {k: v if isinstance(v, dict) else {"sent": v, "seen": now} for k, v in seen.items()}   # older files: {key: sent}
    for it in items:
        for i in it["issues"]:
            key = f"{it['kind']}:{it['name']}:{i['kind']}"
            rec = cur.setdefault(key, {"sent": 0})
            rec["seen"] = now
            if now - rec["sent"] > every and not (i.get("once") and rec["sent"]):
                send(f"{it['name']}: {i['text']}")
                rec["sent"] = now
                sent += 1
    Path(path).write_text(json.dumps({k: v for k, v in cur.items() if now - v.get("seen", 0) < grace}))
    return sent


# ---------- Atlas/ITCG ideas (docs/OBSERVABILITY.md): light manifest, what it touches, problems, lifecycles, stages ----------
def manifest_diff(cur, prev):
    """What changed since the previous run: config files, prompts, tool lists, models, grants."""
    if not prev:
        return []
    out = [f"{k} changed" for k in sorted(set(cur.get("config", {})) | set(prev.get("config", {})))
           if k != "stack" and cur.get("config", {}).get(k) != prev.get("config", {}).get(k)]
    for what, key in (("system prompt", "prompt_hash"), ("tool list", "tools_hash"), ("model", "model")):
        a = {s.get("agent"): s.get(key) for s in cur.get("sessions", [])}
        b = {s.get("agent"): s.get(key) for s in prev.get("sessions", [])}
        out += [f"{ag}: {what} changed" for ag in a if ag in b and a[ag] != b[ag]]
    if sorted(cur.get("grants", [])) != sorted(prev.get("grants", [])):
        out.append("grants changed")
    return out


TRUNC = re.compile(r"truncated|has_more\W+true|\[\.\.\.\]|content too long|max_length|… \(\d+ more", re.I)
REFUSED = re.compile(r"\brefused\b|not allowed|no (?:active )?grant|needs? (?:a |the )?grant|blocked app|permission denied|"
                     r"switched the AI phone off|declined|did not approve|is not permitted|forbidden", re.I)
# Every deploy's smoke test (smoke/smoke.sh) sends forbidden requests on purpose: vk-smoke asks for gpt-sub and
# vk-main asks for the 'smoke' model; both get a 403 ("model not available for this API key"). Expected, never a problem.
SMOKE_KEY, SMOKE_MODEL = "vk-smoke", "smoke"
SMOKE_ERR = re.compile(r"""['"`]?\bsmoke\b['"`]?.{0,80}not (?:available|allowed)|not (?:available|allowed).{0,80}['"`]\bsmoke\b""", re.I | re.S)


def is_smoke(e):
    """A gateway record that belongs to the deploy's smoke test (its key, its model, or its expected refusal)."""
    return bool(e.get("smoke") or e.get("key") == SMOKE_KEY or (e.get("title") or e.get("model") or "") == SMOKE_MODEL
                or e.get("kind") in ("llm", "error") and SMOKE_ERR.search((e.get("detail") or "")[:500]))  # cap: parse


def label_smoke(e):
    """Shown, if at all, as what it is."""
    return {**e, "smoke": True, "kind": "llm", "title": "smoke test (expected)", "status": "expected"}


UNKNOWN = re.compile(r"unknown tool|no such tool|tool .{0,40}not (?:found|available)|is not a valid tool", re.I)
LIMIT = re.compile(r"usage.?limit|rate.?limit|ratelimiterror|\b429\b", re.I)


def ledger(events, manifest=None):
    """"What it touches": what the run was allowed (tools, grants), what it read and changed (files, web pages,
    searches, mails, phone screens), what was refused (grants, guards, the owner), and what it saw only partly."""
    calls = [e for e in events if e.get("kind") == "call"]
    used = sorted({base(e.get("title") or e.get("tool")) for e in calls})
    urls, searches, mails, screens = [], [], [], 0
    for e in calls:
        a, t = _args(e.get("detail") if "detail" in e else e.get("text")), base(e.get("title") or e.get("tool"))
        if a.get("url"):
            urls.append(a["url"])
        if t in ("web_search", "search", "browser_search") or "query" in a and t not in ("qmd_query",):
            searches.append(str(a.get("query") or a.get("q") or ""))
        if t.startswith("mail_read") and a.get("id"):
            mails.append(str(a["id"]))
        if t == "phone_look":
            screens += 1
    partial = [{"tool": e.get("title"), "t": e.get("t"), "why": (TRUNC.search(e.get("detail") or "") or [""])[0]}
               for e in events if e.get("kind") == "result" and TRUNC.search((e.get("detail") or "")[:20000])]  # cap: parse
    refused = [{"tool": e.get("title"), "t": e.get("t"), "why": (e.get("detail") or "")}
               for e in events if e.get("kind") in ("result", "error") and REFUSED.search((e.get("detail") or "")[:400])]  # cap: parse
    allowed = sorted(set((manifest or {}).get("tools") or []))
    return {"allowed_tools": allowed, "grants": (manifest or {}).get("grants", []), "used_tools": used,
            "skipped_tools": [t for t in allowed if base(t) not in used], "files": files_of(events),
            "urls": list(dict.fromkeys(urls))[:200], "searches": list(dict.fromkeys(s for s in searches if s))[:100],  # cap: list (the totals below count all)
            "urls_total": len(set(urls)), "searches_total": len({s for s in searches if s}), "partial_total": len(partial), "refused_total": len(refused),
            "mails_read": len(set(mails)), "phone_screens": screens, "partial": partial[:50], "refused": refused[:50]}  # cap: list (the totals above count all)


def _args_of(e):
    try:
        a = json.loads(e.get("detail") or "{}")
    except ValueError:
        return set()
    return {str(v) for v in (a.values() if isinstance(a, dict) else []) if isinstance(v, (str, int)) and len(str(v)) >= 6}


def unfollowed_cuts(events):
    """Results that were cut off (TRUNC) and not read on: no later call of the same tool shares an argument with the
    call that got the cut (the url, path or id), as fetch(url, start_index) or a second qmd_get would (FND-62)."""
    out = []
    for i, e in enumerate(events):
        if e.get("kind") != "result" or not TRUNC.search((e.get("detail") or "")[:20000]):  # cap: parse
            continue
        tool = base(e.get("title"))
        src = next((x for x in reversed(events[:i]) if x.get("kind") == "call" and base(x.get("title")) == tool), None)
        keys = _args_of(src) if src else set()
        if not any(x.get("kind") == "call" and base(x.get("title")) == tool and keys & _args_of(x) for x in events[i + 1:]):
            out.append(e)
    return out


def problems(events, finished=True, final_status=None):
    """The Problems panel, found without a second model: unknown tools, empty arguments, repeated identical calls,
    truncated reads behind a final answer, usage-limit stalls, tool errors, a run without a clean end."""
    out, seen = [], {}
    events = [e for e in events if not is_smoke(e)]          # the deploy's smoke test refusals are expected
    for e in events:
        k, d = e.get("kind"), e.get("detail") or ""
        if k in ("result", "error") and UNKNOWN.search(d[:500]):  # cap: parse
            out.append({"kind": "unknown-tool", "t": e.get("t"), "text": f"{e.get('title')}: the tool name was not known"})
        if k == "call":
            if empty_call(e):
                out.append({"kind": "empty-args", "t": e.get("t"), "text": f"{e.get('title')} was called without arguments"})
            elif d.strip() and not d.strip().startswith(("{", "[")) and base(e.get("title")) not in SHELL_TOOLS:
                out.append({"kind": "bad-args", "t": e.get("t"), "text": f"{e.get('title')}: arguments are not JSON"})
            key = (e.get("title"), d)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] == 3:
                out.append({"kind": "repeat", "t": e.get("t"), "text": f"{e.get('title')} called 3 times with the same arguments"})
        if k == "error":
            out.append({"kind": "tool-error", "t": e.get("t"), "text": f"{e.get('title')}: {cut(d, 2000)}"})  # cap: store
        if k == "llm" and e.get("status") == "failure" and LIMIT.search(d):
            out.append({"kind": "limit", "t": e.get("t"), "text": "a model call hit a usage limit"})
    trunc = unfollowed_cuts(events)
    if trunc and any(e.get("kind") == "say" for e in events[events.index(trunc[-1]):]):
        out.append({"kind": "partial-read", "t": trunc[-1].get("t"), "text": f"{len(trunc)} result{'s were' if len(trunc) > 1 else ' was'} cut off and not read on, and the answer came after: check it does not claim the whole source"})
    agentic = any(e.get("kind") == "call" for e in events)    # runs without an agent (briefings, scans) have no final answer
    if finished and (final_status not in ("ok", "failed", "done") or agentic and not any(e.get("kind") == "say" for e in events)):
        out.append({"kind": "no-end", "t": events[-1].get("t") if events else 0, "text": "the run has no clean end (no final answer)"})
    lim = [p for p in out if p["kind"] == "limit"]
    return [p for p in out if p["kind"] != "limit"] + lim[:1]


def skills_lifecycle(events):
    """Skills: AVAILABLE (listed to the agent) → LOADED (opened with skill_view) → USED (loaded and followed by
    other tool calls). Recommended/relied-on is not visible in the records."""
    avail, loaded = set(), []
    for i, e in enumerate(events):
        t = base(e.get("title") or e.get("tool"))
        if e.get("kind") == "result" and t == "skills_list":
            avail |= set(re.findall(r'"name"\s*:\s*"([\w.-]+)"', e.get("detail") or ""))
        if e.get("kind") == "call" and t == "skill_view":
            n = _args(e.get("detail")).get("name")
            if n:
                loaded.append((n, i))
    used = {n for n, i in loaded if any(x.get("kind") == "call" and base(x.get("title")) not in ("skill_view", "skills_list") for x in events[i + 1:i + 6])}
    names = {n for n, _ in loaded}
    return {"available": sorted(avail), "loaded": sorted(names), "used": sorted(used), "loaded_count": len(loaded)}


def stages_of(steps):
    """Stage events of a multi-stage run (deep research plan/steps, shopping stages) in one schema."""
    out = []
    for i, s in enumerate(steps or []):
        st = {"done": "COMPLETED", "ok": "COMPLETED", "failed": "FAILED", "skipped": "SKIPPED", "cached": "SKIPPED_CACHE_HIT",
              "partial": "DEGRADED", "running": "STARTED"}.get(str(s.get("status", "")).lower(), str(s.get("status", "")).upper() or "PLANNED")
        out.append({"stage": i + 1, "title": s.get("title", ""), "status": st, "input_chars": len(s.get("question") or ""),
                    "output_chars": len(s.get("finding") or ""), "note": (s.get("finding") or "")})
    return out

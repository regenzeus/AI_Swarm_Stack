"""ops/observe.py: files read vs changed, statistics, crew history, health, and the Atlas/ITCG panes."""
import json
import time

import observe as O


def call(tool, args, ts=0.0):
    return {"kind": "call", "title": tool, "detail": json.dumps(args), "ts": ts}


def test_files_read_and_changed_across_engines():
    ev = [call("read_file", {"path": "/work/ai-stack/ops/builds.py"}),
          call("Read", {"file_path": "/work/.claude-tasks/3/ai-stack/ops/deploy.py"}),
          call("mcp__serena__find_symbol", {"relative_path": "images/app.js"}),
          call("patch", {"patch": "*** Update File: ops/builds.py\n@@"}),
          call("Edit", {"file_path": "README.md"}),
          call("terminal", {"command": "sed -n '1,20p' ops/x.py; sed -i 's/a/b/' ops/y.py; grep -n '>>>>' app.js > /tmp/o.txt"})]
    f = {x["path"]: x for x in O.files_of(ev, diff_files=["docs/new.md"])}
    assert f["ops/builds.py"]["read"] == 1 and f["ops/builds.py"]["modified"] == 1
    assert f["ops/deploy.py"]["read"] == 1 and f["images/app.js"]["tools"] == ["find_symbol"]
    assert f["README.md"]["modified"] and f["ops/y.py"]["modified"] and f["ops/x.py"]["read"] and f["docs/new.md"]["tools"] == ["git diff"]
    assert not any("s/a/b" in p or ">>>>" in p for p in f)


def test_stats_pair_calls_with_results():
    ev = [call("web_search", {"q": "a"}, 1), {"kind": "result", "title": "web_search", "ts": 3},
          call("web_search", {"q": "b"}, 4), {"kind": "error", "title": "web_search", "ts": 10},
          {"kind": "llm", "ms": 1000, "tokens": {"in": 100, "cached": 50}}, {"kind": "llm", "ms": 3000, "tokens": {"in": 300, "cached": 0}}]
    s = O.stats_of(ev, 20)
    assert s["tools"][0] == {"tool": "web_search", "calls": 2, "errors": 1, "avg_s": 4.0, "max_s": 6}
    assert s["model"]["cache_pct"] == 12 and s["model"]["tokens_per_call"] == 200 and s["model"]["p95_ms"] == 3000


def test_health_flags_streaks_overdue_slow_and_limits():
    now = time.time()
    runs = [{"start": now - 100, "seconds": 30, "state": "failed", "error": "usage_limit_reached"},
            {"start": now - 86400, "seconds": 30, "state": "failed"}] + [{"start": now - 86400 * i, "seconds": 30, "state": "ok"} for i in range(2, 6)]
    j = O.judge("RAM", "mission", runs, now=now)
    kinds = {i["kind"] for i in j["issues"]}
    assert "failing" in kinds and "limit" in kinds and j["success_7d"] == 67
    old = [{"start": now - 10 * 86400, "seconds": 5, "state": "ok"}]
    assert "overdue" in {i["kind"] for i in O.judge("x", "crew", old, now=now, interval=86400)["issues"]}
    slow = [{"start": now, "seconds": 400, "state": "ok"}] + [{"start": now - 3600 * i, "seconds": 60, "state": "ok"} for i in range(1, 5)]
    assert "slow" in {i["kind"] for i in O.judge("y", "crew", slow, now=now)["issues"]}


def test_notify_sends_each_issue_once_and_a_flicker_is_not_a_new_issue(tmp_path, monkeypatch):
    items = [{"name": "RAM", "kind": "mission", "issues": [{"kind": "failing", "text": "failed 2 times"}]}]
    sent, t = [], [1_000_000.0]
    monkeypatch.setattr(O.time, "time", lambda: t[0])
    assert O.notify(items, tmp_path / "n.json", sent.append) == 1
    assert O.notify(items, tmp_path / "n.json", sent.append) == 0 and len(sent) == 1        # once a day
    t[0] += 60
    assert O.notify([{**items[0], "issues": []}], tmp_path / "n.json", sent.append) == 0    # a deploy hid it for one check
    t[0] += 60
    assert O.notify(items, tmp_path / "n.json", sent.append) == 0                           # back a minute later: no repeat
    t[0] += 120
    assert O.notify([{**items[0], "issues": []}], tmp_path / "n.json", sent.append) == 0
    t[0] += 7 * 3600
    assert O.notify([{**items[0], "issues": []}], tmp_path / "n.json", sent.append) == 0    # gone for 7 h: forgotten
    assert O.notify(items, tmp_path / "n.json", sent.append) == 1                           # a new occurrence: told again
    (tmp_path / "old.json").write_text(json.dumps({"mission:RAM:failing": t[0] - 60}))      # the file as it was before
    assert O.notify(items, tmp_path / "old.json", sent.append) == 0


def test_problems_what_it_touches_and_skills():
    ev = [{"kind": "result", "title": "skills_list", "detail": '[{"name": "grounded-citations"}, {"name": "x"}]', "t": 1},
          call("skill_view", {"name": "grounded-citations"}) | {"t": 2}, call("web_search", {"query": "ram"}) | {"t": 3},
          call("fetch", {"url": "https://a.example/p"}) | {"t": 4}, {"kind": "result", "title": "fetch", "detail": "text… content truncated", "t": 5},
          call("skill_view", {}) | {"t": 6}, {"kind": "error", "title": "made_up_tool", "detail": "Unknown tool: made_up_tool", "t": 7},
          {"kind": "say", "detail": "The whole page says X.", "t": 8}]
    probs = {p["kind"] for p in O.problems(ev, finished=True, final_status="ok")}
    assert {"empty-args", "unknown-tool", "tool-error", "partial-read"} <= probs and "no-end" not in probs
    assert "no-end" in {p["kind"] for p in O.problems(ev[:-1], finished=True, final_status="ok")}
    assert not O.problems([{"kind": "llm", "t": 1}], finished=True, final_status="ok")      # a scan or briefing without an agent
    d = O.ledger(ev, {"tools": ["web_search", "fetch", "mail_trash"], "grants": ["gmail:read"]})
    assert d["urls"] == ["https://a.example/p"] and d["searches"] == ["ram"] and d["skipped_tools"] == ["mail_trash"] and len(d["partial"]) == 1
    sk = O.skills_lifecycle(ev)
    assert sk["available"] == ["grounded-citations", "x"] and sk["loaded"] == ["grounded-citations"] and sk["used"] == ["grounded-citations"]
    refused = [{"kind": "result", "title": "mail_trash", "detail": "Refused: no grant for gmail:trash", "t": 9}]
    assert O.ledger(refused)["refused"][0]["tool"] == "mail_trash"


def test_manifest_diff_names_what_changed():
    a = {"config": {"stack": "1", "ops/keys.sh": "aa"}, "sessions": [{"agent": "mission", "prompt_hash": "p1", "tools_hash": "t1", "model": "m"}], "grants": []}
    b = {"config": {"stack": "2", "ops/keys.sh": "bb"}, "sessions": [{"agent": "mission", "prompt_hash": "p2", "tools_hash": "t1", "model": "m"}], "grants": ["gmail:read"]}
    assert O.manifest_diff(b, a) == ["ops/keys.sh changed", "mission: system prompt changed", "grants changed"]
    assert O.manifest_diff(b, None) == []


def test_stages_use_one_schema():
    st = O.stages_of([{"title": "Plan", "status": "done", "question": "q", "finding": "f" * 10}, {"title": "x", "status": "failed"}])
    assert [s["status"] for s in st] == ["COMPLETED", "FAILED"] and st[0]["output_chars"] == 10


def test_the_deploy_smoke_test_refusals_are_expected_not_problems():
    smoke = [{"kind": "llm", "title": "gpt-sub", "key": "vk-smoke", "status": "failure", "detail": "403 key not allowed"},
             {"kind": "error", "title": "", "status": "failure", "detail": "Invalid model name passed in model=smoke. This model is not available for this API key"},
             {"kind": "llm", "title": "smoke", "status": "failure"}]
    real = {"kind": "error", "title": "web_search", "status": "failure", "detail": "boom"}
    assert all(O.is_smoke(e) for e in smoke) and not O.is_smoke(real)
    assert O.problems(smoke, finished=False) == []
    assert O.label_smoke(smoke[1])["title"] == "smoke test (expected)" and O.label_smoke(smoke[1])["status"] == "expected"

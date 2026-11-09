"""ops/telemetry.py: the run timeline merges the gateway's calls and Hermes' records, with honest warnings."""
import types


def test_timeline_merges_sources_and_warns(runner, monkeypatch):
    import telemetry as T
    import missions as M
    T.M = M
    t0 = 1_800_000_000.0
    gw = [{"ts": t0 + 1, "agent": "mission", "kind": "llm", "title": "gpt-sub", "ms": 900, "status": "success",
           "tokens": {"in": 60000, "out": 300, "cached": 0, "reasoning": 12}},
          {"ts": t0 + 3, "agent": "scout", "kind": "mcp", "title": "fetch · fetch", "ms": 800, "status": "failure", "detail": "403"}]
    hm = [{"ts": t0 + 2, "agent": "mission", "kind": "call", "title": "web_search", "detail": '{"q": "ram"}'} for _ in range(3)] + \
         [{"ts": t0 + 2.5, "agent": "mission", "kind": "result", "title": "web_search", "detail": "ok"}]
    monkeypatch.setattr(T, "gateway_events", lambda keys, s, e: gw)
    monkeypatch.setattr(T, "hermes_events", lambda s, e: hm)
    run = {"id": 7, "started": "2027-01-15T08:00:00+00:00", "ended": "2027-01-15T08:01:00+00:00"}
    monkeypatch.setattr(T.dt, "datetime", types.SimpleNamespace(fromisoformat=lambda v: types.SimpleNamespace(timestamp=lambda: t0 if v.endswith("00:00:00+00:00") or "08:00:00" in v else t0 + 60)))
    tl = T.build(run, "vk-mission")
    assert [e["kind"] for e in tl["events"]] == ["llm", "call", "call", "call", "result", "mcp"]       # in time order
    s = tl["stats"]
    assert (s["llm_calls"], s["tool_calls"], s["mcp_calls"], s["errors"]) == (1, 3, 1, 1)
    assert s["tokens"] == {"in": 60000, "out": 300, "cached": 0, "reasoning": 12}
    assert any("same arguments" in w for w in tl["warnings"]) and any("caching" in w for w in tl["warnings"])
    assert tl["events"][0]["t"] == 1.0

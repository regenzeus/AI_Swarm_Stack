"""Agent health (owner's rules, 28 Oct 2026): one item per agent, sessions and scout runs roll up into the agent that
started them, alerts only for what needs a human, a good next run clears an issue, Acknowledge hides it until it
happens again, and the open issues are readable for the health doctor (API + MCP)."""
import time
import types

import pytest


@pytest.fixture
def RT(tmp_path, monkeypatch):
    import runrecord as RT
    monkeypatch.setattr(RT, "DB", tmp_path / "runtime.db")
    monkeypatch.setattr(RT, "_db", None)
    return RT


def ev(run, kind, ts, **kw):
    return {"run": run, "kind": kind, "ts": ts, "agent": kw.pop("agent", "mission"), **kw}


def test_sessions_and_scouts_roll_up_and_a_good_run_clears(RT):
    t = time.time() - 3000
    RT.ingest([ev("mission-run:1", "run", t, agent="mission:ram"), ev("hermes:mission:a", "run", t + 1, ref="mission-run:1"),
               ev("hermes:scout:b", "run", t + 2, agent="scout", ref="hermes:mission:a"),
               ev("hermes:scout:b", "end", t + 3, agent="scout", status="failed"),
               ev("hermes:mission:a", "end", t + 4), ev("mission-run:1", "end", t + 5, agent="mission:ram"),
               ev("hermes:main:s1", "run", t, agent="main", ref="chat:abc"), ev("hermes:main:s1", "end", t + 6, agent="main", status="stalled")])
    got = {a["agent"]: [i["kind"] for i in a["issues"]] for a in RT.agent_issues()}
    assert got == {"mission:ram": ["failed"], "main": ["stalled"]}          # the scout's failure counts for the mission
    RT.ingest([ev("hermes:main:s2", "run", t + 10, agent="main", ref="chat:abc"), ev("hermes:main:s2", "end", t + 11, agent="main")])
    assert {a["agent"] for a in RT.agent_issues()} == {"mission:ram"}        # the next clean chat turn clears the stalled one


@pytest.fixture
def C(tmp_path, monkeypatch):
    import crew
    events, sent = [], []
    crew.M = types.SimpleNamespace(event=lambda *a, **k: events.append(a), log=lambda *a: None, _queue_cache=[],
                                   X=types.SimpleNamespace(telegram=lambda text, *a: sent.append(text), APP="https://x"))
    monkeypatch.setattr(crew, "OUT", tmp_path)
    monkeypatch.setattr(crew, "ACK", tmp_path / "health-ack.json")
    monkeypatch.setattr(crew, "refresh_history", lambda c: None)
    monkeypatch.setattr(crew, "status", lambda: [])
    monkeypatch.setattr(crew, "recovery_alarms", lambda items: [])         # not this machine's swap or images
    monkeypatch.setattr(crew, "_health", {"t": 0, "data": {}})
    probs = [{"agent": "main", "root": "hermes:main:s1", "issues": [{"kind": "stalled", "text": "stopped answering", "run": "hermes:main:s1", "at": 100}]},
             {"agent": "scout", "root": "hermes:scout:x", "issues": [{"kind": "tool-error", "text": "tool error", "run": "hermes:scout:x", "at": 90}]},
             {"agent": "mission:old", "root": "mission-run:3", "issues": [{"kind": "partial-read", "text": "partial read", "run": "mission-run:3", "at": 80}]}]
    import runtime
    monkeypatch.setattr(runtime, "problems", lambda hours=24, by="": probs)
    crew.sent, crew.events = sent, events
    return crew


def test_engines_get_one_item_and_only_alerts_are_sent(C):
    d = C.health(None, [])
    items = {i["name"]: i for i in d["items"]}
    assert set(items) == {"Hermes (chat)", "Research (scout)"}             # an archived mission's leftovers tell nobody
    assert items["Hermes (chat)"]["issues"][0]["severity"] == "alert" and items["Research (scout)"]["issues"][0]["severity"] == "note"
    assert len(C.sent) == 1 and "stopped answering" in C.sent[0] and "tool error" not in C.sent[0]
    assert d["alerts"] == 1 and d["issues"] == 2


def test_acknowledge_hides_until_it_happens_again(C, monkeypatch):
    C.health(None, [])
    key = C._health["data"]["items"][0]["issues"][0]["key"]
    assert C.handle({"action": "health_ack", "keys": [key]}, None) == {"acknowledged": 1}
    assert "Acknowledged 1" in C.events[-1][2]                              # logged in the activity feed
    d = C.health(None, [])
    chat = next(i for i in d["items"] if i["name"] == "Hermes (chat)")
    assert chat["issues"] == [] and chat["acked"][0]["key"] == key
    import runtime
    newer = [{"agent": "main", "root": "hermes:main:s9", "issues": [{"kind": "stalled", "text": "again", "run": "hermes:main:s9", "at": 200}]}]
    monkeypatch.setattr(runtime, "problems", lambda hours=24, by="": newer)
    C._health["t"] = 0
    assert next(i for i in C.health(None, [])["items"] if i["name"] == "Hermes (chat)")["issues"][0]["text"] == "again"


def test_the_health_doctor_can_read_open_issues(monkeypatch):
    import asyncio
    import server
    from starlette.testclient import TestClient
    st = {"health": {"items": [{"name": "RAM upgrade", "kind": "mission", "slug": "ram", "issues": [
        {"kind": "failing", "text": "failed 3 times in a row", "severity": "alert", "at": 5, "key": "mission:ram:failing", "run": "mission-run:9"}]}]}}
    monkeypatch.setattr(server, "state", lambda: st)
    x = TestClient(server.app).get("/api/health/issues", headers={"Tailscale-User-Login": "owner@test"}).json()
    assert x == [{"agent": "RAM upgrade", "agent_kind": "mission", "agent_id": "ram", "issue": "failing", "severity": "alert",
                  "text": "failed 3 times in a row", "since": 5, "run": "mission-run:9", "run_view": "#/live/mission-run:9",
                  "agent_page": "#/mission/ram", "key": "mission:ram:failing"}]
    assert "failed 3 times in a row" in asyncio.run(server.health_issues_tool()) and "health_issues" in server.ACTIONS | {"health_issues"}
    assert "health_ack" in server.ACTIONS


def test_a_kind_of_issue_clears_with_the_next_run_without_it_whatever_notes_it_has(RT):
    t = time.time() - 3000                                     # FND-64: a stall stayed open behind a note on every later run
    RT.ingest([ev("claude:task:1", "run", t, agent="claude-task"), ev("claude:task:1", "end", t + 1, agent="claude-task", status="stalled")])
    RT.ingest([ev("claude:task:2", "run", t + 10, agent="claude-task"), ev("claude:task:2", "end", t + 11, agent="claude-task", status="failed")])
    assert sorted(i["kind"] for a in RT.agent_issues() for i in a["issues"]) == ["failed"]      # the stall is over, the failure is new
    RT.ingest([ev("claude:task:3", "run", t + 20, agent="claude-task"), ev("claude:task:3", "end", t + 21, agent="claude-task")])
    assert RT.agent_issues() == []

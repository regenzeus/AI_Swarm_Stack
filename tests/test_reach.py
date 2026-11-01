"""Reach (TSK-33, TSK-19): the calendar as an event source (an ICS file read only, its repeats, a rule firing a set time
before or after an event, once) and outside agents over A2A (off until switched on, on the tailnet with their own token,
each task waiting for the owner's OK, each agent seeing only its own tasks)."""
import datetime as dt
import hashlib
import json
import sqlite3
import types
from zoneinfo import ZoneInfo

import pytest
from starlette.testclient import TestClient

import a2a as A2
import events as EV
import ics

BERLIN = ZoneInfo("Europe/Berlin")
ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:standup@x
SUMMARY:Standup with Anna
LOCATION:Room 2
DTSTART;TZID=Europe/Berlin:20261102T090000
DTEND;TZID=Europe/Berlin:20261102T091500
RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=6
EXDATE;TZID=Europe/Berlin:20261104T090000
END:VEVENT
BEGIN:VEVENT
UID:standup@x
RECURRENCE-ID;TZID=Europe/Berlin:20261109T090000
SUMMARY:Standup with Anna (moved)
DTSTART;TZID=Europe/Berlin:20261109T110000
DTEND;TZID=Europe/Berlin:20261109T111500
END:VEVENT
BEGIN:VEVENT
UID:dentist@x
SUMMARY:Dentist\\, Dr. Weber
DTSTART:20261103T130000Z
DURATION:PT45M
END:VEVENT
BEGIN:VEVENT
UID:holiday@x
SUMMARY:All Saints
DTSTART;VALUE=DATE:20261101
DTEND;VALUE=DATE:20261102
END:VEVENT
END:VCALENDAR
"""


def test_a_calendar_s_events_and_repeats_are_read_with_their_zones_moves_and_exclusions():
    evs = ics.parse(ICS, local=BERLIN)
    occ = ics.occurrences(evs, dt.datetime(2026, 11, 1, tzinfo=BERLIN), dt.datetime(2026, 11, 20, tzinfo=BERLIN))
    got = [(o["summary"], o["start"].astimezone(BERLIN).strftime("%a %d %H:%M"), o["end"].astimezone(BERLIN).strftime("%H:%M")) for o in occ]
    assert got == [("All Saints", "Sun 01 00:00", "00:00"), ("Standup with Anna", "Mon 02 09:00", "09:15"), ("Dentist, Dr. Weber", "Tue 03 14:00", "14:45"),
                   ("Standup with Anna (moved)", "Mon 09 11:00", "11:15"), ("Standup with Anna", "Wed 11 09:00", "09:15"),
                   ("Standup with Anna", "Mon 16 09:00", "09:15"), ("Standup with Anna", "Wed 18 09:00", "09:15")]   # Wed 4 excluded; 6 in all with the moved one
    assert [o["start"] for o in ics.occurrences([{**evs[0], "rrule": {"FREQ": "HOURLY"}}], dt.datetime(2026, 11, 1, tzinfo=BERLIN),
                                                dt.datetime(2026, 12, 1, tzinfo=BERLIN))] == [evs[0]["start"]]   # a rule it does not read: once, no guess


@pytest.fixture
def B(tmp_path, monkeypatch):
    c = sqlite3.connect(tmp_path / "m.sqlite")
    c.row_factory = sqlite3.Row
    created = []
    EV.M = types.SimpleNamespace(log=print, event=lambda *a, **k: None, valid_schedule=lambda s: True)
    monkeypatch.setattr(EV, "CAL_FILE", tmp_path / "private/calendar.json")
    EV._cal.update(t=0, events=[], error=None)
    EV.table(c)
    return types.SimpleNamespace(c=c, created=created, tmp=tmp_path,
                                 create=lambda req, cc: created.append(req["text"]) or {"task": len(created)})


def test_a_calendar_rule_fires_once_its_time_before_the_event_and_the_address_stays_private(B):
    with pytest.raises(ValueError, match="minutes before its start"):
        EV.save_rule(B.c, {"when": "calendar", "name": "Brief me", "param": "an hour before", "task": "Brief me on {title}"})
    rid = EV.save_rule(B.c, {"when": "calendar", "name": "Brief me before meetings", "param": "60 before", "words": "Anna",
                             "task": "Brief me on {title}: {detail}"})
    EV.calendar(B.c, t=dt.datetime(2026, 11, 2, 8, 0, tzinfo=BERLIN), fetch=lambda: ICS, create=B.create)
    assert EV._status["calendar"]["off"].startswith("no calendar address") and not B.created
    with pytest.raises(ValueError, match="secret address"):
        EV.handle({"action": "calendar_set", "url": "http://insecure.example/cal.ics"}, B.c)
    assert EV.handle({"action": "calendar_set", "url": "https://calendar.example/private-abc123/basic.ics"}, B.c) == {"calendar": "calendar.example"}
    assert oct(EV.CAL_FILE.stat().st_mode)[-3:] == "600" and EV.state(B.c)["bus"]["calendar"] == "calendar.example"
    for minute in (0, 5):                                                          # 8:00 is 60 min before the 9:00 standup; 8:05 too, once
        EV.calendar(B.c, t=dt.datetime(2026, 11, 2, 8, minute, tzinfo=BERLIN), fetch=lambda: ICS, create=B.create)
    assert B.created == ["Brief me on Standup with Anna: Mon 02 Nov 09:00–09:15 · Room 2"]
    EV.calendar(B.c, t=dt.datetime(2026, 11, 3, 13, 0, tzinfo=BERLIN), fetch=lambda: ICS, create=B.create)
    assert len(B.created) == 1                                                     # the dentist has no "Anna": the rule's words
    EV.handle({"action": "calendar_clear"}, B.c)
    assert not EV.CAL_FILE.exists() and EV.state(B.c)["bus"]["calendar"] is None


@pytest.fixture
def A(tmp_path, monkeypatch):
    import server as S
    m = tmp_path / "missions"
    for d in ("inbox", "public/results", "app"):
        (m / d).mkdir(parents=True)
    (tmp_path / "vault/tasks").mkdir(parents=True)
    (tmp_path / "vault/tasks/5-x.md").write_text("The answer: 3.15.2")
    tasks = [{"id": 5, "title": "Python", "status": "done", "source": "a2a:laptop", "result": "tasks/5-x.md", "created": "2026-11-01T10:00:00+01:00", "updated": "x"},
             {"id": 6, "title": "Other", "status": "waiting_approval", "source": "a2a:other", "created": "2026-11-01T10:00:00+01:00", "updated": "x"},
             {"id": 7, "title": "Mine", "status": "waiting_approval", "source": "a2a:laptop", "created": "2026-11-01T10:00:00+01:00", "updated": "x"}]
    (m / "public/state.json").write_text(json.dumps({"missions": [], "tasks": tasks}))
    for k, v in {"STATE": m / "public/state.json", "INBOX": m / "inbox", "RESULTS": m / "public/results", "DATA": m / "app", "VAULT": tmp_path / "vault"}.items():
        monkeypatch.setattr(S, k, v)
    sent = []

    async def submit(req, wait=8.0):
        sent.append(req)
        return {"ok": True, "result": {"task": 9} if req["action"] == "task_create" else {"name": req.get("name")}}
    monkeypatch.setattr(S, "submit", submit)

    def conf(on, agents):
        (m / "app/a2a.json").write_text(json.dumps({"enabled": on, "agents": {n: {"hash": hashlib.sha256(t.encode()).hexdigest()} for n, t in agents.items()}}))
    return types.SimpleNamespace(S=S, c=TestClient(S.app), sent=sent, conf=conf)


TAIL = {"Tailscale-User-Login": "owner@test"}


def rpc(A, method, params, token="tok-laptop", headers=TAIL):
    return A.c.post("/a2a", headers={**headers, **({"Authorization": f"Bearer {token}"} if token else {})},
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def test_outside_agents_are_off_until_switched_on_and_then_need_the_tailnet_and_their_token(A):
    A.conf(False, {"laptop": "tok-laptop"})
    assert A.c.get("/.well-known/agent-card.json", headers=TAIL).status_code == 404 and rpc(A, "message/send", {}).status_code == 404
    A.conf(True, {"laptop": "tok-laptop"})
    card = A.c.get("/.well-known/agent-card.json", headers=TAIL).json()
    assert card["url"].endswith("/a2a") and card["securitySchemes"]["bearer"]["scheme"] == "bearer"
    assert A.c.get("/.well-known/agent-card.json").status_code == 404                  # not from outside the tailnet
    assert rpc(A, "message/send", {}, headers={}).status_code == 403
    assert rpc(A, "message/send", {}, token=None).status_code == 401 and rpc(A, "message/send", {}, token="wrong").status_code == 401


def test_an_outside_agent_s_message_is_a_task_that_waits_for_the_owner_and_it_sees_only_its_own(A):
    A.conf(True, {"laptop": "tok-laptop"})
    r = rpc(A, "message/send", {"message": {"role": "user", "parts": [{"kind": "text", "text": "Find the newest Python release and its date"}]}}).json()
    assert r["result"]["id"] == "task-9" and r["result"]["status"]["state"] == "submitted"
    assert A.sent[-1] == {"action": "task_create", "text": "Find the newest Python release and its date", "autonomy": "ask", "source": "a2a:laptop"}
    done = rpc(A, "tasks/get", {"id": "task-5"}).json()["result"]
    assert done["status"]["state"] == "completed" and done["artifacts"][0]["parts"][0]["text"] == "The answer: 3.15.2"
    assert rpc(A, "tasks/get", {"id": "task-7"}).json()["result"]["status"]["state"] == "input-required"   # waits for the owner's OK
    assert rpc(A, "tasks/get", {"id": "task-6"}).json()["error"]["code"] == -32001                       # another agent's task
    assert rpc(A, "tasks/cancel", {"id": "task-7"}).json()["result"]["status"]["state"] == "canceled"
    assert rpc(A, "nope", {}).json()["error"]["code"] == -32601


def test_the_owner_adds_and_revokes_an_outside_agent_and_only_a_hash_is_kept(A, tmp_path):
    r = A.c.post("/api/a2a/token", headers=TAIL, json={"name": "laptop"}).json()
    assert r["ok"] and len(r["token"]) > 30 and A.sent[-1]["hash"] == hashlib.sha256(r["token"].encode()).hexdigest() and r["token"] not in json.dumps(A.sent)
    assert A.c.post("/api/request", headers=TAIL, json={"action": "a2a_token", "name": "x", "hash": "0" * 64}).status_code == 403
    A2.M = types.SimpleNamespace(HOME=tmp_path, event=lambda *a, **k: None)
    (tmp_path / "app").mkdir()
    assert A2.handle({"action": "a2a_token", "name": "laptop", "hash": "a" * 64}) == {"name": "laptop"}
    assert A2.state()["a2a"] == {"enabled": False, "agents": [{"name": "laptop", "created": A2.load()["agents"]["laptop"]["created"]}]}
    assert oct((tmp_path / "app/a2a.json").stat().st_mode)[-3:] == "600"
    A2.handle({"action": "a2a_settings", "on": True})
    A2.handle({"action": "a2a_revoke", "name": "laptop"})
    assert A2.load() == {"enabled": True, "agents": {}}
    with pytest.raises(ValueError):
        A2.handle({"action": "a2a_token", "name": "Bad Name!", "hash": "a" * 64})


def test_the_owner_s_calendar_and_a2a_switches_are_refused_from_the_ai_phone(A):
    for action in ("wiki_delete", "calendar_set", "calendar_clear", "a2a_settings", "a2a_revoke"):
        r = A.c.post("/api/request", headers={**TAIL, "X-Forwarded-For": A.S.AI_PHONE_IP}, json={"action": action})
        assert r.status_code == 403, action
    assert A.c.post("/api/a2a/token", headers={**TAIL, "X-Forwarded-For": A.S.AI_PHONE_IP}, json={"name": "x1"}).status_code == 403

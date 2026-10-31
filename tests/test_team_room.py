"""The team room (SWM-107): the Chatroom is one timeline of what the agents do together, drawn from their work (the
Ledger's events, the Board's messages, tool calls between agents and runs no one asked for), never a place an agent
has to post; a step into another agent's lane is marked as help."""
import re
from pathlib import Path

import teamroom as TR
from ledger import Ledger

ROOT = Path(__file__).resolve().parent.parent
SWARM_JS = (ROOT / "images/mission-control/web/static/swarm.js").read_text()
DOC, SCOUT, OWNER, SYSTEM = {"id": "doctor", "cls": "agent"}, {"id": "scout", "cls": "agent"}, {"id": "owner:owner", "cls": "owner"}, {"id": "system", "cls": "system"}


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        self.t += 1
        return self.t


def test_lines_mark_help_in_another_agent_s_lane_and_keep_every_text_whole():
    long = "why " * 2000
    feed = {"events": [
        {"seq": 1, "artifact_id": 7, "actor": "doctor", "cls": "agent", "kind": "create", "payload": {}, "reason": "", "ts": 10, "akind": "idea", "title": "Fix it", "owner": "doctor"},
        {"seq": 2, "artifact_id": 7, "actor": "scout", "cls": "agent", "kind": "evidence", "payload": {"text": long}, "reason": "", "ts": 11, "akind": "idea", "title": "Fix it", "owner": "doctor"},
        {"seq": 3, "artifact_id": 7, "actor": "owner:the owner (chat)", "cls": "owner", "kind": "transition", "payload": {"to": "active"}, "reason": "Build it", "ts": 12, "akind": "idea", "title": "Fix it", "owner": "doctor"},
        {"seq": 4, "artifact_id": 7, "actor": "system", "cls": "system", "kind": "ref", "payload": {"system": "build", "ref": "9"}, "reason": "", "ts": 13, "akind": "idea", "title": "Fix it", "owner": "doctor"},
        {"seq": 5, "artifact_id": 7, "actor": "checker", "cls": "checker", "kind": "transition", "payload": {"to": "done"}, "reason": "CI green", "ts": 14, "akind": "idea", "title": "Fix it", "owner": "doctor"},
        {"seq": 6, "artifact_id": None, "actor": "doctor", "cls": "agent", "kind": "message", "payload": {}, "reason": "", "ts": 15, "akind": None, "title": None, "owner": None}],
        "messages": [{"sender": "doctor", "sender_cls": "agent", "recipients": '["scout"]', "context": "dm:doctor+scout", "act": "request", "text": "How is YAML quoted?", "ts": 15, "state": "completed", "state_reason": "answered"},
                     {"sender": "owner:owner", "sender_cls": "owner", "recipients": '["doctor"]', "context": "dm:doctor+owner", "act": "inform", "text": "Thanks", "ts": 16}]}
    asks = [{"run": "r1", "from": "mission", "to": "scout", "ts": 9, "ended": 9.5, "state": "done", "ask": "Find the price", "answer": long}]
    runs = [{"run": "r2", "lane": "checker", "name": "Crew · Checker", "started": 8, "ended": 8.2, "state": "done", "by": None},
            {"run": "r1", "lane": "scout", "started": 9, "ended": 9.5, "state": "done", "by": "mission"},          # an ask, not status
            {"run": "r3", "lane": "doctor", "started": 17, "ended": None, "state": "running", "by": None}]       # still running
    out = TR.lines(feed, asks, runs)
    assert [x["ts"] for x in out] == sorted(x["ts"] for x in out)
    by = {(x["type"], x["actor"]): x for x in out}
    assert by[("work", "doctor")]["verb"] == "proposed idea #7"
    help = by[("help", "scout")]
    assert help["target"] == "doctor" and help["verb"] == "added evidence to doctor's idea #7" and help["text"] == long   # whole
    assert by[("you", "you")]["verb"] in ("approved idea #7", "tells")
    assert any(x["type"] == "you" and x["verb"] == "approved idea #7" and x["text"] == "Build it" for x in out)
    assert by[("status", "stack")]["verb"] == "linked build 9 to idea #7"
    assert by[("work", "checker")]["verb"] == "proved idea #7"
    talk = by[("talk", "doctor")]
    assert talk["verb"] == "asks" and talk["target"] == "scout" and talk["ref"]["context"] == "dm:doctor+scout" and talk["state"] == "completed"
    ask = by[("ask", "mission")]
    assert ask["target"] == "scout" and ask["text"] == "Find the price" and ask["detail"] == long and ask["ref"] == {"run": "r1"}
    assert [x["actor"] for x in out if x["type"] == "status"] == ["checker", "stack"]   # only the run no one asked for, once it ended
    assert sum(1 for x in out if x["type"] == "talk") == 1                              # the event of a message is not shown twice


def test_the_ledger_feed_has_events_and_messages_but_not_the_requirements_mirror(tmp_path):
    L = Ledger(str(tmp_path / "swarm.db"), [{"id": "doctor", "tools": []}, {"id": "scout", "tools": ["fetch"]}], now=Clock())
    aid = L.upsert(DOC, "i1", "idea", "detector:x", "The detector fires on pagination", "It flags pages the agent followed.")["id"]
    L.add_evidence(SCOUT, "e1", aid, "page 2 was followed in run 12", ref="run:12")
    L.upsert(SYSTEM, "r1", "requirement", "req:TST-01", "Tests run in the builder", "mirror")
    L.send(DOC, "m1", ["room:all"], "inform", "Did you follow page 2?", artifact_id=aid)          # #all: news about an idea
    f = L.feed(0)
    assert all(e["akind"] != "requirement" for e in f["events"]) and {e["kind"] for e in f["events"]} >= {"create", "evidence"}
    ev = next(e for e in f["events"] if e["kind"] == "evidence")
    assert ev["actor"] == "scout" and ev["owner"] == "doctor" and ev["payload"]["text"] == "page 2 was followed in run 12"
    assert [m["text"] for m in f["messages"]] == ["Did you follow page 2?"]
    line = next(x for x in TR.lines(f, [], []) if x["actor"] == "scout")
    assert line["type"] == "help" and line["target"] == "doctor"
    assert L.feed(10 ** 10) == {"events": [], "messages": []}


def test_the_chatroom_is_the_team_room_with_its_filters():
    server = (ROOT / "images/mission-control/server.py").read_text()
    assert 'Route("/api/swarm/room", api_swarm_room)' in server and '"feed"' in server.split("SWARM_READ =")[1].split("}")[0]
    assert '"feed"' in (ROOT / "images/swarm/swarm.py").read_text().split("APP_OPS =")[1].split("}")[0]
    assert "teamroom.py" in (ROOT / "images/mission-control/Dockerfile").read_text()
    room = SWARM_JS[SWARM_JS.index("// ---------- the Chatroom: the team room"):SWARM_JS.index("// ---------- who works on what")]
    assert '[["ask", "Asks"], ["help", "Helps"], ["talk", "Talk"], ["work", "Work"], ["you", "You"], ["status", "Status"]]' in room
    assert 'types: new Set(["ask", "help", "talk", "work", "you"])' in room                 # Status (routine runs) off at first
    assert "inv.filter((a) => f.agents.has(a)).length < 2" in room                          # two agents: only what passes between them
    assert "data-rtop" in room and "data-rh" in room and 'id="rq"' in room                  # topic, time, text
    assert "g.length < 3" in room and "times</span>" in room                                # a burst of asks folds into one line
    assert "no messages yet" not in room and "/api/swarm/room?hours=" in room                # no list of empty rooms
    assert re.search(r'helps \$\{esc\(swName\(l\.target\)\)\}', room)                       # help names whose lane it is

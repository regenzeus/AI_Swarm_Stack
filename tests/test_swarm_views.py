"""The swarm as it works, on the Swarm page (requirements SWM-103 to SWM-106): a timeline of every agent's runs, the map of
who starts and messages whom, the tool calls between agents as conversations in the Chatroom, and the team map."""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SWARM_JS = (ROOT / "images/mission-control/web/static/swarm.js").read_text()
QUESTION = ("Recheck Domadoo Home Assistant Voice Preview Edition restock wording: is 20 November 2026 or December shown? Also "
            "SmartDomo and ThePiHut genuine Voice Preview Edition Germany availability, total, sell state, and whether any "
            "listing is a reseller bundle rather than the genuine product sold by Nabu Casa partners in Germany.")      # over 200 characters
ANSWER = "Domadoo shows “Restocking” and €59.00; no date. " * 40                                                         # a long answer


@pytest.fixture
def RR(tmp_path, monkeypatch):
    import runrecord as R
    monkeypatch.setattr(R, "DB", tmp_path / "rt.db", raising=False)
    monkeypatch.setattr(R, "_db", None, raising=False)
    t = 1.9e9
    R.ingest([
        {"run": "mission-run:7", "agent": "mission:voice-speaker", "kind": "start", "run_title": "Mission · voice speaker", "ts": t},
        {"run": "hermes:mission:a", "agent": "mission", "ref": "mission-run:7", "kind": "run", "ts": t + 5},
        {"run": "hermes:mission:a", "agent": "mission", "kind": "llm", "title": "gpt-sub", "tokens": {"in": 1000, "out": 200}, "ts": t + 6},
        {"run": "hermes:mission:a", "agent": "mission", "kind": "call", "title": "mcp__vault__research_research",
         "detail": json.dumps({"question": QUESTION}), "ts": t + 9},
        {"run": "hermes:scout:b", "agent": "scout", "ref": "hermes:mission:a", "run_title": QUESTION[:150], "kind": "run", "ts": t + 10},
        {"run": "hermes:scout:b", "agent": "scout", "kind": "say", "title": "Says", "detail": ANSWER, "ts": t + 70},
        {"run": "hermes:scout:b", "agent": "scout", "kind": "end", "status": "done", "ts": t + 71},
        {"run": "hermes:scout:c", "agent": "scout", "ref": "hermes:mission:a", "run_title": "Second question", "kind": "run", "ts": t + 80},
        {"run": "crew:doctor:1", "agent": "crew:doctor", "kind": "start", "run_title": "Crew · Health doctor", "ts": t + 100},
        {"run": "claude:claude-task:x", "agent": "claude-task", "ref": "crew:doctor:1", "run_title": "You are the Health doctor", "kind": "run", "ts": t + 110},
        {"run": "claude:claude-task:x", "agent": "claude-task", "kind": "end", "status": "failed", "ts": t + 200},
        {"run": "claude-task:23", "agent": "claude-task", "ref": "crew:doctor", "kind": "run", "run_title": "Claude task #23: You are the Health doctor",
         "detail": "You are the Health doctor. " + QUESTION, "ts": t + 210},                    # a queued task: who asked, the whole question
        {"run": "claude:claude-task:y", "agent": "claude-task", "ref": "claude-task:23", "kind": "run", "ts": t + 211},
        {"run": "claude:claude-task:y", "agent": "claude-task", "kind": "say", "title": "Says", "detail": '{"diagnoses": []}', "ts": t + 250},
        {"run": "claude:claude-task:y", "agent": "claude-task", "kind": "end", "status": "done", "ts": t + 251},
        {"run": "claude-task:23", "agent": "claude-task", "kind": "end", "status": "done", "ts": t + 252},
        {"run": "hermes:main:c1", "agent": "main", "ref": "chat:c1", "run_title": "Can you research this product?", "kind": "run", "ts": t + 300},
        {"run": "hermes:main:c1", "agent": "main", "kind": "end", "status": "done", "ts": t + 330},
    ])
    R.NOW = t + 400
    return R


def test_runs_are_drawn_in_the_lane_of_their_swarm_agent():
    import runrecord as R
    assert [R.lane_of(a) for a in ("crew:doctor", "mission:ram-upgrade", "mission", "claude-coach", "claude-eval-doctor", "claude-task",
                                   "claude-review", "ai-phone", "mail", "scout", None)] == \
        ["doctor", "mission", "mission", "coach", "evals", "claude", "reviewers", "phone", "gmail", "scout", "?"]


def test_the_timeline_has_every_run_with_its_lane_its_end_and_what_started_it(RR):
    t = RR.timeline(24, now=RR.NOW)
    by = {r["run"]: r for r in t["runs"]}
    assert len(by) == 9 and t["now"] - t["since"] == 24 * 3600
    assert by["claude-task:23"]["by"] == "doctor" and by["claude:claude-task:y"]["by"] == "claude"     # the doctor queued it
    assert by["hermes:scout:b"]["lane"] == "scout" and by["hermes:scout:b"]["by"] == "mission" and by["hermes:scout:b"]["parent"] == "hermes:mission:a"
    assert by["hermes:scout:b"]["state"] == "done" and by["hermes:scout:c"]["state"] == "running"
    assert by["claude:claude-task:x"]["by"] == "doctor" and by["claude:claude-task:x"]["state"] == "failed"
    assert by["hermes:main:c1"]["by"] == "you"                                                  # a chat of yours started it
    assert by["hermes:mission:a"]["calls"] == 1 and by["hermes:mission:a"]["tokens"] == 1200
    assert RR.timeline(24, now=RR.NOW + 3 * 86400)["runs"] == [r for r in RR.timeline(24, now=RR.NOW + 3 * 86400)["runs"] if r["state"] == "running"]


def test_the_map_counts_who_starts_whom_and_shows_what_runs_now(RR):
    it = RR.interactions(168, now=RR.NOW)
    edges = {(e["from"], e["to"]): e for e in it["edges"]}
    assert set(edges) == {("mission", "scout"), ("doctor", "claude"), ("you", "main")}           # a mission's own Hermes run is no line
    assert edges[("mission", "scout")]["n"] == 2 and edges[("mission", "scout")]["live"] == 1 and edges[("doctor", "claude")]["n"] == 2
    nodes = {n["id"]: n for n in it["nodes"]}
    assert nodes["scout"]["runs"] == 2 and nodes["claude"]["failed"] == 1 and "you" in nodes


def test_tool_calls_between_agents_are_exchanges_with_the_whole_question_and_answer(RR, monkeypatch):
    ex = RR.delegations(168, now=RR.NOW)
    first = next(x for x in ex if x["run"] == "hermes:scout:b")
    assert first["from"] == "mission" and first["to"] == "scout"
    assert first["ask"] == QUESTION and first["answer"] == ANSWER                              # whole: the call as sent, the last words
    assert next(x for x in ex if x["run"] == "hermes:scout:c")["answer"] == "(still working)"
    assert next(x for x in ex if x["run"] == "claude:claude-task:x")["answer"] == "(no answer: failed)"
    assert not [x for x in ex if x["to"] == "main"]                                            # your chats are in Chat, not here
    two = RR.delegations(168, "doctor+claude", now=RR.NOW)
    assert [x["run"] for x in two] == ["claude:claude-task:x", "claude-task:23"]
    assert two[1]["ask"] == "You are the Health doctor. " + QUESTION and two[1]["answer"] == '{"diagnoses": []}'   # its Claude run's answer
    import runtime as RTM
    sent = []
    monkeypatch.setattr(RTM, "_post", lambda batch: sent.extend(batch) or True)
    RTM.start("claude-task:9", "claude-task", "Claude task #9", ref="crew:doctor", detail="the whole question")
    assert sent[0]["ref"] == "crew:doctor" and sent[0]["detail"] == "the whole question"


def test_the_swarm_page_has_the_timeline_the_map_the_team_and_tool_calls_in_the_chatroom():
    app = (ROOT / "images/mission-control/web/static/app.js").read_text()          # the views are a row under Agents (app.js)
    for tab in ('["timeline", "Timeline"]', '["map", "Map"]', '["chat", "Chatroom"]', '["agents", "Team"]'):
        assert tab in app
    for part in ("async function swTimeline(", "async function swMap(", "async function swAgents(", "/api/swarm/timeline", "/api/swarm/interactions",
                 "/api/swarm/room?hours=", "'s answer", "Show earlier (", "Show all (", "can send data out"):
        assert part in SWARM_JS, part
    server = (ROOT / "images/mission-control/server.py").read_text()
    assert all(f'Route("/api/swarm/{p}"' in server for p in ("timeline", "interactions", "delegations"))
    fold = re.search(r"^function swFold\(.*?^\}", SWARM_JS, re.M | re.S)[0]
    js = "\n".join(['const esc = (s) => String(s);', fold,
          'process.stdout.write(JSON.stringify([swFold("x".repeat(1300) + "z".repeat(600)), swFold("x".repeat(1700))]));'])
    out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert "<span hidden>" + "x" * 100 + "z" * 600 + "</span>" in out[0] and "Show all (700 more characters)" in out[0]   # folded, not cut
    assert out[1] == "x" * 1700                                                                 # a little more is shown whole


def test_the_map_says_in_words_who_did_what_to_whom_with_each_agent_s_role():
    """The owner's review of 2026-10-30: unlabelled bubbles and line styles said nothing on a phone; each connection
    is now a row of words (SWM-104)."""
    part = lambda name: re.search(rf"^(?:const|function) {name}\b.*?^(?:\}}|\}};)$", SWARM_JS, re.M | re.S)[0]   # noqa: E731
    js = "\n".join(["let swCards = [{id: 'scout', purpose: 'The only agent that reads the web.'}];", part("SW_ROLE"), part("swRole"), part("swVerb"),
        "process.stdout.write(JSON.stringify([swVerb({kind: 'starts', from: 'mission', to: 'scout'}), swVerb({kind: 'starts', from: 'you', to: 'main'}),",
        "  swVerb({kind: 'messages', from: 'checker', to: 'you'}), swVerb({kind: 'starts', from: 'doctor', to: 'claude'}), swRole('scout'), swRole('claude')]));"])
    out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert out[:4] == [["asked to research", "→"], ["chatted with", "→"], ["wrote on the Board with", "↔"], ["asked Claude Code for an analysis", "→"]]
    assert out[4] == "The only agent that reads the web." and out[5].startswith("Claude Code")
    body = re.search(r"^async function swMap\(.*?^\}$", SWARM_JS, re.M | re.S)[0]
    assert "Who works with whom" in body and "Worked alone" in body and "d3.forceSimulation" not in body      # rows of words, no bubbles
    css = (ROOT / "images/mission-control/web/static/app.css").read_text()
    assert ".swconn {" in css and "@media (max-width: 640px)" in css.split(".swconns")[1]                    # one column on a phone

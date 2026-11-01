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


def test_the_agents_tab_is_four_views_and_none_of_the_ten_is_lost():
    """The owner's review of 1 Nov 2026: ten views became four. Overview (working now, the map, every mission and
    housekeeping job), Activity (the room and the run timeline under one set of filters), Team (each agent with its own
    page) and Ideas (ideas, the task graph, the loop's numbers); links to the old views land on the new place."""
    app = (ROOT / "images/mission-control/web/static/app.js").read_text()
    assert '[["list", "Overview"], ["activity", "Activity"], ["agents", "Team"], ["improve", "Ideas"]]' in app
    assert '<div id="ovnow"></div>' in app and '<div id="ovmap">' in app and "swOverview();" in app
    for part in ("async function swTimeline(", "function swMapCard(", "async function swAgents(", "async function swAgentPanel(", "/api/swarm/timeline",
                 "/api/swarm/interactions", "/api/swarm/room?hours=", "'s answer", "Show earlier (", "Show all (", "can send data out",
                 "Merge queue", "Files held by builds", "Being built", "The improvement loop in numbers", "Ideas two or more work on", "Worked alone"):
        assert part in SWARM_JS, part
    assert 'const SW_ALIAS = { chat: "activity", timeline: "activity", tasks: "improve", flow: "improve" };' in SWARM_JS
    assert '["map", "graph", "now", "list"].includes(asked)) { location.replace("#/missions")' in SWARM_JS
    server = (ROOT / "images/mission-control/server.py").read_text()
    assert all(f'Route("/api/swarm/{p}"' in server for p in ("timeline", "interactions", "delegations"))
    fold = re.search(r"^function swFold\(.*?^\}", SWARM_JS, re.M | re.S)[0]
    js = "\n".join(['const esc = (s) => String(s), nf = (n) => Number(n).toLocaleString("en-US");', fold,
          'process.stdout.write(JSON.stringify([swFold("x".repeat(1300) + "z".repeat(600)), swFold("x".repeat(1700))]));'])
    out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert "<span hidden>" + "x" * 100 + "z" * 600 + "</span>" in out[0] and "Show all (700 more characters)" in out[0]   # folded, not cut
    assert out[1] == "x" * 1700                                                                 # a little more is shown whole


def run_activity(script):
    """Activity's filter code in node with a fake address and state."""
    part = lambda name: re.search(rf"^(?:const|function|let) {name}\b(?:[^\n]*;$|.*?^(?:\}}|\}};)$)", SWARM_JS, re.M | re.S)[0]   # noqa: E731
    js = "\n".join(["let route = {q: new URLSearchParams()}, swCards = [{id: 'scout'}, {id: 'mission'}, {id: 'doctor'}], swCtx = '', swLastSig = '', swRoomShow = 0;",
                    "let S = {crew: [{id: 'doctor'}, {id: 'curator'}], swarm: {cards: ['scout', 'mission', 'doctor', 'curator']}};",
                    "const history = {replaceState: (a, b, u) => { globalThis.url = u; }};",
                    part("SW_ROOM_TYPES"), part("swRoomF"), "const SW_LANE = {}; const swGroupOf = () => 'other';",
                    part("swInvolved"), part("swTopicOf"), part("swRoomMatch"), part("swActivityFromUrl"), part("swSyncUrl"), part("SW_OTHER_CREW"), part("swIsCrew"), part("swAgentHref"),
                    part("swActHref"), script])
    return json.loads(subprocess.run(["node", "-"], input=js, capture_output=True, text=True, check=True).stdout)


def test_a_tapped_line_opens_activity_on_what_passed_between_the_two_and_the_filter_does_not_stick():
    """FND-89: the map's rows opened the Chatroom on a conversation id (calls:a+b) that no line carries, so it was empty;
    and the filter stayed for later visits until a reload. Now a pair is two picked agents, from the address each visit."""
    out = run_activity("""
const ask = {type: 'ask', actor: 'mission', target: 'scout', ref: {run: 'hermes:scout:1'}}, other = {type: 'ask', actor: 'doctor', target: 'claude', ref: {}};
const st = {type: 'status', actor: 'scout', target: '', ref: {}};
const res = [];
route.q = new URLSearchParams('tab=activity&agents=mission,scout&h=168'); swActivityFromUrl();
res.push([[...swRoomF.agents], swRoomF.hours, swRoomMatch(ask), swRoomMatch(other), swRoomMatch(st)]);
route.q = new URLSearchParams('tab=chat&ctx=calls:mission+scout'); swActivityFromUrl();         // a link from before
res.push([[...swRoomF.agents], swCtx, swRoomMatch(ask)]);
route.q = new URLSearchParams('tab=activity'); swActivityFromUrl();                             // the tab again: no filter left
res.push([[...swRoomF.agents], swCtx, swRoomF.hours, swRoomMatch(ask), swRoomMatch(st)]);
route.q = new URLSearchParams('tab=activity&agents=scout'); swActivityFromUrl(); swSyncUrl();
res.push([swRoomMatch(st), url, swAgentHref('doctor'), swAgentHref('scout'), swAgentHref('gmail'), swActHref(['a', 'b'], 72), swAgentHref('curator')]);
process.stdout.write(JSON.stringify(res));""")
    assert out[0] == [["mission", "scout"], 168, True, False, False]                    # only what passed between them
    assert out[1] == [["mission", "scout"], "", True]
    assert out[2] == [[], "", 24, True, False]
    assert out[3] == [True, "#/swarm?tab=activity&agents=scout&h=168", "#/crew/doctor?tab=team", "#/swarm/agent/scout", "",
                      "#/swarm?tab=activity&agents=a,b&h=72", "#/swarm/agent/curator"]   # the team's curator is not the skills job "curator"


def test_the_map_is_agents_as_dots_and_lines_that_open_activity():
    """The owner's review of 1 Nov 2026: "This is not a map." Agents are dots (size: runs, red ring: failures), a line
    joins two that worked together (arrow: who asked, number: how often, dashed: only messages); a tap on either opens
    Activity on it; the rows of words and the ideas stay, one tap away."""
    card = re.search(r"^function swMapCard\(.*?^\}$", SWARM_JS, re.M | re.S)[0]
    assert "d3.forceSimulation(nodes)" in card and '.attr("class", "swhit")' in card and 'attr("stroke-width", 22)' in card   # a line is easy to hit
    assert 'go(swActHref([d.p.a, d.p.b], swMapHours))' in card and 'go(d.kind === "idea" ? `#/swarm/artifact/${d.aid}` : swActHref([d.id], swMapHours))' in card
    assert '"var(--err)"' in card and "Math.log2(1 + d.runs)" in card and '"6 5"' in card and "swnum" in card
    assert "Every connection in words" in card and "Worked alone" in card and "Ideas too" in card
    mount = re.search(r"^function swMapMount\(.*?^\}$", SWARM_JS, re.M | re.S)[0]
    assert "ph.replaceWith(swOv.el)" in mount and "sig === swOv.sig" in mount                   # a live redraw keeps the drawn map


def test_every_team_agent_has_one_page():
    """"In team cards not clickable? Do we not have one page per agent?" A housekeeping agent's page gets the team panel
    as its Team tab; any other team agent has #/swarm/agent/<id>; every card opens it."""
    app = (ROOT / "images/mission-control/web/static/app.js").read_text()
    assert 'kind === "crew" && swIsCrew(c.id) && (S?.swarm?.cards || []).includes(c.id) ? [["team", "Team"]] : []' in app
    assert 'if (route.args[0] === "agent") return swAgentPage(view, decodeURIComponent(route.args[1] || ""));' in SWARM_JS
    tile = re.search(r"^function swTile\(.*?^\}$", SWARM_JS, re.M | re.S)[0]
    assert 'data-href="${href}"' in tile and "Its activity" in tile
    panel = re.search(r"^async function swAgentPanel\(.*?^\}$", SWARM_JS, re.M | re.S)[0]
    for part in ("swDaysHtml(", "Works with", "Runs in the last 7 days", "What it said and did", "Ideas it worked on", "swTelemetry()",
                 "<h2>Health", "Tasks it did steps for", "<h2>Memory", "agents/${id}/MEMORY.md", "i.id === SW_ENGINE[id]"):
        assert part in panel, part
    assert "team: (box) => swAgentPanel(box, c.id, true)" in app                       # its housekeeping page shows issues and memory already
    assert 'setTimeout(() => swMissionDays($("#mdays", body), m.slug), 0);' in app      # a mission's History: its last 30 days
    assert 'a,button,summary,details,input,select,textarea,label,form' in app                  # a tap in a card's form stays in it



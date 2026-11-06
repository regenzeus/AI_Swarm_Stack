"""Who works with whom (SWM-110 to SWM-115): one list of interactions. A line's number is what its tap opens, every run has
one cause, one piece of work counts once, tests stay apart from work, and nothing that reaches another agent or the owner
goes undrawn. The owner's questions of 5 Nov 2026: Inbox had no lines, their own arrow opened empty."""
import ast
import json
from pathlib import Path

import yaml

import interactions as IX
import teamroom as TR

ROOT = Path(__file__).resolve().parent.parent
NOW = 1_800_000_000.0


def run(run_id, lane, state="done", **kw):
    return {"run": run_id, "lane": lane, "agent": lane, "name": run_id, "started": kw.pop("started", NOW - 100), "ended": NOW - 50, "last": NOW - 50, "state": state,
            "parent": None, "by": None, "calls": 0, "tokens": 0, "ref": None, "title": "", "recorded": None, "trigger": None, "repo": None, "until": None, **kw}


def test_every_run_has_one_cause_and_no_lumped_starter():
    tasks = {1: {"source": "trial:semver", "door": "plan"}, 2: {"source": "rule:2", "door": "plan"}, 3: {"source": "app", "door": "plan"}}
    runs = [
        run("crew:inbox:old", "inbox"),                                                           # before the cause was kept
        run("crew:doctor:new", "doctor", recorded={"kind": "alert", "who": "stack", "why": "a new issue"}),
        run("crew:checker:new", "checker", recorded={"kind": "clock"}),
        run("hermes:main:c", "main", ref="chat:abc", by="you"),
        run("mission-run:1", "mission", trigger="manual"),
        run("mission-run:2", "mission", trigger="schedule"),
        run("task:1", "conductor"),                                                                # a trial's
        run("hermes:scout:t", "scout", parent="task:1", by="conductor", started=NOW - 90),         # and everything under it
        run("task-intake:2-0", "intake"),
        run("task-intake:3-0", "intake"),
        run("claude-task:9", "claude", ref="chat", by="hermes"),                                   # Hermes' claude tool: whose?
        run("claude:claude-task:9", "claude", parent="claude-task:9", by="claude", started=NOW - 99),
        run("claude-task:10", "claude"),                                                           # a doctor's, its ref lost
        run("hermes:main:bench", "main", ref="eval:bench"),
        run("phone:1", "phone"), run("mail:1", "gmail"), run("phone:2", "phone"),
        run("hermes:mission:x", "mission"),
        run("hermes:main:replay", "main", title="Which NAS do I have?"),
        run("hermes:main:check", "main", ref="chat:chk", by="you"),                                # the stack's own check, not the owner
    ]
    IX.classify(runs, tasks, {9: {"source": "chat"}, 10: {"source": "crew:doctor"}}, {}, {"phone:1": "self", "mail:1": "inbox", "phone:2": None}, [(NOW - 500, "mission"), (NOW - 9000, "main")], {"Which NAS do I have?"}, {"chk"})
    c = {r["run"]: r["cause"] for r in runs}
    by = {r["run"]: r for r in runs}
    assert all(r.get("cause") and r.get("world") in ("real", "test") for r in runs)
    assert c["crew:inbox:old"]["kind"] == "unrecorded" and c["crew:doctor:new"]["kind"] == "alert" and c["crew:checker:new"]["kind"] == "clock"
    assert c["hermes:main:c"]["kind"] == "you" and c["mission-run:1"]["kind"] == "you" and c["mission-run:2"]["kind"] == "clock"
    assert by["task:1"]["world"] == "test" and by["hermes:scout:t"]["world"] == "test" and c["hermes:scout:t"]["kind"] == "test"
    assert c["task-intake:2-0"]["kind"] == "rule" and c["task-intake:3-0"]["kind"] == "you" and by["hermes:main:bench"]["world"] == "test"
    assert by["claude-task:9"]["by"] == "mission" and c["claude-task:9"]["certainty"] == "matched"      # never the lump "hermes"
    assert by["claude:claude-task:9"]["half"] and by["claude-task:10"]["by"] == "doctor"
    assert c["phone:1"]["kind"] == "clock" and c["mail:1"] == {"kind": "agent", "who": "inbox", "why": "", "certainty": "matched"} and c["phone:2"]["kind"] == "unknown"
    assert c["hermes:mission:x"]["kind"] == "unknown" and by["hermes:main:replay"]["world"] == "test" and c["hermes:main:check"]["kind"] == "test"
    cov = IX.coverage(runs)
    assert cov["runs"] == len(runs) - 1 and cov["unknown"] == 2 and cov["unrecorded"] == 1 and cov["known"] == cov["runs"] - 3 and cov["tests"] >= 3


def lines_of_a_week():
    feed = {"events": [{"seq": 1, "artifact_id": 7, "actor": "owner:owner", "cls": "owner", "kind": "transition", "payload": {"to": "active"}, "reason": "", "ts": 10, "akind": "idea", "title": "Fix it", "owner": "doctor"}],
            "messages": [{"sender": "checker", "sender_cls": "checker", "recipients": '["owner:owner", "doctor", "room:health"]', "context": "room:health", "act": "inform", "text": "Proved", "ts": 11},
                         {"sender": "doctor", "sender_cls": "agent", "recipients": '["scout"]', "context": "dm:doctor+scout", "act": "request", "text": "How?", "ts": 12}]}
    asks = [{"run": "r1", "from": "mission", "to": "scout", "ts": 9, "ended": 9.5, "state": "done", "ask": "Find it", "answer": "Found"}]
    chats = [{"id": "c1", "origin": "owner", "messages": [{"role": "user", "content": "Why is the sky blue?", "ts": 20.0}, {"role": "assistant", "content": "Rayleigh", "ts": 21.0}]},
             {"id": "c2", "origin": "automation", "messages": [{"role": "user", "content": "a check", "ts": 22.0}]},
             {"id": "voicechat", "origin": "voice", "messages": [{"role": "user", "content": "how long for an egg", "room": "office", "ts": 23.0}]}]
    calls = IX.tool_calls([{"run": "m1", "lane": "main", "title": "mcp__vault__phone_phone_look", "ts": 30}, {"run": "m1", "lane": "main", "title": "mcp__vault__phone_phone_tap", "ts": 31},
                           {"run": "m1", "lane": "main", "title": "mcp__vault__missions_missions_overview", "ts": 32}, {"run": "m1", "lane": "main", "title": "mcp__vault__missions_mission_create", "ts": 33},
                           {"run": "i1", "lane": "inbox", "title": "mail_search", "ts": 34}, {"run": "s1", "lane": "scout", "title": "web_search", "ts": 35}])
    tasks = {5: {"id": 5, "source": "app", "text": "Find a post", "ts": 40.0}, 6: {"id": 6, "source": "trial:x", "text": "t", "ts": 41.0}}
    steps = [{"task": 8, "occ": 1, "idx": 0, "agent": "scout", "after": "[]", "title": "Look", "ts": 42.0}, {"task": 8, "occ": 1, "idx": 1, "agent": "desk", "after": "[0]", "title": "Write", "ts": 43.0},
             {"task": 6, "occ": 1, "idx": 0, "agent": "analyst", "after": "[]", "title": "a", "ts": 44.0}, {"task": 6, "occ": 1, "idx": 1, "agent": "tester", "after": "[0]", "title": "b", "ts": 45.0}]
    extra = [*IX.prompt_lines(chats, 0), *IX.use_lines(calls, [], {}, {}), *IX.task_lines(tasks, {}, 0), *IX.plan_lines(steps, tasks, 0),
             *IX.idea_lines([{"id": 3, "title": "Do it", "repo": "stack", "idea": 7, "ts": 46.0}], [], {7: "doctor"}, 0),
             *IX.link_lines([{"ts": 47.0, "from": "inbox", "to": "curator", "via": "raw/_inbox/a.md", "text": "A newsletter", "run": "i1"}, {"ts": 48.0, "from": "inbox", "to": "desk", "via": "topics/u/mail/b.md", "text": "Another"}], 0),
             *IX.tell_lines([{"ts": 49, "channel": "telegram", "title": "", "text": "Inbox digest: 2 filed", "decision": "sent", "category": "result"}, {"ts": 49, "channel": "push", "title": "", "text": "Inbox digest: 2 filed", "decision": "sent", "category": "result"},
                             {"ts": 50, "channel": "telegram", "title": "", "text": "off", "decision": "off", "category": "system", "by": "stack"}], 0),
             *IX.owner_lines([{"ts": 51, "action": "build_approve"}, {"ts": 52, "action": "notify_prefs"}], 0)]
    return TR.lines(feed, asks, [], extra)


def test_a_line_s_number_is_what_its_tap_opens():
    lines = [x for x in lines_of_a_week() if x.get("world") != "test"]
    edges = IX.edges(lines)
    assert edges
    pairs = {}
    for e in edges:
        k = frozenset((e["from"], e["to"]))
        pairs[k] = pairs.get(k, 0) + e["n"]
    for k, n in pairs.items():
        assert sum(1 for x in lines if IX.between(x, k)) == n, sorted(k)                        # the checker's message to three is once per pair


def test_what_the_owner_asked_about_is_on_the_map():
    lines = lines_of_a_week()
    e = {(x["from"], x["to"], x["kind"]): x["n"] for x in IX.edges([x for x in lines if x.get("world") != "test"])}
    assert e[("you", "main", "you")] == 2                                                       # typed and spoken; the check's chat isn't theirs
    assert e[("you", "doctor", "you")] == 1 and e[("you", "intake", "you")] == 1 and e[("you", "builder", "you")] == 1
    assert e[("inbox", "gmail", "use")] == 1 and e[("inbox", "curator", "hand")] == 1 and e[("inbox", "desk", "hand")] == 1 and e[("inbox", "you", "tell")] == 1   # Inbox isn't alone
    assert e[("main", "phone", "use")] == 1 and e[("main", "mission", "use")] == 1
    assert e[("scout", "desk", "hand")] == 1 and e[("doctor", "builder", "hand")] == 1
    assert e[("checker", "you", "talk")] == 1 and e[("checker", "doctor", "talk")] == 1 and e[("doctor", "scout", "talk")] == 1
    prompt = next(x for x in lines if x["text"] == "Why is the sky blue?")
    assert prompt["detail"] == "Rayleigh" and prompt["ref"] == {"chat": "c1"}                   # the prompt, its answer, the chat one tap away
    use = next(x for x in lines if x["actor"] == "main" and x["target"] == "phone")
    assert use["text"] == "2 calls: phone_phone_look 1, phone_phone_tap 1"
    assert next(x for x in lines if x["actor"] == "inbox" and x["type"] == "tell")["ref"]["channels"] == ["push", "telegram"]   # one message, two ways
    assert not [x for x in lines if x["text"] == "off"]                                         # switched off: it never reached them
    test = next(x for x in lines if x["actor"] == "analyst")
    assert test["world"] == "test"


def test_a_message_names_its_sender():
    assert IX.sender_of({"by": "coach"}) == "coach"
    assert IX.sender_of({"text": "Health doctor: 2 issues"}) == "doctor" and IX.sender_of({"text": "Inbox digest: 1"}) == "inbox"
    assert IX.sender_of({"title": "Tasks", "text": "Task #4 is done"}) == "conductor" and IX.sender_of({"category": "build", "text": "x"}) == "builder"
    assert IX.sender_of({"category": "system", "text": "The AI stack is back."}) == "stack" and IX.sender_of({"category": "health", "title": "Agent health", "text": "x"}) == "stack"
    assert IX.sender_of({"category": "system", "title": "Copper mining", "text": "Run done"}) == "mission" and IX.sender_of({"category": "approval", "text": "📱 AI phone: OK?"}) == "phone"
    assert IX.sender_of({"category": "system", "text": "Vault: ingested 20"}) == "curator"
    calls = []
    for f in [*(ROOT / "ops").glob("*.py"), ROOT / "eval/bench.py"]:
        tree = ast.parse(f.read_text())
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "send" and isinstance(n.func.value, (ast.Name, ast.Attribute)) \
                    and getattr(n.func.value, "attr", getattr(n.func.value, "id", "")) in ("N", "notify", "NOTIFY"):
                calls.append((f.name, n.lineno, any(k.arg == "by" for k in n.keywords)))
    assert len(calls) >= 12 and all(c[2] for c in calls), [c for c in calls if not c[2]]


def test_no_tool_server_slips_past_the_map():
    servers = yaml.safe_load((ROOT / "config/litellm/config.yaml").read_text())["mcp_servers"]
    assert set(servers) <= set(IX.TOOL_SERVERS), f"say what a call to these means here: {set(servers) - set(IX.TOOL_SERVERS)}"


def test_a_session_is_tied_to_its_caller_or_marked_unknown():
    calls = [{"run": "m", "lane": "main", "node": "phone", "tool": "phone_phone_look", "ts": 105}]
    sess = [{"run": "phone:1", "started": 100, "ended": 200, "titles": ["connect", "phone_look"]}, {"run": "phone:2", "started": 500, "ended": 510, "titles": ["connect", "session ended"]},
            {"run": "mail:1", "started": 800, "ended": 850, "titles": ["search"]}, {"run": "mail:2", "started": 2000, "ended": 2010, "titles": ["search"]}]
    other = [{"run": "crew:inbox:1", "lane": "inbox", "started": 790, "ended": 860}, {"run": "crew:checker:1", "lane": "checker", "started": 790, "ended": 860}]
    assert IX.service_callers(calls, sess, other) == {"phone:1": "main", "phone:2": "self", "mail:1": "inbox", "mail:2": None}
    extra = IX.use_lines(calls, sess, {"phone:1": "main", "phone:2": "self", "mail:1": "inbox", "mail:2": None}, {})
    assert [(x["actor"], x["target"], x["certainty"]) for x in extra] == [("main", "phone", "recorded"), ("inbox", "gmail", "matched")]


def test_a_dot_counts_real_work_once_and_rings_only_while_its_newest_run_failed():
    runs = [run("a", "doctor", state="failed", started=1), run("b", "doctor", started=2), run("c", "tester", state="failed", started=3), run("d", "claude", started=4), run("e", "claude", started=5)]
    IX.classify(runs)
    runs[4]["half"] = True
    runs[2]["world"] = "test"
    n = {x["id"]: x for x in IX.nodes(runs, [{"from": "you", "to": "doctor"}])}
    assert n["doctor"]["runs"] == 2 and n["doctor"]["failed"] == 1 and not n["doctor"]["failing"]    # one failure, then a good run
    assert n["claude"]["runs"] == 1 and "tester" not in n and n["you"]["runs"] == 0
    assert {x["id"]: x for x in IX.nodes(runs, [], tests=True)}["tester"]["failing"]


def test_the_app_draws_the_one_list():
    swarm = (ROOT / "images/mission-control/web/static/swarm.js").read_text()
    server = (ROOT / "images/mission-control/server.py").read_text()
    assert "RT.interactions" not in server and "g.talk" not in swarm                           # no second count of who works with whom
    assert "picked.has(l.actor) && (l.to || []).some(" in swarm                                  # the same rule as interactions.between
    assert 'x["type"] != "tell" and x["actor"] != "you"' in (ROOT / "images/mission-control/interactions.py").read_text()   # not shown to the AI phone
    assert "not from_ai_phone(request)" in server.split("def _picture_of")[1].split("\n\n")[0]
    room = swarm[swarm.index("async function swChat("):swarm.index("// A success check in plain words")]
    assert "What the agents do together" not in room and "Only what involves" not in room      # the explanation is one tap away
    assert 'data-ra=""' not in room and "swRoomF.agents.has(b[0]) - swRoomF.agents.has(a[0])" in room   # who is picked comes first
    assert ".filter(([k, , n]) => n || swRoomF.types.has(k))" in room                            # a kind with nothing in it takes no room
    assert 'every.filter((e) => e.kind !== "tell")' in swarm and "data-mtold" in swarm           # the map's busiest lines are one chip away


def test_the_records_for_it_are_kept():
    crew = (ROOT / "ops/crew.py").read_text()
    assert '"cause": take_cause(name)' in crew and 'set_cause(ag["id"], "you", why="Run now")' in crew and 'set_cause("doctor", "alert", "stack"' in crew
    inbox = (ROOT / "ops/inbox.py").read_text()
    assert 'RTM.stage(tool, json.dumps(args, ensure_ascii=False), kind="call")' in inbox
    assert 'RTM.link("curator", p.relative_to(VAULT), r["subject"])' in inbox and 'RTM.link("desk", p.relative_to(VAULT), m["subject"])' in inbox


def test_a_crew_job_keeps_why_it_started(tmp_path, monkeypatch):
    import crew as C
    monkeypatch.setattr(C, "OUT", tmp_path)
    assert C.take_cause("doctor") == {"kind": "clock"}                                          # no word: its timer
    C.set_cause("doctor", "alert", "stack", "a new issue")
    assert C.take_cause("doctor") == {"kind": "alert", "who": "stack", "why": "a new issue"}
    assert C.take_cause("doctor") == {"kind": "clock"}                                          # the word goes with that run
    C.set_cause("inbox", "you", why="Run now")
    assert C.take_cause("inbox", now=json.loads((tmp_path / "cause/inbox.json").read_text())["t"] + 700) == {"kind": "clock"}   # its run never came

"""The Board (images/swarm/ledger.py): addresses, guards, requests, labels, handoff, the app's read-only door, and the
owner's posts (SWM-10 to SWM-15, SWM-48 to SWM-58, SWM-67)."""
import asyncio
import json

import pytest

import swarm
import swarm_client as SW
from ledger import Ledger, Refused

ROOMS = {"rooms": ["all", "health", "code", "research", "house", "shopping", "ops"]}
CARDS = [{"id": "doctor", "tools": [], "roles": ["health", "reviewers"], "rooms": ["all", "health"], "contact": ["*"]},
         {"id": "builder", "tools": ["graphify"], "roles": ["code"], "rooms": ["all", "code"], "contact": ["*"]},
         {"id": "scout", "tools": ["fetch", "browser"], "roles": ["research"], "rooms": ["all", "research"], "contact": ["doctor"]},
         {"id": "tests", "tools": [], "roles": ["tests", "reviewers"], "rooms": ["all", "code"], "contact": ["*"]}]
DOC, BUILDER, SCOUT, TESTS = ({"id": i, "cls": "agent"} for i in ("doctor", "builder", "scout", "tests"))
OWNER = {"id": "owner:owner", "cls": "owner"}


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        self.t += 1
        return self.t


@pytest.fixture
def L(tmp_path):
    return Ledger(str(tmp_path / "s.db"), CARDS, now=Clock(), registry=ROOMS)


def idea(L, key="k", owner="doctor"):
    return L.upsert({"id": "system", "cls": "system"}, f"i{key}", "idea", key, f"Idea {key} about the backup", "body text " * 6,
                    owner=owner, guard=False)["id"]


def test_each_address_reaches_exactly_its_agents(L):
    aid = idea(L)
    L.watch(BUILDER, "w", aid)
    assert L.send(DOC, "1", ["agent:builder"], "inform", "the build is green")["recipients"] == ["builder"]
    assert L.send(DOC, "2", ["role:reviewers"], "inform", "a review is waiting")["recipients"] == ["tests"]
    r = L.send(DOC, "3", ["room:code"], "inform", "code room news")
    assert r["recipients"] == ["builder", "owner", "tests"] and r["context"] == "room:code"
    r = L.send(TESTS, "4", [f"artifact:{aid}"], "inform", "I looked at it too")
    assert set(r["recipients"]) == {"doctor", "builder", "owner"} and r["context"] == f"artifact:{aid}"
    assert L.send(DOC, "5", ["owner"], "inform", "need your call on retention")["recipients"] == ["owner"]
    with pytest.raises(Refused, match="no room secret"):
        L.send(DOC, "6", ["room:secret"], "inform", "x")
    with pytest.raises(Refused, match="unknown address"):
        L.send(DOC, "7", ["everyone"], "inform", "x")


def test_code_guards_loops_floods_repeats_and_room_all(L):
    aid = idea(L)
    with pytest.raises(Refused, match="room:all takes only informs that link an artifact"):
        L.send(DOC, "a1", ["room:all"], "inform", "hello all")
    L.send(DOC, "a2", ["room:all"], "inform", "the backup fix shipped", artifact_id=aid)
    m = L.send(DOC, "h0", ["agent:builder"], "inform", "first hop of a long chain")["mid"]
    who = [BUILDER, DOC]
    words = ["which build broke", "the backup one from monday", "rerun it with logs please", "logs attached, rsync exit code 23"]
    for n in range(1, 5):
        m = L.send(who[n % 2], f"h{n}", [], "inform", words[n - 1], reply_to=m)["mid"]
    with pytest.raises(Refused, match="4 hops"):
        L.send(BUILDER, "h5", [], "inform", "the fifth hop goes nowhere", reply_to=m)
    L.send(OWNER, "o1", [], "inform", "the owner joins", reply_to=m)                    # the owner may always answer
    with pytest.raises(Refused, match="near-identical"):
        L.send(TESTS, "d1", ["agent:doctor"], "inform", "the nightly backup failed again tonight")
        L.send(TESTS, "d2", ["agent:doctor"], "inform", "the nightly backup failed again tonight")
    topics = ["disk", "memory", "backup", "phone", "mail", "wiki", "ci", "docker", "ollama", "qmd", "hindsight", "phoenix", "litellm",
              "hermes", "scout", "curator", "desk", "digest", "forgejo", "nas"]
    for n, t in enumerate(topics):
        try:
            L.send(TESTS, f"r{n}", ["agent:builder"], "inform", f"{t} looks fine")
        except Refused:
            break
    with pytest.raises(Refused, match="rate limit"):
        L.send(TESTS, "r-last", ["agent:builder"], "inform", "one too many messages this hour")


def test_contact_policy_and_private_content(L):
    with pytest.raises(Refused, match="contact policy"):
        L.send(SCOUT, "c1", ["agent:builder"], "inform", "scout to builder")
    assert L.send(SCOUT, "c2", ["agent:doctor"], "inform", "scout to doctor")["recipients"] == ["doctor"]
    with pytest.raises(Refused, match="SWM-67"):
        L.send(DOC, "p1", ["agent:scout"], "inform", "a note from the vault", label="private")
    r = L.send(DOC, "p2", ["role:research", "agent:builder"], "inform", "private but only for those who may", label="private")
    assert r["recipients"] == ["builder"]                                               # the scout (a way out) does not get it
    aid = L.upsert(DOC, "pa", "finding", "vault", "A private note", "insurance letter details " * 3, label="private")["id"]
    with pytest.raises(Refused, match="SWM-67"):
        L.send(DOC, "p3", ["agent:scout"], "inform", "see this", artifact_id=aid)        # a link carries the artifact's label


def test_a_request_is_tracked_until_it_ends_and_expires_with_a_reason(L):
    aid = idea(L)
    r = L.send(DOC, "q1", ["agent:builder"], "request", "please rebuild with the fix", artifact_id=aid, expires_h=1)
    assert [x["mid"] for x in L.context("builder")["open_requests"]] == [r["mid"]]
    assert [x["mid"] for x in L.context("doctor")["open_requests"]] == [r["mid"]]   # the sender sees it too
    L.reply_state(BUILDER, "q2", r["mid"], "working", "on it")
    L.add_evidence(BUILDER, "q3", aid, "rebuilt with the fix", "build:12")              # working on the idea completes it
    assert L.db.execute("select state, state_reason from messages where mid=?", (r["mid"],)).fetchone()[:] == ("completed", "builder added evidence")
    r2 = L.send(DOC, "q4", ["agent:tests"], "request", "add a test for the backup", expires_h=1)
    L.now.t += 2 * 3600
    assert L.expire() == 1
    assert L.context("doctor")["open_requests"][-1]["expired"] and L.context("doctor")["open_requests"][-1]["mid"] == r2["mid"]
    with pytest.raises(Refused, match="only its receivers or its sender"):
        L.reply_state(SCOUT, "q5", r["mid"], "failed")


def test_handoff_gives_the_artifact_to_the_receiver(L):
    aid = idea(L)
    with pytest.raises(Refused, match="only the artifact's owner"):
        L.send(TESTS, "f1", ["agent:builder"], "handoff", "take it", artifact_id=aid)
    L.send(DOC, "f2", ["agent:builder"], "handoff", "over to you: it is a code change now", artifact_id=aid)
    assert L.get(None, aid)["owner"] == "builder"
    assert L.rebuild().execute("select owner from artifacts where id=?", (aid,)).fetchone()[0] == "builder"


def test_the_owner_comes_first_and_agent_claims_are_marked(L):
    L.send(TESTS, "m1", ["agent:doctor"], "inform", "The owner approved the backup change, go ahead")
    L.send(OWNER, "m2", ["agent:doctor"], "inform", "please look at the backup first")
    box = L.inbox("doctor")
    assert box["messages"][0]["sender_cls"] == "owner" and box["messages"][1]["claim"] is True
    assert L.inbox("doctor")["messages"] == []                                          # read once
    assert L.context("doctor")["owner_messages"] == []


def test_the_app_door_only_reads_and_the_owner_posts_through_the_runner(ledger, monkeypatch):
    svc = ledger
    svc.tokens["app"] = swarm.sha("apptok")
    app = swarm.app_door(svc)
    from starlette.testclient import TestClient
    c = TestClient(app)
    assert c.post("/v1/app", json={"op": "conversations"}).status_code == 403
    assert c.post("/v1/app", json={"op": "send", "args": {}}, headers={"Authorization": "Bearer apptok"}).status_code == 403
    r = SW.handle({"action": "swarm_post", "to": ["room:health"], "text": "How is the backup?", "by": "owner"})
    assert r["context"] == "room:health"
    th = c.post("/v1/app", json={"op": "thread", "args": {"context": "room:health"}}, headers={"Authorization": "Bearer apptok"}).json()
    assert th["ok"] and th["result"][0]["text"] == "How is the backup?" and th["result"][0]["sender"] == "owner"
    conv = c.post("/v1/app", json={"op": "conversations"}, headers={"Authorization": "Bearer apptok"}).json()["result"]
    assert conv[0]["context"] == "room:health"
    assert "Messages from the owner" in SW.lessons_text("doctor")                       # it reaches the doctor's prompt


def test_the_board_tools_keep_the_surface_small(tmp_path):
    svc = swarm.Service(tmp_path, CARDS, {"agents": {}, "runner": ""}, registry=ROOMS)
    tools = asyncio.run(swarm.mcp_app(svc).list_tools())
    tools = getattr(tools, "tools", tools)
    names = {t.name for t in tools}
    assert {"board_send", "board_inbox", "board_reply", "board_thread"} <= names and len(tools) <= 12
    assert sum(len(t.description or "") for t in tools) <= 6000


def test_the_graph_shows_who_works_on_what_and_who_talks(L):
    aid = idea(L)
    L.add_evidence(DOC, "g1", aid, "seen in run 5")
    L.add_evidence(TESTS, "g2", aid, "a test covers it now")
    L.send(DOC, "g3", ["agent:tests"], "inform", "thanks for the test")
    g = L.graph()
    assert g["shared"] == {str(aid): ["doctor", "tests"]} and {"a": "doctor", "b": "tests", "n": 1} in g["talk"]
    L.add_evidence(OWNER, "g4", aid, "I saw it too")
    L.add_evidence({"id": "checker", "cls": "checker"}, "g5", aid, "checker: still waiting")
    assert L.graph()["shared"][str(aid)] == ["checker", "doctor", "owner", "tests"]   # the owner and the Checker count


def test_tokens_per_agent_include_the_claude_runs_under_a_crew_job(tmp_path, monkeypatch):
    import runrecord as RR
    monkeypatch.setattr(RR, "DB", tmp_path / "rt.db")
    monkeypatch.setattr(RR, "_db", None)
    import otlp
    monkeypatch.setattr(otlp, "export_later", lambda spans: None)
    RR.ingest([{"run": "crew:doctor:1", "agent": "crew:doctor", "source": "runner", "ts": 1.8e9, "kind": "run"},
               {"run": "claude:claude-task:x", "agent": "claude-task", "source": "claude", "ref": "crew:doctor:1", "ts": 1.8e9 + 1, "kind": "llm",
                "tokens": {"in": 1000, "out": 200}}])
    monkeypatch.setattr(RR.time, "time", lambda: 1.8e9 + 60)
    assert RR.tokens_by_agent(30) == {"doctor": 1200}
    assert json.dumps(RR.tokens_by_agent(30))


def test_a_request_wakes_an_on_request_agent_within_its_budget(ledger, monkeypatch):
    import registry
    reg = registry.load()
    doctor = next(c for c in reg["agents"] if c["id"] == "doctor")
    assert doctor["wake"] == "on_request" and doctor["budgets"]["wakes_per_day"] == 6
    checker = {"id": "checker", "cls": "checker"}
    topics = ["the backup", "the disk", "the wiki", "the phone", "the mail", "the docker logs", "the nas share", "the certificates"]
    ask = lambda n: ledger.ledger.send(checker, f"w{n}", ["agent:doctor"], "request", f"look at {topics[n]} again")
    ask(0)
    started, running = [], set()
    assert SW.wake(start=started.append, active=lambda u: u in running, now=1.9e9) == ["doctor"] and started == ["crew-doctor"]
    assert SW.wake(start=started.append, active=lambda u: False, now=1.9e9 + 30) == []                # one wake per request
    ask(1)
    running.add("crew-doctor")
    assert SW.wake(start=started.append, active=lambda u: u in running, now=1.9e9 + 60) == []         # not while it runs
    running.clear()
    for n in range(2, 7):
        ask(n)
        SW.wake(start=started.append, active=lambda u: False, now=1.9e9 + 120 + n)
    assert started.count("crew-doctor") == 6                                                           # budget: 6 a day
    ask(7)
    assert SW.wake(start=started.append, active=lambda u: False, now=1.9e9 + 86400 + 300) == ["doctor"]

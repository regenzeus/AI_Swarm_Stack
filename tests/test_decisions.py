"""The decision queue and its shadow (ops/decisions.py, AUT-03, AUT-05, AUT-07): every source's waits in one ranked
list with what, why, the stack's recommendation and the answers; the shadow records what it would decide and the
owner's outcome; the queue's numbers; the floor classes stay at ask. No services: a fake state and a temporary log."""
import pysrc
import webjs
import importlib
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_JS = webjs.app_js()
T0 = 1793600000.0


@pytest.fixture
def DQ(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMY_LOG", str(tmp_path / "autonomy.jsonl"))
    import decisions
    m = importlib.reload(decisions)
    m._seen.clear(); m._loaded["t"] = 0
    return m


def state(**kw):
    st = {"builds": [{"id": 4, "status": "review", "title": "Fix the map", "checks_ok": True, "checks": "x", "ci": "success",
                      "ai_review": {"verdict": "approve"}, "updated": T0 - 3600},
                     {"id": 5, "status": "working", "title": "Busy"}],
          "shopping": {"proposals": [{"id": "p-1", "slug": "ram", "status": "proposed", "item": "RAM kit", "total_eur": 99, "shop": "Alternate",
                                      "deadline": T0 + 3600, "created": T0 - 60},
                                     {"id": "p-2", "slug": "ram", "status": "watching", "item": "Other", "total_eur": 189}]},
          "crew": [{"id": "phone-cleanup", "actions": [{"id": "a1", "status": "open", "kind": "cache", "title": "Empty all app caches", "size": 2e9},
                                                       {"id": "a2", "status": "open", "kind": "uninstall", "title": "Uninstall com.whatsapp"},
                                                       {"id": "a3", "status": "done", "kind": "cache"}]}],
          "system": {"pending_memory": [{"id": "m1", "text": "The owner prefers English"}]},
          "tasks": [{"id": 9, "status": "waiting_approval", "kind": "research", "title": "Compare two NAS"},
                    {"id": 10, "status": "needs_answer", "title": "Build it", "questions": ["Which repository?"]},
                    {"id": 11, "status": "running", "title": "At work"}],
          "swarm": {"owner_requests": [{"id": 3, "sender": "coach", "text": "May I?", "context": "c1"}],
                    "board": {"open": [{"id": 16, "kind": "idea", "title": "Exempt no-argument tools", "priority": 4.8, "effort": "small"},
                                       {"id": 17, "kind": "dispute", "title": "Two founding years"}], "recent": []},
                    "changes": [{"id": "scout", "agent": "scout", "version": 3, "state": "ready", "experiment": {"passed": True, "version": 3}}]}}
    st.update(kw)
    return st


def test_every_source_s_waits_are_one_ranked_list_with_what_why_and_a_recommendation(DQ):
    ds = DQ.gather(state(), now=T0)
    ids = [d["id"] for d in ds]
    assert set(ids) == {"build:4", "shop:p-1", "phone-step:a1", "phone-step:a2", "memory:m1", "task:9", "task-q:10", "ask:3",
                        "idea:16", "idea:17", "change:scout:3"}             # working builds, watched prices, running tasks are not decisions
    assert ids[0] == "shop:p-1"                                            # it expires within two hours: first
    assert ids.index("build:4") < ids.index("idea:16")                     # a deploy costs more to delay than an idea
    by = {d["id"]: d for d in ds}
    assert by["build:4"]["recommend"] == {"answer": "yes", "why": "its checks, CI and AI review all passed"} and by["build:4"]["cls"] == "coding-low-risk"
    assert by["phone-step:a1"]["recommend"]["answer"] == "yes" and by["phone-step:a2"]["recommend"]["answer"] == "no"   # an app is the owner's to remove
    assert by["phone-step:a1"]["routine"] and not by["phone-step:a2"]["routine"]      # so it is never in an "Approve all"
    assert by["phone-step:a2"]["answers"][1] == {"label": "Keep it", "act": {"action": "phone_cleanup_dismiss", "id": "a2"}}   # a no is one tap too
    assert by["task-q:10"]["recommend"] is None and "Which repository?" in by["task-q:10"]["why"]                       # words, not a yes or no
    assert by["idea:17"]["cls"] == "memory" and by["idea:17"]["what"].startswith("Which is true?")
    assert by["task:9"]["answers"][0] == {"label": "Start", "act": {"action": "task_approve", "id": 9}}
    assert all(d["what"] and d["href"] and "unanswered" in d for d in ds)


def test_the_shadow_records_once_and_then_the_owner_s_outcome(DQ):
    st = state()
    DQ.shadow(DQ.gather(st, T0), st, T0)
    DQ.shadow(DQ.gather(st, T0 + 60), st, T0 + 60)                           # seen once, not every pass
    seen = [r for r in DQ._records() if r["event"] == "seen"]
    assert len(seen) == 11 and all(r.get("backlog") for r in seen)          # what waited before the record began is a backlog
    after = state(builds=[{"id": 4, "status": "deployed"}], shopping={"proposals": [{"id": "p-1", "status": "rejected"}]},
                  tasks=[{"id": 9, "status": "running"}, {"id": 10, "status": "needs_answer", "questions": ["Which repository?"]}])
    after["crew"][0]["actions"][1]["status"] = "dismissed"
    DQ.shadow(DQ.gather(after, T0 + 7200), after, T0 + 7200)
    out = {r["id"]: r for r in DQ._records() if r["event"] == "answered"}
    assert out["build:4"]["owner"] == "yes" and out["build:4"]["would"] == "yes"
    assert out["shop:p-1"]["owner"] == "no" and out["shop:p-1"]["would"] == "yes" and out["task:9"]["owner"] == "yes"
    assert out["phone-step:a2"]["owner"] == "no" and out["build:4"]["secs"] == 7200
    s = DQ.stats(T0 + 7200)
    assert s["agreement"]["coding-low-risk"] == {"n": 1, "agreed": 1, "unsafe": 0}
    assert s["agreement"]["shopping-buy"] == {"n": 1, "agreed": 0, "unsafe": 1}       # it would have bought what the owner refused
    assert s["per_day"] == 0 and s["answered"] == 0                                    # the backlog counts for neither


def test_the_queue_s_numbers_a_day_the_median_and_the_expired(DQ):
    recs = [{"t": T0 + i * 3600, "event": "seen", "id": f"x{i}", "cls": "ideas"} for i in range(6)]
    recs += [{"t": T0 + 86400, "event": "answered", "id": "x0", "cls": "ideas", "owner": "yes", "would": "yes", "secs": 3600},
             {"t": T0 + 86400, "event": "answered", "id": "x1", "cls": "ideas", "owner": "no", "would": "no", "secs": 3 * 3600},
             {"t": T0 + 86400, "event": "answered", "id": "x2", "cls": "shopping-buy", "owner": "expired", "would": "yes", "secs": 9000}]
    s = DQ.stats(T0 + 2 * 86400, recs)
    assert s["per_day"] == 3.0 and s["median_h"] == 2.0 and s["expired"] == 1 and s["target"] == {"per_day": 5, "answer_h": 12}
    assert s["agreement"] == {"ideas": {"n": 2, "agreed": 2, "unsafe": 0}}


def test_the_floor_stays_at_ask_whatever_its_configured_level(DQ):
    cs = DQ.classes()
    assert {k for k, v in cs.items() if v.get("floor")} >= {"shopping-buy", "coding", "phone", "delete", "access"}
    for k, v in cs.items():
        assert DQ.level(k, cs) <= int(v.get("highest") or 0)
        if v.get("floor"):
            assert DQ.level(k, {k: {**v, "level": 2, "highest": 2}}) == 0              # no setting raises it
    assert DQ.level("memory", cs) == 2 and DQ.level("research", cs) == 0               # the Keeper's licence as it is; the rest ask


def the_seven():
    """What waited for the owner outside the queue until GEN-02, plus the two states that stay out of it."""
    return state(crew=[{"id": "memory", "suggestions": [{"id": "f1", "text": "The owner lives on Mars", "why": "contradiction: the wiki says Berlin"}]},
                       {"id": "phone-cleanup", "actions": []}],
                 tasks=[{"id": 20, "status": "failed", "kind": "change", "door": "plan", "title": "Fix the map", "error": "its budget is spent", "source": "app"},
                        {"id": 21, "status": "failed", "kind": "change", "door": "intake", "title": "Never specified"},
                        {"id": 22, "status": "failed", "kind": "change", "door": "plan", "title": "A trial's", "source": "trial:mustache"},
                        {"id": 23, "status": "failed", "kind": "research", "door": "plan", "title": "Not a change"}],
                 house={"reachable": True, "onboarded": True, "connected": False, "integrations": []},
                 health={"alerts": 2, "items": [{"id": "phone-check", "issues": [{"kind": "phone-down", "severity": "alert", "text": "The AI phone: down"}]}]})


def server_list():
    src = pysrc.server()
    ns = {}
    exec(re.search(r"^def owner_decisions\(s\):.*?^    return .*?$", src, re.M | re.S)[0], ns)
    return ns["owner_decisions"]


def test_what_the_owner_must_answer_reaches_the_queue_and_a_state_does_not(DQ):
    """GEN-02: Keeper suggestions, the Checker's "It works", a mission's access, House setup and a stopped change are in it."""
    st = the_seven()
    st["swarm"]["to_confirm"] = [{"id": 31, "title": "The Echo speaks", "state_since": T0}]
    ds = DQ.gather(st, now=T0)
    by = {d["id"]: d for d in ds}
    assert by["keeper:f1"]["answers"][0] == {"label": "Forget", "act": {"action": "crew_memory_forget", "ids": ["f1"]}} and by["keeper:f1"]["routine"]
    assert by["keeper:f1"]["what"] == "Forget this? The owner lives on Mars" and by["keeper:f1"]["recommend"]["answer"] == "yes" and by["keeper:f1"]["why"].startswith("contradiction")
    assert by["confirm:31"]["answers"][0] == {"label": "It works", "act": {"action": "swarm_confirm", "id": 31}} and by["confirm:31"]["cls"] == "owner-confirm"
    assert by["confirm:31"]["answers"][1]["act"] == {"action": "swarm_reopen", "id": 31} and by["confirm:31"]["answers"][1]["into"] == "reason"   # a no says why, in words
    assert by["house:setup"]["what"] == "Finish setting up the House" and by["house:setup"]["why"] == "next: connect it to the ai stack" and by["house:setup"]["href"] == "#/house"
    assert [a["label"] for a in by["stopped:20"]["answers"]] == ["Go on, with its budget doubled", "Leave it stopped", "Look first"] and "budget is spent" in by["stopped:20"]["why"]
    assert not {"stopped:21", "stopped:22", "stopped:23"} & set(by)   # never specified, a trial's, not a change: nothing to resume for the owner
    assert not [d for d in ds if "phone" in d["id"] and "down" in d["what"]] and not [d for d in ds if "health" in d["what"].lower()]   # states, not decisions
    out = server_list()({"connections": {"gmail": {"grants": {"read": 1}}}, "decisions": [],
                         "missions": [{"slug": "a", "title": "Mail digest", "status": "active", "needs": ["gmail:read", "gmail:organize"]},
                                      {"slug": "b", "title": "Granted", "status": "active", "needs": ["gmail:read"]},
                                      {"slug": "c", "title": "Paused", "status": "paused", "needs": ["gmail:organize"]}]})
    assert [d["id"] for d in out] == ["access:a"] and out[0]["what"] == "Mail digest needs access" and out[0]["why"] == "grant gmail:organize on its page"
    assert out[0]["cls"] == "access" and out[0]["answers"] == [{"label": "Grant on its page", "href": "#/mission/a"}]
    nothing = DQ.gather(state(house={"reachable": False}), now=T0)
    assert not [d for d in nothing if d["id"].startswith("house:")]   # a NAS that is off is no step for the owner
    assert all(d["cls"] in DQ.classes() for d in ds)


def test_every_item_in_the_queue_has_a_working_way_to_act(DQ):
    """GEN-02: a tap the server lets through and the runner handles, or a link to a screen the app has."""
    import changes as CHG
    import server as SV
    import swarm_client as SW
    import tasks as TK
    st = state()
    st["crew"].append({"id": "memory", "suggestions": [{"id": "f1", "text": "x", "why": "y"}]})
    st["tasks"].append({"id": 20, "status": "failed", "kind": "change", "door": "plan", "title": "Fix"})
    st["house"] = {"reachable": True}
    st["swarm"]["to_confirm"] = [{"id": 31, "title": "x"}]
    st["decision_test"] = {"token": "abc", "state": "open"}
    ds = server_list()({"phone": {"pending": 1}, "connections": {"pending": 1}, "missions": [{"slug": "a", "status": "active", "needs": ["gmail:read"]}], "decisions": DQ.gather(st, now=T0)})
    assert {d["id"].split(":")[0] for d in ds} == {"build", "shop", "phone-step", "memory", "task", "task-q", "ask", "idea", "change", "keeper", "confirm", "house", "stopped", "test",
                                                   "access", "phone-ask", "gmail-trash"}
    routes = {x.split(":")[0].strip() for x in re.search(r"const fn = \{(.*?)\}\[route\.name\]", APP_JS)[1].split(",")}
    crew = set(re.search(r"^CREW_ACTIONS = \{(.*?)\}", pysrc.missions(), re.M)[1].replace('"', "").replace(" ", "").split(","))
    runner = CHG.ACTIONS | TK.ACTIONS | SW.ACTIONS | DQ.ACTIONS | crew | {"memory"}
    for d in ds:
        assert d["answers"], d["id"]
        assert re.match(r"#/(\w+)", d["href"])[1] in routes, d["href"]
        for x in d["answers"]:
            assert bool(x.get("act")) != bool(x.get("href")), x
            if x.get("act"):
                assert x["act"]["action"] in SV.ACTIONS and x["act"]["action"] in runner, x
            else:
                assert re.match(r"#/(\w+)", x["href"])[1] in routes, x
    broken = DQ.gather({"builds": 3}, now=T0)                        # a source that cannot be read says so, and where to look
    assert broken[0]["id"].startswith("error:") and broken[0]["answers"][0]["href"] == "#/missions?f=problems"


def test_a_link_to_an_agent_s_question_keeps_its_context(DQ):
    got = DQ.gather({"swarm": {"owner_requests": [{"id": 1, "sender": "coach", "context": "calls:mission+scout"}]}}, now=T0)[0]
    assert got["href"] == "#/swarm?tab=chat&ctx=calls%3Amission%2Bscout" == got["answers"][0]["href"]


def test_the_test_item_is_marked_and_changes_nothing_but_itself(DQ, tmp_path, monkeypatch):
    """GEN-03: the smallest test kind: its own class and its own file; the shadow never records it; the app can only answer it."""
    import server as SV
    monkeypatch.setattr(DQ, "TEST_ITEM", tmp_path / "test.json")
    assert DQ.test_record() is None and [d for d in DQ.state({}, T0)["decisions"]] == []
    assert DQ.handle({"action": "decision_test_make", "token": "abc12345"}) == {"token": "abc12345"}
    got = DQ.state({}, T0)
    d = got["decisions"][0]
    assert d["id"] == "test:abc12345" and d["test"] is True and d["cls"] == "journey-test" and "Test item" in d["what"] and got["decision_test"]["state"] == "open"
    assert d["answers"][0]["act"] == {"action": "decision_test_answer", "token": "abc12345", "answer": "yes"}
    assert DQ._records() == [] and DQ._seen == {}                    # it never reaches the shadow or the queue's numbers
    assert DQ.classes()["journey-test"]["highest"] == 0
    assert "decision_test_answer" in SV.ACTIONS and not {"decision_test_make", "decision_test_remove"} & SV.ACTIONS   # only the runner's inbox makes or removes one
    for bad in ({"token": "other", "answer": "yes"}, {"token": "abc12345", "answer": "maybe"}):
        with pytest.raises(ValueError):
            DQ.handle({"action": "decision_test_answer", **bad})
    with pytest.raises(ValueError):
        DQ.handle({"action": "decision_test_make", "token": "../../etc"})
    assert DQ.handle(d["answers"][0]["act"])["answer"] == "yes"
    got = DQ.state({}, T0)
    assert got["decisions"] == [] and got["decision_test"]["answer"] == "yes"
    with pytest.raises(ValueError):                                  # answered once
        DQ.handle(d["answers"][0]["act"])
    DQ.handle({"action": "decision_test_remove", "token": "other"})
    assert DQ.test_record()                                          # another's stays
    DQ.handle({"action": "decision_test_remove", "token": "abc12345"})
    assert DQ.test_record() is None and sorted(p.name for p in tmp_path.iterdir()) == []


def test_it_works_waits_in_the_queue_until_the_owner_said_so(tmp_path, monkeypatch):
    """GEN-02: by the Checker's own rule, read from the Ledger, so an idea past the board's newest 12 still reaches the owner."""
    import checker as CK
    import swarm_client as SC
    monkeypatch.setattr(SC, "REPORT", tmp_path / "public/swarm.json")
    monkeypatch.setattr(SC, "STATE", tmp_path / "state")
    arts = [{"id": 1, "title": "Waits", "state_since": 100, "check": {"type": "owner_confirms"}, "evidence": [], "body": "long"},
            {"id": 2, "title": "Said", "state_since": 100, "check": {"type": "owner_confirms"}, "evidence": [{"origin": "owner", "text": "confirmed: it works (the owner)", "ts": 200}]},
            {"id": 3, "title": "Said before it shipped again", "state_since": 300, "check": {"type": "owner_confirms"}, "evidence": [{"origin": "owner", "text": "confirmed", "ts": 200}]},
            {"id": 4, "title": "A health check", "state_since": 100, "check": {"type": "health_issue_absent"}, "evidence": []}]
    got = SC.publish(lambda op, args, actor, **k: {"ok": True, "result": arts if op == "artifacts_in" else None})
    assert got["to_confirm"] == [{"id": 1, "title": "Waits", "state_since": 100}, {"id": 3, "title": "Said before it shipped again", "state_since": 300}]
    assert "checking" not in got
    assert CK.evaluate(arts[1], None, now=400)[0] == "pass" and CK.evaluate(arts[0], None, now=400)[0] == "wait"


def test_the_house_step_in_the_queue_is_the_one_the_house_page_names(DQ):
    fn = re.search(r"^function houseSteps\(.*?^\}", APP_JS, re.M | re.S)[0]
    cases = [{"reachable": True}, {"reachable": True, "onboarded": True}, {"reachable": True, "onboarded": True, "connected": True},
             {"reachable": True, "onboarded": True, "connected": True, "integrations": [{"domain": "alexa_devices"}]}]
    js = "const esc = (x) => x, DEPLOY = {};" + fn + f"process.stdout.write(JSON.stringify({json.dumps(cases)}.map((h) => (houseSteps(h).find((x) => !x.done && !x.optional) || {{}}).title || null)));"
    want = json.loads(subprocess.run(["node", "-e", js], check=True, capture_output=True, text=True).stdout)
    got = [(list(DQ._house({"house": h})) or [{"why": None}])[0]["why"] for h in cases]
    assert got == [f"next: {w.lower()}" if w else None for w in want] and want[-1] is None


def test_the_server_adds_the_waits_only_it_sees_and_the_app_draws_the_list():
    src = pysrc.server()
    fn = re.search(r"^def owner_decisions\(s\):.*?^    return .*?$", src, re.M | re.S)[0]
    ns = {}
    exec(fn, ns)
    out = ns["owner_decisions"]({"phone": {"pending": 2}, "connections": {"pending": 1}, "decisions": [{"id": "build:4"}]})
    assert [d["id"] for d in out] == ["phone-ask", "gmail-trash", "build:4"] and out[0]["what"] == "The AI phone asks for 2 approvals"
    assert src.count('["decisions"] = owner_decisions(') == 2                    # the state and the stream
    js = "\n".join([re.search(rf"^function {n}\(.*?^\}}", APP_JS, re.M | re.S)[0] for n in ("decideGroups",)]) + """
const g = decideGroups([{ id: "a", cls: "phone-routine", routine: true }, { id: "b", cls: "coding" }, { id: "c", cls: "phone-routine", routine: true },
  { id: "d", cls: "memory", routine: true }]);
const ids = (x, l) => ({ label: l || "Approve", act: { action: "phone_cleanup_do_all", ids: [x] } });
const all = [decideAll([{ answers: [ids("a")] }, { answers: [ids("b")] }]), decideAll([{ answers: [ids("a")] }, { answers: [{ label: "Remember", act: { action: "memory", id: 1 } }] }]), decideAll([{ answers: [{ href: "#/x" }] }])];
process.stdout.write(JSON.stringify([g.map((x) => x.one ? x.one.id : x.items.map((i) => i.id)), all]));"""
    js = re.search(r"^function decideAll\(.*?^\}", APP_JS, re.M | re.S)[0] + js
    grouped, together = json.loads(subprocess.run(["node", "-e", js], check=True, capture_output=True, text=True).stdout)
    assert grouped == [["a", "c"], "b", "d"]
    assert together == [{"label": "Approve", "act": {"action": "phone_cleanup_do_all", "ids": ["a", "b"]}}, None, None]   # a mixed group is answered one by one
    assert "decide: vDecide" in APP_JS and 'const LIVE = new Set(["home", "decide"])' in APP_JS and 'href="#/decide"' in APP_JS

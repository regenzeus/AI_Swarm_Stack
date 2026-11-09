"""Customisation (TSK-28 to TSK-30): an agent's settings changed in the app become an agent change that is replayed
before it applies (no score may drop), a tool added is a grant the owner confirms and is recorded as a security change,
a tool removed needs only the replay; and the composer's chosen agents and model do the task's steps, marked as the
owner's choice, and routing leaves them alone."""
import types

import pytest

import conductor as CD
import ledger as Lm
import swarm_client as SC
import tasks as TK

CARDS = {"scout": {"id": "scout", "harness": "hermes", "model": "gpt-sub-fast", "tools": ["fetch", "browser"], "instructions": ["cite every claim"]},
         "inbox": {"id": "inbox", "harness": "python", "model": "gpt-sub-fast", "tools": ["mail"], "instructions": []}}
MODELS = {"gpt-sub", "gpt-sub-fast", "claude-sonnet-5-5"}


@pytest.fixture
def send(monkeypatch):
    calls = []

    def fake(op, args, actor, by="", run=""):
        calls.append((op, args, actor))
        return {"ok": True, "result": {"id": 41} if op == "upsert" else {}}
    monkeypatch.setattr(SC, "publish", lambda: None)
    fake.calls = calls
    return fake


def test_an_agent_s_model_change_is_an_agent_change_put_up_for_its_replay(send):
    r = SC.agent_change({"agent": "scout", "change": {"model": "gpt-sub", "harness": "hermes", "tools": ["fetch", "browser"],
                                                      "instructions": ["cite every claim"]}, "why": "better searches"}, "owner", send, CARDS, MODELS)
    assert r == {"id": 41, "diff": ["model: gpt-sub-fast → gpt-sub"], "security": None}
    op, args, actor = send.calls[0]
    assert (op, actor, args["kind"]) == ("upsert", "owner", "agent_change")
    assert args["plan"]["change"] == {"model": "gpt-sub"} and args["plan"]["target"] == {"score": None, "why": "better searches"}
    assert [(c[0], c[1].get("to")) for c in send.calls[1:]] == [("transition", "open"), ("transition", "ready")]
    with pytest.raises(ValueError, match="nothing changes"):
        SC.agent_change({"agent": "scout", "change": {"model": "gpt-sub-fast"}}, "owner", send, CARDS, MODELS)
    with pytest.raises(ValueError, match="no model the gateway serves"):
        SC.agent_change({"agent": "scout", "change": {"model": "gpt-99"}}, "owner", send, CARDS, MODELS)
    with pytest.raises(ValueError, match="no such agent"):
        SC.agent_change({"agent": "nobody", "change": {"model": "gpt-sub"}}, "owner", send, CARDS, MODELS)


def test_a_tool_added_is_a_grant_the_owner_confirms_and_a_tool_removed_needs_only_the_replay(send):
    with pytest.raises(ValueError, match="tick the grant"):
        SC.agent_change({"agent": "scout", "change": {"tools": ["fetch", "browser", "mail"]}}, "owner", send, CARDS, MODELS)
    assert not send.calls                                                           # nothing filed without the grant
    r = SC.agent_change({"agent": "scout", "change": {"tools": ["fetch", "browser", "mail"]}, "grant": True}, "owner", send, CARDS, MODELS)
    assert r["security"] == {"adds": ["mail"], "granted_by": "owner"} and "ops/keys.sh" in send.calls[0][1]["plan"]["files"]
    ev = [c for c in send.calls if c[0] == "evidence"]
    assert len(ev) == 1 and ev[0][1]["text"].startswith("security change: adds mail to scout's key grants")
    send.calls.clear()
    r = SC.agent_change({"agent": "scout", "change": {"tools": ["fetch"]}}, "owner", send, CARDS, MODELS)
    assert r["diff"] == ["tools: removes browser"] and r["security"] is None and not [c for c in send.calls if c[0] == "evidence"]
    with pytest.raises(ValueError, match="no such tool"):
        SC.agent_change({"agent": "scout", "change": {"tools": ["rm-rf"]}, "grant": True}, "owner", send, CARDS, MODELS)


def test_the_owner_s_change_passes_its_replay_only_when_no_score_drops():
    base = {"valid": 0.9, "keeps_proven": 0.8, "avoids_declined": 0.7, "avoids_duplicates": 0.9, "no_noise": 0.8}
    assert Lm.gate(base, dict(base), None)[0] is True                               # nothing worse: it may apply
    worse = {**base, "keeps_proven": 0.6}
    ok, why = Lm.gate(base, worse, None)
    assert not ok and "keeps_proven 0.80 -> 0.60" in why
    assert Lm.gate(base, dict(base), "valid")[0] is False                            # the Coach's target must still rise


@pytest.fixture
def K(tmp_path, monkeypatch):
    import sqlite3
    import threading
    import runtime as RTM
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    TK.table(c)
    CD.table(c)
    import missions as MM
    TK.M = CD.M = types.SimpleNamespace(event=lambda *a, **k: None, valid_schedule=MM.valid_schedule, X=types.SimpleNamespace(clean_triggers=lambda t: t),
                                        notify_task=lambda *a: None, paused=lambda s: False, stop=threading.Event(), log=print)
    monkeypatch.setattr(TK, "B_repos", lambda: ["ai-stack"])
    for f in ("start", "end", "set_ref"):
        monkeypatch.setattr(RTM, f, lambda *a, **k: None)
    monkeypatch.setattr(CD, "mapped", lambda *a, **k: None)
    return c


def test_the_composer_s_chosen_agents_and_model_do_the_steps_as_the_owner_s_choice(K, monkeypatch):
    with pytest.raises(ValueError, match="no agent that runs task steps: nobody"):      # named, never dropped (review SWM-R12)
        TK.handle({"action": "task_create", "text": "Compare the three cheapest 32 GB kits", "agents": ["scout", "desk", "nobody"]}, K)
    tid = TK.handle({"action": "task_create", "text": "Compare the three cheapest 32 GB kits", "agents": ["scout", "desk"], "model": "gpt-sub"}, K)["task"]
    assert TK.row(K, tid)["spec"]["preset"] == {"agents": ["scout", "desk"], "model": "gpt-sub"}
    plan = [{"step": "find offers", "agent": "scout", "why": "web", "after": []},
            {"step": "compare them", "agent": "mission", "why": "works through it", "after": [1]},
            {"step": "write it up", "agent": "planner", "why": "reasons", "after": [2]}]
    TK.intake(K, tid, ask=lambda p: {"title": "RAM kits", "goal": "compare", "kind": "research", "done": ["names three kits with prices"],
                                     "rhythm": {"type": "once"}, "plan": plan, "questions": []})
    ss = CD.steps(K, tid)
    assert [s["agent"] for s in ss] == ["scout", "desk", "scout"]
    assert ss[0]["why"].endswith("(your choice)") and "(your choice: desk instead of mission)" in ss[1]["why"]
    assert (ss[1]["harness"], ss[1]["model"]) == ("python", "gpt-sub") and ss[0]["model"] == "gpt-sub-fast"   # a Hermes step keeps its profile's model
    routed = []
    monkeypatch.setattr(CD, "routed", lambda c, t, s, agents: routed.append(s["idx"]) or s)
    monkeypatch.setattr(CD, "headroom", lambda s: None)
    monkeypatch.setattr(CD, "ADAPTERS", {"hermes": lambda *a: "x", "python": lambda *a: "x"})
    CD.tick(K, start_thread=lambda f: None)
    assert routed == []                                                             # the owner's choice is never routed away
    with pytest.raises(ValueError, match="no model the gateway serves"):
        TK.handle({"action": "task_create", "text": "Compare the three cheapest kits", "model": "gpt-99"}, K)

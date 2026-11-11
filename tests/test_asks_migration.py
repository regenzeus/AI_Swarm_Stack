"""ASK-12, ASK-13: every Needs you source is an Ask (ops/decisions.py asks_sync, server.asks.py) and none is lost: each
item opens its Ask with its answers as chips, a dismissed or put-off item leaves the list, an answer runs the item's own
request, an item its source dropped is settled, and the app's own waits are Asks it hides when dismissed."""
import importlib
import json

import pytest

import asks as A
from test_decisions import state as full

T0 = 1793600000.0


@pytest.fixture
def DQ(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMY_LOG", str(tmp_path / "autonomy.jsonl"))
    monkeypatch.setattr(A, "TYPES", {})
    import decisions
    m = importlib.reload(decisions)
    m._seen.clear(); m._loaded["t"] = 0
    return m


def rich():
    st = full()
    st["crew"].append({"id": "memory", "suggestions": [{"id": "f1", "text": "x", "why": "y"}]})
    st["tasks"].append({"id": 20, "status": "failed", "kind": "change", "door": "plan", "title": "Fix", "error": "budget"})
    st["house"] = {"reachable": True}
    st["swarm"]["to_confirm"] = [{"id": 31, "title": "The Echo speaks"}]
    return st


def test_every_needs_you_source_becomes_an_ask_and_none_is_lost(DQ):
    st = rich()
    items = DQ.gather(st, now=T0)
    out = DQ.state(st, T0)["decisions"]
    assert len(out) == len(items) and all(d.get("ask") for d in out)
    asks = {a["source"]: a for a in A.listing(("open",))}
    assert set(asks) == {f"dq:{d['id']}" for d in items}
    for d in items:
        a = asks[f"dq:{d['id']}"]
        assert a["question"] == d["what"] and len(a["choices"]) == len(d["answers"])
        for x, ch in zip(d["answers"], a["choices"]):
            assert ch["label"] == x["label"] and (ch.get("href") == x.get("href") if x.get("href") else a["acts"][ch["id"]]["action"] == x["act"]["action"])
    floor = {k for k, v in DQ.classes().items() if v.get("floor")}
    assert all(A.TYPES[k]["gate"] for k in floor) and not A.TYPES["phone-routine"]["gate"]
    assert asks["dq:build:4"]["gate"] is False and asks["dq:shop:p-1"]["gate"] is True            # buying: only the owner's tap
    pub = A.published(now=T0)
    assert len(pub["asks"]) == len(items) and not any("acts" in a for a in pub["asks"])           # the page never sees the acts
    assert DQ.state(st, T0)["decisions"] == out                                                   # a second pass changes nothing


def test_a_dismissed_or_put_off_item_leaves_needs_you_and_an_answer_runs_the_items_own_request(DQ):
    st = rich()
    out = {d["id"]: d for d in DQ.state(st, T0)["decisions"]}
    A.dismiss(out["memory:m1"]["ask"], answer_id="dis-mem00001", person="me@x", now=T0)
    A.later(out["task:9"]["ask"], answer_id="lat-task0001", person="me@x", words="in 2 hours", now=T0)
    ids = {d["id"] for d in DQ.state(st, T0)["decisions"]}
    assert "memory:m1" not in ids and "task:9" not in ids and "keeper:f1" in ids
    A.tick(now=T0 + 7201)
    assert "task:9" in {d["id"] for d in DQ.state(st, T0 + 7201)["decisions"]}
    sent = []
    A.DISPATCH[0] = lambda req: sent.append(req) or {"ok": True, "message": "Approved"}
    keep = out["keeper:f1"]["ask"]
    A.answer(keep, answer_id="ans-keeper01", person="me@x", via="app", outcome="forget", chip=True, now=T0)
    assert "keeper:f1" not in {d["id"] for d in DQ.state(st, T0)["decisions"]}                   # answered: it leaves the list at once
    A.tick(now=T0 + A.HOLD_S)
    assert sent == [{"action": "crew_memory_forget", "ids": ["f1"], "who": "me@x", "source": "ask", "ask": keep}]


def test_a_chip_that_takes_words_carries_them_into_its_request(DQ):
    st = rich()
    out = {d["id"]: d for d in DQ.state(st, T0)["decisions"]}
    a = A.get(out["confirm:31"]["ask"])
    broken = next(c for c in a["choices"] if c["label"] == "Still broken")
    assert broken["words"] == "What is still broken?"
    with pytest.raises(ValueError, match="What is still broken"):
        A.answer(a["id"], answer_id="ans-broken01", person="me@x", via="app", outcome=broken["id"], chip=True, now=T0)
    A.answer(a["id"], answer_id="ans-broken02", person="me@x", via="app", outcome=broken["id"], chip=True, words="It speaks twice", now=T0)
    sent = []
    A.DISPATCH[0] = lambda req: sent.append(req) or {"ok": True}
    A.tick(now=T0 + A.HOLD_S)
    assert sent[0]["action"] == "swarm_reopen" and sent[0]["reason"] == "It speaks twice"


def test_an_item_its_source_dropped_is_settled_and_comes_back_as_a_new_round(DQ):
    st = rich()
    one = {d["id"]: d for d in DQ.state(st, T0)["decisions"]}["build:4"]["ask"]
    st["builds"] = []
    DQ.state(st, T0 + 10)
    a = A.get(one)
    assert a["status"] == "answered" and a["answer"]["via"] == "elsewhere" and a["gone"]
    st["builds"] = full()["builds"]
    assert "build:4" in {d["id"] for d in DQ.state(st, T0 + 20)["decisions"]} and A.get(one)["status"] == "open"
    assert [h["event"] for h in A.history(one)] == ["opened", "settled", "again", "opened"]


def test_an_item_the_store_cannot_take_stays_in_the_list(DQ, monkeypatch):
    st = rich()
    monkeypatch.setattr(A, "open_ask", lambda *a, **k: (_ for _ in ()).throw(ValueError("refused by the data rule")))
    said = []
    out = DQ.asks_sync(DQ.gather(st, now=T0), now=T0, log=said.append)
    assert len(out) == len(DQ.gather(st, now=T0)) and said and "refused by the data rule" in said[0]


def test_the_apps_own_waits_are_asks_it_hides_when_dismissed_and_answers_wait_in_the_inbox(tmp_path):
    import server as SV
    items = [{"id": "phone-ask", "what": "x"}, {"id": "gmail-trash", "what": "y"}, {"id": "build:4", "ask": "abc"}]
    out = SV.app_asks(items, [])
    assert [d["ask"] for d in out] == [A.ask_id("srv:phone-ask"), A.ask_id("srv:gmail-trash"), "abc"] and out[0]["source_key"] == "srv:phone-ask"
    assert [d["id"] for d in SV.app_asks(items, [A.ask_id("srv:gmail-trash")])] == ["phone-ask", "build:4"]
    (tmp_path / "1.json").write_text(json.dumps({"action": "ask_answer", "id": "abc", "answer_id": "x1", "outcome": "go"}))
    (tmp_path / "2.json").write_text(json.dumps({"action": "run", "slug": "u"}))
    q = SV.queued_answers(tmp_path)
    assert [(x["id"], x["outcome"]) for x in q] == [("abc", "go")]

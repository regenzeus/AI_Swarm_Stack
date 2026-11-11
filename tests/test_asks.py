"""Asks (ASK-01..ASK-08, ops/asks.py): one durable kind of question, tiers and standing rules, roles and gates, the data
rule and channels. A gate gets one test per path that must never resolve it."""
import json
import sqlite3

import pytest

import asks as A
from domain import roles as RL

T0 = 1_800_000_000.0


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ASKS_DIR", str(tmp_path / "asks"))
    monkeypatch.setenv("AISTACK_ROLES", str(tmp_path / "none.yaml"))
    monkeypatch.setattr(A, "TYPES", {})
    monkeypatch.setattr(A, "APPLY", {})
    A.register("toy", "A toy question", action="answer", outcomes=(("go", "Go"), ("stop", "Stop")), values={"km": "number"})
    A.register("toy-gate", "A toy gate", action="deploy", outcomes=(("approve", "Approve"), ("reject", "Reject")), gate=True, role="reviewer")
    done = []
    A.APPLY["toy"] = A.APPLY["toy-gate"] = lambda a, ans: done.append((a["id"], ans["outcome"])) or "did it"
    return done


def roles(tmp_path, monkeypatch, text="owner: [own@x]\ndefault: [owner]\nroles:\n  reviewer: {people: [rev@x], escalate: [lead]}\n  lead: [lead@x]\n"):
    f = tmp_path / "roles.yaml"
    f.write_text(text)
    monkeypatch.setenv("AISTACK_ROLES", str(f))


def q(kind="toy", source="toy:1", **kw):
    return A.open_ask({"kind": kind, "source": source, "question": "Go ahead with the toy?", **kw}, now=T0)


def test_an_ask_and_its_answer_survive_a_restart_and_an_answer_id_applies_once(store, tmp_path):
    a = q()
    assert a["status"] == "open" and A.open_ask({"kind": "toy", "source": "toy:1", "question": "Go ahead with the toy?"}, now=T0)["id"] == a["id"]
    r = A.answer(a["id"], answer_id="ans-00000001", person="me@x", via="app", outcome="go", chip=True, now=T0)
    assert r["label"] == "Go" and r["undo_until"] == T0 + A.HOLD_S
    again = A.answer(a["id"], answer_id="ans-00000001", person="me@x", via="app", outcome="go", chip=True, now=T0 + 1)
    assert again["again"]
    c = sqlite3.connect(tmp_path / "asks" / "asks.db")          # a new process: the store holds it
    assert c.execute("select status from asks").fetchone()[0] == "answered" and c.execute("pragma journal_mode").fetchone()[0] == "wal"
    assert A.tick(now=T0 + A.HOLD_S) and store == [(a["id"], "go")]
    assert A.tick(now=T0 + A.HOLD_S + 5) == [] and store == [(a["id"], "go")]


def test_an_answer_is_held_for_its_undo_then_applied_and_a_refusal_reopens_it(store):
    a = q()
    A.answer(a["id"], answer_id="ans-00000002", person="me@x", via="app", outcome="stop", chip=True, now=T0)
    assert A.tick(now=T0 + 1) == [] and store == []
    assert A.undo(a["id"], answer_id="ans-00000002", person="me@x", now=T0 + 2)["status"] == "open"
    assert A.tick(now=T0 + 100) == [] and store == []
    A.APPLY["toy"] = lambda a, ans: (_ for _ in ()).throw(ValueError("the build is gone"))
    A.answer(a["id"], answer_id="ans-00000003", person="me@x", via="app", outcome="go", chip=True, now=T0 + 3)
    A.tick(now=T0 + 100)
    b = A.get(a["id"])
    assert b["status"] == "open" and "the build is gone" in b["error"]
    with pytest.raises(ValueError, match="done already"):
        A.APPLY["toy"] = lambda a, ans: "ok"
        A.answer(a["id"], answer_id="ans-00000004", person="me@x", via="app", outcome="go", chip=True, now=T0 + 200)
        A.tick(now=T0 + 300)
        A.undo(a["id"], answer_id="ans-00000004", person="me@x", now=T0 + 301)


def test_tiers_do_and_tell_act_with_an_undo_record_ask_asks_never_refuses(store, tmp_path, monkeypatch):
    pol = A.policy()
    A.register("tidy", "Tidy up", action="tidy", outcomes=(("yes", "Yes"), ("no", "No")))
    for tr, status in (("ask", "open"), ("do", "answered"), ("tell", "answered")):
        pol["tiers"]["tidy"] = tr
        a = A.open_ask({"kind": "tidy", "source": f"tidy:{tr}", "question": "Tidy the cache?", "acts": {"yes": {"action": "x"}},
                        "undo": {"yes": {"action": "x_undo", "hours": 2}}}, now=T0, pol=pol)
        assert a["status"] == status, tr
    told, sent = [], []
    A.DISPATCH[0] = lambda req: sent.append(req) or {"ok": True}
    A.tick(now=T0, notify=lambda text, *a: told.append(text))
    assert len(told) == 1 and told[0].startswith("Done for you")
    recs = A.undo_records(now=T0)
    assert len(recs) == 2 and recs[0]["until"] == T0 + 7200
    A.undo_action(recs[0]["id"], "me@x", now=T0 + 10)
    assert sent[-1]["action"] == "x_undo"
    pol["tiers"]["tidy"] = "never"
    with pytest.raises(ValueError, match="never"):
        A.open_ask({"kind": "tidy", "source": "tidy:never", "question": "Tidy the cache?"}, now=T0, pol=pol)


def test_the_stack_policy_names_a_tier_for_every_action_kind_and_a_deployment_overrides_it():
    base = A.policy(folder=A.ROOT / "deployments/home")
    assert set(base["tiers"].values()) <= set(A.TIERS) and base["tiers"]["deploy"] == "ask" and base["tiers"]["credentials"] == "never"
    assert base["channels"] == ["app", "ticket", "telegram"] and base["tickets"] == {"tracker": "inbox"}
    work = A.policy(folder=A.ROOT / "deployments/example-work")
    assert work["tiers"]["deploy"] == "never" and "telegram" not in work["channels"] and work["data"]["extract_paths"]


def test_a_standing_rule_answers_its_kind_under_its_limit_and_says_who_made_it(store):
    r = A.rule_save({"kind": "toy", "effect": "allow", "outcome": "go", "under": {"fact": "size_gb", "max": 1}}, "me@x", T0)
    assert r["by"] == "me@x" and r["at"] == T0
    small = A.open_ask({"kind": "toy", "source": "toy:s", "question": "Clean 0.4 GB?", "facts": {"size_gb": "0.4"}}, now=T0)
    big = A.open_ask({"kind": "toy", "source": "toy:b", "question": "Clean 3 GB?", "facts": {"size_gb": "3"}}, now=T0)
    assert small["status"] == "answered" and small["answer"]["via"].startswith("rule:") and big["status"] == "open"
    A.rule_delete(r["id"], "me@x")
    assert A.rules() == []
    a = A.open_ask({"kind": "toy", "source": "toy:al", "question": "Go?"}, now=T0)
    A.answer(a["id"], answer_id="ans-always1", person="me@x", via="app", outcome="go", chip=True, always=True, now=T0)
    assert A.rules()[0]["kind"] == "toy" and A.rules()[0]["by"] == "me@x"


def test_dismiss_and_later_work_on_every_ask_and_later_understands_tomorrow_morning(store):
    a, b = q(source="toy:d"), q(source="toy:l")
    assert A.dismiss(a["id"], answer_id="dis-0000001", person="me@x", words="not mine", now=T0)["status"] == "dismissed"
    assert q(source="toy:d")["status"] == "dismissed"              # its source lists it again: it stays dismissed
    s = A.later(b["id"], answer_id="lat-0000001", person="me@x", words="tomorrow morning", now=T0)
    assert s["status"] == "snoozed" and A.when("tomorrow morning", T0) == s["wake"]
    assert A.tick(now=s["wake"] - 1) == [] and A.tick(now=s["wake"]) == [f"{b['id']} woke"] and A.get(b["id"])["status"] == "open"
    for words in ("tonight", "in 3 hours", "next week", "friday", "2027-12-01", "january", "in April"):
        assert A.when(words, T0) > T0, words
    with pytest.raises(ValueError, match="say when"):
        A.later(b["id"], answer_id="lat-0000002", person="me@x", words="whenever", now=T0)
    srv = A.ask_id("srv:phone-ask")                                # an Ask only the app sees: recorded so the app hides it
    A.dismiss(srv, answer_id="dis-0000002", person="me@x", source="srv:phone-ask", now=T0)
    assert srv in A.published(now=T0)["asks_hidden"]


def test_a_default_applies_at_its_deadline_and_says_so_and_one_without_expires(store):
    a = q(source="toy:def", default={"outcome": "stop"}, deadline=T0 + 60)
    b = q(source="toy:exp", deadline=T0 + 60)
    A.tick(now=T0 + 61)
    assert A.get(a["id"])["answer"]["via"] == "default" and A.get(a["id"])["answer"]["why"] == "applied by default at its deadline"
    assert A.get(b["id"])["status"] == "expired"
    A.tick(now=T0 + 62)
    assert store == [(a["id"], "stop")]


def test_words_wait_for_the_interpreter_and_its_reading_is_held_with_understood_as(store):
    a = q()
    assert A.answer(a["id"], answer_id="wrd-0000001", person="me@x", via="app", words="go, 23 km", now=T0)["reading"]
    assert [x["answer_id"] for x in A.reading()] == ["wrd-0000001"]
    b = A.understood(a["id"], "wrd-0000001", {"outcome": "go", "values": {"km": 23, "evil": 1}, "understood": "Go, 23 km"}, now=T0 + 1)
    assert b["status"] == "answered" and b["answer"]["interpreted_as"] == "Go, 23 km" and b["answer"]["values"] == {"km": 23}
    c = q(source="toy:2")
    A.answer(c["id"], answer_id="wrd-0000002", person="me@x", via="app", words="hm", now=T0)
    d = A.understood(c["id"], "wrd-0000002", {"ask_back": "Go or stop?"}, now=T0)
    assert d["status"] == "open" and d["pending"]["ask_back"] == "Go or stop?"


def test_roles_come_from_the_deployment_and_nobody_answers_without_a_sign_in(store, tmp_path, monkeypatch):
    a = q()
    for person in ("", "owner"):                                  # review 10 Nov O8: the page's word is no sign-in
        with pytest.raises(ValueError, match="only the owner"):
            A.answer(a["id"], answer_id="ans-noone01", person=person, via="app", outcome="go", chip=True, now=T0)
    roles(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="only own@x"):
        A.answer(a["id"], answer_id="ans-noone02", person="someone@x", via="app", outcome="go", chip=True, now=T0)
    assert A.answer(a["id"], answer_id="ans-owner01", person="own@x", via="app", outcome="go", chip=True, now=T0)["label"] == "Go"
    monkeypatch.delenv("AISTACK_ROLES")
    monkeypatch.setenv("AISTACK_DEPLOYMENT", "example-work")
    assert RL.path().name == "roles.yaml" and RL.path().parent.name == "example-work"
    assert RL.holds("reviewer", "anna@example.com") and not RL.holds("reviewer", "a@example.com")
    assert RL.escalation("reviewer") == ["lead", "owner"]
    with pytest.raises(ValueError, match="signed-in person"):
        A.handle({"action": "ask_answer", "id": a["id"], "answer_id": "ans-nobody1", "outcome": "go", "source": "app"})


# ---------------------------------------------------------------- the gate: one test per path that must never resolve it
def gate(tmp_path, monkeypatch, **kw):
    roles(tmp_path, monkeypatch)
    return A.open_ask({"kind": "toy-gate", "source": "gate:1", "question": "Approve the release record?", **kw}, now=T0)


def test_only_a_role_holders_explicit_chip_tap_in_the_app_resolves_a_gate(store, tmp_path, monkeypatch):
    g = gate(tmp_path, monkeypatch)
    assert g["gate"] and not g["allow_words"] and g["role"] == "reviewer"
    with pytest.raises(ValueError, match="only rev@x"):
        A.answer(g["id"], answer_id="gat-0000001", person="own@x", via="app", outcome="approve", chip=True, now=T0)
    with pytest.raises(ValueError, match="in the app"):
        A.answer(g["id"], answer_id="gat-0000002", person="rev@x", via="telegram", outcome="approve", chip=True, now=T0)
    r = A.answer(g["id"], answer_id="gat-0000003", person="rev@x", via="app", outcome="approve", chip=True, now=T0)
    assert r["label"] == "Approve" and A.get(g["id"])["answer"]["person"] == "rev@x" and A.get(g["id"])["answer"]["role"] == "reviewer"


def test_a_gate_is_never_resolved_by_free_text(store, tmp_path, monkeypatch):
    g = gate(tmp_path, monkeypatch)
    r = A.answer(g["id"], answer_id="gat-0000004", person="rev@x", via="app", words="yes approve it, looks fine", now=T0)
    assert r["comment"] and A.get(g["id"])["status"] == "open" and A.get(g["id"])["comments"][0]["words"].startswith("yes approve")
    A.tick(now=T0 + 3600)
    assert store == []


def test_a_gate_is_never_resolved_by_the_interpreter_only_a_suggested_chip(store, tmp_path, monkeypatch):
    g = gate(tmp_path, monkeypatch)
    A.answer(g["id"], answer_id="gat-0000005", person="rev@x", via="app", words="approve", now=T0)
    b = A.understood(g["id"], "gat-0000005", {"outcome": "approve", "understood": "Approve"}, now=T0 + 1)
    assert b["status"] == "open" and b["pending"]["suggest"] == "approve" and b["answer"] is None
    with pytest.raises(ValueError, match="tap"):
        A.answer(g["id"], answer_id="gat-0000006", person="rev@x", via="app", outcome="approve", interpreted_as="Approve", now=T0)
    A.tick(now=T0 + 3600)
    assert store == []


def test_a_gate_is_never_resolved_by_a_tier_policy(store, tmp_path, monkeypatch):
    roles(tmp_path, monkeypatch)
    pol = A.policy()
    pol["tiers"]["deploy"] = "do"
    g = A.open_ask({"kind": "toy-gate", "source": "gate:t", "question": "Approve?"}, now=T0, pol=pol)
    assert g["status"] == "open" and A.tier("toy-gate", pol)[0] == "ask"


def test_a_gate_is_never_resolved_by_a_standing_rule(store, tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="never takes a standing rule"):
        A.rule_save({"kind": "toy-gate", "effect": "allow", "outcome": "approve"}, "own@x")
    A.rules_path().parent.mkdir(parents=True, exist_ok=True)
    A.rules_path().write_text(json.dumps([{"id": "r1", "kind": "toy-gate", "effect": "allow", "outcome": "approve"}]))   # by hand
    g = gate(tmp_path, monkeypatch)
    assert g["status"] == "open" and A.rule_for(g) is None
    with pytest.raises(ValueError, match="never takes a standing rule"):
        A.answer(g["id"], answer_id="gat-0000007", person="rev@x", via="app", outcome="approve", chip=True, always=True, now=T0)


def test_a_gate_has_no_default_and_its_deadline_reminds_then_escalates_and_never_proceeds(store, tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="no default"):
        A.register("bad-gate", "x", action="deploy", gate=True, default={"outcome": "yes"})
    with pytest.raises(ValueError, match="no default"):
        gate(tmp_path, monkeypatch, default={"outcome": "approve"}, source="gate:d")
    g = gate(tmp_path, monkeypatch, deadline=T0 + 60)
    told = []
    note = lambda text, *a: told.append(text)                     # noqa: E731
    assert A.tick(now=T0 + 61, notify=note) == [f"{g['id']} reminded"]
    assert A.tick(now=T0 + 120, notify=note) == []
    assert A.tick(now=T0 + 61 + A.ESCALATE_H * 3600, notify=note) == [f"{g['id']} escalated to lead"]
    e = A.get(g["id"])
    assert e["status"] == "escalated" and e["role"] == "lead" and store == []
    assert A.tick(now=T0 + 61 + 2 * A.ESCALATE_H * 3600 + 10, notify=note)[0].endswith("escalated to owner")
    assert A.get(g["id"])["status"] == "escalated" and store == [] and len(told) == 3


def test_a_gate_is_never_resolved_by_a_group_answer_or_digest(store, tmp_path, monkeypatch):
    g = gate(tmp_path, monkeypatch)
    q(kind="toy-gate", source="gate:2")
    r = A.group_answer("toy-gate", answer_id="grp-0000001", person="rev@x", outcome="approve", now=T0)
    assert r["answered"] == [] and len(r["left"]) == 2 and A.get(g["id"])["status"] == "open"
    with pytest.raises(ValueError, match="one by one"):
        A.answer(g["id"], answer_id="gat-0000008", person="rev@x", via="app", outcome="approve", chip=True, group=True, now=T0)
    q(source="toy:g1"), q(source="toy:g2")
    one = A.ask_id("toy:g2")
    r = A.group_answer("toy", answer_id="grp-0000002", person="own@x", outcome="go", overrides={one: "stop"}, now=T0)
    assert len(r["answered"]) == 2 and A.get(one)["answer"]["outcome"] == "stop"


def test_the_data_rule_refuses_extracts_and_over_the_cap_and_marks_private(store):
    pol = A.policy(folder=A.ROOT / "deployments/example-work")
    with pytest.raises(ValueError, match="by reference"):
        A.open_ask({"kind": "toy", "source": "toy:x", "question": "Is /data/extracts/run-3 right?"}, now=T0, pol=pol)
    with pytest.raises(ValueError, match="the limit is 2,000"):
        A.open_ask({"kind": "toy", "source": "toy:x", "question": "Ok?", "facts": {"note": "w" * 2001}}, now=T0, pol=pol)
    a = A.open_ask({"kind": "toy", "source": "toy:p", "question": "Is the confidential plan ready?", "refs": ["/srv/ai/work/plan.md"]}, now=T0, pol=pol)
    assert a["sensitivity"] == "private" and A.outward(a).startswith("A private question") and "confidential" not in A.outward(a)
    with pytest.raises(ValueError, match="local path"):
        A.open_ask({"kind": "toy", "source": "toy:r", "question": "Ok?", "refs": ["http://x"]}, now=T0, pol=pol)


def test_a_channel_that_is_off_sends_nothing():
    pol = {"channels": ["app", "ticket", "telegram"]}
    assert A.channels(pol, has=lambda f: False) == ["app", "ticket"]
    assert A.channels(pol, has=lambda f: True) == ["app", "ticket", "telegram"]
    assert A.channels({"channels": ["app", "pigeon"]}, has=lambda f: True) == ["app"]


def test_the_stop_switch_records_who_and_what_it_paused(store):
    assert not A.stopped()
    A.handle({"action": "ask_stop", "on": True, "who": "me@x", "source": "app"})
    assert A.stopped() and A.stop_state()["by"] == "me@x"
    A.handle({"action": "ask_stop", "on": False, "who": "me@x", "source": "app"})
    assert not A.stopped()


def test_an_undo_that_arrives_before_its_answer_keeps_the_answer_from_acting_and_the_app_sees_who_answers(store, tmp_path, monkeypatch):
    a = q()
    A.undo(a["id"], answer_id="ans-early001", person="me@x", now=T0)            # the inbox has no order: the undo came first
    r = A.answer(a["id"], answer_id="ans-early001", person="me@x", via="app", outcome="go", chip=True, now=T0 + 1)
    assert r["message"] == "Undone before it arrived" and A.get(a["id"])["status"] == "open"
    A.tick(now=T0 + 100)
    assert store == []
    roles(tmp_path, monkeypatch)
    g = A.open_ask({"kind": "toy-gate", "source": "gate:p", "question": "Approve?"}, now=T0)
    pub = {x["id"]: x for x in A.published(now=T0)["asks"]}
    assert pub[g["id"]]["people"] == ["rev@x"] and pub[a["id"]]["people"] == ["own@x"] and "acts" not in pub[g["id"]]


def test_threads_each_keep_one_connection_and_write_together_with_nothing_lost_or_applied_twice(store):
    """ASK-21: on 11 Nov 2026 the runner died twice (SIGSEGV) during the first sync, many threads opening fresh connections
    to a store still being made. Each thread now keeps one connection; eight threads writing at once lose nothing and
    apply each answer once, and a connection is never usable from another thread."""
    import threading
    errors, mine = [], {}

    def work(n):
        try:
            c = A.connect()
            assert c is A.connect()
            mine[n] = id(c)
            for i in range(25):
                a = A.open_ask({"kind": "toy", "source": f"toy:t{n}:{i}", "question": "Go?"}, now=T0)
                A.open_ask({"kind": "toy", "source": "toy:shared", "question": "Go?"}, now=T0)
                A.answer(a["id"], answer_id=f"ans-{n:02d}-{i:04d}", person="me@x", via="app", outcome="go", chip=True, now=T0)
                A.published(now=T0)
                A.tick(now=T0 + A.HOLD_S)
        except Exception as e:                       # collected: the test names it
            errors.append(e)
    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert errors == [] and len(set(mine.values())) == 8
    A.tick(now=T0 + A.HOLD_S)
    assert len(A.listing(A.STATUSES)) == 8 * 25 + 1 and len(store) == 8 * 25 and len(set(store)) == 8 * 25
    c, crossed = A.connect(), []
    th = threading.Thread(target=lambda: crossed.append(pytest.raises(sqlite3.ProgrammingError, c.execute, "select 1")))
    th.start()
    th.join()
    assert crossed

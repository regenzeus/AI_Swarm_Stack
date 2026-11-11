"""ASK-17, ASK-18: the ticket as the record of Asks (ops/asks_tickets.py) on the stand-in tracker: one ticket per task or
decision, never one per Ask; opening it is a tracker write of its own kind under the shadow and write: off, as comments
are; what waited before tickets began never gets one (11 Nov 2026: 89 issues opened at once); a private Ask only as a
line that it waits; a reply on the ticket answers through the same path as words in the app."""
import json

import pytest

import asks as A
import asks_tickets as K
from domain import trackers as TR

T0 = 1_800_000_000.0
POL = {"channels": ["app", "ticket"], "tickets": {"tracker": "inbox"}, "tiers": {}, "data": {"text_max": 2000}}


@pytest.fixture
def desk(tmp_path, monkeypatch):
    store = tmp_path / "standin.json"
    store.write_text(json.dumps({"items": {}}))
    cfg = tmp_path / "trackers.yaml"
    cfg.write_text(f"trackers:\n  - {{name: inbox, kind: standin, path: {store}, workflow: home/inbox}}\n"
                   f"  - {{name: ro, kind: standin, path: {tmp_path / 'ro.json'}, workflow: home/inbox, write: off}}\n")
    for k, v in (("AISTACK_TRACKERS", cfg), ("AISTACK_TRACKER_STATE", tmp_path / "state"), ("ASKS_DIR", tmp_path / "asks"),
                 ("AISTACK_ROLES", tmp_path / "none.yaml")):
        monkeypatch.setenv(k, str(v))
    monkeypatch.setattr(A, "TYPES", {})
    monkeypatch.setattr(A, "policy", lambda folder=None: POL)
    A.register("tax", "Your taxes", action="answer", outcomes=(("single", "Single"), ("joint", "Joint")))
    A.register("ideas", "Ideas", action="idea", outcomes=(("take", "Take"), ("no", "Not now")))
    A.register("gate-q", "A release record", action="deploy", outcomes=(("approve", "Approve"), ("reject", "Reject")), gate=True)
    A.APPLY["tax"] = A.APPLY["gate-q"] = lambda a, ans: ""
    K.since(T0 - 10)                                         # tickets began just before these Asks
    return lambda: json.loads(store.read_text())["items"]


def live(*kinds):
    for k in kinds:
        TR.handle({"action": "tracker_live", "kind": k, "live": True, "who": "me@x"})


def tax(n, at=T0, **kw):
    return A.open_ask({"kind": "tax", "source": f"dq:tax:q{n}", "question": f"Tax question {n}?", **kw}, now=at)


def test_asks_of_one_kind_or_task_share_one_ticket_with_one_comment_a_pass(desk):
    live("open", "comment")
    a, b = tax(1), tax(2)
    A.open_ask({"kind": "ideas", "source": "dq:idea:7", "question": "Take this idea?"}, now=T0)   # ideas open no ticket now
    K.sync(pol=POL, now=T0)
    items = desk()
    assert list(items) == ["A-1"] and items["A-1"]["title"] == "Your taxes"
    said = [c["body"] for c in items["A-1"]["comments"]]
    assert len(said) == 1 and "**Tax question 1?**" in said[0] and "**Tax question 2?**" in said[0] and "Answers: Single, Joint" in said[0]
    tax(3, at=T0 + 5)
    K.sync(pol=POL, now=T0)
    assert list(desk()) == ["A-1"] and len(desk()["A-1"]["comments"]) == 2 and "Tax question 3?" in desk()["A-1"]["comments"][1]["body"]
    A.answer(a["id"], answer_id="ans-tk00001", person="me@x", via="app", outcome="joint", chip=True, now=T0)
    A.tick(now=T0 + A.HOLD_S)
    K.sync(pol=POL, now=T0)
    K.sync(pol=POL, now=T0)
    last = desk()["A-1"]["comments"][-1]["body"]
    assert "Answered: Joint" in last and "By me@x (owner), via app." in last and len(desk()["A-1"]["comments"]) == 3
    w1 = A.open_ask({"kind": "tax", "source": "flow:r1", "task": "n8n:wf/9", "question": "Send the draft?"}, now=T0 + 6)
    A.open_ask({"kind": "tax", "source": "flow:r2", "task": "n8n:wf/9", "question": "And the copy?"}, now=T0 + 6)
    K.sync(pol=POL, now=T0)
    assert len(desk()) == 2 and A.get(w1["id"])["ticket"] == "inbox/A-2" and A.get(b["id"])["ticket"] == "inbox/A-1"


def test_opening_a_ticket_is_a_write_under_the_shadow_and_write_off_as_comments_are(desk):
    a = tax(1)
    K.sync(pol=POL, now=T0)
    assert desk() == {} and "waits in shadow" in A.get(a["id"])["ticket_local"]
    pending = [i for i in TR._shadow()["open"]["items"] if i["status"] == "pending"]
    assert len(pending) == 1 and pending[0]["body"].startswith("Your taxes")
    K.sync(pol=POL, now=T0)
    assert len(TR._shadow()["open"]["items"]) == 1                                   # asked once, however often it looks
    assert [h["event"] for h in A.history(a["id"])].count("ticket") == 1
    TR.handle({"action": "tracker_shadow_approve", "kind": "open", "id": pending[0]["id"], "send": True, "who": "me@x"})
    assert list(desk()) == ["A-1"]                                                 # the owner sent it: opened once
    K.sync(pol=POL, now=T0)
    assert A.get(a["id"])["ticket"] == "inbox/A-1" and A.get(a["id"])["ticket_state"] == "shadow" and desk()["A-1"]["comments"] == []
    assert K.where({**POL, "tickets": {"tracker": "ro"}})[1] == "ro is read-only (write: off)"
    assert TR.open_item("ro", "x", "y", "w2")["off"] and K.where({**POL, "channels": ["app"]})[1] == "this deployment has no ticket channel"


def test_what_waited_before_tickets_began_never_gets_a_ticket(desk):
    live("open", "comment")
    old = tax(1, at=T0 - 3600)                                                     # migrated: it waited before tickets began
    K.sync(pol=POL, now=T0)
    assert desk() == {} and not A.get(old["id"]).get("ticket")
    A.answer(old["id"], answer_id="ans-tk00009", person="me@x", via="app", outcome="joint", chip=True, now=T0)
    A.tick(now=T0 + A.HOLD_S)
    K.sync(pol=POL, now=T0)
    assert desk() == {}


def test_a_private_ask_puts_only_a_line_on_its_ticket(desk):
    live("open", "comment")
    tax(1, question="Was your income from the side job 4,200 EUR?", sensitivity="private")
    K.sync(pol=POL, now=T0)
    it = desk()["A-1"]
    assert "4,200" not in json.dumps(it) and "A private question waits for you in the app" in it["comments"][0]["body"]


def test_a_reply_on_the_ticket_is_an_answer_in_words_and_at_a_gate_a_comment(desk):
    live("open", "comment")
    a = A.open_ask({"kind": "tax", "source": "x:1", "task": "t1", "question": "How do you file?"}, now=T0)
    g = A.open_ask({"kind": "gate-q", "source": "gate:r", "task": "rel", "question": "Approve the release record?"}, now=T0)
    two = [A.open_ask({"kind": "tax", "source": f"x:{n}", "task": "t2", "question": f"Q{n}?"}, now=T0) for n in (2, 3)]
    K.sync(pol=POL, now=T0)
    key = lambda x: A.get(x["id"])["ticket"].split("/")[1]                         # noqa: E731
    said = lambda x, r, t: {"tracker": "inbox", "key": key(x), "said": [{"ref": r, "author": "me@x", "text": t}]}   # noqa: E731
    ev = [said(a, "c:1", "joint, as last year"), said(g, "c:2", "approve"), said(two[0], "c:3", "joint")]
    logged = []
    assert K.replies(ev, now=T0, log=logged.append) == 2 and K.replies(ev, now=T0, log=lambda *x: None) == 2   # once per comment
    assert [(x["ask_id"], x["via"], x["state"]) for x in A.reading()] == [(a["id"], "ticket", "reading"), (g["id"], "ticket", "comment")]
    assert A.get(g["id"])["status"] == "open" and A.get(g["id"])["comments"][0]["words"] == "approve"   # a gate: never by a reply
    assert "2 questions wait there" in logged[0]                                  # which one is meant is not clear: the app

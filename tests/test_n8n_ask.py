"""WFL-07: a workflow that needs the owner puts one question into Needs you with its own answers and waits; the owner's
tap there is the step's answer, delivered to the waiting execution; nothing else can answer it."""
import json
import types

import time
from pathlib import Path

import pytest

import asks as A
import decisions as D
import flows as FW

RESUME = "https://pc.example.ts.net:8450/webhook-waiting/88/q1"


class Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(FW, "PENDING", tmp_path / "pending")
    monkeypatch.setattr(FW, "DONE", tmp_path / "done")
    monkeypatch.setattr(FW, "ASKS", tmp_path / "asks")
    FW.PENDING.mkdir()
    monkeypatch.setenv("ASKS_DIR", str(tmp_path / "store"))
    monkeypatch.setattr(A, "channels", lambda pol=None, has=None: ["app", "telegram"])
    told = []
    FW.M = types.SimpleNamespace(stop=__import__("threading").Event(), log=print, notify=lambda text, *a: told.append(text), db=None)
    return told


def test_a_question_waits_in_needs_you_and_the_owners_tap_resumes_the_workflow(tmp_path, monkeypatch):
    """ASK-19: the question is an Ask; the tap is the step's answer, delivered to the waiting execution with its outcome,
    the person, the role and the channel, so the workflow branches on it."""
    told = setup(tmp_path, monkeypatch)
    req = {"kind": "ask", "question": "Merge the change for task 238?", "why": "Its checks passed.", "answers": ["Merge", "Not now"],
           "resume_url": RESUME}
    p = FW.PENDING / "q1.json"
    p.write_text(json.dumps(req))
    sent = []
    post = lambda r, timeout=30: sent.append(json.loads(r.data)) or Resp()
    FW.handle("q1", p, cards={}, crew={}, post=post, sleep=lambda s: None)
    assert p.exists() and sent == [] and told == ["A workflow asks you: Merge the change for task 238?"]
    a = A.by_source("flow:q1")
    assert [c["label"] for c in a["choices"]] == ["Merge", "Not now"] and a["kind"] == "workflow" and a["why"] == "Its checks passed."
    assert a["id"] in {x["id"] for x in A.published()["asks"]}                                    # in Needs you
    FW.handle("q1", p, cards={}, crew={}, post=post, sleep=lambda s: None)          # asked again: still one question, one message
    assert len(told) == 1 and sent == []
    A.answer(a["id"], answer_id="ans-flow0001", person="me@x", via="app", outcome="merge", chip=True)
    FW.handle("q1", p, cards={}, crew={}, post=post, sleep=lambda s: None)
    assert sent == []                                                               # held for its undo: the workflow still waits
    A.tick(now=time.time() + A.HOLD_S + 1)
    FW.handle("q1", p, cards={}, crew={}, post=post, sleep=lambda s: None)
    assert not p.exists() and sent[0]["status"] == "done" and sent[0]["answer"] == "Merge" and sent[0]["outcome"] == "merge"
    assert sent[0]["person"] == "me@x" and sent[0]["via"] == "app" and sent[0]["role"] == "owner"


def test_only_one_of_the_offered_answers_counts_and_only_once(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    FW.ask("q2", {"question": "Go?", "answers": ["Go", "Stop"]})
    a = A.by_source("flow:q2")
    with pytest.raises(ValueError, match="not one of its answers"):
        A.answer(a["id"], answer_id="ans-flow0002", person="me@x", via="app", outcome="delete-everything", chip=True)
    A.answer(a["id"], answer_id="ans-flow0003", person="me@x", via="app", outcome="stop", chip=True)
    with pytest.raises(ValueError, match="answered already"):
        A.answer(a["id"], answer_id="ans-flow0004", person="me@x", via="app", outcome="go", chip=True)
    A.tick(now=time.time() + A.HOLD_S + 1)
    assert FW.ask("q2", {"question": "Go?", "answers": ["Go", "Stop"]})["outcome"] == "stop"


def test_a_question_is_checked_before_it_is_asked():
    ok = {"kind": "ask", "question": "Go?", "answers": ["Go", "Stop"]}
    assert FW.validate(ok, {}, {}) == "" and FW.validate({"kind": "ask", "question": "Go?"}, {}, {}) == ""   # Yes / No by default
    assert "question" in FW.validate({**ok, "question": ""}, {}, {})
    assert "chips" in FW.validate({**ok, "answers": ["a", "b", "c", "d", "e", "f", "g"]}, {}, {})
    assert "label" in FW.validate({**ok, "answers": ["x" * 61]}, {}, {})
    assert "no default" in FW.validate({**ok, "gate": True, "default": "Go"}, {}, {})
    assert "default" in FW.validate({**ok, "default": "Maybe"}, {}, {})
    assert "registered" in FW.validate({**ok, "type": "no-such-kind"}, {}, {})
    assert "sensitivity" in FW.validate({**ok, "sensitivity": "secret"}, {}, {})


def test_the_app_lets_the_owner_answer_and_the_runner_hands_it_to_the_step_service():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert '"ask_answer"' in (root / "images/mission-control/server.py").read_text().split("ACTIONS = {")[1].split("}")[0]
    assert "AK.handle(req) if a in AK.ACTIONS" in (root / "ops/missions.requests.py").read_text()
    assert not hasattr(D, "_flows")                                                  # a workflow's question is an Ask of its own


def test_the_ask_block_s_inputs_reach_the_ask_and_its_answer_reaches_the_workflow(tmp_path, monkeypatch):
    """ASK-19: type, choices, allow_words, default, deadline, role, gate and sensitivity; a dismissal, an expiry and a
    default are answers the workflow branches on; words are read; a gate takes only a tap."""
    told = setup(tmp_path, monkeypatch)
    FW.ask("d1", {"question": "Keep the draft?", "choices": ["Keep", "Drop"], "default": "Drop", "deadline_hours": 1, "allow_words": False})
    a = A.by_source("flow:d1")
    assert a["default"] == {"outcome": "drop"} and not a["allow_words"] and a["deadline"] > time.time()
    later = time.time() + 3601
    A.tick(now=later)
    A.tick(now=later + 1)
    got = FW.ask("d1", {"question": "Keep the draft?", "choices": ["Keep", "Drop"]})
    assert got["status"] == "done" and got["outcome"] == "drop" and got["via"] == "default"
    FW.ask("d2", {"question": "Send it?"})
    A.dismiss(A.ask_id("flow:d2"), answer_id="dis-flow0001", person="me@x", words="not now")
    assert FW.ask("d2", {"question": "Send it?"}) == {**FW.ask("d2", {"question": "Send it?"}), "status": "dismissed", "words": "not now"}
    FW.ask("d3", {"question": "Was the income 4,200 EUR?", "sensitivity": "private"}, notify=FW.M.notify)
    assert told[-1] == "A workflow asks you: A private question waits for you in the app (A workflow asks)."
    FW.ask("g1", {"question": "Release it?", "choices": ["Release", "Hold"], "gate": True})
    g = A.by_source("flow:g1")
    assert g["gate"] and not g["allow_words"]
    assert A.answer(g["id"], answer_id="ans-flow0005", person="me@x", via="app", words="release")["comment"]
    assert FW.ask("g1", {"question": "Release it?", "choices": ["Release", "Hold"], "gate": True}) is None
    js = (Path(__file__).resolve().parents[1] / "n8n/custom/AistackStep.node.js").read_text()
    for k in ("type: p('type'", "allow_words: p('allow_words'", "default: p('default'", "deadline_hours:", "gate: p('gate'", "sensitivity: p('sensitivity'"):
        assert k in js, k
    assert set(("outcome", "values", "words", "person", "via", "interpreted_as")) <= set(FW.LEAN)


def test_a_workflow_tells_the_owner_through_the_stacks_own_notifications(tmp_path, monkeypatch):
    told = setup(tmp_path, monkeypatch)
    assert "message" in FW.validate({"kind": "notify", "message": ""}, {}, {})
    assert "message" in FW.validate({"kind": "notify", "message": "x" * (FW.NOTE_MAX + 1)}, {}, {})
    p = FW.PENDING / "n1.json"
    p.write_text(json.dumps({"kind": "notify", "message": "The weekly report is in the vault.", "resume_url": RESUME}))
    sent = []
    FW.handle("n1", p, cards={}, crew={}, post=lambda r, timeout=30: sent.append(json.loads(r.data)) or Resp(), sleep=lambda s: None)
    assert told == ["The weekly report is in the vault."] and sent == [{"status": "done", "sent": True}]
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "n8n/custom/AistackStep.node.js").read_text()
    assert "value: 'notify'" in js and "if (kind === 'notify') body.message = p('message');" in js

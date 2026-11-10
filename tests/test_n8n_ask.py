"""WFL-07: a workflow that needs the owner puts one question into Needs you with its own answers and waits; the owner's
tap there is the step's answer, delivered to the waiting execution; nothing else can answer it."""
import json
import types

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
    told = []
    FW.M = types.SimpleNamespace(stop=__import__("threading").Event(), log=print, notify=lambda text, *a: told.append(text), db=None)
    return told


def test_a_question_waits_in_needs_you_and_the_owners_tap_resumes_the_workflow(tmp_path, monkeypatch):
    told = setup(tmp_path, monkeypatch)
    req = {"kind": "ask", "question": "Merge the change for task 238?", "why": "Its checks passed.", "answers": ["Merge", "Not now"],
           "resume_url": RESUME}
    p = FW.PENDING / "q1.json"
    p.write_text(json.dumps(req))
    sent = []
    post = lambda r, timeout=30: sent.append(json.loads(r.data)) or Resp()
    FW.handle("q1", p, cards={}, crew={}, post=post, sleep=lambda s: None)
    assert p.exists() and sent == [] and told == ["A workflow asks you: Merge the change for task 238? (Needs you)"]
    items = [d for d in D._flows({})]
    assert len(items) == 1 and items[0]["id"] == "flow:q1" and items[0]["cls"] == "agent-request"
    assert [a["label"] for a in items[0]["answers"]] == ["Merge", "Not now"]
    assert items[0]["answers"][0]["act"] == {"action": "flow_answer", "id": "q1", "answer": "Merge"}
    FW.handle("q1", p, cards={}, crew={}, post=post, sleep=lambda s: None)          # asked again: still one question, one message
    assert len(told) == 1 and sent == []
    assert FW.answer({"id": "q1", "answer": "Merge"}) == {"ok": True, "answer": "Merge"}
    assert list(D._flows({})) == []
    FW.handle("q1", p, cards={}, crew={}, post=post, sleep=lambda s: None)
    assert not p.exists() and sent[0]["status"] == "done" and sent[0]["answer"] == "Merge"


def test_only_one_of_the_offered_answers_counts_and_only_once(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    FW.ask("q2", {"question": "Go?", "answers": ["Go", "Stop"]})
    assert FW.answer({"id": "q2", "answer": "Delete everything"})["ok"] is False
    assert FW.answer({"id": "../q2", "answer": "Go"})["ok"] is False
    assert FW.answer({"id": "nope", "answer": "Go"})["ok"] is False
    assert FW.answer({"id": "q2", "answer": "Stop"})["ok"] is True
    assert FW.answer({"id": "q2", "answer": "Go"}) == {"ok": False, "error": "it was answered already"}


def test_a_question_is_checked_before_it_is_asked():
    ok = {"kind": "ask", "question": "Go?", "answers": ["Go", "Stop"]}
    assert FW.validate(ok, {}, {}) == "" and FW.validate({"kind": "ask", "question": "Go?"}, {}, {}) == ""   # Yes / No by default
    assert "question" in FW.validate({**ok, "question": ""}, {}, {})
    assert "answers" in FW.validate({**ok, "answers": ["a", "b", "c", "d", "e"]}, {}, {})
    assert "answers" in FW.validate({**ok, "answers": ["x" * 41]}, {}, {})


def test_the_app_lets_the_owner_answer_and_the_runner_hands_it_to_the_step_service():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert '"flow_answer"' in (root / "images/mission-control/server.py").read_text().split("ACTIONS = {")[1].split("}")[0]
    assert '__import__("flows").answer(req) if a == "flow_answer"' in (root / "ops/missions.requests.py").read_text()
    assert D._flows in D.SOURCES


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

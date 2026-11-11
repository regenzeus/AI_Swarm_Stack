"""ASK-20, REC-08: the records' gate (ops/domain/records.py set_gate) asks through the Ask store (ops/asks.py
record_gate). The toy pack gates a change request's move to Approved for the role approver: the transition waits for
one gate Ask, words never approve it, someone outside the role cannot, Not now refuses it, and only the approver's tap
lets the write through, recorded with who approved."""
import json
import time

import pytest

import asks as A
import flows as FW
from domain import packs as PK
from domain import records as RC
from domain import trackers as TR
from test_domain_records import TOY


@pytest.fixture
def gated(tmp_path, monkeypatch):
    store = tmp_path / "standin.json"
    items = {"CR-1": {"updated": "2026-11-09T10:00:00", "title": "a change", "type": "Change Request", "status": "In Review"},
             "CR-2": {"updated": "2026-11-09T10:00:00", "title": "another", "type": "Change Request", "status": "In Review"}}
    store.write_text(json.dumps({"items": items}))
    cfg = tmp_path / "trackers.yaml"
    cfg.write_text(f"trackers:\n  - {{name: t, kind: standin, path: {store}, workflow: toy/ticket, records: toy}}\n")
    roles = tmp_path / "roles.yaml"
    roles.write_text("owner: [own@x]\ndefault: [owner]\nroles:\n  approver: {people: [appr@x], escalate: [owner]}\n")
    for k, v in (("AISTACK_TRACKERS", cfg), ("AISTACK_TRACKER_STATE", tmp_path / "state"), ("AISTACK_RECORDS", tmp_path / "r.db"),
                 ("AISTACK_ROLES", roles), ("ASKS_DIR", tmp_path / "asks")):
        monkeypatch.setenv(k, str(v))
    packs = [PK.read("toy", "c0ffee", TOY, allow=None)]
    monkeypatch.setattr(PK, "load", lambda *a, **k: {"packs": packs, "pending": [], "refused": []})
    monkeypatch.setattr(A, "TYPES", {})
    RC.sync(packs=packs)
    RC.set_gate(A.record_gate)
    yield packs
    RC.set_gate(None)


def write(key, wid):
    return FW.tracker_write(wid, {"tracker": "t", "key": key, "write": "transition", "body": "Approved", "execution": "", "title": "approve"})


def test_a_gated_status_waits_for_its_role_holders_tap_and_never_for_words_or_another_person(gated):
    assert write("CR-1", "w1") is None                                   # the step waits on its gate's Ask
    a = A.by_source("gate:t/CR-1/Approved")
    assert a["gate"] and a["role"] == "approver" and a["status"] == "open" and A.public(a)["people"] == ["appr@x"]
    assert write("CR-1", "w1") is None and len(A.listing()) == 1         # asked again: one Ask
    A.answer(a["id"], answer_id="gat-rec00001", person="appr@x", via="app", words="approved, go ahead")
    assert write("CR-1", "w1") is None                                   # words are a comment
    with pytest.raises(ValueError, match="only appr@x"):
        A.answer(a["id"], answer_id="gat-rec00002", person="own@x", via="app", outcome="approve", chip=True)
    A.answer(a["id"], answer_id="gat-rec00003", person="appr@x", via="app", outcome="approve", chip=True)
    assert write("CR-1", "w1") is None                                   # held for its undo: not yet
    A.tick(now=time.time() + A.HOLD_S + 1)
    got = write("CR-1", "w1")
    assert got["status"] == "done" and got["shadow"]                     # through, into shadow as every write
    assert RC.cache("t", packs=gated).gates[0]["person"] == "appr@x" and RC.cache("t", packs=gated).gates[0]["ask"] == a["id"]


def test_not_now_at_a_records_gate_refuses_the_transition(gated):
    assert write("CR-2", "w2") is None
    a = A.by_source("gate:t/CR-2/Approved")
    A.answer(a["id"], answer_id="gat-rec00004", person="appr@x", via="app", outcome="reject", chip=True)
    A.tick(now=time.time() + A.HOLD_S + 1)
    got = write("CR-2", "w2")
    assert got["status"] == "refused" and "waits for the approval" in got["error"] and got["gate"] == a["id"]
    assert TR.write({"tracker": "t", "kind": "transition", "key": "CR-2", "body": "Approved", "write_id": "w3"})["refused"]

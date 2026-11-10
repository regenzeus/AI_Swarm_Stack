"""ops/doctor.py, the Health doctor: issues from the board, redacted evidence, diagnoses -> findings and proposals,
and crew.call_doctor's debounced trigger after a new alert."""
import json
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def D(tmp_path, monkeypatch):
    import crew
    import doctor
    monkeypatch.setattr(crew, "OUT", tmp_path)
    doctor.C = crew
    return doctor


HEALTH = {"items": [
    {"name": "RAM upgrade", "kind": "mission", "id": None, "slug": "ram", "issues": [
        {"kind": "partial-read", "text": "last run: 9 results were cut off", "severity": "note", "key": "mission:ram:partial-read"}]},
    {"name": "Hermes (chat)", "kind": "engine", "id": "Hermes (chat)", "run": "hermes:main:b3", "issues": [
        {"kind": "limit", "text": "limit", "severity": "note"}], "acked": [{"kind": "stalled", "text": "stopped answering"}]},
    {"name": "Backup", "kind": "crew", "id": "backup", "issues": []},
]}


def test_open_issues_come_from_the_board_one_per_issue(D):
    out = D.issues_of(HEALTH)
    assert [(i["id"], i["name"], i["issue"]) for i in out] == [("i1", "RAM upgrade", "partial-read"), ("i2", "Hermes (chat)", "limit")]
    assert out[0]["key"] == "mission:ram:partial-read" and out[1]["key"] == "engine:Hermes (chat):limit"   # the board's keys (acknowledge)
    assert out[1]["run"] == "hermes:main:b3"                                    # acknowledged issues ("acked") are not open
    board = {"items": [{"name": "A", "kind": "crew", "id": "a", "issues": [{"kind": "slow", "text": "slow", "severity": "note"}]},
                       {"name": "B", "kind": "crew", "id": "b", "issues": [{"kind": "failing", "text": "failing", "severity": "alert"}]}]}
    assert [i["name"] for i in D.issues_of(board)] == ["B", "A"]                # alerts first
    assert D.issues_of({}) == []


def test_evidence_is_redacted(D):
    env = {"LITELLM_MASTER_KEY": "supersecretvalue123", "HOME": "/home/owner"}
    s = D.redact("key supersecretvalue123 Authorization: Bearer abcdefghijklmnop sk-1234567890abcdef "
                 "bot 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawabc token=hunter22222 home /home/owner", env)
    for secret in ("supersecretvalue123", "abcdefghijklmnop", "sk-1234567890abcdef", "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw", "hunter22222"):
        assert secret not in s
    assert "[redacted LITELLM_MASTER_KEY]" in s and "/home/owner" in s            # only secrets go, not the rest


def test_event_lines_keep_errors_when_they_do_not_fit(D):
    ev = [{"t": n, "kind": "call", "title": "read_file", "detail": "x" * 300} for n in range(200)]
    ev.insert(50, {"t": 50.5, "kind": "error", "title": "fetch", "detail": "Error: timeout"})
    ev.append({"t": 300, "kind": "result", "title": "fetch", "detail": "page … (12 more lines) truncated"})
    text = D.event_lines(ev, budget=2000)
    assert "fetch: Error: timeout" in text and "truncated" in text and len(text) < 2100
    assert "read_file" in D.event_lines(ev[:3])                                # small runs come in full


ANSWER = {"diagnoses": [
    {"issue": "i1", "class": "noise", "cause": "TRUNC matches the shop's own '… (3 more)' text", "evidence": ["images/mission-control/obs_core.py:240"],
     "fix": "only count tool-side truncation", "confidence": "high"},
    {"issue": "i2", "class": "external", "cause": "ChatGPT usage limit", "evidence": ["litellm: 429 usage limit"], "fix": "nothing to build", "confidence": "high"},
    {"issue": "i3", "class": "real", "cause": "the scout swallows fetch timeouts", "evidence": ["ops/x.py:12"], "fix": "retry once", "confidence": "medium"}],
    "proposals": [
    {"issues": ["i1"], "kind": "detector", "title": "Count only tool-side truncation as partial reads", "why": "Fewer false alarms.",
     "area": "app", "steps": ["Narrow TRUNC", "2. Add a test"], "files": ["images/mission-control/obs_core.py"], "tests": ["tests/test_observe.py"]},
    {"issues": ["i2"], "kind": "fix", "title": "Raise the ChatGPT limit", "steps": ["no"]},
    {"issues": ["i3"], "kind": "fix", "title": "Retry a timed-out fetch once in the scout", "why": "Fewer failed reads.", "steps": ["Retry once"],
     "files": ["ops/x.py"], "tests": ["tests/test_x.py"]}]}


def test_diagnoses_become_findings_and_proposals(D):
    issues = D.issues_of(HEALTH) + [{"id": "i3", "key": "runtime:Scout:tool-error", "name": "Scout", "kind": "runtime", "issue": "tool-error", "text": "tool error"},
                                    {"id": "i4", "key": "crew:Backup:failed", "name": "Backup", "kind": "crew", "issue": "failed", "text": "failed"}]
    findings, props = D.outcome(issues, ANSWER)
    by = {f["key"]: f for f in findings}
    assert by["mission:ram:partial-read"]["class"] == "noise" and by["mission:ram:partial-read"]["acknowledge"]
    assert (by["mission:ram:partial-read"]["file"], by["mission:ram:partial-read"]["line"]) == ("images/mission-control/obs_core.py", 240)
    assert by["engine:Hermes (chat):limit"]["class"] == "external" and not by["engine:Hermes (chat):limit"]["acknowledge"]
    assert by["crew:Backup:failed"]["kind"] == "not diagnosed"                  # an issue without an answer says so
    assert [p["title"] for p in props] == ["Count only tool-side truncation as partial reads", "Retry a timed-out fetch once in the scout"]
    assert props[0]["description"].startswith("1. Narrow TRUNC\n2. Add a test\n\nFiles: images/mission-control/obs_core.py\nTests: tests/test_observe.py")
    assert props[0]["signal"].startswith("health doctor (detector)") and props[1]["signal"].startswith("health doctor (fix)")
    assert by["runtime:Scout:tool-error"]["proposal"] == "Retry a timed-out fetch once in the scout"


def test_doctor_waits_for_a_usage_limit_without_failing(D, tmp_path, monkeypatch):
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "state.json").write_text(json.dumps({"health": HEALTH}))
    D.M = types.SimpleNamespace(PUBLIC=tmp_path / "public")
    monkeypatch.setattr(D, "evidence", lambda i: f"## {i['id']}")
    monkeypatch.setattr(D, "ask", lambda issues, ctx: (7, "waiting", "2026-10-28T21:30:00", issues))
    assert D.doctor(None) == 0
    assert "waits for the Claude usage limit (until 21:30)" in D.C.agent_file("doctor")["result"]
    made = []
    monkeypatch.setattr(D, "ask", lambda issues, ctx: (8, "done", json.dumps(ANSWER), issues))
    monkeypatch.setattr(D.C, "propose", lambda c, props, signal, source: made.append((source, len(props))) or len(props))
    assert D.doctor(None) == 1                                                  # i1's detector proposal (i3 is not on this board)
    f = D.C.agent_file("doctor")
    assert made == [("doctor", 1)] and f["pending"] is None and f["result"].startswith("2 issues: 1 noise, 1 external · 1 new proposal")


def test_a_new_alert_calls_the_doctor_at_most_every_30_minutes(D, monkeypatch):
    T = 1_800_000_000
    C = D.C
    C.M = types.SimpleNamespace(event=lambda *a, **k: None)
    import n8n_jobs as NJ
    on = {"active": True}
    monkeypatch.setattr(NJ, "of", lambda kind, key, idx=None: on if (kind, key) == ("crew", "doctor") else None)
    started = []
    monkeypatch.setattr(C.subprocess, "run", lambda cmd, **k: started.append(cmd) or types.SimpleNamespace(returncode=0))
    assert C.call_doctor(["Health doctor: the last run failed"], now=T) is False     # never for its own issues
    assert C.call_doctor(["Scout: tool error"], now=T) is True
    assert C.call_doctor(["RAM upgrade: partial read"], now=T + 29 * 60) is False
    assert C.call_doctor(["RAM upgrade: partial read"], now=T + 31 * 60) is True
    assert started == [["systemctl", "--user", "start", "--no-block", "crew-doctor.service"]] * 2
    on["active"] = False
    assert C.call_doctor(["x: y"], now=T + 10 ** 6) is False                       # its workflow switched off by the owner: stays off


def test_the_doctor_is_a_crew_agent_with_its_units(D):
    a = D.C.BY_ID["doctor"]
    assert a["unit"] == "crew-doctor" and a["agent"] and "doctor" in D.C.PROPOSERS
    svc = (ROOT / "ops/systemd/crew-doctor.service").read_text()
    assert "ops/crew.py doctor" in svc and not (ROOT / "ops/systemd/crew-doctor.timer").exists()
    import n8n_jobs as NJ
    assert NJ.schedule("crew", "doctor", NJ.index(ROOT / "n8n/workflows", ROOT / "no-such-folder")) == "every 6 hours"   # its workflow's (WFL-09)

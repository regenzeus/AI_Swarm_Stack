"""ops/improve.py and the crew's proposing since the switch-over: signals -> ideas in the swarm's Ledger (one faked model
call), a known problem refined instead of copied, no caps, accept -> builder assignment, dismiss -> a lesson for the agent,
and when a self-review is due."""
import datetime as dt
import json

import pytest


@pytest.fixture
def I(runner, tmp_path, monkeypatch, ledger):
    import improve
    import builds
    improve.M, improve.B, builds.M = runner, builds, runner
    monkeypatch.setattr(builds, "repos", lambda: ["ai-stack"])
    stack = tmp_path / "stack"
    (stack / "docs").mkdir(parents=True)
    (stack / "AGENTS.md").write_text("# x\n## Repository map\n| `ops/` | runner |\n## How to work\n")
    (stack / "docs" / "REVIEW-2026-10-27.md").write_text("# Review\n## Technical debt\n- no retention job for run logs\n## Other\n")
    monkeypatch.setattr(improve, "STACK", stack)
    monkeypatch.setattr(improve, "STATE", tmp_path / "improve.json")
    monkeypatch.setattr(runner, "sh", lambda *a, **k: "")                   # no failed systemd units
    monkeypatch.setattr(runner, "stack_info", lambda: {"ci": [{"repo": "ai-stack", "status": "failure", "sha": "abc1234"}]})
    monkeypatch.setattr(improve.subprocess, "run", lambda *a, **k: type("P", (), {"stdout": "", "returncode": 0})())
    c = runner.db()
    builds.table(c)
    return improve, c


def fake_model(monkeypatch, runner, proposals, seen=None):
    def ask_json(prompt, key, model="gpt-sub", timeout=300):
        if seen is not None:
            seen.append(prompt)
        return {"proposals": proposals}
    monkeypatch.setenv("VK_REVIEW", "vk-test")
    monkeypatch.setattr(runner, "ask_json", ask_json)


GOOD = {"title": "Add a retention job for old run logs", "why": "Run logs grow forever.", "signal": "review: no retention job",
        "area": "ops", "size": "small", "description": "Add ops/retention.py that deletes run logs older than 90 days; test it."}


def ideas(svc, **where):
    rows = [dict(r) for r in svc.ledger.db.execute("select * from artifacts where kind='idea' order by id")]
    return [r for r in rows if all(r[k] == v for k, v in where.items())]


def test_scan_turns_signals_into_ideas_and_refines_a_known_one(I, runner, monkeypatch, ledger):
    improve, c = I
    c.execute("insert into runs (slug, status, started, summary) values ('u', 'failed', ?, 'KeyError: steps')", (runner.now().isoformat(),))
    c.execute("insert into runs (slug, status, started, summary) values ('v', 'failed', ?, 'HTTP Error 429: Too Many Requests')",
              (runner.now().isoformat(),))
    seen = []
    fake_model(monkeypatch, runner, [GOOD, {**GOOD, "title": "x"}, {**GOOD, "title": "Add a retention job for the old run logs"}], seen)
    assert improve.scan(c, "on request") == 1                         # too short dropped; the reworded one refines the first
    (a,) = ideas(ledger)
    assert (a["owner"], a["state"], a["effort"]) == ("self-review", "open", "small")
    assert len(ledger.ledger.get(None, a["id"])["evidence"]) == 2 and "1 known ones refined" in improve.last_scan()["result"]
    assert "KeyError: steps" in seen[0] and "429" not in seen[0]         # usage-limit pauses are not defects
    assert "CI failing on ai-stack" in seen[0] and "no retention job" in seen[0] and "| `ops/` | runner |" in seen[0]
    events = [json.loads(x) for x in (runner.PUBLIC / "events.jsonl").read_text().splitlines()]
    assert events[-1]["push"] is True and "proposes 1 improvement" in events[-1]["text"]


def test_accept_creates_a_build_and_dismiss_becomes_a_lesson(I, runner, monkeypatch, ledger):
    improve, c = I
    fake_model(monkeypatch, runner, [GOOD, {**GOOD, "title": "Show the disk trend on the Stack page", "area": "app",
                                            "description": "Draw the free disk space of the last 30 days as a small chart on the Stack page."}])
    improve.scan(c)
    a, b = [x["id"] for x in ideas(ledger)]
    r = improve.handle({"action": "proposal_accept", "id": a, "by": "owner"}, c)
    build = c.execute("select * from builds where id=?", (r["build"],)).fetchone()
    assert build["status"] == "planning" and build["idea"] == a and "Run logs grow forever." in build["description"]   # the planner splits it first
    got = ledger.ledger.get(None, a)
    assert got["state"] == "active" and {"system": "build", "ref": str(r["build"])} in got["refs"]
    with pytest.raises(ValueError):
        improve.handle({"action": "proposal_accept", "id": a}, c)          # not open any more
    improve.handle({"action": "proposal_dismiss", "id": b, "reason": "not needed on a phone"}, c)
    assert ledger.ledger.get(None, b)["state"] == "declined"
    assert ledger.ledger.context("self-review")["lessons"][0]["reason"] == "not needed on a phone"   # the proposer learns why
    assert "declined: not needed on a phone" in improve.known(c) and "build (planning)" in improve.known(c)
    import swarm_client as SW
    assert "declined: \"Show the disk trend on the Stack page\" (his reason: not needed on a phone)" in SW.lessons_text("self-review")
    doc = SW.lessons_text("doctor")                                    # each agent gets only the decisions on its own ideas
    assert "decisions on your earlier ideas" not in doc and "Show the disk trend" not in doc and doc.startswith("Your team")
    import swarm_client as SW
    assert SW.build_done(r["build"], "deployed") == a and ledger.ledger.get(None, a)["state"] == "checking"
    assert SW.build_done(999, "deployed") is None                      # a build without an idea changes nothing


def test_no_signals_no_model_call(I, runner, monkeypatch):
    improve, c = I
    monkeypatch.setattr(runner, "stack_info", lambda: {"ci": []})
    (improve.STACK / "docs" / "REVIEW-2026-10-27.md").unlink()
    monkeypatch.setattr(runner, "ask_json", lambda *a, **k: pytest.fail("no model call without signals"))
    assert improve.scan(c) == 0 and "nothing to improve" in improve.last_scan()["result"]


def test_when_a_self_review_is_due(I, runner, monkeypatch, at):
    improve, _ = I
    monkeypatch.setattr(runner, "now", lambda: at)
    iso = lambda d: (at + d).isoformat(timespec="seconds")
    assert improve.due({}) is None and improve.last_scan()["last"] == at.isoformat(timespec="seconds")   # first start waits
    assert improve.due({"last": iso(dt.timedelta(days=-1))}) is None
    assert improve.due({"last": iso(dt.timedelta(days=-8))}) == "weekly"
    assert improve.due({"last": iso(dt.timedelta(days=-1)), "requested": iso(dt.timedelta(minutes=-1))}) == "on request"
    assert improve.due({"last": iso(dt.timedelta(days=-8)), "retry_at": iso(dt.timedelta(minutes=30))}) is None
    assert improve.due({"retry_at": iso(dt.timedelta(minutes=-1))}) == "retry"


def test_requests_are_validated(I):
    improve, c = I
    with pytest.raises(ValueError):
        improve.handle({"action": "proposal_accept", "id": 99}, c)
    assert improve.handle({"action": "improve_scan"}, c) == {"scanning": True}


def test_no_caps_and_a_known_problem_is_refined_not_copied(I, runner, monkeypatch, ledger):
    improve, c = I
    import crew
    import doctor
    monkeypatch.setattr(crew, "I", improve)
    monkeypatch.setattr(doctor, "C", crew)
    mk = lambda t, covers=None, d=None: {"title": t, "why": "w", "description": d or f"Change it properly, with a test: {t}.", "covers": covers}
    det = mk("Tune the partial read detector", ["mission:ram:partial-read", "kind:partial-read"])
    assert crew.propose(c, [det], "s", "doctor") == 1
    assert crew.propose(c, [mk("Make partial reads quieter", ["mission:x:partial-read", "kind:partial-read"])], "s", "doctor") == 0
    (d,) = ideas(ledger, owner="doctor")
    assert d["key"] == "detector:partial-read" and len(ledger.ledger.get(None, d["id"])["evidence"]) == 2   # the same fix: refined
    many = [mk(t, d=f"{t} in the module that needs it, with its own unit test {n}.") for n, t in enumerate(
        ("Split the request handler", "Share one front matter parser", "Route notifications through notify", "Name the magic numbers"))]
    assert crew.propose(c, many, "s", "maintainability") == 4                                           # no cap (DEC-10)
    fix = mk("Make the backup skip phone/home", ["crew:backup:failed"])
    assert crew.propose(c, [fix], "s", "doctor") == 1
    assert doctor.close_gone(c, {"crew:phone-check:failing"}) == 1                 # fixed by hand: gone; detector fixes stay
    assert {x["key"]: x["state"] for x in ideas(ledger, owner="doctor")} == {"detector:partial-read": "open", "health:crew:backup:failed": "gone"}
    assert doctor.issues_of({"items": [{"name": "RAM", "kind": "mission", "slug": "ram", "issues": [
        {"kind": "partial-read", "key": "mission:ram:partial-read"}, {"kind": "failed", "key": "mission:ram:failed"}]}]},
        skip=doctor.covered_now())[0]["issue"] == "failed"                       # the doctor skips what is covered
    assert crew.propose(c, [fix], "seen again", "doctor") == 0                    # the problem is back: the gone idea reopens
    assert {x["key"]: x["state"] for x in ideas(ledger, owner="doctor")}["health:crew:backup:failed"] == "open"
    assert not hasattr(improve, "CAPS") and not hasattr(improve, "tidy") and not hasattr(improve, "duplicate")
    t1 = mk("Add tests for missions.py: handle_stack and more", None, "Add unit tests for missions.py functions handle_stack and others.")
    assert crew.propose(c, [t1], "untested", "tests") == 1
    (a,) = ideas(ledger, owner="tests")
    improve.handle({"action": "proposal_dismiss", "id": a["id"], "reason": "only from 'no test mentions this name'"}, c)
    t2 = mk("Add tests for missions.py: write_state and more", None, "Add unit tests for missions.py functions write_state and others.")
    assert crew.propose(c, [t2], "untested", "tests") == 0                       # what the owner declined is not proposed again
    got = ledger.ledger.get(None, a["id"])
    assert got["state"] == "declined" and "seen again by tests" in got["evidence"][-1]["text"] and not got["evidence"][-1]["alert"]


def test_a_detector_fix_never_covers_every_failure():
    import doctor
    by = {"i1": {"key": "crew:backup:failed", "issue": "failed"}, "i2": {"key": "mission:ram:partial-read", "issue": "partial-read"}}
    assert doctor.covers({}, ["i1", "i2"], by, "detector") == ["crew:backup:failed", "mission:ram:partial-read", "kind:partial-read"]
    assert doctor.covers({}, ["i2"], by, "fix") == ["mission:ram:partial-read"]

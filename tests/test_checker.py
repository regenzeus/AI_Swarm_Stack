"""ops/checker.py and the Ledger's phase 2 rules: success checks decide done and reopen (SWM-07, SWM-44 to SWM-47), the
work-in-progress limit (SWM-40), the owner's autonomy rules (SWM-42, SWM-43), a failing agent pauses itself (SWM-71),
the swarm's failure signals (SWM-80) and scorecards (SWM-17)."""
import subprocess
import time

import pytest

import checker as CK
import swarm_client as SW
from ledger import Refused

DAY = 86400
OWNER, SYSTEM = {"id": "owner:owner", "cls": "owner"}, {"id": "system", "cls": "system"}


class Facts:
    def __init__(self, keys=(), kinds=(), ci=None, head="abc1234", deploys=(), logs=0, alerts=0, tests=("tests/test_x.py::test_y",)):
        self.issue_keys, self.issue_kinds, self.alerts = set(keys), set(kinds), alerts
        self.ci = {"ai-stack": ci or {"repo": "ai-stack", "status": "running", "sha": "abc1234"}}
        self.head, self.deploys, self._logs, self._tests = head, list(deploys), logs, set(tests)

    def tests(self):
        return self._tests

    def log_count(self, container, pattern, since):
        return self._logs

    def containers(self):
        return {"aistack-hermes-1"}

    def failed_runs(self, since):
        return 0


def art(check, since, evidence=()):
    return {"id": 1, "version": 3, "check": check, "state_since": since, "evidence": list(evidence)}


def test_each_check_type_passes_fails_or_waits():
    now = 1_800_000_000
    h = {"type": "health_issue_absent", "keys": ["crew:backup:failed"], "days": 7}
    assert CK.evaluate(art(h, now - 8 * DAY), Facts(), now)[0] == "pass"
    assert CK.evaluate(art(h, now - 2 * DAY), Facts(), now)[0] == "wait"
    assert CK.evaluate(art(h, now - 3600), Facts(keys=["crew:backup:failed"]), now)[0] == "wait"        # the board's grace
    assert CK.evaluate(art(h, now - DAY), Facts(keys=["crew:backup:failed"]), now) == ("fail", "the health issue is on the board (crew:backup:failed)")
    assert CK.evaluate(art({"type": "health_issue_absent", "kind": "partial-read"}, now - DAY), Facts(kinds=["partial-read"]), now)[0] == "fail"
    lc = {"type": "log_count", "container": "aistack-hermes-1", "pattern": "ddgs", "max": 0, "hours": 24}
    assert CK.evaluate(art(lc, now - 2 * DAY), Facts(logs=0), now)[0] == "pass" and CK.evaluate(art(lc, now - 3600), Facts(logs=2), now)[0] == "fail"
    ci = {"type": "ci_green", "repo": "ai-stack"}
    assert CK.evaluate(art(ci, now), Facts(ci={"status": "success", "sha": "abc1234"}), now)[0] == "pass"
    assert CK.evaluate(art(ci, now), Facts(ci={"status": "success", "sha": "0000000"}), now)[0] == "wait"   # green, but not this main
    assert CK.evaluate(art(ci, now), Facts(ci={"status": "failure", "sha": "abc1234"}), now)[0] == "fail"
    assert CK.evaluate(art({"type": "test_passes", "nodeid": "tests/test_x.py::test_gone"}, now), Facts(), now)[0] == "fail"
    assert CK.evaluate(art({"type": "smoke_ok"}, now - 60), Facts(deploys=[{"ts": now - 30, "ok": True}]), now)[0] == "pass"
    m = {"type": "metric", "name": "health_alerts", "op": "<=", "value": 0, "days": 1}
    assert CK.evaluate(art(m, now - 2 * DAY), Facts(alerts=0), now)[0] == "pass" and CK.evaluate(art(m, now), Facts(alerts=3), now)[0] == "fail"
    oc = {"type": "owner_confirms", "why": "a person must see the Echo speak"}
    assert CK.evaluate(art(oc, now - 60), Facts(), now)[0] == "wait"
    assert CK.evaluate(art(oc, now - 60, [{"origin": "owner", "text": "confirmed: it works", "ts": now - 10}]), Facts(), now)[0] == "pass"


def test_a_check_must_be_complete_and_name_what_exists(ledger):
    L = ledger.ledger
    with pytest.raises(Refused, match="owner_confirms needs why"):
        L.upsert(SYSTEM, "c1", "idea", "k1", "An idea that nobody can check", "x" * 50, check={"type": "owner_confirms"}, owner="doctor", guard=False)
    with pytest.raises(Refused, match="log_count needs container and pattern"):
        L.upsert(SYSTEM, "c2", "idea", "k2", "Another idea with a bad check", "y" * 50, check={"type": "log_count"}, owner="doctor", guard=False)
    f = Facts()
    assert CK.validate({"type": "test_passes", "nodeid": "tests/test_x.py::test_nope"}, f) == ["no test 'tests/test_x.py::test_nope'"]
    assert CK.validate({"type": "log_count", "container": "aistack-nope", "pattern": "x"}, f) == ["no container 'aistack-nope'"]
    assert CK.validate({"type": "ci_green"}, f) == []


def shipped(ledger, key, check, owner="doctor"):
    L = ledger.ledger
    aid = L.upsert(SYSTEM, f"s:{key}", "idea", key, f"Idea {key} to ship and check", f"Body of the idea {key} " * 4, owner=owner, guard=False, check=check)["id"]
    for to, who in (("open", OWNER), ("ready", OWNER), ("active", OWNER), ("checking", SYSTEM)):
        L.transition(who, f"s:{key}:{to}", aid, to, "test path")
    return aid


def test_the_checker_proves_reopens_and_catches_a_regression(ledger, monkeypatch):
    monkeypatch.setattr(SW, "REPORT", SW.REPORT)
    good = shipped(ledger, "a", {"type": "health_issue_absent", "keys": ["crew:backup:failed"], "days": 7})
    bad = shipped(ledger, "b", {"type": "health_issue_absent", "keys": ["mission:ram:slow"], "days": 7})
    now = time.time()
    assert CK.check_all(Facts(keys=["mission:ram:slow"]), now + DAY) == (0, 1, 1)                  # b failed, a still counts days
    hist = ledger.ledger.get(None, bad)["history"]
    assert ledger.ledger.get(None, bad)["state"] == "open" and "its check failed" in next(h for h in hist if h["kind"] == "transition")["reason"]
    assert any(h["kind"] == "message" for h in hist)                         # the Checker asked the doctor to refine it
    assert SW._load("checker.json", {})["progress"][str(good)].startswith("the health issue is away")
    said = [m for m in ledger.ledger.thread(None, "room:health") if m["text"].startswith(f"Checking #{good} ")]
    CK.check_all(Facts(keys=["mission:ram:slow"]), now + DAY + 3600)
    assert len(said) == 1 and len([m for m in ledger.ledger.thread(None, "room:health") if m["text"].startswith(f"Checking #{good} ")]) == 1
    assert CK.check_all(Facts(), now + 8 * DAY) == (1, 0, 0)
    g = ledger.ledger.get(None, good)
    assert g["state"] == "done" and g["evidence"][-1]["text"].startswith("checker: the health issue stayed away")
    assert CK.check_all(Facts(keys=["crew:backup:failed"]), now + 9 * DAY) == (0, 1, 0)             # it came back: a regression
    g = ledger.ledger.get(None, good)
    assert g["state"] == "open" and g["recurrence"] == 1 and "regression" in next(h for h in g["history"] if h["kind"] == "transition")["reason"]


def test_only_two_ideas_are_built_at_once(ledger):
    L = ledger.ledger
    ids = [L.upsert(SYSTEM, f"w{n}", "idea", f"w{n}", f"Work in progress idea {n}", f"text {n} " * 10, owner="doctor", guard=False)["id"] for n in range(3)]
    for aid in ids:
        for to in ("open", "ready"):
            L.transition(OWNER, f"w{aid}{to}", aid, to, "x")
    L.transition(OWNER, "a1", ids[0], "active", "go")
    L.transition(OWNER, "a2", ids[1], "active", "go")
    with pytest.raises(Refused, match="work-in-progress limit 2"):
        L.transition(OWNER, "a3", ids[2], "active", "go")
    assert L.get(None, ids[2])["state"] == "ready"


def doctor_idea(ledger, key="health:crew:backup:failed", title="Make the backup skip the unreadable phone home",
                desc="rsync fails on /srv/ai/phone/home; exclude it in ops/backup.sh and test it."):
    new, _ = SW.propose("doctor", [{"title": title, "covers": [key.removeprefix("health:")], "description": desc,
                                    "files": ["ops/backup.sh"], "tests": ["tests/test_backup.py"], "confidence": "high"}], "health doctor")
    return ledger.ledger.db.execute("select id from artifacts where key=?", (key,)).fetchone()[0]


def test_an_enabled_rule_starts_what_it_covers_and_withdrawing_it_holds_the_rest(ledger):
    aid = doctor_idea(ledger)
    assert CK.autonomy(None, Facts(), assign=lambda c, a: 77) == []                  # no rule: nothing starts by itself
    with pytest.raises(ValueError, match="no such rule"):
        SW.handle({"action": "swarm_autonomy", "template": "buy-things", "on": True})
    SW.handle({"action": "swarm_autonomy", "template": "doctor-small-fixes", "on": True, "by": "owner"})
    assert CK.autonomy(None, Facts(), assign=lambda c, a: 77) == [aid]
    a = ledger.ledger.get(None, aid)
    assert a["state"] == "active" and {"system": "build", "ref": "77"} in a["refs"] and a["check"]["type"] == "health_issue_absent"
    assert any(h["actor"] == "rule:1" for h in a["history"])
    second = doctor_idea(ledger, "health:crew:digest:failed", "Send the morning digest after the mail check is back",
                         "The digest unit runs before the mail grant refresh at boot; order the timers and add a regression test.")
    assert CK.autonomy(None, Facts(), assign=lambda c, a: 78) == []                  # at most one a day per rule
    SW.handle({"action": "swarm_autonomy", "template": "doctor-small-fixes", "on": False})
    assert ledger.ledger.get(None, aid)["state"] == "blocked" and ledger.ledger.get(None, second)["state"] == "open"
    L = ledger.ledger
    with pytest.raises(Refused, match="may only start ideas"):
        L.set_rule(OWNER, "purchase", "doctor", {}, "buy the speaker")
    with pytest.raises(Refused, match="cannot cover money"):
        L.set_rule(OWNER, "idea", "doctor", {}, "may deploy fixes")
    with pytest.raises(Refused, match="only the owner"):
        L.set_rule({"id": "doctor", "cls": "agent"}, "idea", "doctor", {}, "mine")


def test_a_failing_proposer_pauses_itself_once(ledger):
    cards = [{"id": "doctor", "jobs": ["crew-doctor"]}, {"id": "phone-check", "jobs": ["crew-phone-check"]}]
    failed = lambda unit: [{"state": "failed"}] * 3
    assert CK.self_pause(cards, failed) == ["doctor"]                               # the phone check reports faults, it is not paused
    assert SW.paused("doctor") and CK.self_pause(cards, failed) == []
    with pytest.raises(Refused, match="only the owner pauses and resumes"):
        ledger.ledger.pause(SYSTEM, "doctor", on=False)                             # only the owner resumes


def test_refused_writes_become_a_health_signal_and_scorecards_add_up(ledger):
    for n in range(12):
        ledger.answer(lambda: ledger.actor_for_runner({"authorization": "Bearer tok", "x-swarm-actor": "tests"}), "transition",
                      {"idem": f"r{n}", "id": 999, "to": "open", "reason": "x"})
    [sig] = CK.signals()
    assert sig.startswith("tests had 12 refused swarm writes in 24 h, 12 of them transition: ")
    ledger.ledger.db.execute("update refusals set ts=ts-3*3600"); ledger.ledger.db.commit()
    assert CK.signals() == []                                   # FND-93: none for 2 h, its cause stopped
    aid = doctor_idea(ledger)
    SW.dismiss(aid, "fixed by hand already")
    SW.propose("doctor", [{"title": "Make the backup skip the phone home folder", "covers": ["crew:backup:failed"],
                           "description": "rsync fails on /srv/ai/phone/home again; exclude it in ops/backup.sh."}], "again")
    sc = ledger.ledger.scorecard("doctor")
    assert (sc["ideas"], sc["declined"], sc["accepted"]) == (1, 1, 0) and sc["decline_reasons"] == [("fixed by hand already", 1)]
    assert sc["refined"] >= 1 and sc["accepted_share"] == 0.0 and sc["proven_share"] is None
    pub = SW.publish()
    assert pub["scorecards"]["doctor"]["declined"] == 1 and [a["on"] for a in pub["autonomy"]] == [False, False]


def test_the_owner_confirms_or_reopens_a_shipped_idea(ledger):
    aid = shipped(ledger, "c", {"type": "owner_confirms", "why": "only a person hears the Echo"})
    SW.handle({"action": "swarm_confirm", "id": aid, "by": "owner"})
    assert CK.check_all(Facts(), time.time() + 60) == (1, 0, 0) and ledger.ledger.get(None, aid)["state"] == "done"
    other = shipped(ledger, "d", {"type": "ci_green"})
    SW.handle({"action": "swarm_reopen", "id": other, "reason": "the page still shows the old count"})
    o = ledger.ledger.get(None, other)
    assert o["state"] == "open" and next(h for h in o["history"] if h["kind"] == "transition")["reason"] == "still broken: the page still shows the old count"


def test_the_facts_read_as_empty_where_the_stack_is_not(tmp_path, monkeypatch):
    monkeypatch.setattr(CK, "STACK", tmp_path / "nowhere")
    monkeypatch.setattr(CK, "PUBLIC", tmp_path / "nowhere")
    f = CK.Facts()
    assert (f.head, f.issue_keys, f.alerts, f.ci) == ("", set(), 0, {})
    assert CK.evaluate(art({"type": "ci_green"}, time.time()), f)[0] == "wait"          # unknown is never "proved"


def test_a_log_count_can_read_a_host_units_journal(monkeypatch):
    """The runner's own errors are in the journal of the missions service, not in a container (idea #23)."""
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        out = {"docker": "aistack-hermes-1\n", "systemctl": "missions.service loaded active running Missions\n",
               "journalctl": "wiki summaries failed: mapping values\nok\nwiki summaries failed: again\n"}[cmd[0]]
        return subprocess.CompletedProcess(cmd, 0, out, "")
    monkeypatch.setattr(CK.subprocess, "run", run)
    f = CK.Facts.__new__(CK.Facts)
    assert {"aistack-hermes-1", "unit:missions"} <= f.containers()
    assert f.log_count("unit:missions", "wiki summaries failed", 1000) == 2
    assert seen[-1][:4] == ["journalctl", "--user", "-u", "missions"] and "@1000" in seen[-1]


def test_a_log_count_waits_its_days_not_one_day():
    now = 1.9e9
    a = {"check": {"type": "log_count", "container": "aistack-hermes-1", "pattern": "x", "max": 0, "days": 3}, "state_since": now - 2 * DAY}
    assert CK.evaluate(a, Facts(logs=0), now) == ("wait", "0 matching log lines in 48 of 72 hours")
    assert CK.evaluate({**a, "state_since": now - 3 * DAY - 60}, Facts(logs=0), now)[0] == "pass"

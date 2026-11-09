"""Lane discipline (SWM-109): an agent's own step into another agent's lane names why its owner would not see it, brings
something new and fits a daily budget; the helped agent or the owner judges it, the work's fate judges it otherwise, and
the scorecard and the Coach learn from what was not useful. Nothing makes an agent step in."""
import pysrc
from pathlib import Path

import pytest

import coach
import teamroom as TR
from ledger import Ledger, Refused

ROOT = Path(__file__).resolve().parent.parent
CARDS = [{"id": "doctor", "purpose": "The Health doctor.", "owns": {"idea": "its issue stays away"}, "tools": []},
         {"id": "tests", "purpose": "The test agent.", "owns": {"idea": "the test is fast"}, "tools": [], "budgets": {"helps_per_day": 2}},
         {"id": "scout", "purpose": "Web research only.", "tools": ["fetch"]}]
DOC = {"id": "doctor", "cls": "agent", "via": "mcp"}
TESTS = {"id": "tests", "cls": "agent", "via": "mcp"}
TESTS_HOST = {"id": "tests", "cls": "agent", "via": "runner"}
OWNER, SYSTEM = {"id": "owner:owner", "cls": "owner"}, {"id": "system", "cls": "system"}
WHY = "the doctor reads health logs, not the test timings I measured in run 31"
BODY = "The partial-read detector flags fetch pagination notices although the agent followed the next page."


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        self.t += 1
        return self.t


@pytest.fixture
def L(tmp_path):
    return Ledger(str(tmp_path / "swarm.db"), CARDS, now=Clock())


TOPICS = {"detector:x": BODY, "other:y": "Backups of the phone home folder stop when rsync meets a locked database file.",
          "k0": "Mail digests skip senders whose names hold an emoji, so their threads vanish from the morning summary.",
          "k1": "The wiki compiler halts on one page with broken front matter instead of leaving that page out.",
          "k2": "Price watch alerts arrive twice when a shop changes its currency label during the night."}


def idea(L, key="detector:x", title="The detector fires on pagination"):
    return L.upsert(DOC, f"i:{key}", "idea", key, title, TOPICS[key], evidence=[{"text": "run 4 shows it", "ref": "run:4"}])["id"]


def test_a_step_into_another_lane_names_why_its_owner_would_not_see_it(L):
    aid = idea(L)
    with pytest.raises(Refused, match="say in unseen why doctor would not see this"):
        L.add_evidence(TESTS, "e0", aid, "the pagination test takes 40 s since run 30")
    L.add_evidence(TESTS, "e1", aid, "the pagination test takes 40 s since run 30", unseen=WHY)
    ev = [e for e in L.feed(0)["events"] if e["kind"] == "evidence" and e["actor"] == "tests"]
    assert ev[0]["payload"]["help"] == {"owner": "doctor", "unseen": WHY}
    L.add_evidence(DOC, "e2", aid, "seen again in run 9")                                       # its own lane: no gate
    L.add_evidence(TESTS_HOST, "e3", aid, "the stack's code for a host agent writes this")      # the runner: its reason is in the code
    with pytest.raises(Refused, match="say in unseen why doctor would not see this"):
        L.link(TESTS, "l0", aid, idea(L, "other:y", "Another detector fires on long pages"), "relates", "same")
    with pytest.raises(Refused, match="already holds this"):
        L.add_evidence(TESTS, "e4", aid, "the pagination test takes 40 s since run 30!", unseen=WHY)


def test_each_agent_steps_in_only_a_few_times_a_day(L):
    ids = [idea(L, f"k{n}", ["Mail digests skip emoji senders", "The wiki compiler halts on one page", "Price alerts arrive twice"][n]) for n in range(3)]
    L.add_evidence(TESTS, "a", ids[0], "slow test one", unseen=WHY)
    L.add_evidence(TESTS, "b", ids[1], "slow test two", unseen=WHY)
    with pytest.raises(Refused, match="used its 2 steps into other agents' lanes today"):      # its card: helps_per_day 2
        L.add_evidence(TESTS, "c", ids[2], "slow test three", unseen=WHY)
    L.now.t += 90000                                                                             # a day later
    L.add_evidence(TESTS, "d", ids[2], "slow test three", unseen=WHY)


def test_the_helped_agent_or_the_owner_judges_and_the_work_s_fate_does_otherwise(L):
    a, b, c = (idea(L, f"k{n}", ["Mail digests skip emoji senders", "The wiki compiler halts on one page", "Price alerts arrive twice"][n]) for n in range(3))
    for n, aid in enumerate((a, b, c)):
        L.add_evidence(TESTS, f"h{n}", aid, f"timing note {n} from the test agent", unseen=WHY)
        L.now.t += 90000                                                                         # a day each: the budget stays free
    seq = {h["artifact_id"]: h["seq"] for h in L.helps(helper="tests")}
    assert [h["seq"] for h in L.context("doctor")["help_received"]] == [seq[a], seq[b], seq[c]]  # the doctor sees what it got
    with pytest.raises(Refused, match="only doctor"):
        L.help_verdict(TESTS, "v0", seq[a], True)
    L.finish(DOC, "f1", "Read the test agent's notes.", ops=[{"op": "rate", "seq": seq[a], "useful": False, "reason": "already known"}])
    L.help_verdict(OWNER, "v1", seq[a], True, "it was the clue")                                 # the owner's word stands
    L.transition(DOC, "o", b, "open", "stated with evidence")
    L.transition(OWNER, "d", b, "declined", "not worth it")                                      # b dropped: not useful
    hs = {h["artifact_id"]: h for h in L.helps(helper="tests")}
    assert hs[a]["verdict"] == "useful" and hs[a]["verdict_by"] == "owner:owner" and hs[a]["useful"] is True
    assert hs[b]["verdict"] is None and hs[b]["outcome"] == "dropped" and hs[b]["useful"] is False
    assert hs[c]["useful"] is None                                                               # nothing happened yet
    assert [h["seq"] for h in L.context("doctor")["help_received"]] == [seq[c]]                   # judged or settled: not asked again
    assert L.scorecard("tests")["helps"] == {"given": 3, "useful": 1, "not_useful": 1, "pending": 1}
    L.rebuild()                                                                                  # the verdicts replay (SWM-30)


def test_the_coach_turns_unhelpful_steps_into_an_agent_change_for_quiet():
    cards = {"tests": {"model": "gpt-sub"}, "doctor": {"model": "claude-subscription"}}
    f = coach.findings(cards, {"tests": {"ideas": 1, "helps": {"given": 4, "useful": 1, "not_useful": 2, "pending": 1}},
                               "doctor": {"ideas": 1, "helps": {"given": 3, "useful": 2, "not_useful": 1, "pending": 0}}})
    assert [(x["agent"], x["target"]) for x in f] == [("tests", "no_noise")] and "2 of its 3 judged steps" in f[0]["problem"]


def test_the_room_shows_why_and_lets_the_owner_judge():
    e = {"seq": 41, "artifact_id": 7, "actor": "tests", "cls": "agent", "kind": "evidence", "ts": 5, "akind": "idea", "title": "Fix it", "owner": "doctor",
         "payload": {"text": "slow test", "help": {"owner": "doctor", "unseen": WHY}}, "reason": ""}
    v = {"seq": 42, "artifact_id": 7, "actor": "owner:the owner", "cls": "owner", "kind": "help_verdict", "ts": 6, "akind": "idea", "title": "Fix it",
         "owner": "doctor", "payload": {"seq": 41, "useful": True, "helper": "tests"}, "reason": "it was the clue"}
    help, verdict = TR.event_line(e), TR.event_line(v)
    assert help["type"] == "help" and help["ref"]["help"] == 41 and help["detail"] == f"Why doctor would not see it, it says: {WHY}"
    assert verdict["type"] == "you" and verdict["ref"]["judges"] == 41 and verdict["verb"] == "judged tests's help on idea #7: useful"
    js = (ROOT / "images/mission-control/web/static/swarm.js").read_text()
    assert 'data-hv="${l.ref.help}" data-useful="1">Useful' in js and 'action: "swarm_help_verdict"' in js
    assert '"swarm_help_verdict"' in pysrc.server()
    assert '"swarm_help_verdict"' in (ROOT / "ops/swarm_client.py").read_text().split("ACTIONS =")[1].split("}")[0]

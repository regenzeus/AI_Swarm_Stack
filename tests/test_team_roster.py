"""Every agent knows the team (SWM-108): the start-of-run pack has one line per agent with the lane rule, and two tools
look into another agent's role and work, as far as the asking agent may see it (SWM-67)."""
from pathlib import Path

import pytest

import swarm_client as SW
from ledger import Ledger, Refused

ROOT = Path(__file__).resolve().parent.parent
CARDS = [{"id": "doctor", "purpose": "The Health doctor.", "responsibilities": ["diagnose health issues"], "owns": {"idea": "its issue stays away"},
          "roles": ["health"], "wake": "on_request", "tools": []},
         {"id": "scout", "purpose": "Web research only.", "owns": {}, "roles": ["research"], "tools": ["fetch", "browser"]},
         {"id": "coach", "purpose": "Improves the agents.", "owns": {"agent_change": "held 14 days"}, "tools": []}]
DOC, SCOUT, OWNER = {"id": "doctor", "cls": "agent"}, {"id": "scout", "cls": "agent"}, {"id": "owner:owner", "cls": "owner"}
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


def test_every_run_starts_knowing_the_team_and_the_lane_rule(L):
    L.upsert(DOC, "i1", "idea", "detector:x", "The detector fires on pagination", BODY, evidence=[{"text": "run 4", "ref": "run:4"}])
    pack = L.context("scout")
    team = {t["id"]: t for t in pack["team"]}
    assert set(team) == {"doctor", "scout", "coach"} and team["scout"].get("you") and not team["doctor"].get("you")
    assert team["doctor"]["purpose"] == "The Health doctor." and team["doctor"]["owns"] == ["idea"] and team["doctor"]["open"] == 1
    assert team["doctor"]["last_ledger_write"] == "just now" and team["coach"]["last_ledger_write"] == "not yet"
    assert "own lane first" in pack["team_rule"] and "staying out is often the responsible choice" in pack["team_rule"]


def test_team_who_shows_an_agent_s_card_and_open_work_but_not_what_the_asker_may_not_see(L):
    pub = L.upsert(DOC, "i1", "idea", "detector:x", "The detector fires on pagination", BODY, evidence=[{"text": "run 4", "ref": "run:4"}])["id"]
    priv = L.upsert(DOC, "i2", "idea", "mail:y", "A mail sender keeps failing the digest", "Private mail detail for the digest.",
                    evidence=[{"text": "digest run", "ref": "run:5"}], label="private")["id"]
    who = L.team_who("coach", "doctor")
    assert who["purpose"] == "The Health doctor." and who["responsibilities"] == ["diagnose health issues"] and who["wake"] == "on_request"
    assert {x["id"] for x in who["open_work"]} == {pub, priv}
    assert {x["id"] for x in L.team_who("scout", "doctor")["open_work"]} == {pub}          # the scout has a way out (SWM-67)
    with pytest.raises(Refused, match="the team is coach, doctor, scout"):
        L.team_who("doctor", "nobody")


def test_team_work_shows_runs_settled_work_and_help_given_to_others(L):
    aid = L.upsert(DOC, "i1", "idea", "detector:x", "The detector fires on pagination", BODY, evidence=[{"text": "run 4", "ref": "run:4"}])["id"]
    L.finish(DOC, "f1", "Looked at the partial-read detector and proposed a fix.")
    L.transition(OWNER, "t1", aid, "declined", "the detector is right")
    L.add_evidence(SCOUT, "e1", aid, "page 2 was followed in run 12", ref="run:12")
    work = L.team_work("coach", "doctor")
    assert [r["summary"] for r in work["runs"]] == ["Looked at the partial-read detector and proposed a fix."]
    assert any(s["id"] == aid and s["to"] == "declined" and s["reason"] == "the detector is right" and s["by"] == "owner" for s in work["settled"])
    helped = L.team_work("coach", "scout")["helped_others"]
    assert helped == [{"id": aid, "title": "The detector fires on pagination", "owner": "doctor", "text": "page 2 was followed in run 12", "ts": helped[0]["ts"]}]
    assert L.team_work("coach", "doctor")["helped_others"] == []                              # its evidence on its own idea is not help


def test_host_agents_read_the_team_in_their_prompt_and_mcp_agents_have_the_tools():
    pack = {"team": [{"id": "doctor", "you": True, "purpose": "The Health doctor.", "owns": ["idea"], "open": 2, "last_ledger_write": "3 h ago"},
                     {"id": "scout", "purpose": "Web research only.", "owns": [], "open": 0, "last_ledger_write": "not yet"}],
            "team_rule": "Each agent is responsible for its own lane first."}
    text = SW.lessons_text("doctor", send=lambda op, a, actor: {"ok": True, "result": pack})
    assert "Your team (one line per agent):" in text and "- doctor (you): The Health doctor. Owns: idea. Open: 2. Last wrote to the Ledger: 3 h ago." in text
    assert "- scout: Web research only. Open: 0. Last wrote to the Ledger: not yet." in text and text.endswith("Each agent is responsible for its own lane first.")
    sw = (ROOT / "images/swarm/swarm.py").read_text()
    assert 'async def swarm_context(ctx: Context, team: bool = False, agent: str = "", days: int = 14)' in sw     # no new tool: <= 12
    assert 'call(ctx, "team", {"agent": agent, "days": days}) if agent' in sw and 'if name == "team":' in sw

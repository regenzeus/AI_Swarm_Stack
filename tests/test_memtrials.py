"""The memory stack's trials (MEM-47): the coverage trial on its fixture passes, continuity fails when a mission's last result is
missing from its opening, and the memory agent's structural changes wait while a trial fails or is old."""
import json
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def MT(tmp_path, monkeypatch):
    import memtrials
    monkeypatch.setattr(memtrials, "DIR", tmp_path / "mem")
    monkeypatch.setattr(memtrials, "RESULTS", tmp_path / "mem" / "trials.json")
    import runtime
    monkeypatch.setattr(runtime, "emit", lambda *a, **k: None)
    return memtrials


def test_the_coverage_trial_passes_on_its_fixture(MT):
    r = MT.coverage()
    assert r["passed"], json.dumps(r["detail"], indent=1)
    assert r["cases"] == 3 and MT.load()["coverage"][-1]["passed"] is True


def test_the_continuity_trial_fails_when_the_last_result_is_missing(MT, tmp_path, monkeypatch):
    import memstack as MS
    import journal as J
    vault = tmp_path / "vault"
    (vault / "agents/mission-ram").mkdir(parents=True)
    (vault / "agents/mission-ram/MEMORY.md").write_text("# Memory: RAM\n\n## Journal\n\n### 2026-11-01 · run 1 · done\n- Found: two kits\n")
    (vault / "missions/ram/wiki").mkdir(parents=True)
    monkeypatch.setattr(MS, "VAULT", vault)
    monkeypatch.setattr(J, "VAULT", vault)
    ms = [{"slug": "ram", "title": "RAM", "wiki": "missions/ram/wiki"}]
    good = MT.continuity(ms, build=lambda m: "#### Your run 2026-11-01 (vault:agents/mission-ram/MEMORY.md#2026-11-01 · run 1)\n- two kits\n"
                                            "#### Kit (with notes) (vault:missions/ram/wiki/entities/kit.md, as of 2026-11-01)\nA kit.")
    assert good["passed"] and good["share"] == 1.0
    bad = MT.continuity(ms, build=lambda m: "#### Kit (vault:missions/ram/wiki/entities/kit.md)\nA kit.")
    assert not bad["passed"] and bad["detail"] == [{"mission": "ram", "state": False, "wiki": True}]


def test_structural_changes_wait_while_a_trial_fails(MT):
    assert MT.gate() == (False, "the coverage trial has not run yet")
    MT.keep("coverage", {"passed": True})
    MT.keep("continuity", {"passed": False})
    ok, why = MT.gate()
    assert not ok and why.startswith("the continuity trial failed")
    MT.keep("continuity", {"passed": True})
    assert MT.gate()[0]
    assert not MT.gate(now=time.time() + 30 * 86400)[0]                                   # an old result opens nothing
    MT.keep("recall", {"passed": False})
    assert MT.gate()[1].startswith("the recall trial failed")


def test_the_recall_trial_writes_only_to_its_own_bank(MT):
    src = (ROOT / "ops/memtrials.py").read_text()
    assert 'BANK = "trial-memstack"' in src and "banks/\" + BANK + \"/" in src and "banks/owner" not in src
    posted = []
    r = MT.recall(post=lambda path, body: posted.append(path) or {"results": [{"text": "The owner drinks tea; works from home on Mondays; gravel bike"}]}, wait=1)
    assert r["passed"] and posted[0] == "memories" and set(posted[1:]) == {"memories/recall"}


def test_the_memory_agent_runs_the_trials_every_night(MT, monkeypatch):
    import crew
    monkeypatch.setattr(MT, "coverage", lambda: {"passed": True})
    monkeypatch.setattr(MT, "continuity", lambda: {"passed": False})

    def boom():
        raise RuntimeError("Hindsight is down")
    monkeypatch.setattr(MT, "recall", boom)
    assert crew.memory_trials(False) == {"coverage": True, "continuity": False}               # recall only on judgement nights
    assert crew.memory_trials(True) == {"coverage": True, "continuity": False, "recall": None}
    assert 'trials = memory_trials(rep.get("deep"))' in (ROOT / "ops/crew.py").read_text()

def test_an_opening_that_only_names_its_state_or_wiki_fails_continuity(MT, tmp_path, monkeypatch):
    """Review MEM-R19: the trial counted a ref in the "not given" list or the wiki's index as given."""
    import memstack as MS
    import journal as J
    vault = tmp_path / "vault"
    (vault / "agents/mission-ram").mkdir(parents=True)
    (vault / "agents/mission-ram/MEMORY.md").write_text("# Memory: RAM\n\n## Journal\n\n### 2026-11-01 · run 1 · done\n- Found: two kits\n")
    (vault / "missions/ram/wiki").mkdir(parents=True)
    monkeypatch.setattr(MS, "VAULT", vault)
    monkeypatch.setattr(J, "VAULT", vault)
    ms = [{"slug": "ram", "title": "RAM", "wiki": "missions/ram/wiki"}]
    pointers = ("#### The wiki (vault:missions/ram/wiki/index.md)\nits pages\n\n### Also in memory for this task, not given\n"
                "- vault:agents/mission-ram/MEMORY.md: Your state\n- vault:missions/ram/wiki/entities/kit.md: Kit")
    assert MT.continuity(ms, build=lambda m: pointers)["detail"] == [{"mission": "ram", "state": False, "wiki": False}]



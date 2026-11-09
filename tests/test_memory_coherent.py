"""The stack's memory made coherent (MEM-03 to MEM-06): one opening per run in a fixed order and budget with the swarm's
pack inside it, a mission's working state in its journal, reading scoped by the card (its own wiki first, never another
mission's private wiki), one writer per wiki that folds in other agents' helps, and no journal copies in Hindsight."""
import pysrc
import json
import subprocess
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def J(tmp_path, monkeypatch):
    import journal
    vault = tmp_path / "vault"
    for rel, title in {"missions/ram/wiki/entities/gskill.md": "G.Skill", "missions/ram/wiki/concepts/ddr4.md": "DDR4",
                       "missions/pc/wiki/concepts/ddr4.md": "DDR4", "missions/mail/wiki/concepts/ddr4.md": "DDR4",
                       "topics/copper/wiki/entities/acme-mining.md": "Acme Mining", "wiki/concepts/x.md": "X"}.items():
        (vault / rel).parent.mkdir(parents=True, exist_ok=True)
        (vault / rel).write_text(f"---\ntitle: {title}\n---\nbody")
    subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
    monkeypatch.setattr(journal, "VAULT", vault)
    monkeypatch.setattr(journal, "hindsight", lambda path, body, timeout=30: None)
    monkeypatch.setattr(journal, "run_view", lambda run: None)
    emitted = []
    monkeypatch.setattr(journal, "_emit_read", lambda run, agent, title, args, result, chars: emitted.append((title, args)))
    journal.emitted = emitted
    journal.M = types.SimpleNamespace(log=lambda *a: None, private_wikis=lambda: ["missions/mail/wiki"])
    journal.end()
    yield journal
    journal.M = None


def test_a_run_s_opening_has_one_order_one_budget_and_the_swarm_pack_once(J, monkeypatch):
    import swarm_client as SW
    calls = []
    monkeypatch.setattr(SW, "pack", lambda card, send=None: calls.append(card) or {
        "instructions": ["Cite the shop page."], "owner_messages": [{"mid": "m1", "text": "Prefer 3200 MHz."}],
        "team": [{"id": "scout", "purpose": "Web research only.", "owns": [], "open": 0, "last_ledger_write": "not yet"}], "team_rule": "Own lane first."})
    monkeypatch.setattr(J, "card_wikis", lambda card: ["own", "vault", "related"])
    monkeypatch.setattr(J, "wiki_matches", lambda q, n=3, scope=None: [{"path": "qmd://missions/ram/wiki/entities/gskill.md", "title": "G.Skill", "snippet": "kit"}])
    J.set_state("mission:ram", "- state: two kits left\n- next: check the QVL", "RAM upgrade")
    first = J.brief_v1("mission:ram", "RAM upgrade", run="mission-run:5", card="mission", wiki="missions/ram/wiki") + "PROMPT"   # the fixed opening MEM-26 replaced, kept for a trial's arm
    heads = [first.index(h) for h in ("## 1 · From the swarm", "## 2 · Your state", "## 3 · Your knowledge", "## 4 · The owner's facts", "## 5 · Your team")]
    assert heads == sorted(heads) and first.endswith("PROMPT") and len(first) < J.OPEN_CHARS + 1500
    assert "Cite the shop page." in first and "Prefer 3200 MHz." in first and "- next: check the QVL" in first and "Web research only." in first
    assert "do not call it in this run" in first and calls == ["mission"]                  # the pack once, from the runner
    assert [t for t, _ in J.emitted].count("swarm_context") == 1


def test_a_mission_s_working_state_lives_in_its_journal(J):
    J.set_state("mission:ram", "- state: two kits\n\n- next: QVL", "RAM upgrade")
    assert J.state_text("mission:ram") == "- state: two kits\n- next: QVL"
    text = (J.VAULT / "agents/mission-ram/MEMORY.md").read_text()
    assert text.index("## Working state") < text.index("## Standing notes") and J.parse(text)["state"] == ["- state: two kits", "- next: QVL"]
    J.set_state("mission:ram", "- state: one kit")
    assert J.state_text("mission:ram") == "- state: one kit"                               # replaced, not added to
    runner = pysrc.missions()
    assert '(d / "NOTES.md").write_text' not in runner and 'J.set_state(f"mission:{m[\'slug\']}", notes, m["title"], extra)' in runner
    assert "old.unlink()" in runner and "{notes}" not in runner.split("TASK_PROMPT = ")[1].split('"""')[1]


def test_a_run_reads_the_wikis_its_card_names_its_own_first_and_never_a_private_one(J, monkeypatch):
    monkeypatch.setattr(J, "card_wikis", lambda card: ["own", "vault", "related"])
    scope = J.wiki_scope("mission", "missions/ram/wiki")
    assert scope == ["qmd://missions/ram/wiki/", "qmd://vault-wiki/", "qmd://vault-raw/", "qmd://missions/pc/wiki/"]   # pc shares DDR4; mail is private
    hits = [{"file": f, "title": f, "snippet": "s"} for f in ("qmd://vault-wiki/x.md", "qmd://missions/other/log/r.md", "qmd://missions/ram/wiki/a.md",
                                                             "qmd://missions/mail/wiki/b.md", "qmd://missions/pc/wiki/c.md", "qmd://missions/ram/wiki/d.md")]
    monkeypatch.setattr(J.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout=json.dumps(hits), returncode=0))
    got = [h["path"] for h in J.wiki_matches("ddr4 kit", n=4, scope=scope)]
    assert got == ["qmd://missions/ram/wiki/a.md", "qmd://missions/ram/wiki/d.md", "qmd://vault-wiki/x.md", "qmd://missions/pc/wiki/c.md"]
    monkeypatch.setattr(J, "card_wikis", lambda card: ["vault"])
    assert J.wiki_scope("main", "missions/ram/wiki") == ["qmd://vault-wiki/", "qmd://vault-raw/"]
    import registry
    cards = {c["id"]: c for c in registry.load().get("agents") or []}
    assert cards["mission"]["memory"]["wikis"] == ["own", "vault", "related"] and cards["desk"]["memory"]["wikis"] == ["own", "vault", "related"]
    assert registry.WIKIS == ("own", "vault", "related")


def test_one_writer_per_wiki_folds_in_the_help_other_agents_gave_it(tmp_path, monkeypatch):
    import swarm_client as SW
    sent = []
    def send(op, a, actor):
        sent.append((op, a))
        if op == "find":
            return {"ok": True, "result": [{"id": 12}]}
        if op == "get":
            return {"ok": True, "result": {"evidence": [{"ref": "fold:40", "text": "folded"}]}}
        if op == "helps":
            return {"ok": True, "result": [{"seq": 39, "artifact_id": 12, "helper": "tests", "text": "old", "unseen": "u"},
                                           {"seq": 44, "artifact_id": 12, "helper": "scout", "text": "Kit X is EOL", "unseen": "the mission does not read the maker's notices"},
                                           {"seq": 45, "artifact_id": 99, "helper": "scout", "text": "other wiki", "unseen": "u"}]}
        return {"ok": True, "result": {"id": 12}}
    assert SW.wiki_owner("wiki") == "curator" and SW.wiki_owner("topics/u/wiki") == "desk" and SW.wiki_owner("missions/ram/wiki") == "mission"
    helps = SW.wiki_helps("missions/ram/wiki", "RAM", send)
    assert [h["seq"] for h in helps] == [44]                                                # only what came after the last fold
    SW.wiki_folded("missions/ram/wiki", helps, "missions/ram/log/r", send)
    assert sent[-1] == ("evidence", {"idem": "fold:missions/ram/wiki:44", "id": 12, "ref": "fold:44",
                                     "text": "folded 1 contribution (scout) into the wiki with missions/ram/log/r"})
    import mission_extras as X
    prompts = []
    X.M = types.SimpleNamespace(VAULT=tmp_path, ask_json=lambda p, key, timeout=0: prompts.append(p) or {"pages": []},
                                split_front=lambda t: ({}, t), write_front=lambda *a: None, RTM=types.SimpleNamespace(touched=lambda *a, **k: None))
    monkeypatch.setattr(SW, "wiki_helps", lambda root, title="", send=None: helps)
    folded = []
    monkeypatch.setattr(SW, "wiki_folded", lambda root, hs, src, send=None: folded.append((root, [h["seq"] for h in hs])))
    (tmp_path / "missions/ram/wiki").mkdir(parents=True)
    X.compile_wiki({"slug": "ram", "type": "task", "title": "RAM"}, "missions/ram/log/r.md", "a result", "k")
    assert "- from scout: Kit X is EOL (why its owner would not see it, it says: the mission does not read the maker's notices)" in prompts[0]
    assert folded == [("missions/ram/wiki", [44])]
    X.M = None


def test_an_old_note_moves_into_its_journal_even_when_its_mission_never_runs_again(tmp_path, monkeypatch):
    """MEM-05: the move happened only at a mission's next run, so an archived or on-demand one kept its NOTES.md for good
    (three on 8 Nov 2026). The runner moves each one left at its start; a journal with a working state keeps it."""
    import missions as MM
    states, sets = {"mission:has-state": "working on it"}, []
    monkeypatch.setattr(MM, "MISSIONS", tmp_path)
    monkeypatch.setattr(MM, "log", lambda *a: None)
    monkeypatch.setattr(MM.J, "state_text", lambda agent: states.get(agent, ""))
    monkeypatch.setattr(MM.J, "set_state", lambda agent, text, title="", extra=(): sets.append((agent, text, list(extra))))
    for slug, text in (("archived", "- the 2025 figures are in"), ("has-state", "- old")):
        (tmp_path / slug).mkdir()
        (tmp_path / slug / "NOTES.md").write_text(text)
    assert MM.move_old_notes() == ["archived"]
    assert sets == [("mission:archived", "- the 2025 figures are in", ["missions/archived/NOTES.md"])]
    assert not (tmp_path / "archived/NOTES.md").exists() and (tmp_path / "has-state/NOTES.md").exists()   # nothing is overwritten
    assert MM.move_old_notes() == []                                                                     # once


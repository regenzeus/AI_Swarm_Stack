"""What enters memory (docs/MEMORY-STACK.md "Writing", MEM-35 to MEM-38, MEM-48, MEM-49): every candidate through the rubric and its
sector's reconcile, every outcome logged with its undo."""
import pysrc
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def MW(tmp_path, monkeypatch):
    import memwrite
    import memstack
    import journal
    vault = tmp_path / "vault"
    vault.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
    for mod in (memwrite, memstack):
        monkeypatch.setattr(mod, "VAULT", vault)
        monkeypatch.setattr(mod, "DIR", tmp_path / "mem")
    monkeypatch.setattr(memwrite, "LOG", tmp_path / "mem" / "writes.jsonl")
    monkeypatch.setattr(journal, "VAULT", vault)
    monkeypatch.setattr(memwrite, "commit", lambda paths, msg: None)
    monkeypatch.setattr(memstack, "qmd_search", lambda q, n=30, mode="search": [])
    memwrite.M = None
    return memwrite


keep = lambda p: {"keep": True, "why": "durable and sourced"}


def test_a_candidate_without_evidence_or_about_its_own_run_is_rejected(MW):
    assert MW.candidate("lesson", "Check the board manual before ordering RAM.", "", agent="mission:ram", ask=keep).startswith("Not kept")
    assert MW.candidate("lesson", "In this task I ran the tests three times.", "run 4", agent="mission:ram", ask=keep).startswith("Not kept")
    assert MW.candidate("failure", "The parser breaks on empty input.", "build #3", agent="crew:builder", ask=keep).startswith("Not kept")   # no repository
    assert MW.candidate("rumour", "Something happened somewhere today.", "x", ask=keep).startswith("Not kept")
    no = MW.candidate("lesson", "The function parse() reads a file and returns a dict.", "ops/x.py", agent="crew:builder", ask=lambda p: {"keep": False, "why": "restates the code"})
    assert no.startswith("Not kept") and "restates the code" in no
    assert all(w["outcome"] == "reject" for w in MW.writes())


def test_a_lesson_is_added_once_and_a_repeat_confirms_it(MW):
    a = MW.candidate("lesson", "Check the board manual's memory list before ordering RAM.", "run 12 of the RAM mission", agent="mission:ram", ask=keep)
    assert a.startswith("Kept") and "howto/lessons/missions.md" in a
    b = MW.candidate("lesson", "Check the board manual memory list before ordering RAM kits.", "run 15", agent="mission:ram", ask=keep)
    assert b.startswith("Already known; confirmed")
    import memstack as MS
    ls = MS.active_lessons("missions")
    assert len(ls) == 1 and ls[0]["tally"] == 2 and "confirmed" in ls[0]["evidence"]


def test_every_outcome_is_logged_with_its_undo_and_undone(MW):
    MW.candidate("lesson", "Run the suite once before the change to know what fails already.", "change #170", agent="crew:judge", role="tests", ask=keep)
    w = MW.writes()[-1]
    assert w["outcome"] == "add" and w["undo"]["kind"] == "lesson" and w["ref"].startswith("lesson:tests:L-")
    MW.undo(w["id"])
    import memstack as MS
    assert MS.active_lessons("tests") == [] and MW.writes()[-1]["undone"] is True
    with pytest.raises(ValueError):
        MW.undo(w["id"])                                                                  # once


def test_a_filed_fact_the_curator_already_took_in_is_not_called_undone(MW):
    """Review MEM-R6: vault-ingest moves a filed note on within a minute; Undo then said "undone" and changed nothing."""
    MW.candidate("fact", "Acme Mining produced 22 million pounds of copper in 2025.", "Acme Mining annual report 2025, p. 4", agent="mission:copper", ask=keep)
    w = MW.writes()[-1]
    assert w["outcome"] == "add" and w["undo"]["kind"] == "file"
    (MW.VAULT / w["undo"]["path"]).unlink()                                                # the ingest took it to raw/articles
    with pytest.raises(ValueError, match="already taken in"):
        MW.undo(w["id"])
    assert not MW.writes()[-1].get("undo") == w["id"]                                      # no "undone" entry was logged


def test_each_kind_of_candidate_reaches_its_sector(MW, monkeypatch):
    import repowiki as RW
    import journal
    lines = []
    monkeypatch.setattr(RW, "note", lambda name, slug, text, evidence, by="agent": lines.append((name, slug, text)) or f"repos/{name}/wiki/{slug}.md")
    sent = []
    monkeypatch.setattr(journal, "hindsight", lambda path, body, timeout=30: sent.append((path, body)) or {"ok": True})
    f = MW.candidate("fact", "Kazatomprom cut its 2026 guidance by 10 percent.", "https://example.com/kap", agent="mission:copper", ask=keep)
    assert f.startswith("Kept") and "raw/_inbox/" in f
    filed = next((MW.VAULT / "raw/_inbox").glob("*.md")).read_text()
    assert "evidence: https://example.com/kap" in filed and "untrusted: true" in filed and "from: C-" in filed           # MEM-48, MEM-49
    assert MW.candidate("failure", "Empty input crashes the parser.", "build #3", agent="crew:builder", repo="click", ask=keep).startswith("Kept")
    assert lines == [("click", "fragile", "Empty input crashes the parser.")]
    assert MW.candidate("owner", "The owner prefers answers in English.", "chat 4", agent="main", ask=keep).startswith("Kept")
    assert sent[0][0] == "memories" and sent[0][1]["items"][0]["tags"] == ["source:agent:main"]
    assert MW.candidate("skill", "Search the vault, then ask research, then write the summary.", "", agent="main", ask=keep).startswith("Queued")
    assert json.loads((MW.DIR / "skill-ideas.jsonl").read_text().splitlines()[0])["kind"] == "skill"


def test_a_claude_task_answer_is_yielded_to_its_repository_wiki(MW, monkeypatch):
    import repowiki as RW
    folded = []
    monkeypatch.setattr(RW, "exists", lambda name: name == "click")
    monkeypatch.setattr(RW, "fold", lambda name, text, src, key=None, compile_into=None: folded.append((name, src)) or ["build", "fragile"])
    e = MW.yield_answer("click", "Why do the help tests flake?", "They depend on the terminal width; set COLUMNS=80.", 77, ask=keep)
    assert e["outcome"] == "add" and folded == [("click", "repos/click/sources/claude-task-77.md")] and e["candidate"]["run"] == "claude-task:77"
    assert (MW.VAULT / "repos/click/sources/claude-task-77.md").read_text().startswith("# Claude task #77")
    assert MW.yield_answer("nope", "q", "a", 78, ask=keep)["outcome"] == "reject"
    assert MW.yield_answer("click", "q", "It reads a file.", 79, ask=lambda p: {"keep": False, "why": "restates the code"})["outcome"] == "reject"
    src = (ROOT / "ops/claude_tasks.py").read_text()
    assert "threading.Thread(target=yield_answer" in src


def test_a_moved_fact_names_its_long_term_id():
    src = pysrc.missions()
    assert "; long-term fact {f['id']})" in src and "where u.bank_id = 'owner'" in src

def test_a_fact_with_other_numbers_is_newer_and_a_short_lesson_is_not_a_longer_one(MW):
    """Review MEM-R10: 2026's guidance was skipped as 2025's, and a short lesson confirmed an unrelated longer one."""
    old = "Kazatomprom cut its production guidance for 2025 to 25,000 tU"
    assert MW.same_fact(old, "Kazatomprom cut its production guidance for 2025 to 25000 tU")        # the same, written another way
    assert not MW.same_fact(old, "Kazatomprom cut its production guidance for 2026 to 19,000 tU")   # a newer fact
    long = "Before changing ops/builds.py run the whole test suite with make check, it takes ten minutes"
    assert not MW.same_lesson(long, "Never run make check on the NAS")
    assert not MW.same_lesson("Always pin the base image by digest", "Never pin the base image by digest")
    assert MW.same_lesson("Check the board manual before ordering RAM", "Check the board manual before you order RAM")


def test_a_confirmation_keeps_its_evidence_and_its_undo_takes_back_only_itself(MW):
    """Review MEM-R10, R11: a repeat's evidence was dropped; undoing a confirmation wiped later changes, and undoing it after
    a retirement brought the lesson back."""
    import memstack as MS
    text = "Check the board manual before ordering RAM."
    MW.candidate("lesson", text, "run 4 of the RAM mission", agent="mission:ram", ask=keep)
    MW.candidate("lesson", "Check the board manual before you order RAM.", "the RAM mission's run 9", agent="mission:ram", ask=keep)
    first, second = MW.writes()[-2:]
    assert (first["outcome"], second["outcome"]) == ("add", "confirm")
    role = second["undo"]["role"]
    line = lambda: next(ln for ln in MW.read_playbook(role)[1] if MS.LESSON.match(ln))
    m = MS.LESSON.match(line())
    assert m["tally"] == "2" and "run 4 of the RAM mission" in m["ev"] and "latest: the RAM mission's run 9" in m["ev"]
    meta, live, retired = MW.read_playbook(role)                     # a run's tally moves it on after the confirmation
    MW.write_playbook(role, meta, [MW.lesson_line(m["text"], m["ev"], 5, m["id"], m["since"] or "") if MS.LESSON.match(ln) else ln for ln in live], retired)
    MW.undo(second["id"])
    m = MS.LESSON.match(line())
    assert m["tally"] == "4" and "latest:" not in m["ev"]            # only this confirmation went: the tally's later steps stay
    meta, live, retired = MW.read_playbook(role)
    MW.write_playbook(role, meta, [], live)                          # retired since
    MW.candidate("lesson", "Check the board manual before you order the RAM.", "run 12", agent="mission:ram", ask=keep)
    third = MW.writes()[-1]
    assert third["outcome"] == "add"                                 # a retired lesson is not confirmed: a new one is added
    MW.undo(first["id"])                                             # an addition goes wherever it is now
    assert not [ln for ln in MW.read_playbook(role)[2] if m["id"] in ln]

"""ops/journal.py: each agent's own memory (vault agents/<agent>/MEMORY.md): read at a run's start, an entry at its end,
edits from the app, and the curator's folding. A temporary git vault; the model and the runtime record are fakes."""
import pysrc
import webjs
import json
import re
import subprocess
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def J(tmp_path, monkeypatch):
    import journal
    vault = tmp_path / "vault"
    vault.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
    monkeypatch.setattr(journal, "VAULT", vault)
    monkeypatch.setattr(journal, "wiki_matches", lambda q, n=3, scope=None: [{"path": "qmd://vault-wiki/ram.md", "title": "RAM", "snippet": "DDR4 kits"}] if q else [])
    monkeypatch.setattr(journal, "run_view", lambda run: None)
    hs = []
    monkeypatch.setattr(journal, "hindsight", lambda path, body, timeout=30: hs.append((path, body)) or None)
    journal.hs = hs
    emitted = []
    monkeypatch.setattr(journal, "_emit_read", lambda run, agent, title, args, result, chars: emitted.append((run, title, args, result)))
    journal.M = types.SimpleNamespace(log=lambda *a: None, paused=lambda s: "usage limit" in (s or ""), now=__import__("datetime").datetime.now,
                                      ask_text=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no model in tests")),
                                      ask_json=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no model in tests")))
    journal.emitted = emitted
    journal.end()
    yield journal
    journal.M = None


def commits(J):
    return subprocess.run(["git", "log", "--format=%s"], cwd=J.VAULT, capture_output=True, text=True).stdout.splitlines()


def test_agent_ids_are_the_runtime_agents_and_nothing_else(J):
    assert J.aid("mission:ram-upgrade-to-32-gb") == "mission-ram-upgrade-to-32-gb" and J.aid("crew:memory") == "crew-memory"
    for bad in ("main", "mission:../x", "crew:", "mission:A B"):
        with pytest.raises(ValueError):
            J.aid(bad)


def test_the_file_round_trips_and_stays_readable(J):
    doc = {"title": "RAM upgrade", "state": ["- next: compare two kits"], "notes": ["check the board manual first"],
           "entries": [{"head": "2026-10-28 19:13 · run 19 · done", "lines": ["Did: researched 6 shops", "Found: G.Skill kit €272.80"]}]}
    text = J.render(doc, "mission-ram")
    assert text.startswith("# Memory: RAM upgrade") and "## Standing notes" in text and "### 2026-10-28 19:13 · run 19 · done" in text
    assert J.parse(text) == doc
    assert J.parse(J.render({"title": "", "state": [], "notes": [], "entries": []}, "crew-x"))["notes"] == []      # "(none yet)" is no note


def test_a_runs_first_prompt_gets_its_memory_once(J):
    J.save("mission:ram", {"title": "RAM", "notes": ["n1"], "entries": [{"head": f"h{i}", "lines": [f"Found: x{i}"]} for i in range(8)]}, "seed")
    import memstack as MS
    asked = []
    MS_open = MS.opening
    MS.opening = lambda agent, **k: asked.append((agent, k)) or "## Memory for this run\n- n1\n\n---\n\n"   # MEM-26: built by the memory stack
    try:
        J.begin("mission:ram", "RAM upgrade", run="mission-run:20", card="mission", wiki="missions/ram/wiki")
        first = J.take("PROMPT")
        assert J.take("SECOND") == "SECOND"                                        # once per run
    finally:
        MS.opening = MS_open
    assert first.endswith("PROMPT") and "- n1" in first and "Build on what you found before" in first and "do not call it in this run" in first
    assert asked == [("mission:ram", {"kind": "mission", "task": "RAM upgrade", "card": "mission", "own": "missions/ram/wiki", "run": "mission-run:20", "tools": True})]


def test_the_memory_is_capped(J, monkeypatch):
    monkeypatch.setattr(J, "CAP_CHARS", 400)
    doc = {"title": "x", "notes": [], "entries": [{"head": f"h{i}", "lines": ["Did: " + "y" * 150]} for i in range(5)]}
    text, n = J.memory_text(doc)
    assert len(text) <= 402 and n < 5 and "h4" in text                          # the oldest go first


def test_a_plain_model_prompt_gets_no_tool_hint(J):
    J.begin("crew:memory", "Memory curator", run="crew:memory:1", tools=False)
    assert "agent_note" not in J.take("FACTS", tools=False)


def test_a_run_writes_one_entry_deterministically_when_the_model_is_out(J):
    lines = J.record("mission:ram", "RAM upgrade", "mission-run:19", "done", "Top pick: G.Skill Aegis 32 GB from Playox, €272.80.", 543, "## Result\nlong")
    doc = J.load("mission:ram")
    assert doc["title"] == "RAM upgrade" and len(doc["entries"]) == 1
    assert doc["entries"][0]["head"].endswith("· run 19 · done · 9 min") and lines[0].startswith("Did:") and "G.Skill" in lines[1]
    assert commits(J)[0].startswith("journal: mission-ram ")
    assert J.emitted[-1][1] == "journal_write" and "### " in J.emitted[-1][2]["content"]   # the log's WRITE line


def test_failures_say_what_and_why(J, monkeypatch):
    view = {"stats": {"model": {"calls": 3}}, "problems": [{"kind": "tool-error", "text": "fetch failed twice"}],
            "events": [{"kind": "call", "title": "mcp__vault__research_research", "detail": json.dumps({"question": "RAM prices DE"})},
                       {"kind": "error", "title": "mcp__webfetch__fetch_fetch", "detail": "403 bot check"}]}
    monkeypatch.setattr(J, "run_view", lambda run: view)
    lines = J.record("mission:ram", "RAM", "mission-run:21", "failed", "ChatGPT usage limit", 60)
    assert "research_research(RAM prices DE)" not in lines[0] and "research_research ×1" in lines[0]
    assert any(x.startswith("Failed: failed") and "403 bot check" in x for x in lines)


def test_the_model_condenses_when_it_can(J, monkeypatch):
    seen = {}
    def ask(prompt, key, model="", timeout=0):
        seen.update(prompt=prompt, model=model)
        return "Did: compared 6 shops\nFound: Playox €272.80 (playox.de)\nchatter\nOpen: watch Black Friday"
    monkeypatch.setenv("VK_JOURNAL", "k")
    J.M.ask_text = ask
    monkeypatch.setattr(J, "run_view", lambda run: {"events": [{"kind": "call", "title": "research", "detail": "{}"}], "stats": {}, "problems": []})
    assert J.record("mission:ram", "RAM", "mission-run:22", "done", "ok", 100) == ["Did: compared 6 shops", "Found: Playox €272.80 (playox.de)", "Open: watch Black Friday"]
    assert seen["model"] == "gpt-sub-fast"


def test_notes_edits_and_forgetting_are_commits(J):
    J.handle({"action": "journal_note", "agent": "mission:ram", "text": "check the board manual first", "by": "agent"})
    J.handle({"action": "journal_note", "agent": "mission:ram", "text": "check the board manual first"})      # no duplicate
    J.record("mission:ram", "RAM", "mission-run:19", "done", "found a kit", 60)
    line = J.load("mission:ram")["entries"][0]["lines"][1]
    J.handle({"action": "journal_edit", "agent": "mission:ram", "section": "notes", "old": "check the board manual first", "text": "board manual: p. 12"})
    J.handle({"action": "journal_edit", "agent": "mission:ram", "section": "journal", "old": line, "text": ""})
    doc = J.load("mission:ram")
    assert doc["notes"] == ["board manual: p. 12"] and line not in doc["entries"][0]["lines"]
    with pytest.raises(ValueError, match="not in the memory"):
        J.handle({"action": "journal_edit", "agent": "mission:ram", "section": "notes", "old": "gone", "text": "x"})
    msgs = commits(J)
    assert sum("journal: mission-ram" in m for m in msgs) == 4 and any("forgotten by the owner" in m for m in msgs)


def test_the_curator_folds_old_entries_and_archives_them(J, monkeypatch):
    J.save("crew:tests", {"title": "Test agent", "notes": ["old note"], "entries": [{"head": f"h{i}", "lines": [f"Found: {i}"]} for i in range(J.FOLD_AT)]}, "seed")
    J.save("crew:digest", {"title": "Digest", "notes": [], "entries": [{"head": "h", "lines": ["Did: x"]}]}, "seed")
    monkeypatch.setenv("VK_JOURNAL", "k")
    J.M.ask_json = lambda prompt, key, model="", timeout=0: {"notes": ["flaky: test_phone (3 of 9 runs)"]}
    assert J.curate() == 1
    doc = J.load("crew:tests")
    assert doc["notes"] == ["flaky: test_phone (3 of 9 runs)"] and len(doc["entries"]) == J.KEEP
    arch = (J.VAULT / "agents/crew-tests/ARCHIVE.md").read_text()
    assert "### h0" in arch and "### h5" in arch and "### h6" not in arch
    J.M.ask_json = lambda *a, **k: {"notes": []}
    J.save("crew:tests", {**J.load("crew:tests"), "entries": [{"head": f"g{i}", "lines": ["x"]} for i in range(J.FOLD_AT)]}, "more")
    assert J.curate() == 0 and J.load("crew:tests")["notes"]                     # an empty answer never wipes the notes


def test_the_runner_and_the_app_are_wired():
    ms, crew = pysrc.missions(), (ROOT / "ops/crew.py").read_text()
    assert "prompt = J.take(prompt)" in ms and "J.begin(f\"mission:{m['slug']}\"" in ms and "J.after_run(m, rid" in ms
    assert "J.take(MAINT_PROMPT" in crew and "J.curate()" in crew and "J.begin(f\"crew:{name}\"" in crew
    import server
    assert {"journal_note", "journal_edit"} <= server.ACTIONS
    app = webjs.app_js()
    assert app.count("function logKind(") == 1 and "parseJournal" in app


def test_the_log_kinds_are_the_designed_ones():
    app = webjs.app_js()
    kinds = re.findall(r'"(\w+)"', re.search(r"const LOG_KINDS = \[(.*?)\];", app)[1])
    assert kinds == ["START", "READ", "WRITE", "TOOL", "WEB", "MAIL", "PHONE", "THINK", "SAYS", "WAIT", "PROPOSE", "ERROR", "END"]
    for name in ("tlItem", "TL_IC"):
        assert name not in app                                                      # one log component, not two


def test_the_runner_can_read_one_run_view(monkeypatch):
    import server
    from starlette.testclient import TestClient
    monkeypatch.setattr(server, "HERMES_KEY", "k")
    monkeypatch.setattr(server.RT, "view", lambda run: {"run": run, "events": []} if run == "mission-run:1" else None)
    c = TestClient(server.rt_app)
    assert c.get("/view/mission-run:1").status_code == 401
    assert c.get("/view/mission-run:1", headers={"Authorization": "Bearer k"}).json()["run"] == "mission-run:1"
    assert c.get("/view/nope", headers={"Authorization": "Bearer k"}).status_code == 404



def test_entries_stay_out_of_long_term_memory_and_the_opening_recalls_the_owner_s_facts(J, monkeypatch):
    import time as _t
    J.record("mission:ram", "RAM upgrade", "mission-run:21", "done", "found a kit")
    _t.sleep(0.2)
    assert J.hs == [] and not hasattr(J, "retain")                               # MEM-06: no copy of the entry in Hindsight
    assert J.load("mission:ram")["entries"]                                       # it is in the journal
    monkeypatch.setattr(J, "hindsight", lambda path, body, timeout=30: {"results": [{"text": "The owner's board is an ASRock Z270 Pro4"},
                                                                                   {"text": "x" * 2000}]})
    import memstack as MS
    subs = MS.subscriptions("mission", "mission:ram", own="missions/ram/wiki")
    assert "owner:facts" in subs                                                   # the opening recalls the owner's facts for its task (MEM-24)
    got = MS.items_owner("owner:facts", "mission:ram", "buy 32 GB DDR4")
    assert got[0]["text"] == "The owner's board is an ASRock Z270 Pro4" and got[0]["trust"] == "extracted"

def test_a_write_during_a_fold_is_kept_and_a_long_note_is_refused_not_cut(J, monkeypatch):
    """Review MEM-R9, R18: the fold saved the journal it read minutes before, losing what was written meanwhile; the owner's
    note was cut at 300 characters without a word."""
    import types
    for i in range(J.FOLD_AT):
        J.record("mission:ram", "RAM", None, "done", f"summary {i}")
    def fold(prompt, key, model="", timeout=0):
        J.record("mission:ram", "RAM", None, "done", "written while the model folded")   # the runner, meanwhile
        J.note("mission:ram", "The owner's note typed meanwhile", by="The owner")
        return {"notes": ["Kits under EUR 150 are rare"]}
    monkeypatch.setattr(J, "M", types.SimpleNamespace(ask_json=fold, now=J.dt.datetime.now))
    monkeypatch.setenv("VK_JOURNAL", "k")
    assert J.curate() == 1
    doc = J.load("mission:ram")
    assert any("written while the model folded" in " ".join(e["lines"]) + e["head"] for e in doc["entries"])
    assert doc["notes"] == ["Kits under EUR 150 are rare", "The owner's note typed meanwhile"]
    assert len(doc["entries"]) == J.KEEP + 1
    with pytest.raises(ValueError, match="limit"):
        J.note("mission:ram", "x" * (J.NOTE_CHARS + 1), by="The owner")

"""The repository card and what a coder can reach (DEC-49, docs/CODER-KNOWLEDGE.md): a small card made without a model from what
onboarding learned, given first to every coding run; the owner's pins and strikes; everything else exported as files to grep,
never pushed; the edit hook's linter; the brief's tests to run first and closest example; the exam's knowledge arm."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ops"))
import onboard as O  # noqa: E402
import repocard as RC  # noqa: E402
import pysrc  # noqa: E402
import webjs  # noqa: E402

CONV = """---
title: Conventions
commit: abc123
files:
- app/app.py
---

## Facts

- Standard library only. (evidence: README.md, Rules (SEC-1))
- Date not supplied: Keep JSON error bodies as {"error": "..."} in app/app.py.

## Superseded

- An old rule nobody keeps.
"""
GUIDE = """# Guide

## Module map

- app/: the service.

## How to extend it

- Add a branch in `do_GET`, copy `/api/stats` (`app/app.py:67`).

## Fragile areas

- Keep `scp -O`: the NAS has SFTP disabled.
"""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for attr, sub in (("CODE", "code"), ("DOCS", "docs"), ("VAULT", "vault")):
        (tmp_path / sub).mkdir()
        monkeypatch.setattr(O, attr, tmp_path / sub)
    d = O.CODE / "notes"
    (d / "app").mkdir(parents=True)
    (d / "tests").mkdir()
    (d / ".git").mkdir()
    (d / "app" / "app.py").write_text("x = 1\n")
    (d / "tests" / "test_app.py").write_text("def test_x():\n    pass\n")
    (d / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    w = O.VAULT / "repos" / "notes" / "wiki"
    w.mkdir(parents=True)
    (w / "conventions.md").write_text(CONV)
    (O.DOCS / "notes.analysis.md").write_text(GUIDE)
    monkeypatch.setattr(O, "head_of", lambda name: "1234567890abcdef")
    return d


def test_the_card_is_made_from_what_onboarding_learned_without_a_model(repo):
    """DEC-49: commands from the repository's files when no change has learned them, the wiki's current conventions (not the
    superseded ones, the evidence kept as the source, no "Date not supplied"), the guide's fragile areas and parts and where to
    start; each line keeps the files it cites."""
    c = RC.make("notes")
    kinds = {x["kind"] for x in c["lines"]}
    assert {"command", "rule", "fragile", "module", "start"} <= kinds and c["commit"] == "1234567890ab"
    texts = [x["text"] for x in c["lines"]]
    assert "All tests: `python3 -m pytest -q`" in texts and "Lint the files you changed: `ruff check {files}`" in texts
    assert "Standard library only." in texts and not any("old rule" in t or "Date not supplied" in t for t in texts)
    rule = next(x for x in c["lines"] if x["text"] == "Standard library only.")
    assert "README.md" in rule["files"] and "SEC-1" in rule["source"]
    assert any(x["kind"] == "start" and "app/app.py" in x["files"] for x in c["lines"])
    t = RC.text("notes", folder="/work/.memory/knowledge/notes")
    assert t.startswith("## The repository card: notes") and "### Rules that are not obvious" in t and "/work/.memory/knowledge/notes/" in t
    assert len(t) <= RC.CHARS


def test_the_owner_pins_strikes_and_adds_and_a_remake_keeps_it(repo):
    c = RC.make("notes")
    rule = next(x for x in c["lines"] if x["text"] == "Standard library only.")
    frag = next(x for x in c["lines"] if x["kind"] == "fragile")
    RC.edit("notes", "strike", frag["id"])
    RC.edit("notes", "pin", rule["id"])
    RC.edit("notes", "add", text="Never call the NAS from tests.")
    RC.make("notes")                                                          # Update makes it again; the owner's hand stays
    lines, _ = RC.lines_of("notes")
    assert frag["id"] not in {x["id"] for x in lines}
    rules = [x for x in lines if x["kind"] == "rule"]
    assert rules[0]["id"] == rule["id"] or rules[0]["source"] == "the owner"
    assert any(x["text"] == "Never call the NAS from tests." and x["source"] == "the owner" for x in lines)
    with pytest.raises(ValueError):
        RC.edit("notes", "add", text="  ")
    with pytest.raises(ValueError):
        RC.edit("notes", "explode", "x")


def test_an_exam_s_older_code_gets_no_line_about_files_it_lacks(repo):
    RC.make("notes")
    RC.edit("notes", "add", text="Mind newmod/thing.py when you change the API.")
    lines, _ = RC.lines_of("notes", tree={"app/app.py", "tests/test_app.py"})
    assert not any("newmod/thing.py" in x["text"] for x in lines)
    assert any(x["kind"] == "command" for x in lines)                         # commands always stay


def test_everything_else_is_exported_to_grep_never_pushed(repo, tmp_path):
    RC.make("notes")
    kg = {"nodes": [{"type": "file", "filePath": "app/app.py", "summary": "The notes service. It stores notes."}], "layers": []}
    O.kg_of("notes").parent.mkdir(parents=True, exist_ok=True)
    O.kg_of("notes").write_text(json.dumps(kg))
    dest = tmp_path / "box" / "notes"
    n = RC.export("notes", dest)
    assert n >= 4 and (dest / "card.md").exists() and (dest / "guide.md").exists() and (dest / "wiki" / "conventions.md").exists()
    assert "- app/app.py: The notes service." in (dest / "files.md").read_text()


def test_the_linter_comes_from_the_repository_or_the_errors_that_are_always_errors(repo):
    assert RC.lint_command("notes") == "ruff check {files}"
    (repo / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    assert RC.lint_command("notes") == RC.SAFE_PY_LINT and "E9,F63,F7,F82" in RC.SAFE_PY_LINT
    assert RC.detect(repo)["test"] == "python3 -m pytest -q"


def test_the_card_is_onboarding_s_last_step_and_update_makes_it_again():
    assert O.STEPS[-1] == ("card", "Card for coding agents") and O.UPDATE_STEPS[-2:] == ("wiki", "card")
    src = Path(O.__file__).read_text()
    assert '"card": (VAULT / "repos" / name / "card.json").exists()' in src and 'f"{st[\'repo\']}.notes.json"' in src


def test_a_coding_run_gets_the_card_first_and_the_brief_without_its_commands_twice():
    ms = (ROOT / "ops/memstack.py").read_text()
    assert 'item(coll, f"code:{name}:card", "The repository card"' in ms and "must=True)" in ms.split("def card_item", 1)[1].split("def items_code", 1)[0]
    assert 'if card and h.startswith("commands") and "### Commands" in card["text"]:' in ms and '.replace("\\n### ", "\\n##### ")' in ms
    assert '"knowledge": knowledge}' in ms and "knowledge=ctx.get(\"knowledge\", True)" in ms
    assert 'lines = ([f"the code map: {summaries[f]}"] if f in summaries else [])' in ms and 'out["_folders"] = folders' in ms
    b = pysrc.joined("ops/builds.py") if hasattr(pysrc, "joined") else (ROOT / "ops/builds.py").read_text()
    assert 'RC.export(know, NOTES_DIR / "knowledge" / know' in b and '"-e", f"AISTACK_LINT={lint}"' in b
    assert 'return bool(spec.get("knowledge", not spec.get("trial")))' in b                    # on for real changes, an exam's arm says
    ch = (ROOT / "ops/changes.py").read_text()
    assert 'knowledge=bool(ch.get("knowledge", not ch.get("trial")))' in ch and '"memory_budget", "knowledge")' in ch


def test_the_exam_has_a_knowledge_arm_and_cases_after_the_knowledge_s_commit():
    import replay as RP
    assert RP.ARMS["knowledge"] == {"memory": "knowledge", "notes": True, "brief": True, "knowledge": True}
    assert "knowledge" not in RP.ARMS["swarm"] and "after" in RP.pick.__code__.co_varnames


def test_the_brief_names_tests_to_run_first_and_the_closest_example():
    import repofacts as RF
    known = {"ops/a.py", "ops/b.py", "ops/fetch_feed.py", "tests/test_a.py", "tests/test_b.py"}
    edges = {("ops/b.py", "ops/a.py"): 3}
    got = RF.tests_first("x", ["ops/a.py"], edges, {"ops/a.py": ["tests/test_a.py"]}, known)
    assert got[0] == "tests/test_a.py"
    ex = RF.examples(["ops/feed_reader.py", "tests/test_feed.py", "ops/a.py"], known, {"ops/b.py": "2026-11-08"})
    assert ex[0].startswith("- ops/feed_reader.py is new: write it like ops/fetch_feed.py")       # the name it shares wins
    assert ex[1].startswith("- tests/test_feed.py is new: write it like tests/test_")
    assert len(ex) == 2                                                                          # an existing file needs no example
    assert RF.examples(["ops/new.py"], {"ops/a.py", "ops/b.py"}, {"ops/b.py": "2026-11-08", "ops/a.py": "2026-01-01"})[0].endswith("ops/b.py (the same kind of file in the same folder)")


def hook(name, event, env):
    p = subprocess.run([sys.executable, str(ROOT / "config/hermes/claude-hooks" / name)], input=json.dumps(event), capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", **env})
    assert p.returncode == 0
    return json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"] if p.stdout.strip() else None


def test_a_wide_search_hears_which_folders_its_hits_fall_in_once(tmp_path):
    notes = tmp_path / "build-9.json"
    notes.write_text(json.dumps({"_folders": {"ops": "Host operations.", "tests": "The tests."}}))
    out = "\n".join([f"ops/x{i}.py:1:hit" for i in range(40)] + [f"tests/t{i}.py:2:hit" for i in range(20)])
    ev = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": "s1", "cwd": "/work/r", "tool_input": {"command": "grep -rn hit ."},
          "tool_response": {"stdout": out}}
    said = hook("memory_hook.py", ev, {"AISTACK_MEMNOTES": str(notes)})
    assert "This search printed 60 lines in 2 top folders. ops/ (40 lines): Host operations; tests/ (20 lines): The tests" in said
    assert hook("memory_hook.py", ev, {"AISTACK_MEMNOTES": str(notes)}) is None                   # once per command a session
    narrow = {**ev, "session_id": "s2", "tool_response": {"stdout": "ops/x.py:1:hit"}}
    assert hook("memory_hook.py", narrow, {"AISTACK_MEMNOTES": str(notes)}) is None
    assert hook("memory_hook.py", {**ev, "session_id": "s3", "tool_input": {"command": "pytest -q"}}, {"AISTACK_MEMNOTES": str(notes)}) is None


def test_an_edit_gets_the_repository_s_linter_and_a_missing_linter_says_nothing(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    ev = {"hook_event_name": "PostToolUse", "tool_name": "Edit", "cwd": str(tmp_path), "tool_input": {"file_path": str(tmp_path / "a.py")}}
    lint = "sh -c 'echo \"a.py:1: E1 bad\"; exit 1' -- {files}"
    notes = tmp_path / "build-1.json"
    said = hook("lint_hook.py", ev, {"AISTACK_LINT": lint, "AISTACK_MEMNOTES": str(notes)})
    assert said.startswith("The repository's linter on a.py") and "E1 bad" in said
    assert json.loads((tmp_path / "build-1.json.lint").read_text())["file"].endswith("a.py")     # counted beside the notes
    assert hook("lint_hook.py", ev, {"AISTACK_LINT": "true {files}"}) is None                   # clean says nothing
    assert hook("lint_hook.py", ev, {"AISTACK_LINT": "no-such-linter-here {files}"}) is None    # missing (127) says nothing
    assert hook("lint_hook.py", {**ev, "tool_input": {"file_path": "/etc/passwd"}}, {"AISTACK_LINT": lint}) is None
    assert hook("lint_hook.py", ev, {"AISTACK_LINT": "ruff check {files}"} | {"PATH": ""}) is None
    assert hook("lint_hook.py", {**ev, "tool_input": {"file_path": str(tmp_path / "a.txt")}}, {"AISTACK_LINT": "ruff check {files}"}) is None
    settings = json.loads((ROOT / "config/hermes/claude-hooks/claude-runtime-settings.json").read_text())
    assert any(h["matcher"] == "Edit|Write|MultiEdit" and "lint_hook.py" in h["hooks"][0]["command"] for h in settings["hooks"]["PostToolUse"])


def test_the_app_shows_the_card_with_the_owner_s_hand_on_it_and_what_else_agents_reach():
    app = webjs.app_js()
    assert '["card", "Card"]' in app and "function repoCardHtml(name, r, c)" in app and 'data-card="strike"' in app and 'act: "add"' in app
    assert "What a coding agent is told on first reading this file" in app and 'title="The code this page cites changed since it was written">to check' in app
    assert "<b>To check:</b> the code this page cites changed" in app
    server = pysrc.server()
    assert 'Route("/api/repo/{name}/card", api_repo_card)' in server and '"note": file_note(name, n.get("source_file") or ""),' in server
    req = (ROOT / "ops/missions.requests.py").read_text()
    assert 'if a == "card_edit":' in req and '"card_edit"' in req.split("STACK_ACTIONS = ", 1)[1].split("\n", 1)[0]


def test_a_learned_command_makes_the_card_again(repo, monkeypatch):
    """Overnight exercise, 8 Nov 2026: TestRepo's card kept the pytest command read from its files (it collects no test) after
    change #238 learned the right one by running it."""
    import repowiki as RW
    RC.make("notes")
    assert any(x["text"] == "All tests: `python3 -m pytest -q`" for x in RC.load("notes")["lines"])
    monkeypatch.setattr(RW, "profile_path", lambda name: O.VAULT / "repos" / name / "profile.json")
    monkeypatch.setattr(RW.mm(), "vault_commit", lambda *a, **k: None)                    # the test's vault is a folder
    RW.save_profile("notes", {"test": "python3 tests/test_app.py", "setup": "", "test_one": "", "minutes": 1})
    lines = RC.load("notes")["lines"]
    assert any(x["text"].startswith("The whole suite takes about 1 minute:") for x in lines)
    assert any(x["text"] == "All tests: `python3 tests/test_app.py`" and "learned by running it" in x["source"] for x in lines)
    assert not any("pytest" in x["text"] and x["kind"] == "command" for x in lines)          # nor its one-test command: none was learned


def test_the_card_form_stacks_and_health_shows_each_part_as_a_bar():
    """The owner, 9 Nov 2026: the add form's text field was squeezed to a sliver on the phone ("That one box seems clipped");
    "In health could we visualize more?"; and a card line's files were cut to three with "..."."""
    app = webjs.app_js()
    css = (ROOT / "images/mission-control/web/static/app.css").read_text()
    assert '<form class="cardadd" id="rcardadd">' in app and ".cardadd { display: flex; flex-direction: column;" in css
    assert '${x.files.map(esc).join(", ")}' in app and "x.files.slice(0, 3)" not in app
    assert "function healthBars(byId)" in app and "${healthBars(byId)}" in app and 'h < 4 ? ["err", "weak"]' in app
    assert ".hbar-f.err { background: var(--err); }" in css


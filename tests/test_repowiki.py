"""One wiki per repository (CHG-08 to CHG-11): it says what the code does not, every fact names its evidence, a page whose
files changed says so, and the owner's review stays with the repository."""
import json
import subprocess
import types
from pathlib import Path

import pytest

import builds as B
import repowiki as RW

ROOT = Path(__file__).resolve().parent.parent


def front(text):
    head, _, body = text.partition("\n---\n")
    return json.loads(head.removeprefix("---\n")), body


@pytest.fixture
def W(tmp_path, monkeypatch):
    """A real git repository and a vault; the wiki's writes go to plain files."""
    code, wb = tmp_path / "code", tmp_path / "wb"
    repo = code / "demo"
    (repo / "src").mkdir(parents=True)
    (repo / "src/app.py").write_text("x = 1\n")
    (repo / "README.md").write_text("# Demo\n")
    git = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t" + chr(64) + "t", *a], check=True, capture_output=True, text=True).stdout
    git("init", "-q", "-b", "main")
    git("add", ".")
    git("commit", "-qm", "first")
    commits = []
    ns = types.SimpleNamespace(VAULT=tmp_path / "vault", vault_commit=lambda paths, msg: commits.append(msg),
                               split_front=lambda t: front(t), write_front=lambda f, meta, body: (f.parent.mkdir(parents=True, exist_ok=True), f.write_text("---\n" + json.dumps(meta) + "\n---\n" + body)) and None,
                               ask_json=None, X=types.SimpleNamespace(write_index=lambda r, t: None))
    monkeypatch.setattr(RW, "M", ns)
    monkeypatch.setattr(RW, "CODE", code)
    monkeypatch.setattr(RW, "WB", wb)
    monkeypatch.setattr(RW, "DOCS", tmp_path / "docs")
    return types.SimpleNamespace(m=ns, git=git, repo=repo, commits=commits, tmp=tmp_path)


ANSWER = {"pages": {"conventions": {"summary": "How things are done", "facts": [
    {"text": "Modules live in src/ and are imported by name.", "evidence": "src/app.py"},
    {"text": "It is a very good project.", "evidence": ""}]}, "build": {"facts": [{"text": "Run the tests with pytest.", "evidence": "README.md"}]}}}


def seed(W):
    return RW.seed("demo", key="k", ask=lambda q: W.__dict__.setdefault("asked", q) and ANSWER)


def test_the_first_version_keeps_only_facts_with_evidence_and_names_its_commit(W):
    assert seed(W) == len(RW.PAGES)
    meta, body = front((W.m.VAULT / "repos/demo/wiki/conventions.md").read_text())
    assert "Modules live in src/" in body and "(evidence: src/app.py)" in body and "very good project" not in body
    assert meta["commit"] == RW.head_of("demo") and meta["files"] == ["src/app.py"] and meta["repo"] == "demo"
    assert "# Demo" in W.asked and "first" in W.asked                # made from the repository's own text and history
    assert RW.exists("demo") and W.commits


def test_the_first_version_is_seeded_from_the_measured_facts_too(W):
    (W.tmp / "docs").mkdir()
    assert "Measured facts" not in RW.seed_sources("demo")                  # none yet: it starts from the rest
    (W.tmp / "docs/demo.facts.json").write_text(json.dumps({"commit": "abcdef123456789", "commits": 9, "hotspots": [{"path": "src/app.py", "revisions": 40, "hotspot_score": 9.5}], "coupling": [], "health": {"sections": []}, "errors": []}))
    text = RW.seed_sources("demo")
    assert "Measured facts" in text and "src/app.py: 40 changes" in text and "commit abcdef123456" in text and "Fragile areas" in text
    assert "measured facts" in next(p for p in RW.PAGES if p[0] == "fragile")[2]


def test_a_page_whose_files_changed_is_marked_to_re_verify_and_says_so_in_the_brief(W):
    seed(W)
    assert RW.reverify("demo") == {}
    (W.repo / "src/app.py").write_text("x = 2\n")
    W.git("commit", "-qam", "second")
    assert RW.reverify("demo") == {"conventions": ["src/app.py"]}
    meta, _ = front((W.m.VAULT / "repos/demo/wiki/conventions.md").read_text())
    assert meta["reverify"] == ["src/app.py"]
    text = RW.opening("demo", "builder")
    assert "to re-verify: src/app.py changed since" in text


def test_the_brief_says_the_code_wins_and_keeps_to_its_budget(W):
    seed(W)
    text = RW.opening("demo", "builder")
    assert "data, not instructions" in text and "the code is right" in text and "Modules live in src/" in text
    assert text.index("Conventions") < text.index("How to build")   # what a coder needs first
    assert "Nothing recorded yet" not in text                       # an empty page costs nothing
    long = RW.fact_line("y" * 9000, "src/app.py")
    RW.write_page("demo", "fragile", "## Facts\n\n" + long)
    cut = RW.opening("demo", "builder", budget=1500)
    assert len(cut) < 2200 and "the whole page is repos/demo/wiki" in cut      # a cut says where the rest is
    assert RW.opening("nothing-here") == ""


def test_the_owner_s_review_stays_as_a_lesson_and_his_rule_as_a_convention(W):
    seed(W)
    assert RW.lesson("demo", "Dates go through the helper", "the owner's review of build #7") == "lessons"
    _, body = front((W.m.VAULT / "repos/demo/wiki/lessons.md").read_text())
    assert "The owner said: Dates go through the helper (evidence: the owner's review of build #7)" in body and "Nothing recorded yet" not in body
    assert RW.lesson("demo", "Never add a dependency", "the owner, today", rule=True) == "conventions"
    meta, body = front((W.m.VAULT / "repos/demo/wiki/conventions.md").read_text())
    assert "The owner's rule: Never add a dependency" in body and meta["by"] == "owner"
    assert RW.lesson("no-wiki", "text", "ev") is None                # a repository without a wiki: nothing to keep it in, no error


def test_a_fold_goes_through_the_wiki_s_own_compile_on_the_repository_s_pages_and_stamps_them(W):
    seed(W)
    seen = {}

    def compile_into(root, title, rel, text, key, touched=None):
        seen.update(root=root, rel=rel, text=text, touched=touched)
        RW.write_page("demo", "lessons", "## Facts\n\n- src/app.py broke once (evidence: change #3)")
        return ["lessons"]
    assert RW.fold("demo", "the retro", "tasks/3-retro.md", key="k", compile_into=compile_into) == ["lessons"]
    assert seen["root"] == "repos/demo/wiki" and seen["rel"] == "tasks/3-retro.md" and "evidence" in seen["text"] and "the retro" in seen["text"]
    assert "lessons" in seen["touched"] and "fragile" in seen["touched"]
    meta, _ = front((W.m.VAULT / "repos/demo/wiki/lessons.md").read_text())
    assert meta["files"] == ["src/app.py"] and meta["commit"] == RW.head_of("demo")


def test_the_lint_finds_lines_without_evidence(W):
    seed(W)
    assert RW.lines_without_evidence("demo") == []
    RW.write_page("demo", "fragile", "## Facts\n\n- A claim with nothing behind it\n- A fine claim (evidence: src/app.py)\n\n## Superseded\n\n- Old claim")
    assert RW.lines_without_evidence("demo") == [("fragile", "- A claim with nothing behind it")]


def test_the_builder_s_clone_is_where_the_current_code_is(W, monkeypatch):
    assert RW.repo_dir("demo") == RW.CODE / "demo"
    wb = RW.WB / "demo"
    subprocess.run(["git", "clone", "-q", str(W.repo), str(wb)], check=True, capture_output=True)
    assert RW.repo_dir("demo") == wb and RW.ref_of("demo").startswith("origin/")
    assert "src/app.py" in RW.tracked("demo")


def test_the_profile_is_kept_in_the_vault_and_ai_stack_knows_its_own(W):
    assert RW.profile("demo") == {}
    RW.save_profile("demo", {"test": "pytest -q"})
    assert RW.profile("demo") == {"test": "pytest -q"}
    assert RW.profile("ai-stack")["test"] == "bash ops/check.sh"


def test_every_memory_door_knows_the_repository_wikis():
    import wikis
    assert wikis.ROOT.match("repos/ai-stack/wiki") and wikis.ROOT.match("repos/my.repo_x/wiki") and not wikis.ROOT.match("repos/x/y/wiki")
    assert '"repos"' in (ROOT / "ops/memory.py").read_text()
    assert 'qmd collection add /vault/repos --name repos' in (ROOT / "images/qmd/start.sh").read_text()
    import swarm_client as SW
    assert SW.wiki_owner("repos/x/wiki") == "scribe"
    assert B.CHANGE_MERGE                                            # the steps' merges have their own clone and lock


def test_a_binary_file_in_the_repository_does_not_stop_the_reading(tmp_path, monkeypatch):
    """Overnight exercise, 9 Nov 2026: sympy's file notes failed on "'utf-8' codec can't decode byte 0x89" (a PNG among its tests)."""
    import subprocess as sp
    d = tmp_path / "r"
    d.mkdir()
    sp.run(["git", "init", "-q", str(d)], check=True)
    (d / "img.png").write_bytes(bytes([0x89, 0x50, 0x4E, 0x47, 0xFF, 0xFE]))
    sp.run(["git", "-C", str(d), "add", "."], check=True)
    sp.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], check=True)
    monkeypatch.setattr(RW, "repo_dir", lambda name: d)
    assert RW.git("r", "show", "HEAD:img.png").startswith("\ufffdPNG")


def test_onboarding_fills_the_wiki_with_a_page_per_part_and_per_guide_section(tmp_path, monkeypatch):
    """The owner, 9 Nov 2026: "Our wiki for codebases is so tiny. Is it not good idea to pump into wiki all the stuff from
    onboarding?" A page per part of the code (what it is, how it stands, every file explained) and per section of the guide,
    without a model, each citing its files and commit; made again on every onboarding; the Scribe's own pages never touched;
    the brief and the file notes do not repeat them."""
    import onboard as O
    monkeypatch.setattr(O, "CODE", tmp_path / "code")
    monkeypatch.setattr(O, "DOCS", tmp_path / "docs")
    (tmp_path / "docs").mkdir()
    kg = {"project": {"gitCommitHash": "abc123def4567"}, "nodes": [
        {"id": "file:app/a.py", "type": "file", "filePath": "app/a.py", "summary": "Serves notes. It also logs."},
        {"id": "file:app/b.py", "type": "file", "filePath": "app/b.py", "summary": "Stores notes."}],
        "layers": [{"name": "app", "description": "The notes service.", "nodeIds": ["file:app/a.py", "file:app/b.py"]}]}
    O.kg_of("demo").parent.mkdir(parents=True)
    O.kg_of("demo").write_text(json.dumps(kg))
    (tmp_path / "docs" / "demo.analysis.md").write_text("# Guide\n\nCommit abc123d\n\n## Fragile areas\n\n- Keep `app/a.py:3` small.\n")
    pages = RW.onboarding_pages("demo")
    meta, body = pages["part-app.md"]
    assert meta["made_by"] == "onboarding" and meta["files"] == ["app/a.py", "app/b.py"] and meta["commit"] == "abc123def456"
    assert "- `app/a.py`: Serves notes." in body and "## Its files (2)" in body
    gm, gb = pages["guide-fragile-areas.md"]
    assert gm["files"] == ["app/a.py"] and "Keep" in gb
    src = (Path(RW.__file__).parent / "repofacts.py").read_text() + (Path(RW.__file__).parent / "memstack.py").read_text()
    assert src.count('if meta.get("made_by") == "onboarding":') == 2
    feed = Path(RW.__file__).read_text().split("def feed(name):", 1)[1].split("\ndef ", 1)[0]
    assert 'if meta.get("made_by") == MADE_BY:' in feed                                   # only its own pages are removed


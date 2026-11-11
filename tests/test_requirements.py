"""ops/req.py, the requirements checker: the repo's own requirements pass, and each rule of requirements/README.md
refuses what it should (on a small throwaway repo in tmp_path)."""
import textwrap
from pathlib import Path

import pytest

import req

ROOT = Path(__file__).resolve().parent.parent

NEEDS = """
area: Stakeholder needs
prefix: SN
items:
  - {id: SN-01, title: A need, need: Something the owner wants., priority: must, sources: [README.md]}
"""
DECISIONS = """
area: Decisions
prefix: DEC
items:
  - {id: DEC-01, date: 2026-10-29, title: A decision, decision: The owner decided it.}
"""
FINDINGS = """
area: Findings
prefix: FND
items:
  - id: FND-01
    severity: low
    kind: drift
    title: A finding
    finding: The doc says one thing, the code another.
    evidence: ["src.py:1"]
    affects: [XX-01]
    recommendation: Fix the doc.
    status: open
"""
AREA = """
area: Example
prefix: XX
items:
  - id: XX-01
    title: It answers
    statement: When asked, the runner shall answer within 2 seconds.
    type: functional
    priority: must
    status: implemented
    parents: [SN-01]
    sources: [DEC-01, README.md]
    verify: {method: test, by: [tests/test_a.py::test_one]}
    trace: [src.py]
    findings: [FND-01]
"""


def repo(tmp_path, area=AREA, tests="def test_one():\n    pass\n", base="", **files):
    (tmp_path / "requirements").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "README.md").write_text("x")
    (tmp_path / "src.py").write_text("x")
    (tmp_path / "tests" / "test_a.py").write_text(tests)
    docs = {"stakeholder-needs.yaml": NEEDS, "decisions.yaml": DECISIONS, "findings.yaml": FINDINGS, "example.yaml": area, **files}
    for name, text in docs.items():
        (tmp_path / "requirements" / name).write_text(textwrap.dedent(text))
    (tmp_path / "requirements" / "unmapped-tests.txt").write_text("# list\n" + base)
    (tmp_path / "requirements" / "REQUIREMENTS.md").write_text(req.render(tmp_path))
    return tmp_path


def problems(root):
    return "\n".join(req.check(root))


def test_the_repo_requirements_pass_the_checker():
    assert req.check(ROOT) == []


def test_missing_fields_and_unknown_values_are_refused(tmp_path):
    assert req.check(repo(tmp_path)) == []                                     # the small repo itself is sound
    bad = AREA.replace("    type: functional\n", "    type: wish\n").replace("status: implemented", "status: done")
    p = problems(repo(tmp_path / "a", area=bad))
    assert "type must be one of" in p and "status must be one of" in p
    p = problems(repo(tmp_path / "b", area=AREA.replace("    priority: must\n", "")))
    assert "XX-01 (example.yaml): priority must be one of" in p
    p = problems(repo(tmp_path / "c", area=AREA.replace("id: XX-01", "id: XX-1")))
    assert "id must be XX-<number>" in p


def test_dangling_references_are_refused(tmp_path):
    bad = (AREA.replace("parents: [SN-01]", "parents: [SN-09]").replace("sources: [DEC-01, README.md]", "sources: [DEC-07, docs/none.md]")
           .replace("trace: [src.py]", "trace: [gone.py]").replace("test_a.py::test_one", "test_a.py::test_missing"))
    p = problems(repo(tmp_path, area=bad))
    for want in ("unknown parent SN-09", "unknown source DEC-07", "source docs/none.md does not exist", "trace gone.py does not exist",
                 "test_a.py::test_missing is not a test", "SN-01: no requirement refines this need"):
        assert want in p, want


def test_vague_statements_are_refused(tmp_path):
    p = problems(repo(tmp_path, area=AREA.replace("shall answer within 2 seconds", "shall answer quickly")))
    assert "vague word 'quickly'" in p
    p = problems(repo(tmp_path / "b", area=AREA.replace("the runner shall answer", "the runner answers")))
    assert "no 'shall' (EARS)" in p


def test_status_needs_its_evidence(tmp_path):
    p = problems(repo(tmp_path, area=AREA.replace("status: implemented", "status: partial")))
    assert "partial needs a gap" in p
    p = problems(repo(tmp_path / "b", area=AREA.replace("status: implemented", "status: violated\n    gap: It does not.").replace("    findings: [FND-01]\n", "")))
    assert "violated needs a finding" in p and "affects XX-01, but XX-01 does not list it" in p   # findings link both ways
    p = problems(repo(tmp_path / "c", area=AREA.replace("status: implemented", "status: deprecated")))
    assert "deprecated needs superseded_by or reason" in p
    no_verify = AREA.replace("    verify: {method: test, by: [tests/test_a.py::test_one]}\n", "")
    p = problems(repo(tmp_path / "d", area=no_verify, base="tests/test_a.py::test_one\n"))
    assert "implemented needs verify" in p
    planned = no_verify.replace("status: implemented", "status: planned\n    acceptance: A test will ask it.")
    assert "XX-01" not in problems(repo(tmp_path / "e", area=planned, base="tests/test_a.py::test_one\n"))   # planned needs no proof yet


def test_an_unclaimed_test_is_refused_and_the_baseline_only_shrinks(tmp_path):
    two = "def test_one():\n    pass\n\n\ndef test_two():\n    pass\n"
    assert "tests/test_a.py::test_two: no requirement claims this test" in problems(repo(tmp_path, tests=two))
    assert req.check(repo(tmp_path / "b", tests=two, base="tests/test_a.py::test_two\n")) == []
    p = problems(repo(tmp_path / "c", base="tests/test_a.py::test_one\ntests/test_a.py::test_gone\n"))
    assert "test_one is claimed now; remove it" in p and "test_gone no longer exists; remove it" in p


def test_the_rendering_is_current_and_complete(tmp_path):
    root = repo(tmp_path)
    assert req.render(root) == req.render(root)                                 # deterministic, so it can be compared
    text = req.render(root)
    for want in ("### XX-01", "### FND-01", "**SN-01**", "**DEC-01**", "`tests/test_a.py::test_one` | [XX-01](#xx-01)", "| **All** | **1** |"):
        assert want in text, want
    (root / "requirements" / "example.yaml").write_text(textwrap.dedent(AREA).replace("within 2 seconds", "within 3 seconds"))
    assert "REQUIREMENTS.md is stale" in problems(root)


def test_planned_needs_acceptance_and_a_known_phase(tmp_path):
    no_verify = AREA.replace("    verify: {method: test, by: [tests/test_a.py::test_one]}\n", "")
    planned = no_verify.replace("status: implemented", "status: planned")
    base = "tests/test_a.py::test_one\n"
    assert "planned needs acceptance" in problems(repo(tmp_path, area=planned, base=base))
    phased = "phases: {0: Proof, 1: First}\n" + planned.replace("status: planned", "status: planned\n    acceptance: A test.\n    phase: 7")
    assert "XX-01 (example.yaml): phase must be one of [0, 1]" in problems(repo(tmp_path / "b", area=phased, base=base))
    assert "XX-01" not in problems(repo(tmp_path / "c", area=phased.replace("phase: 7", "phase: 1"), base=base))
    assert "phase given, but the area lists no phases" in problems(repo(tmp_path / "d", area=AREA + "    phase: 1\n"))


def test_groups_and_phases_are_rendered(tmp_path):
    area = "phases: {0: Proof, 1: First}\n" + AREA + "    group: Answers\n    phase: 1\n    acceptance: A test.\n"
    text = req.render(repo(tmp_path, area=area))
    for want in ("| 1 | First | [XX-01](#xx-01) |", "### Answers", "#### XX-01", "- Phase: 1 First", "- Acceptance: A test."):
        assert want in text, want
    assert "#### XX-01" not in req.render(repo(tmp_path / "b"))                  # ungrouped areas keep ### per requirement


@pytest.mark.parametrize("word", ["appropriate", "etc", "user-friendly", "as needed", "several"])
def test_vague_words_are_known(word):
    assert req.VAGUE_RE.search(f"the runner shall be {word}")
    assert not req.VAGUE_RE.search("the runner shall use gpt-sub-fast")      # a name is not a vague word


def sources(root):
    (root / "ops").mkdir()
    (root / "ops" / "tool.py").write_text("x")
    (root / "images" / "app").mkdir(parents=True)
    (root / "images" / "app" / "app.py").write_text("x")
    (root / "images" / "app" / "Dockerfile").write_text("x")
    return root


def test_every_source_file_is_traced_or_listed_with_a_reason(tmp_path):
    p = problems(sources(repo(tmp_path)))                                     # QA-18, FND-69
    assert "ops/tool.py: no requirement names this file" in p and "images/app/app.py: no requirement names" in p
    assert "images/app/Dockerfile: no requirement names" in p                  # its image's code is not traced either
    root = sources(repo(tmp_path / "b", area=AREA.replace("trace: [src.py]", "trace: [src.py, images/app/app.py]")))
    (root / "requirements" / "untraced-files.txt").write_text("# list\nops/tool.py  # a one-off helper\nimages/app/app.py\nops/gone.py  # old\n")
    p = problems(root)
    assert "ops/tool.py" not in p and "Dockerfile" not in p                     # listed with a reason; goes with app.py
    assert "untraced-files.txt: images/app/app.py is traced now; remove it" in p and "ops/gone.py no longer exists" in p
    (root / "requirements" / "untraced-files.txt").write_text("ops/tool.py\n")
    assert "untraced-files.txt: ops/tool.py needs its reason after a #" in problems(root)


def _git(root, *args):
    import os
    import subprocess
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "test@example.com"}
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True, env=env).stdout.strip()


SECOND = AREA + """
  - id: XX-02
    title: It remembers
    statement: When asked twice, the runner shall answer the second time from its record.
    type: functional
    priority: should
    status: implemented
    parents: [SN-01]
    sources: [README.md]
    verify: {method: test, by: [tests/test_a.py::test_one]}
"""


def _landing(tmp_path, area):
    """A target branch with XX-01 and XX-02, then the branch that lands with `area` instead -> (base, problems)."""
    root = repo(tmp_path, area=SECOND)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "main")
    base = _git(root, "rev-parse", "HEAD")
    (root / "requirements" / "example.yaml").write_text(textwrap.dedent(area))
    _git(root, "commit", "-qam", "the branch")
    return base, req.kept(root, base, "HEAD")


def test_an_id_on_the_target_branch_may_be_added_to_or_deprecated_but_never_renumbered_reused_or_removed(tmp_path):
    """QA-28 (review 10 Nov 2026, D2): WFL-15..19 became WFL-19..23 in one day and commit trailers pointed at other
    requirements; a landing that changes what an id of main means stops, with the ids named."""
    added = SECOND + """
  - id: XX-03
    title: It forgets on request
    statement: When the owner asks, the runner shall delete its record within 1 minute.
    type: functional
    priority: could
    status: proposed
    parents: [SN-01]
    sources: [README.md]
"""
    assert _landing(tmp_path / "a", added)[1] == []
    deprecated = SECOND.replace("    status: implemented\n    parents: [SN-01]\n    sources: [README.md]\n",
                                "    status: deprecated\n    reason: the record is gone\n    parents: [SN-01]\n    sources: [README.md]\n")
    assert "deprecated" in deprecated and _landing(tmp_path / "b", deprecated)[1] == []

    renumbered = SECOND.replace("id: XX-02", "id: XX-04")
    base, problems = _landing(tmp_path / "c", renumbered)
    assert len(problems) == 1 and problems[0].startswith(f'XX-02 ("It remembers") is on {base} and gone here')
    assert "its title is now at XX-04: renumbered?" in problems[0]

    reused = SECOND.replace("title: It remembers", "title: It sends a summary")
    problems = _landing(tmp_path / "d", reused)[1]
    assert len(problems) == 1 and '"It remembers"' in problems[0] and '"It sends a summary"' in problems[0]
    assert "never reused" in problems[0]

    removed = AREA
    problems = _landing(tmp_path / "e", removed)[1]
    assert len(problems) == 1 and "XX-02" in problems[0] and "never removed" in problems[0]


def test_a_title_changes_in_words_only_with_the_old_one_kept_and_an_unreadable_branch_is_no_pass(tmp_path):
    reworded = SECOND.replace("title: It remembers", "title: It remembers what it answered\n    titles_before: [It remembers]")
    assert _landing(tmp_path / "a", reworded)[1] == []
    root = tmp_path / "a"
    (root / "requirements" / "REQUIREMENTS.md").write_text(req.render(root))
    assert req.check(root) == [] and "Earlier titles: `It remembers`" in req.render(root)
    bad = SECOND.replace("title: It remembers", "title: It remembers\n    titles_before: It was")
    (root / "requirements" / "example.yaml").write_text(textwrap.dedent(bad))
    assert any("titles_before is a list" in p for p in req.check(root))
    problems = req.kept(root, "no-such-branch", "HEAD")
    assert problems == ["no-such-branch could not be read, so whether every requirement id kept its meaning is not known"]

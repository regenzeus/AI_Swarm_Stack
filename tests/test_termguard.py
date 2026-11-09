"""ops/termguard.py (SEC-22): what the deployment's private never-in-git list forbids is refused on commit (the change and
the message) and on push (every commit the push sends), also on the runner's own pushes, which run no hook. The guard
never prints a match, and without a list everything passes."""
import os
import subprocess
from pathlib import Path

import pytest

import termguard as TG

ROOT = Path(__file__).resolve().parents[1]


def run(*a, cwd, env=None, check=True):
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True, check=check, env=env)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    lst = tmp_path / "never.txt"
    lst.write_text("# test list\nforbiddenword\n(?<![a-z])tla(?![a-z])\n")
    env = {**os.environ, "NEVER_IN_GIT": str(lst), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "test@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "test@example.com"}
    monkeypatch.setattr(TG, "LIST", lst)
    bare, repo = tmp_path / "remote.git", tmp_path / "repo"
    run("git", "init", "-q", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    run("git", "clone", "-q", str(bare), str(repo), cwd=tmp_path)
    run("git", "config", "core.hooksPath", str(ROOT / "ops/git-hooks"), cwd=repo)
    return repo, env


def commit(repo, env, name, text, msg="a change", verify=True):
    (repo / name).write_text(text)
    run("git", "add", name, cwd=repo, env=env)
    return run("git", "commit", "-q", *([] if verify else ["--no-verify"]), "-m", msg, cwd=repo, env=env, check=False)


def test_a_commit_holding_a_forbidden_term_is_refused_and_a_clean_one_passes(setup):
    repo, env = setup
    r = commit(repo, env, "a.txt", "this mentions ForbiddenWord once\n")
    assert r.returncode == 1 and "never-in-git list forbids (its line 2" in r.stderr and "ForbiddenWord" not in r.stderr
    run("git", "reset", "-q", cwd=repo, env=env)
    r = commit(repo, env, "b.txt", "clean\n", msg="about the tla site")
    assert r.returncode == 1 and "the message holds" in r.stderr
    r = commit(repo, env, "c.txt", "function phoneTlaHtml() {}\nclean\n", msg="a clean change")   # a short term inside a word passes
    assert r.returncode == 0, r.stderr


def test_a_push_of_a_commit_that_skipped_the_hooks_is_refused(setup):
    repo, env = setup
    assert commit(repo, env, "ok.txt", "clean\n").returncode == 0
    assert run("git", "push", "-q", "origin", "main", cwd=repo, env=env, check=False).returncode == 0
    assert commit(repo, env, "x.txt", "forbiddenword\n", verify=False).returncode == 0           # --no-verify skips the commit hooks
    r = run("git", "push", "-q", "origin", "main", cwd=repo, env=env, check=False)
    assert r.returncode == 1 and "push refused" in r.stderr and "forbiddenword" not in r.stderr.lower()


def test_the_runners_own_push_is_guarded_and_a_removed_line_is_no_leak(setup):
    repo, env = setup
    commit(repo, env, "x.txt", "forbiddenword\n", verify=False)
    assert TG.push_revs(["-q", "origin", "main"]) == ["main"] and TG.push_revs(["-q", "-f", "url", "b1:refs/heads/ai/b1"]) == ["b1"]
    assert TG.push_revs(["-q", "origin", "--delete", "b1"]) == []
    assert "its line 2" in TG.refused(repo, ["main"])
    run("git", "rm", "-q", "x.txt", cwd=repo, env=env)
    run("git", "commit", "-q", "--no-verify", "-m", "remove it", cwd=repo, env=env)
    assert TG.refused(repo, ["main", "^main~1"]) == ""                                  # removing the line sends nothing forbidden
    src = (ROOT / "ops/builds.py").read_text()
    assert 'why = TG.refused(path, TG.push_revs(list(args[1:])))' in src and "termguard.py\"), \"install\"" in (ROOT / "ops/deploy.py").read_text()


def test_without_a_list_everything_passes(tmp_path):
    assert TG.patterns(tmp_path / "none.txt") == [] and TG.found("anything", []) == []

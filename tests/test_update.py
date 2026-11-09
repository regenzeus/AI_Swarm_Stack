"""Updates from signed-off tags (GEN-16): only a release tag signed by a key the deployment allows is deployed, after the
whole check on its tree; main, a commit, an unsigned or a stranger's tag is refused, and a failed deploy goes back."""
import shutil
import subprocess

import pytest

import update as U

pytestmark = pytest.mark.skipif(not shutil.which("ssh-keygen"), reason="no ssh-keygen for signing")


def sh(*a, cwd=None):
    return subprocess.run(list(a), cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def R(tmp_path):
    keys = {}
    for who in ("owner", "stranger"):
        sh("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", who, "-f", str(tmp_path / who))
        keys[who] = tmp_path / who
    repo = tmp_path / "stack"
    repo.mkdir()
    g = lambda *a: sh("git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=test@example.com", "-c", "gpg.format=ssh", *a)
    g("init", "-q", "-b", "main")
    (repo / "a.txt").write_text("one\n")
    g("add", "-A")
    g("commit", "-qm", "one")
    first = g("rev-parse", "HEAD")
    (repo / "a.txt").write_text("two\n")
    g("commit", "-qam", "two")
    g("-c", f"user.signingkey={keys['owner']}", "tag", "-s", "v2026.11.08", "-m", "Released by the owner")
    g("-c", f"user.signingkey={keys['stranger']}", "tag", "-s", "v2026.11.09", "-m", "Not the owner")
    g("tag", "-a", "v2026.11.10", "-m", "annotated, unsigned")
    g("tag", "v2026.11.11")                                   # lightweight
    g("checkout", "-q", "--detach", first)
    signers = tmp_path / "allowed_signers"
    signers.write_text(f"owner {(keys['owner'].with_suffix('.pub')).read_text().split(' ', 2)[0]} {(keys['owner'].with_suffix('.pub')).read_text().split(' ', 2)[1]}\n")
    return type("R", (), {"repo": repo, "signers": signers, "first": first})


def test_only_a_release_tag_the_owner_signed_passes(R):
    assert U.check(R.repo, "v2026.11.08", R.signers) is None
    assert "not signed by a key this deployment allows" in U.check(R.repo, "v2026.11.09", R.signers)
    assert "not signed by a key this deployment allows" in U.check(R.repo, "v2026.11.10", R.signers)
    assert "not an annotated tag" in U.check(R.repo, "v2026.11.11", R.signers)
    for ref in ("main", R.first, "HEAD"):
        assert "is no release tag" in U.check(R.repo, ref, R.signers)
    assert "no allowed signers" in U.check(R.repo, "v2026.11.08", R.signers.with_name("none"))


def test_an_update_checks_before_it_deploys_and_a_failed_deploy_goes_back(R):
    ran = []
    said = U.apply(R.repo, "v2026.11.08", R.signers, run_checks=lambda c: ran.append(("checks", c)) or True,
                   deploy=lambda old, new: ran.append(("deploy", old, new)) or True)
    assert said.startswith("UPDATED to v2026.11.08") and [r[0] for r in ran] == ["checks", "deploy"]
    assert (R.repo / "a.txt").read_text() == "two\n"
    sh("git", "-C", str(R.repo), "checkout", "-q", "--detach", R.first)
    said = U.apply(R.repo, "v2026.11.08", R.signers, run_checks=lambda c: False, deploy=lambda o, n: pytest.fail("deployed after failed checks"))
    assert said.startswith("NOT UPDATED: the checks failed") and (R.repo / "a.txt").read_text() == "one\n"
    said = U.apply(R.repo, "v2026.11.08", R.signers, run_checks=lambda c: True, deploy=lambda o, n: o != R.first)
    assert said.startswith("DEPLOY FAILED") and (R.repo / "a.txt").read_text() == "one\n"      # back where it was
    assert U.apply(R.repo, "main", R.signers, run_checks=lambda c: True, deploy=lambda o, n: True).startswith("NOT UPDATED")

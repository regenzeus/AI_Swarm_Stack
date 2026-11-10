"""ops/deploy.py main() end to end, every outside effect stubbed (review QA-R1: of 9 planted defects in deploy.py 6 went
unnoticed; a failed health check, a failed step or a missing smoke test still said DEPLOY OK, so the rollback that
depends on it could silently stop working)."""
import json
import types

import pytest

import deploy as D


@pytest.fixture
def stub(monkeypatch, tmp_path):
    ran, fail = [], set()
    state = {"changed": "ops/missions.py\n", "healthy": True}
    monkeypatch.setattr(D, "ok", True)
    monkeypatch.setenv("DEPLOY_RECORD", str(tmp_path / "deploys.jsonl"))

    def run(*cmd, timeout=1800, **kw):
        ran.append(" ".join(cmd))
        if any(f in " ".join(cmd) for f in fail):
            D.ok = False
            return False
        return True
    monkeypatch.setattr(D, "run", run)
    monkeypatch.setattr(D, "healthy", lambda url, n=100: state["healthy"])
    monkeypatch.setattr(D.subprocess, "run", lambda cmd, **k: types.SimpleNamespace(stdout=state["changed"], returncode=1, stderr=""))
    return types.SimpleNamespace(ran=ran, fail=fail, state=state, record=tmp_path / "deploys.jsonl")


def last(stub):
    return json.loads(stub.record.read_text().splitlines()[-1])


def test_a_whole_deploy_says_ok_and_runs_the_smoke_test(stub, capsys):
    assert D.main("a" * 40, "b" * 40) == 0
    assert "DEPLOY OK" in capsys.readouterr().out and last(stub)["ok"] is True
    assert any("smoke/smoke.sh" in r for r in stub.ran)


@pytest.mark.parametrize("what", ["smoke", "health", "build"])
def test_a_failed_smoke_test_health_check_or_build_is_a_failed_deploy(stub, capsys, what):
    if what == "smoke":
        stub.fail.add("smoke/smoke.sh")
    elif what == "health":
        stub.state["healthy"] = False
    else:
        stub.state["changed"] = "images/desk/desk.py\n"
        stub.fail.add("docker build")
    assert D.main("a" * 40, "b" * 40) == 1
    out = capsys.readouterr().out
    assert "DEPLOY FAILED" in out and "DEPLOY OK" not in out and last(stub)["ok"] is False


def test_a_new_machine_builds_in_from_order_with_the_pins_and_stops_on_a_failure(stub, capsys):
    """review OPS-R6: new-machine.sh built alphabetically (the builder before Hermes, its base), with no base pins, and a
    failed build still read "images built"."""
    assert D.build_all(["builder", "hermes", "pricewatch"]) == 0
    builds = [r for r in stub.ran if r.startswith("docker build")]
    assert [b.split()[-1] for b in builds].index("images/hermes") < [b.split()[-1] for b in builds].index("images/builder")
    assert any("--build-arg PRICEWATCH_IMAGE=" in b for b in builds)
    stub.ran.clear()
    stub.fail.add("images/hermes")
    assert D.build_all(["builder", "hermes"]) == 1
    assert not any("images/builder" in r for r in stub.ran)        # stopped at the failure
    assert "did not build" in capsys.readouterr().out


@pytest.mark.parametrize("ready", [True, False])
def test_an_n8n_image_change_goes_ahead_while_runs_wait_and_waits_until_n8n_is_ready(stub, monkeypatch, capsys, ready):
    """PLT-39: a new n8n image keeps every waiting run (2.44.7 -> 2.45.4 on 10 Nov 2026: a run in wait_item and one in a
    long command both resumed on the new image, docs/N8N-MIGRATION.md §11), so the deploy neither refuses nor waits for
    them; it recreates n8n with compose and then waits for /healthz/readiness, which n8n answers only after its
    migrations, its workflows and its start-up recovery (/healthz answers before all three). An n8n that never gets
    ready is a failed deploy."""
    old = "N8N_IMAGE=n8nio/n8n:2.44.7@sha256:aa\nPOSTGRES_IMAGE=postgres:17-alpine\n"
    new = "N8N_IMAGE=n8nio/n8n:2.45.4@sha256:bb\nPOSTGRES_IMAGE=postgres:17-alpine\n"
    git = {f"{'a' * 40}:versions.env": old, f"{'b' * 40}:versions.env": new}
    monkeypatch.setattr(D.subprocess, "run", lambda cmd, **k: types.SimpleNamespace(
        stdout=git.get(cmd[-1], "versions.env\n") if cmd[:2] == ["git", "show"] else "versions.env\n", returncode=0, stderr=""))
    asked = []
    monkeypatch.setattr(D, "healthy", lambda url, n=100: asked.append(url) or (ready or url != D.N8N_READY))
    assert D.main("a" * 40, "b" * 40) == (0 if ready else 1)
    out = capsys.readouterr().out
    assert any(" compose " in r and r.endswith("up -d --remove-orphans") for r in stub.ran)
    assert "n8n's image changes: n8nio/n8n:2.44.7 -> n8nio/n8n:2.45.4; runs that wait in n8n resume" in out
    assert asked[0] == D.N8N_READY == "http://127.0.0.1:5678/healthz/readiness"
    assert ("n8n on its new image: ready" in out and "DEPLOY OK" in out) if ready else ("NOT READY" in out and "DEPLOY FAILED" in out)
    assert D.n8n_upgrade(["versions.env"], "a" * 40, "a" * 40) == [] and D.n8n_upgrade(["compose/core.yaml"], "a" * 40, "b" * 40) == []
    src = (D.R / "ops/deploy.py").read_text()                     # the import after a workflow change waits for readiness too
    assert "healthy(N8N_READY)" in src and 'healthy("http://127.0.0.1:5678/healthz")' not in src

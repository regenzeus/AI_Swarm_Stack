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

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


class FakeSystemctl:
    """systemctl --user as far as a deploy uses it: the enabled timers, enable/disable --now, is-active, daemon-reload."""
    def __init__(self, enabled, fail=()):
        self.enabled, self.fail = set(enabled), set(fail)

    def __call__(self, cmd):
        """-> (exit code, output) of one call."""
        verb, args = cmd[2], [a for a in cmd[3:] if not a.startswith("-")]
        if verb == "list-unit-files":
            return 0, "".join(f"{n} enabled enabled\n" for n in sorted(self.enabled))
        if verb in ("enable", "disable") and set(args) & self.fail:
            return 1, ""
        if verb == "enable":
            self.enabled |= set(args)
        elif verb == "disable":
            self.enabled -= set(args)
        return (3 if verb == "is-active" else 0), ""


@pytest.fixture
def site(monkeypatch, tmp_path):
    """main() on a machine with a fake systemctl and its user units in tmp_path; every other outside effect stubbed."""
    s = types.SimpleNamespace(ran=[], fail=set(), changed=[], rollback=False, systemctl=FakeSystemctl(()),
                              units=tmp_path / ".config/systemd/user", record=tmp_path / "deploys.jsonl")
    s.units.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DEPLOY_RECORD", str(s.record))
    monkeypatch.setattr(D, "ok", True)
    monkeypatch.setattr(D, "healthy", lambda url, n=100: True)

    def run(*cmd, timeout=1800, **kw):
        s.ran.append(" ".join(cmd))
        good = s.systemctl(cmd)[0] == 0 if cmd[0] == "systemctl" else not any(f in " ".join(cmd) for f in s.fail)
        if not good:
            D.ok = False
        return good

    def sub(cmd, **kw):
        if cmd[0] == "systemctl":
            code, out = s.systemctl(cmd)
        elif cmd[:2] == ["git", "merge-base"]:
            code, out = (0 if s.rollback else 1), ""
        elif cmd[:2] == ["git", "diff"]:
            code, out = 0, "\n".join(s.changed)
        else:
            code, out = 0, ""
        return types.SimpleNamespace(returncode=code, stdout=out, stderr="")
    monkeypatch.setattr(D, "run", run)
    monkeypatch.setattr(D.subprocess, "run", sub)
    return s


def installed(site, *names):
    for n in names:
        (site.units / n).write_text("[Timer]\n")


@pytest.mark.parametrize("fails", ["smoke", "enable"])
def test_a_failed_deploy_leaves_the_same_timers_enabled_as_before_it(site, capsys, fails):
    """PLT-43: a failed deploy enables no timer it brings, takes off no unit the repository dropped, and leaves the
    owner's own timers alone; when enabling its new timers fails half way, the ones it enabled are disabled again."""
    installed(site, "backup.timer", "crew-old.timer", "own.timer")
    before = {"backup.timer", "crew-old.timer", "own.timer"}
    site.systemctl.enabled = set(before)
    site.changed = ["ops/systemd/stack-ready.timer", "ops/systemd/restore-drill.timer", "ops/systemd/backup.timer",
                    "ops/systemd/crew-old.timer"]                  # two new timers, one changed, one the repository dropped
    if fails == "smoke":
        site.fail.add("smoke/smoke.sh")
    else:
        site.systemctl.fail.add("restore-drill.timer")            # the second new timer cannot be enabled
    assert D.main("a" * 40, "b" * 40) == 1
    out = capsys.readouterr().out
    assert "DEPLOY FAILED" in out and site.systemctl.enabled == before
    assert (site.units / "crew-old.timer").exists() and (site.units / "stack-ready.timer").exists()
    if fails == "smoke":
        assert not any(" enable " in r for r in site.ran) and "disabled again" not in out
    else:
        assert "systemctl --user enable --now stack-ready.timer" in site.ran
        assert "timer stack-ready.timer: disabled again, as this deploy found it" in out


def test_a_good_deploy_enables_its_new_timers_and_takes_off_the_dropped_ones_after_the_checks(site, capsys):
    installed(site, "backup.timer", "crew-old.timer")
    site.systemctl.enabled = {"backup.timer", "crew-old.timer", "own.timer"}
    site.changed = ["ops/systemd/stack-ready.timer", "ops/systemd/backup.timer", "ops/systemd/crew-old.timer"]
    assert D.main("a" * 40, "b" * 40) == 0
    out = capsys.readouterr().out
    assert site.systemctl.enabled == {"backup.timer", "stack-ready.timer", "own.timer"} and not (site.units / "crew-old.timer").exists()
    assert "unit crew-old.timer removed" in out and "DEPLOY OK" in out
    smoke = next(i for i, r in enumerate(site.ran) if "smoke/smoke.sh" in r)
    assert smoke < site.ran.index("systemctl --user enable --now stack-ready.timer")
    assert smoke < site.ran.index("systemctl --user disable --now crew-old.timer")


@pytest.mark.parametrize("good", [True, False])
def test_a_rollback_enables_no_timer_of_its_diff_and_leaves_the_enabled_ones_as_it_found_them(site, capsys, good):
    """PLT-43. 10 Nov 2026, a site's first update: the rollback after a failed update (ops/update.py's
    `deploy.py <new> <old>`) enabled graphify-sync, a timer of its diff that the site never had. A rollback brings back
    the units of the older commit but enables none of them, and takes off the units the newer one added."""
    installed(site, "backup.timer", "added-by-new.timer")
    before = {"backup.timer", "own.timer"}
    site.systemctl.enabled = set(before)
    site.rollback = True
    site.changed = ["ops/systemd/restore-drill.timer", "ops/systemd/backup.timer", "ops/systemd/added-by-new.timer"]
    if not good:
        site.fail.add("smoke/smoke.sh")
    assert D.main("b" * 40, "a" * 40) == (0 if good else 1)
    out = capsys.readouterr().out
    assert "a rollback to aaaaaaaa: it enables no timer" in out and site.systemctl.enabled == before
    assert (site.units / "restore-drill.timer").exists() and not (site.units / "added-by-new.timer").exists()
    assert not any(" enable " in r for r in site.ran)


def test_putting_back_touches_only_the_diffs_timers_and_says_what_it_cannot(tmp_path):
    (tmp_path / "a.timer").write_text("[Timer]\n")
    calls = []
    out = D.put_back_timers({"a.timer", "b.timer", "gone.timer"}, {"a.timer", "b.timer", "c.timer", "gone.timer"}, tmp_path,
                            sh=lambda *a: calls.append(a) or True, now={"b.timer", "c.timer", "own.timer"})
    assert calls == [("systemctl", "--user", "disable", "--now", "c.timer"), ("systemctl", "--user", "enable", "--now", "a.timer")]
    assert out[-1] == "timer gone.timer: enabled when this deploy began, but its unit is gone: not enabled"
    assert D.put_back_timers(None, {"a.timer"}, tmp_path, sh=calls.append, now=set()) == [
        "the enabled timers could not be read (systemctl --user list-unit-files): none put back"]


def test_the_rollback_after_a_failed_update_tells_the_deploy_it_is_one(monkeypatch):
    """PLT-43: ops/update.py's rollback (`deploy.py <new> <old>` after a failed update) says DEPLOY_ROLLBACK=1, so the
    deploy knows it is one also when a site's own commit leaves the two commits diverged; without it the deploy goes by
    whether the new commit is an ancestor of the old one."""
    import update as U
    seen = []
    monkeypatch.setattr(U.subprocess, "run", lambda cmd, **k: seen.append((cmd[-2:], k["env"].get("DEPLOY_ROLLBACK")))
                        or types.SimpleNamespace(returncode=1))
    monkeypatch.delenv("DEPLOY_ROLLBACK", raising=False)
    deploy = U.deploy_with("/stack")
    assert deploy("old", "new") is False and deploy("new", "old") is False
    assert seen == [(["old", "new"], None), (["new", "old"], "1")]
    asked = []
    monkeypatch.setattr(D.subprocess, "run", lambda cmd, **k: asked.append(cmd) or types.SimpleNamespace(returncode=0 if cmd[-2:] == ["a", "b"] else 1))
    assert D.rolls_back("new", "old", env={"DEPLOY_ROLLBACK": "1"}) and asked == []
    assert D.rolls_back("b", "a", env={}) and not D.rolls_back("a", "b", env={}) and not D.rolls_back("a", "a", env={})
    assert asked[0] == ["git", "merge-base", "--is-ancestor", "a", "b"]

"""ops/deploy.py: one deploy at a time (PLT-10)."""
import subprocess
import sys

import deploy


def test_a_second_deploy_waits_and_then_gives_up(tmp_path):
    path = tmp_path / "deploy.lock"
    first = deploy.lock(path, wait=0)
    assert first is not None                                    # free: taken at once
    assert deploy.lock(path, wait=0.2) is None                  # held by the first: gives up after the wait
    first.close()                                               # released (a finished or crashed deploy)
    again = deploy.lock(path, wait=0)
    assert again is not None
    again.close()


def test_a_deploy_is_recorded_with_its_source(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPLOY_SOURCE", "session")
    deploy.record("aaaa", "bbbb", True, 7, path=tmp_path / "deploys.jsonl")
    import json
    r = json.loads((tmp_path / "deploys.jsonl").read_text())
    assert (r["source"], r["old"], r["new"], r["ok"], r["files"]) == ("session", "aaaa", "bbbb", True, 7)


def test_the_landing_script_checks_before_it_merges():
    """BLD-20: ops/land.sh runs ops/check.sh on the commit that lands and stops on a failure, before any merge or push."""
    from pathlib import Path
    s = (Path(__file__).resolve().parent.parent / "ops/land.sh").read_text()
    assert s.index("bash ops/check.sh") < s.index("merge -q --ff-only") < s.index("python3 ops/deploy.py")
    assert 'grep -q "ALL CHECKS PASSED"' in s and "NOT LANDED: the checks failed" in s
    assert "DEPLOY_SOURCE=session" in s and "restart missions.service" in s and '"kind": "deploy"' in s


def test_the_lock_is_held_across_processes(tmp_path):
    path = tmp_path / "deploy.lock"
    held = deploy.lock(path, wait=0)
    probe = ("import fcntl,sys; f=open(sys.argv[1],'a')\n"
             "try:\n    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); print('free')\n"
             "except BlockingIOError:\n    print('held')")
    out = subprocess.run([sys.executable, "-c", probe, str(path)], capture_output=True, text=True).stdout.strip()
    assert out == "held"
    held.close()


def test_a_new_timer_is_enabled_with_its_first_deploy_and_a_known_one_keeps_its_state(tmp_path):
    (tmp_path / "crew-checker.timer").write_text("[Timer]\n")              # installed before: the owner may have switched it off
    units = ["ops/systemd/crew-checker.timer", "ops/systemd/crew-coach.timer", "ops/systemd/crew-coach.service"]
    assert deploy.new_timers(units, tmp_path) == ["crew-coach.timer"]


def test_a_card_change_restarts_the_swarm_service_so_the_agents_get_it():
    assert deploy.swarm_restart(["config/agents.yaml", "ops/crew.py"])           # FND-37
    assert not deploy.swarm_restart(["ops/keys.sh", "images/swarm/ledger.py"])     # an image change recreates it anyway


def test_every_image_has_a_tag_the_deploy_rebuilds_also_one_run_from_an_ops_script():
    import deploy as D
    tags = {d.name: D.image_tag(d.name) for d in sorted((D.R / "images").iterdir()) if (d / "Dockerfile").exists()}
    assert tags["desk"] == "aistack/desk:1"                                         # ops/desk.sh runs it, compose does not (FND-46)
    assert [n for n, t in tags.items() if not t] == []


def test_the_runner_restarts_for_any_module_it_may_import_also_one_it_reaches_indirectly():
    import deploy as D
    assert D.runner_changed(["images/mission-control/obs_core.py"]) and D.runner_changed(["ops/observe.py"])   # through crew.py (FND-49)
    assert D.runner_changed(["ops/missions.py"]) and D.runner_changed(["ops/systemd/missions.service"])
    assert not D.runner_changed(["ops/desk.sh", "ops/windows/x.py", "images/mission-control/server.py", "prompts/desk.md"])


def test_an_image_is_built_after_the_image_it_is_built_from():
    """Review IMG-R4: the builder (FROM the Hermes image) was built first in alphabetical order, so a Hermes upgrade looked
    for the new tag on Docker Hub."""
    order = deploy.build_order(["builder", "desk", "hermes"])
    assert sorted(order) == ["builder", "desk", "hermes"] and order.index("hermes") < order.index("builder")
    assert deploy.pinned_by(["ops/deploy.py"], "HEAD", "HEAD") == set()     # versions.env unchanged: nothing extra to build

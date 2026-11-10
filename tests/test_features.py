"""Features per deployment (GEN-13) and the deployment folder (DEC-45): which deployment a machine runs, what its features
switch, and that home switches every one on, so home behaves as before."""
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import deployment as DEPLOY

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **env):
    return subprocess.run([sys.executable, "ops/deployment.py", *args], cwd=ROOT, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "HOME": env.pop("HOME", "/nonexistent"), **env})


def test_a_machine_runs_home_unless_it_names_another_deployment(tmp_path):
    assert DEPLOY.chosen(env={}, home=tmp_path) == ROOT / "deployments/home"
    (tmp_path / ".config/aistack").mkdir(parents=True)
    (tmp_path / ".config/aistack/deployment").write_text("example-work\n")
    assert DEPLOY.chosen(env={}, home=tmp_path) == ROOT / "deployments/example-work"
    work = tmp_path / "work"                                  # a real one lives off the repository
    work.mkdir()
    (work / "deployment.env").write_text("DEPLOYMENT=work\nFEATURES=builder\n")
    assert DEPLOY.chosen(env={"AISTACK_DEPLOYMENT": str(work)}, home=tmp_path) == work
    with pytest.raises(SystemExit, match="does not exist"):
        DEPLOY.chosen(env={"AISTACK_DEPLOYMENT": "nowhere"}, home=tmp_path)


def test_a_feature_is_known_or_refused_and_core_is_always_on():
    assert DEPLOY.features({"FEATURES": "builder,memory"}) == {"core", "builder", "memory"}
    assert DEPLOY.features({}) == {"core"}
    with pytest.raises(SystemExit, match="phonee"):
        DEPLOY.features({"FEATURES": "builder,phonee"})
    with pytest.raises(ValueError):
        DEPLOY.has("phonee")


def deployment(name):
    return DEPLOY.load(ROOT / "deployments" / name / "deployment.env", env={})


def test_home_switches_every_feature_on_and_every_deployment_hands_its_features_to_compose():
    assert DEPLOY.features(deployment("home")) == {"core", *DEPLOY.KNOWN}
    for env in sorted((ROOT / "deployments").glob("*/deployment.env")):
        values = DEPLOY.load(env, env={})
        assert values["COMPOSE_PROFILES"] == values["FEATURES"], env      # COMPOSE_PROFILES=${FEATURES}
        assert values["DEPLOYMENT"] == env.parent.name
        DEPLOY.features(values)                                          # every name known
    assert {"home", "phone", "mail", "telegram", "web", "publish"}.isdisjoint(DEPLOY.features(deployment("example-work")))


def services():
    out = {}
    for f in ("compose/core.yaml", "compose/apps.yaml"):
        doc = yaml.safe_load((ROOT / f).read_text().replace("!reset ", "").replace("!override ", ""))
        out.update(doc["services"])
    return out


def test_each_service_of_a_feature_names_it_as_its_profile_and_core_has_none():
    svc = services()
    profiles = {name: s.get("profiles") for name, s in svc.items()}
    for name, p in profiles.items():
        assert p is None or (len(p) == 1 and p[0] in DEPLOY.KNOWN), (name, p)
    assert all(profiles[n] is None for n in ("postgres", "litellm", "phoenix", "hermes", "swarm"))
    assert profiles["builder"] == ["builder"] and profiles["phone"] == ["phone"] and profiles["mail"] == ["mail"]
    assert profiles["mission-control"] == ["mission-control"] and profiles["qmd"] == ["memory"]


def test_a_service_depends_only_on_what_its_deployments_start():
    svc = services()
    feature = {n: (s.get("profiles") or ["core"])[0] for n, s in svc.items()}
    for env in sorted((ROOT / "deployments").glob("*/deployment.env")):
        on = DEPLOY.features(DEPLOY.load(env, env={}))
        for name, s in svc.items():
            if feature[name] not in on:
                continue
            deps = s.get("depends_on") or []
            for d in (deps if isinstance(deps, list) else list(deps)):
                assert feature[d] in on, f"{env.parent.name}: {name} needs {d}, whose feature {feature[d]} is off"


def test_each_unit_names_a_known_feature_and_a_deployment_starts_only_its_timers():
    for u in sorted((ROOT / "ops/systemd").glob("*.*")):
        if u.suffix in (".service", ".timer"):
            assert DEPLOY.unit_feature(u) in {"core", *DEPLOY.KNOWN}, u.name
    names = {t.name for t in (ROOT / "ops/systemd").glob("*.timer")}
    assert set(DEPLOY.timers()) == names if DEPLOY.FOLDER.name == "home" else True
    work = run("timers", AISTACK_DEPLOYMENT="example-work").stdout.split()
    assert "backup.timer" not in work and "restore-drill.timer" not in work and "stack-ready.timer" in work
    assert "ops/deployment.py timers" in (ROOT / "ops/new-machine.sh").read_text()


def test_a_script_of_a_feature_that_is_off_says_not_configured_before_any_network_call():
    off = run("need", "phone", AISTACK_DEPLOYMENT="example-work")
    assert off.returncode == 1 and "not configured: the feature phone is off" in off.stdout
    assert run("need", "builder", AISTACK_DEPLOYMENT="example-work").returncode == 0
    for script, feature, first_net in (("ops/backup.sh", "home", "ssh "), ("ops/deploy-ha.sh", "home", "ssh"),
                                       ("ops/desk.sh", "web", "docker run"), ("ops/restore.sh", "home", "ssh synology")):
        code = [ln for ln in (ROOT / script).read_text().splitlines() if not ln.lstrip().startswith("#")]
        guard = next(i for i, ln in enumerate(code) if f"deployment.py\" need {feature}" in ln)   # "|| exit 0", or a refusal (GEN-20)
        assert guard < next(i for i, ln in enumerate(code) if first_net in ln), script


def test_compose_demands_no_home_value_of_a_deployment_without_the_feature():
    """A work site, 9 Nov 2026: compose interpolates services whose feature is off, and ${X:?} refused the empty home hosts,
    so deployments/example-work itself failed `docker compose config`. Only secrets stay required in compose; a host value
    is optional there, and `ops/deployment.py check` (make up) refuses a switched-on feature whose value is empty."""
    import re
    import deployment as D
    root = Path(D.__file__).resolve().parents[1]
    work = D.load(root / "deployments/example-work/deployment.env", env={})
    secret = re.compile(r"^(VK_\w+|\w*(KEY|PASSWORD|TOKEN|SECRET)\w*)$")
    for f in ("compose/core.yaml", "compose/apps.yaml"):
        for v in re.findall(r"\$\{(\w+):\?", (root / f).read_text()):
            assert secret.match(v) or str(work.get(v) or "").strip(), f"{f}: ${{{v}:?}} would stop a deployment that leaves {v} empty"
    assert D.missing(work) == []
    home_like = {**work, "FEATURES": "home,phone,tailnet", "NAS_HOST": "nas.lan", "HA_URL": "", "ROUTER_URL": "x", "PHONE_HOST": "off.invalid",
                 "PC_TAILNET_HOST": "pc.ts.net"}
    assert D.missing(home_like) == ["HA_URL is empty, and home needs it", "PHONE_HOST is empty, and phone needs it"]
    assert "python3 ops/deployment.py check" in (root / "Makefile").read_text()


def test_a_deployment_without_home_never_restores_or_rebuilds_the_home_stack():
    """GEN-20. A work site, 9 Nov 2026, kept a local commit so that the home stack's backup, restore and new-machine
    scripts could not run there. Backup and the drill already stood aside; a restore and new-machine.sh now refuse too,
    before they read or replace anything."""
    root = Path(DEPLOY.__file__).resolve().parents[1]
    env = {**__import__("os").environ, "AISTACK_DEPLOYMENT": "example-work"}
    r = subprocess.run(["bash", str(root / "ops/restore.sh"), "apply", "x.tar.gz.age"], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 1 and "refused" in r.stderr and "no home feature" in r.stderr
    r = subprocess.run(["bash", str(root / "ops/restore.sh"), "drill"], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0 and "not configured" in r.stdout
    r = subprocess.run(["bash", str(root / "ops/new-machine.sh")], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 1 and "refused" in r.stderr
    assert "need home || exit 0" in (root / "ops/backup.sh").read_text()


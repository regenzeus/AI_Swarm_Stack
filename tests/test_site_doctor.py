"""The site: a machine that names no deployment, or a deployment without home, runs the platform only (PLT-44); every
workflow and job names its factory (PLT-45); the doctor names each reason a site does not run as its deployment says,
and the deploy fails loud on it (PLT-46); a deployment refuses a factory by setting (PLT-47); every deployment folder
opens with the site's rule (PLT-48). The work side, 11 Nov 2026: no packs file and nothing warned, home's workflows on
their site because nothing tagged them, a dead runner unnoticed, and a private marker file for refusals."""
import json
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

import crew as CR
import deployment as DEPLOY
import n8n_gen as G
import n8n_sync as NS
from domain import packs as PK
from domain import places as PL

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / "n8n/workflows"
PLATFORM_ON = DEPLOY.features(DEPLOY.load(ROOT / "deployments/platform/deployment.env", env={}))
HOME_ON = DEPLOY.features(DEPLOY.load(ROOT / "deployments/home/deployment.env", env={}))
# PLT-45: which jobs are home's (the household's work, and the jobs whose unit needs home's NAS); every other is the
# platform's. The generic ones that moved to the platform's Upkeep on 11 Nov 2026 (MOVED).
HOME_JOBS = {"phone-cleanup", "phone-check", "inbox", "postmaster", "mail-sort", "tax-find", "tax-file", "skills-sync",
             "backup", "restore-drill"}
PLATFORM_JOBS = {"memory-review", "memory", "curator", "self-review", "maintainability", "tests", "editor", "doctor",
                 "coach", "journeys", "checker", "swarm-sync", "graphify-sync", "repofacts-sync", "upgrade-check",
                 "digest", "vault-ingest", "rotation", "recycle", "tracker-poll", "token-probe"}
MOVED = {"swarm-sync", "vault-ingest", "curator", "rotation"}


def cli(*args, **env):
    return subprocess.run([sys.executable, "ops/deployment.py", *args], cwd=ROOT, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "HOME": env.pop("HOME", "/nonexistent"), **env})


def chosen(folder):
    names = DEPLOY.workflow_names(folder)
    values = DEPLOY.load(Path(folder) / "deployment.env", env={})
    return sorted(p.name for p in REPO.glob("*.json") if DEPLOY.runs_workflow(p, names, values))


# ---------- PLT-44: the platform only ----------
def test_a_machine_that_names_no_deployment_runs_the_platform_only():
    out = cli("workflows").stdout.split()
    assert out == chosen(ROOT / "deployments/platform") and "stack-self-test.json" in out and "crew-swarm-sync.json" in out
    assert all(json.loads((REPO / f).read_text())["factory"] == "platform" for f in out)
    assert cli("DEPLOYMENT").stdout.strip() == "platform" and cli("need", "home").returncode == 1
    assert PLATFORM_ON == {"core", "mission-control", "memory"}                      # the app, the engine (core) and memory
    assert cli("check").returncode == 0                                              # its values fit its features
    assert cli("DEPLOY_HOME", HOME="/home/someone").stdout.strip() == "/home/someone"  # ${HOME}, as compose reads it too


def test_a_site_without_home_runs_none_of_homes_workflows_or_jobs_and_home_keeps_its_own(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "deployment.env").write_text("DEPLOYMENT=site\nFEATURES=builder,mission-control,memory,mail,phone\n")
    (site / "workflows.yaml").write_text("workflows:\n  - stack-self-test\n  - crew-postmaster\n  - task-*\n  - crew-swarm-sync\n")
    (site / "trackers.yaml").write_text("trackers:\n  - {name: b, kind: forgejo, repo: o/inbox, workflow: home/inbox}\n")
    assert chosen(site) == ["crew-swarm-sync.json", "crew-tracker-poll.json", "stack-self-test.json"]   # no postmaster, no task-*, no item-home-inbox
    values = DEPLOY.load(site / "deployment.env", env={})
    assert DEPLOY.off_problems(site, values) == [
        "the deployment names crew-postmaster, a workflow of the factory home, and FEATURES does not switch home on: it does not run here",
        "the deployment names item-home-inbox, a workflow of the factory home, and FEATURES does not switch home on: it does not run here"]
    assert not {a["id"] for a in CR.jobs(DEPLOY.features(values))} & HOME_JOBS
    home = {a["id"] for a in CR.jobs(HOME_ON)}
    assert HOME_JOBS - home == set()                                                  # home runs every job of home, the phone's too (PHN-28)
    assert DEPLOY.off_problems(ROOT / "deployments/home", DEPLOY.load(ROOT / "deployments/home/deployment.env", env={})) == []


def test_home_chooses_exactly_what_it_chose_before_the_factories():
    """Home runs every file but the AI phone's two (off since 11 Nov 2026, PHN-28), as before the tags: 31 of 33."""
    every = sorted(p.name for p in REPO.glob("*.json"))
    assert chosen(ROOT / "deployments/home") == every                                 # home chooses the AI phone again (11 Nov)
    assert cli("workflows", AISTACK_DEPLOYMENT="home").stdout.split() == chosen(ROOT / "deployments/home")


def test_a_deploy_refuses_on_a_machine_that_names_no_deployment(monkeypatch):
    """A deploy there would take a running site down to the platform only (the home PC named none until 11 Nov 2026)."""
    monkeypatch.setattr(DEPLOY, "NAMED", "")
    assert DEPLOY.deploy_refusals() == ["this machine names no deployment: write its name into ~/.config/aistack/deployment "
                                        "(platform for the platform only); without one nothing is deployed"]
    monkeypatch.setattr(DEPLOY, "NAMED", "home")
    assert DEPLOY.deploy_refusals() == []


# ---------- PLT-45: every workflow and job names its factory ----------
def test_every_job_and_workflow_names_its_factory_and_the_lists_say_which():
    assert {a["id"] for a in CR.CREW if a["factory"] == "home"} == HOME_JOBS
    assert {a["id"] for a in CR.CREW if a["factory"] == "platform"} == PLATFORM_JOBS
    assert {a["factory"] for a in CR.CREW} == set(DEPLOY.FACTORIES)                 # none untagged
    assert all(CR.BY_ID[j]["area"] == "upkeep" for j in MOVED)
    assert DEPLOY.tag_problems() == []
    import n8n_jobs as NJ
    for f in sorted(REPO.glob("*.json")):
        wf = json.loads(f.read_text())
        kind, key = NJ.target(wf)
        mine = ("home" if f.stem.startswith("task-") or f.stem in ("tax-desk", "item-home-inbox")       # the owner's briefings,
                else CR.BY_ID[key]["factory"] if kind == "crew" else "platform")                    # taxes and inbox are home's
        assert wf["factory"] == mine, f.name


def test_a_workflow_no_factory_owns_runs_nowhere_and_is_named(tmp_path):
    (tmp_path / "crew-x.json").write_text(json.dumps({"id": "aiscX", "name": "x", "nodes": [], "connections": {}}))
    (tmp_path / "crew-y.json").write_text(json.dumps({"id": "aiscY", "name": "y", "factory": "work", "nodes": [], "connections": {}}))
    assert DEPLOY.tag_problems(tmp_path) == [
        'crew-x.json names no factory ("factory": platform or home): it runs nowhere',
        "crew-y.json names no factory (\"factory\": platform or home; it says 'work'): it runs nowhere"]
    assert not DEPLOY.runs_workflow("crew-x.json", ["*"], repo=tmp_path)


def test_new_workflows_and_exports_carry_their_factory(tmp_path):
    assert G.workflow("crew", "postmaster", "Crew: Postmaster", "0 * * * *", {"kind": "crew", "job": "postmaster"}, "")["factory"] == "home"
    assert G.workflow("crew", "swarm-sync", "Crew: Swarm sync", "* * * * *", {"kind": "crew", "job": "swarm-sync"}, "")["factory"] == "platform"
    assert G.workflow("task", 7, "Task #7: x", "0 8 * * *", {"kind": "task", "task": 7}, "")["factory"] == "home"   # made at home
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir(), out.mkdir()
    for name in ("Kept", "Fresh"):
        (src / f"{name}.json").write_text(json.dumps({"id": f"ais{name}", "name": name, "nodes": [], "connections": {}}))
    (out / "kept.json").write_text(json.dumps({"id": "aisKept", "name": "Kept", "factory": "platform", "area": "upkeep"}))
    NS.write_stable(sorted(src.glob("*.json")), out)
    assert json.loads((out / "kept.json").read_text())["factory"] == "platform"     # n8n's export carries none: git keeps it
    assert json.loads((out / "fresh.json").read_text())["factory"] == "home"         # made on the canvas at home


# ---------- PLT-47: refusing a factory ----------
def test_a_refused_factory_never_switches_on_and_its_scripts_and_the_deploy_refuse(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "deployment.env").write_text("DEPLOYMENT=site\nFEATURES=mission-control,home\nREFUSE=home\nCOMPOSE_PROFILES=${FEATURES}\n")
    values = DEPLOY.load(site / "deployment.env", env={})
    assert "home" not in DEPLOY.features(values) and DEPLOY.factories(values) == {"platform"}
    assert DEPLOY.refusal_problems(values) == ["FEATURES switches on home, which this deployment refuses (REFUSE): it stays off"]
    assert DEPLOY.deploy_refusals(values)[-1] == DEPLOY.refusal_problems(values)[0]
    r = cli("need", "home", AISTACK_DEPLOYMENT=str(site))
    assert r.returncode == 1 and r.stdout.strip() == "refused: the deployment site refuses home (REFUSE in its deployment.env)"
    assert DEPLOY.refusal_problems({"FEATURES": "", "REFUSE": "platform"}) == [
        "REFUSE names platform: the platform runs at every site, only a factory can be refused"]


def test_a_refused_pack_is_refused_by_name_before_it_is_fetched(tmp_path, monkeypatch):
    (tmp_path / "packs.txt").write_text("toy /nowhere 0123456789abcdef\n")
    monkeypatch.setattr(DEPLOY, "VALUES", {**DEPLOY.VALUES, "REFUSE": "toy"})
    got = PK.load(tmp_path / "packs.txt", base=tmp_path / "cache", approvals=tmp_path / "a.json")
    assert got["packs"] == [] and got["refused"] == [{"name": "toy", "commit": "0123456789abcdef",
                                                      "why": "pack toy: this deployment refuses it (REFUSE in its deployment.env)"}]


# ---------- PLT-46: the doctor ----------
def test_the_doctor_names_a_missing_packs_file_a_pack_not_listed_and_one_not_approved_at_its_pin(tmp_path):
    (tmp_path / "trackers.yaml").write_text("trackers:\n  - {name: a, kind: jira, url: x, query: q, workflow: demo/bug}\n"
                                            "  - {name: r, kind: jira, url: x, query: q, write: off, records: rec}\n")
    assert DEPLOY.packs_named(tmp_path) == ["demo", "rec"]
    assert DEPLOY.pack_problems(tmp_path, txt=tmp_path / "packs.txt") == [
        "no packs.txt beside the deployment.env, and trackers.yaml names the packs demo, rec: nothing of them runs"]
    (tmp_path / "packs.txt").write_text("demo /src/demo 1111111111111111111111111111111111111111\n")
    loaded = {"packs": [{"name": "demo", "problems": ["workflows/x.json: not JSON"], "workflows": []}],
              "pending": [{"name": "demo", "commit": "2" * 40, "runs": "1" * 40}],
              "refused": [{"name": "old", "commit": "3" * 40, "why": "pack old: commit 333333333333 was refused by owner"}]}
    assert DEPLOY.pack_problems(tmp_path, loaded, txt=tmp_path / "packs.txt") == [
        "trackers.yaml names the pack rec, which packs.txt does not list: nothing of it runs",
        "pack demo: its pinned commit 222222222222 is not approved (commit 111111111111 runs meanwhile); "
        "stack pack approve demo 222222222222 asks for it",
        "pack old: commit 333333333333 was refused by owner",
        "pack demo: workflows/x.json: not JSON"]


def test_the_doctor_names_a_dead_runner_a_stale_worker_and_a_stopped_ci_runner(tmp_path, monkeypatch):
    import winworker as WW
    now = time.time()
    host, win, wsl = tmp_path / "host", tmp_path / "win", tmp_path / "wsl"
    for d in (host / "outbox", win, wsl / "inbox" / "r1", wsl / "outbox"):
        d.mkdir(parents=True)
    (host / "outbox/status.json").write_text(json.dumps({"ts": now - 600}))
    (wsl / "outbox/status.json").write_text(json.dumps({"ts": now - 600}))
    monkeypatch.setattr(WW, "ANSWERS", win)
    answers = {"systemctl": (3, "inactive\n"), "docker": (0, "exited\n")}
    sh = lambda cmd, timeout=120: answers[cmd[0]]                                    # noqa: E731
    cfg = {"wsl": {"root": str(wsl)}, "wsl-host": {"root": str(host)}}
    probs, notes = DEPLOY.runner_problems({"FEATURES": "forgejo-ci,windows-worker"}, sh, now, cfg)
    assert probs == ["the stack's runner (missions.service) is inactive: no workflow step runs",
                     "the CI runner (aistack-ci-runner-1, the feature forgejo-ci) is exited: CI waits",
                     "the wsl-host worker last answered 10 min ago (it answers every 10 s): it is dead or stuck",
                     "1 request waits at the wsl place, and its worker (a thread of the runner) does not answer"]
    assert notes == ["the windows worker has never answered (no status.json): its setup on Windows is the owner's"]
    for d in (host, wsl):
        (d / "outbox/status.json").write_text(json.dumps({"ts": now - 5}))
    answers.update(systemctl=(0, "active\n"), docker=(0, "running\n"))
    assert DEPLOY.runner_problems({"FEATURES": "forgejo-ci"}, sh, now, cfg) == ([], [])
    assert PL.ALIVE_S == 60


def test_the_doctor_names_what_was_written_into_the_windows_drive_folder_with_its_owner_and_time(tmp_path):
    """DEC-43, 11 Nov 2026: empty folders in /mnt/c, made from WSL by mistake, failed a deploy's smoke test, and nothing
    said who made them."""
    import os
    import pwd
    drive = tmp_path / "c"
    drive.mkdir()
    assert DEPLOY.drive_problems(drive) == []
    (drive / "Users/x/Temp/claude").mkdir(parents=True)
    [line] = DEPLOY.drive_problems(drive)
    try:
        me = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:                                                                 # a container's user without a name
        me = str(os.getuid())
    assert line.startswith(f"{drive} holds {drive}/Users/x/Temp/claude (made by {me}, 20")
    assert line.endswith(f"remove {drive}/Users")
    assert "made by %u" in (ROOT / "smoke/smoke.sh").read_text()                    # the smoke test names it too


def test_the_doctor_names_workflows_not_imported_or_published_as_the_deployment_says():
    mine = {"aisA": {"file": "crew-a.json", "wf": {"active": True}}, "aisB": {"file": "crew-b.json", "wf": {"active": True}},
            "aisC": {"file": "crew-c.json", "wf": {"active": False}}}
    every = {**mine, "aisP": {"file": "crew-postmaster.json", "wf": {"active": True}}}
    lists = {"--onlyId": "aisA\naisC\naisP\n", "true": "aisC\naisP\n"}
    sh = lambda cmd, timeout=120: (0, lists["true" if "--active=true" in cmd else "--onlyId"])   # noqa: E731
    assert DEPLOY.n8n_problems(sh, mine=mine, every=every) == [
        "crew-a.json is unpublished in n8n, and the deployment says published",
        "crew-b.json is not imported in n8n, and this deployment runs it",
        "crew-c.json is published in n8n, and the deployment says unpublished",
        "n8n publishes crew-postmaster.json, which this deployment does not run"]
    assert DEPLOY.n8n_problems(lambda cmd, timeout=120: (1, "Error: no database"), mine=mine, every=every) == [
        "n8n does not say which workflows it holds (aistack-n8n-1: Error: no database): nothing is known to run"]


def test_an_override_whose_standard_workflow_changed_since_its_check_is_named(tmp_path):
    """Prepared for phase B (rule 8): the check exists; until the platform ships standard workflows nothing overrides."""
    (tmp_path / "t").mkdir()
    (tmp_path / "t/request.json").write_text(json.dumps({"version": "3", "changes": {"3": "the check step asks first"}}))
    flows = []
    for name, o in (("demo/a", {"template": "request", "checked": "2"}), ("demo/b", {"template": "request", "checked": "3"}),
                    ("demo/c", {"template": "change", "checked": "1"}), ("demo/d", None)):
        p = tmp_path / f"{name.split('/')[1]}.json"
        p.write_text(json.dumps({"name": name, **({"overrides": o} if o else {})}))
        flows.append({"name": name, "path": str(p)})
    assert DEPLOY.override_problems([{"workflows": flows}], tmp_path / "t") == [
        "demo/a overrides the standard workflow request, last checked against version 2; it is now version 3: the check step asks first",
        "demo/c overrides the standard workflow change, which the platform does not have"]
    assert not DEPLOY.TEMPLATES.exists() and DEPLOY.override_problems([]) == []


def test_the_doctor_of_home_from_its_files_finds_nothing_and_of_a_broken_site_names_every_reason(tmp_path):
    assert DEPLOY.doctor(live=False) == {"deployment": "home", "ok": True, "problems": [], "notes": []}
    site = tmp_path / "site"
    site.mkdir()
    (site / "deployment.env").write_text("DEPLOYMENT=site\nFEATURES=mission-control,home\nREFUSE=home\nAPP_GATE=local\n"
                                         "N8N_EDITOR_URL=http://127.0.0.1:8090/n8n/\nN8N_WEBHOOK_URL=http://127.0.0.1:5678/\n")
    (site / "workflows.yaml").write_text("workflows:\n  - stack-self-test\n  - crew-postmaster\n")
    (site / "trackers.yaml").write_text("trackers:\n  - {name: a, kind: jira, url: x, query: q, workflow: demo/bug}\n")
    d = DEPLOY.doctor(DEPLOY.load(site / "deployment.env", env={}), site, live=False)
    assert d["ok"] is False and d["deployment"] == "site" and d["problems"] == [
        "FEATURES switches on home, which this deployment refuses (REFUSE): it stays off",
        "the deployment names crew-postmaster, a workflow of the factory home, and this deployment refuses it (REFUSE): it does not run here",
        "no packs.txt beside the deployment.env, and trackers.yaml names the pack demo: nothing of it runs"]
    r = cli("doctor", "--json", AISTACK_DEPLOYMENT=str(site))
    assert r.returncode == 1 and json.loads(r.stdout)["problems"][0].startswith("FEATURES switches on home")


def test_the_deploy_runs_the_doctor_last_and_a_failing_doctor_fails_it(monkeypatch, tmp_path, capsys):
    import deploy as D
    ran = []
    monkeypatch.setattr(D, "ok", True)
    monkeypatch.setenv("DEPLOY_RECORD", str(tmp_path / "deploys.jsonl"))
    monkeypatch.setattr(D, "healthy", lambda url, n=100: True)
    calls = []
    monkeypatch.setattr(D.subprocess, "run", lambda cmd, **k: calls.append(" ".join(map(str, cmd))) or types.SimpleNamespace(
        stdout="ops/missions.py\n", returncode=1, stderr=""))

    def run(*cmd, timeout=1800, **kw):
        ran.append(" ".join(cmd))
        if "deployment.py doctor" in " ".join(cmd):
            D.ok = False
            return False
        return True
    monkeypatch.setattr(D, "run", run)
    assert D.main("a" * 40, "b" * 40) == 1
    out = capsys.readouterr().out
    assert "DEPLOY FAILED" in out and "the doctor named what is wrong" in out
    assert ran.index("python3 ops/deployment.py doctor") > ran.index("bash smoke/smoke.sh")
    # the `stack` command line (whose `stack doctor` is this doctor) is installed by every deploy, once it exists
    assert any("ops/stack_cli.py install" in c for c in calls) == (D.R / "ops/stack_cli.py").is_file()
    ran.clear()
    monkeypatch.setattr(D, "ok", True)
    monkeypatch.setattr(DEPLOY, "NAMED", "")
    assert D.main("a" * 40, "b" * 40) == 1 and ran == []                            # refused before any step
    assert "nothing was changed" in capsys.readouterr().out


# ---------- PLT-48: the site's rule ----------
def test_every_deployment_folder_opens_with_the_sites_rule_and_a_new_one_gets_it(tmp_path):
    folders = sorted(e.parent for e in (ROOT / "deployments").glob("*/deployment.env"))
    assert [f.name for f in folders] == ["example-work", "home", "platform"]
    def rule(f):
        return " ".join((f / "AGENTS.md").read_text().split("\n\n")[1].split())      # the paragraph right under the title
    for f in folders:
        assert rule(f) == DEPLOY.RULE, f.name
    for word in ("workflow run", "Asks", "commit to its pack, approved before it is used", "by hand", "`stack`"):
        assert word in DEPLOY.RULE
    site = DEPLOY.new(str(tmp_path / "site-a"))
    assert sorted(p.name for p in site.iterdir()) == ["AGENTS.md", "data.yaml", "deployment.env", "models.yaml", "workflows.yaml"]
    assert rule(site) == DEPLOY.RULE
    values = DEPLOY.load(site / "deployment.env", env={})
    assert values["DEPLOYMENT"] == "site-a" and DEPLOY.features(values) == PLATFORM_ON and DEPLOY.factories(values) == {"platform"}
    assert DEPLOY.doctor(values, site, live=False)["problems"] == []
    with pytest.raises(SystemExit, match="holds files already"):
        DEPLOY.new(str(site))
    with pytest.raises(SystemExit, match="letters, digits and dashes"):
        DEPLOY.new(str(tmp_path / "Bad_Name"))

"""PLT-38: a deployment runs the stack's own workflows it lists (deployments/<name>/workflows.yaml) and those its
trackers imply; the rest of n8n/workflows/ is never imported there, and one imported earlier that it no longer runs is
unpublished. Home's list is everything home runs today, so home changes nothing."""
import json
import types
from pathlib import Path

import pytest

import deployment as DEPLOY
import flows as FW
import n8n_gen as G
import n8n_jobs as NJ
import n8n_switch as SW
import n8n_sync as NS

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / "n8n/workflows"


def chosen(name):
    names = DEPLOY.workflow_names(ROOT / "deployments" / name)
    return sorted(p.name for p in REPO.glob("*.json") if DEPLOY.runs_workflow(p, names))


def test_home_runs_every_workflow_it_ran_before_the_list():
    """Home ran every file of n8n/workflows/ (all published: 29 jobs with the mail sorter of 10 Nov 2026, the self-test, the
    inbox's item workflow and the tracker poller); its list and its tracker select exactly those, so a deploy changes nothing
    at home. The tax desk (TAX-08) joined on 10 Nov 2026, unpublished until its first live run."""
    every = sorted(p.name for p in REPO.glob("*.json"))
    assert chosen("home") == every and len(every) == 33
    assert all(json.loads((REPO / f).read_text())["active"] for f in every)   # the tax desk too, on since its first run (10 Nov)
    names = DEPLOY.workflow_names(ROOT / "deployments/home")
    assert "crew-tracker-poll" in names and "item-home-inbox" in names          # from trackers.yaml, not listed
    assert DEPLOY.workflow_problems(ROOT / "deployments/home") == []


def test_a_work_deployment_runs_only_the_self_test_and_its_tracker_poller():
    assert chosen("example-work") == ["crew-tracker-poll.json", "stack-self-test.json"]
    assert DEPLOY.workflow_problems(ROOT / "deployments/example-work") == []


def test_the_tracker_poller_and_the_stacks_item_workflows_come_with_the_trackers(tmp_path):
    (tmp_path / "workflows.yaml").write_text("workflows:\n  - stack-self-test\n")
    assert DEPLOY.workflow_names(tmp_path) == ["stack-self-test"]                  # no trackers: no poller
    (tmp_path / "trackers.yaml").write_text("trackers:\n  - {name: a, kind: jira, url: x, query: q, workflow: demo/bug}\n"
                                            "  - {name: b, kind: forgejo, repo: o/inbox, workflow: home/inbox}\n")
    assert DEPLOY.workflow_names(tmp_path) == ["stack-self-test", "crew-tracker-poll", "item-home-inbox"]
    assert DEPLOY.runs_workflow("task-12-x.json", ["task-*"]) and not DEPLOY.runs_workflow("crew-postmaster.json", ["task-*"])


def test_a_name_no_workflow_has_is_refused_by_the_deployment_check(tmp_path):
    (tmp_path / "workflows.yaml").write_text("workflows:\n  - stack-self-test\n  - crew-postmastr\n  - task-*\n")
    assert DEPLOY.workflow_problems(tmp_path) == ["workflows.yaml names crew-postmastr, which n8n/workflows/ does not have"]


def flow(folder, stem, wid, active):
    (folder / f"{stem}.json").write_text(json.dumps({"id": wid, "name": stem, "active": active, "nodes": [], "connections": {}}))


def test_a_deploy_imports_only_the_deployments_workflows_and_unpublishes_the_ones_it_no_longer_runs(tmp_path, monkeypatch):
    repo, made = tmp_path / "repo", tmp_path / "made"
    repo.mkdir(), made.mkdir()
    flow(repo, "crew-a", "aiscA", True)
    flow(repo, "crew-b", "aiscB", False)
    flow(repo, "crew-postmaster", "aiscP", True)                   # published here earlier, no longer listed
    flow(repo, "crew-phone-check", "aiscQ", True)                  # never imported here: n8n does not have it
    flow(made, "task-9-x", "aistT", True)                          # the runner made it here: always this deployment's
    monkeypatch.setattr(NS, "sync_packs", lambda *a, **k: [])
    monkeypatch.setenv("N8N_HOOK_TOKEN", "hook-test")          # SEC-27: the webhooks' credential is written first
    calls = []

    def run(cmd, **k):
        calls.append(cmd)
        out = "aiscA\naiscP\n" if "list:workflow" in cmd else "Successfully imported 2 workflows."
        return types.SimpleNamespace(returncode=0, stdout=out, stderr="")

    assert NS.import_all(repo, run=run, made=made, names=["crew-a", "crew-b"]) == 0
    script = calls[1][-1]                                                       # calls[0]: the webhooks' credential (SEC-27)
    assert calls[1][:6] == ["docker", "exec", "-u", "node", "aistack-n8n-1", "sh"]
    assert "cp crew-a.json crew-b.json /home/node/.n8n/chosen/" in script and "--input=/home/node/.n8n/chosen" in script
    ex = ["docker", "exec", "-u", "node", "aistack-n8n-1", "n8n"]
    assert ex + ["publish:workflow", "--id=aiscA"] in calls and ex + ["unpublish:workflow", "--id=aiscB"] in calls
    assert ex + ["publish:workflow", "--id=aistT"] in calls
    assert ex + ["unpublish:workflow", "--id=aiscP"] in calls                   # imported earlier, no longer this deployment's
    assert not [c for c in calls if "--id=aiscQ" in c]                          # not in n8n: left alone
    assert calls[-1] == ["docker", "restart", "aistack-n8n-1"]


def test_the_app_and_the_runner_see_only_the_deployments_workflows(tmp_path, monkeypatch):
    """The Workflows page (ops/flows_view.py) and every schedule the app shows (ops/n8n_jobs.py, flows.catalog) read the
    stack's folder through the deployment's list: a work deployment shows none of home's jobs."""
    monkeypatch.setattr(DEPLOY, "workflow_names", lambda folder=None: ["stack-self-test", "crew-tracker-poll"])
    ids = {w["file"] for w in NJ.workflows(NJ.REPO, tmp_path).values()}
    assert ids == {"stack-self-test.json", "crew-tracker-poll.json"}
    assert set(FW.catalog(made=tmp_path)["jobs"]) == {"crew:tracker-poll"}
    assert len(NJ.workflows(NJ.REPO, tmp_path, ["*"])) == 33                  # every file, for the import's unpublishing


def test_a_switch_publishes_only_a_workflow_the_deployment_runs(monkeypatch):
    monkeypatch.setattr(DEPLOY, "workflow_names", lambda folder=None: ["stack-self-test"])
    calls = []
    with pytest.raises(RuntimeError, match="is not one of this deployment's workflows: add crew-postmaster to"):
        SW.switch(REPO / "crew-postmaster.json", True, run=lambda *a, **k: calls.append(a))
    assert calls == []


def test_a_new_crew_job_and_a_canvas_workflow_join_the_deployments_list(tmp_path):
    dep, out = tmp_path / "dep", tmp_path / "wf"
    dep.mkdir(), out.mkdir()
    (dep / "workflows.yaml").write_text("# the list\nworkflows:\n  - stack-self-test\n  - task-*\n")
    p = G.crew("checker", "0 * * * *", out=out, folder=dep)
    assert p.name == "crew-checker.json" and json.loads(p.read_text())["active"] is False
    assert (dep / "workflows.yaml").read_text() == "# the list\nworkflows:\n  - stack-self-test\n  - task-*\n  - crew-checker\n"
    assert DEPLOY.add_workflow("my-flow.json", dep) is True and DEPLOY.add_workflow("task-80-x.json", dep) is False
    assert DEPLOY.workflow_names(dep) == ["stack-self-test", "task-*", "crew-checker", "my-flow"]
    deploy = (ROOT / "ops/deploy.py").read_text()                 # a changed list or tracker file is imported by the deploy
    assert 'f.startswith(("n8n/workflows/", "compose/", "deployments/"))' in deploy
    sync = (ROOT / "ops/n8n_sync.py").read_text()
    assert "if DEPLOY.add_workflow(n):" in sync

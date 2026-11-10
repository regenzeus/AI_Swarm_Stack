"""WFL-08: workflows live in git. The repository's workflows are valid n8n workflows that reach the step service and
wait for its answer; a deploy imports them, each active or not as its file says; an export is stable for git."""
import json
import types
from pathlib import Path

import yaml

import flows as FW
import n8n_gen as G
import n8n_sync as NS

ROOT = Path(__file__).resolve().parents[1]
WF = sorted((ROOT / "n8n/workflows").glob("*.json"))


def test_every_workflow_in_the_repository_is_a_whole_n8n_workflow():
    assert WF
    ids, hooks_seen = set(), set()
    for f in WF:
        wf = json.loads(f.read_text())
        assert {"id", "name", "nodes", "connections", "active", "settings"} <= set(wf), f.name
        assert len(wf["id"]) == 16 and wf["id"] not in ids and NS.file_name(wf) == f.name
        ids.add(wf["id"])
        names = {n["name"] for n in wf["nodes"]}
        for src, outs in wf["connections"].items():
            assert src in names and all(c["node"] in names for o in outs["main"] for c in o), f.name
        steps = [n for n in wf["nodes"] if n["type"] == "CUSTOM.aistackStep"]
        assert steps, f"{f.name}: the stack's work goes through the AI Stack step"
        for n in wf["nodes"]:   # WFL-03; an IF node only branches on a step's answer (an item workflow's wait)
            assert n["type"] in ("CUSTOM.aistackStep", "n8n-nodes-base.scheduleTrigger", "n8n-nodes-base.webhook", "n8n-nodes-base.if"), f.name
        for n in steps:
            assert n["parameters"]["kind"] in FW.KINDS and n["webhookId"], f.name
        hooks = [n["webhookId"] for n in wf["nodes"] if n.get("webhookId")]
        assert len(hooks) == len(set(hooks)) and not hooks_seen & set(hooks), f.name     # n8n registers each webhook once
        hooks_seen.update(hooks)


def test_every_scheduled_job_runs_on_n8n():
    """WFL-09: since 10 Nov 2026 every scheduled job (the crew's and the plan tasks', 28 with the three that left their
    timers that day: vault ingest, the trial rotation, the nightly restart) runs on n8n. A file says what runs:
    "active"; ops/n8n_switch.py <file> off takes one back."""
    jobs = {f.name: json.loads(f.read_text()) for f in WF if f.name.startswith(("crew-", "task-")) or f.name == "memory-keeper.json"}
    waiting = {"crew-tracker-poll.json"}                 # WFL-19: the tracker poller, published by a deployment that has trackers (home since its inbox, GEN-45)
    assert len(jobs) == 29 and all(wf["active"] for n, wf in jobs.items() if n not in waiting)


def test_a_deploy_imports_the_repositorys_workflows_each_as_its_file_says(monkeypatch):
    calls = []
    run = lambda cmd, **k: calls.append(cmd) or types.SimpleNamespace(returncode=0, stdout="Successfully imported 2 workflows.", stderr="")
    monkeypatch.setattr(NS, "sync_packs", lambda *a, **k: [])
    assert NS.import_all(run=run, made=Path("/nonexistent")) == 0
    ex = ["docker", "exec", "-u", "node", "aistack-n8n-1", "n8n"]
    assert f"cp {' '.join(f.name for f in WF)} /home/node/.n8n/chosen/" in calls[0][-1]     # home: every file (PLT-38)
    assert "n8n import:workflow --separate --input=/home/node/.n8n/chosen" in calls[0][-1]
    off = {c[7] for c in calls if len(c) > 7 and c[6] == "unpublish:workflow"}       # only the files that say inactive
    assert off == {f"--id={json.loads(f.read_text())['id']}" for f in WF if not json.loads(f.read_text())["active"]}
    assert ex + ["publish:workflow", "--id=aistackSelfTest1"] in calls and ex + ["publish:workflow", "--id=aistackMemKeeper"] in calls
    assert calls[-1] == ["docker", "restart", "aistack-n8n-1"]                      # the server loads what was published
    core = yaml.safe_load((ROOT / "compose/core.yaml").read_text())["services"]["n8n"]
    assert "../n8n/workflows:/workflows:ro" in core["volumes"]
    deploy = (ROOT / "ops/deploy.py").read_text()
    assert 'run("python3", "ops/n8n_sync.py", "import")' in deploy and '"n8n/workflows/"' in deploy


def test_an_export_is_stable_for_git(tmp_path):
    raw = {"id": "aistackSelfTest1", "name": "Stack self-test", "active": True, "updatedAt": "2026-11-10T08:00:00Z",
           "versionId": "x1", "connections": {}, "settings": {}, "nodes": [{"name": "b"}, {"name": "a"}]}
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "1.json").write_text(json.dumps(raw))
    assert NS.write_stable((tmp_path / "in").glob("*.json"), tmp_path / "out") == ["stack-self-test.json"]
    got = json.loads((tmp_path / "out" / "stack-self-test.json").read_text())
    assert "updatedAt" not in got and "versionId" not in got and [n["name"] for n in got["nodes"]] == ["a", "b"]


def test_the_ai_stack_step_sends_the_step_waits_and_gives_the_answer():
    """WFL-06: the node posts to the step service with this execution's resume URL, waits until resumed, and its output
    is the answer the runner posted; n8n loads it from the repository's n8n/custom."""
    js = (ROOT / "n8n/custom/AistackStep.node.js").read_text()
    assert "const STEPS = 'http://mission-control:8099/steps';" in js
    assert "resume_url: this.evaluateExpression('{{ $execution.resumeUrl }}', 0)" in js
    assert "await this.putExecutionToWait(WAIT_INDEFINITELY);" in js and "restartWebhook: true" in js
    assert "return { workflowData: [[{ json: answer }]] };" in js
    n8n = yaml.safe_load((ROOT / "compose/core.yaml").read_text())["services"]["n8n"]
    assert n8n["environment"]["N8N_CUSTOM_EXTENSIONS"] == "/home/node/custom" and "../n8n/custom:/home/node/custom:ro" in n8n["volumes"]


def test_the_ai_stack_step_offers_every_block_with_the_stacks_live_lists():
    """WFL-06: the node's kinds are the step service's, each with its fields; the Agent, Crew job, Place and Repository
    pickers load the stack's lists from the step service's GET /catalog through n8n's loadOptions."""
    js = (ROOT / "n8n/custom/AistackStep.node.js").read_text()
    for kind in FW.KINDS:
        assert f"value: '{kind}'" in js, kind
    assert "const CATALOG = 'http://mission-control:8099/catalog';" in js
    assert "this.methods = {\n      loadOptions: {" in js
    for method, part in (("getAgents", "agents"), ("getCrewJobs", "crew"), ("getPlaces", "places"), ("getRepos", "repos")):
        assert f"async {method}() {{ return pick(this, '{part}'); }}" in js and f"loadOptionsMethod: '{method}'" in js
    assert "if (kind === 'build') Object.assign(body, { repo: p('repo'), brief: p('brief') });" in js
    assert "if (kind === 'recall') Object.assign(body, { query: p('query'), scope: p('scope', '') });" in js
    assert "if (kind === 'command') Object.assign(body, { place: p('place'), command: p('command'), values: json(p('values', '{}'), {}) });" in js
    assert "if (kind === 'plan') body.steps = json(p('steps', '[]'), []);" in js
    assert "note: p('note'), text: p('text'), evidence: p('evidence', '')" in js


def test_an_answer_that_is_not_done_ends_the_n8n_run_as_an_error():
    """WFL-06: a failed, refused or cancelled answer fails the node on resume (n8n's history shows the run in red), with
    the answer's error as the message and the whole answer as its description; a done answer (an owner's answer too) is
    the node's output. Shown on a throwaway n8n 2.44.7 on 10 Nov 2026: a done answer ended in success, a failed one in error."""
    js = (ROOT / "n8n/custom/AistackStep.node.js").read_text()
    assert "if (!succeeded(answer)) failOnResume(this, answer);" in js
    assert "const succeeded = (a) => a.status === 'done' || (a.outcome !== undefined && !FAILED.includes(a.status));" in js
    assert "const FAILED = ['failed', 'refused', 'cancelled'];" in js
    assert "const entry = ctx.runExecutionData && ctx.runExecutionData.executionData && ctx.runExecutionData.executionData.nodeExecutionStack[0];" in js
    assert "entry.node.disabled = false;" in js and "resumeError: {\n    name: 'NodeOperationError'," in js
    assert "message: `The step ${answer.status || 'gave no status'}: ${answer.error || 'no reason given'}`," in js
    assert "description: JSON.stringify(answer, null, 2)," in js
    assert 'return {"status": "done", "answer": a["answer"]' in (ROOT / "ops/flows.py").read_text()   # the owner's answer is "done"


def test_every_scheduled_workflow_can_be_run_now_through_n8n():
    """WFL-13: each generated workflow, and the Memory Keeper's, has a Webhook "Run now" (POST, path run/<file stem>)
    on its AI Stack step, with ids derived from the workflow's id, so a regeneration or an import never makes a second."""
    for f in WF:
        wf = json.loads(f.read_text())
        if not f.name.startswith(("crew-", "task-", "memory-keeper")):
            continue
        hook = next(n for n in wf["nodes"] if n["name"] == "Run now")
        step = next(n for n in wf["nodes"] if n["type"] == "CUSTOM.aistackStep")
        assert hook["type"] == "n8n-nodes-base.webhook" and hook["parameters"]["httpMethod"] == "POST", f.name
        assert hook["parameters"]["path"] == f"run/{f.stem}", f.name
        assert hook["webhookId"] == G.node_id(wf["id"], "Run now/hook") and hook["id"] == G.node_id(wf["id"], "Run now"), f.name
        assert wf["connections"]["Run now"] == {"main": [[{"index": 0, "node": step["name"], "type": "main"}]]}, f.name
        assert len(G.run_now(json.loads(f.read_text()), f.stem)["nodes"]) == len(wf["nodes"])   # added once
    selftest = json.loads((ROOT / "n8n/workflows/stack-self-test.json").read_text())
    assert [n["parameters"]["path"] for n in selftest["nodes"] if n["type"] == "n8n-nodes-base.webhook"] == ["stack-self-test"]

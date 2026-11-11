"""Packs (GEN-21, GEN-32, docs/AI-STACK.md): the toy pack copied outside the repository adds agents, a skill, a
workflow and a job kind once its commit is approved; a name clash and an unapproved commit are refused with the reason;
a new commit leaves the old one running and puts one decision in the queue; home without packs is unchanged."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from domain import packs as PK

ROOT = Path(__file__).resolve().parents[1]
TOY = ROOT / "tests/fixtures/packs/toy"


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@localhost", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A deployment's world outside the repository: the pack's own repository, packs.txt, the cache, the approvals."""
    src = tmp_path / "elsewhere/toy"
    shutil.copytree(TOY, src)
    git(src, "init", "-q", "-b", "main")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "first")
    monkeypatch.setenv("AISTACK_PACKS_TXT", str(tmp_path / "packs.txt"))
    monkeypatch.setenv("AISTACK_PACKS", str(tmp_path / "cache"))
    monkeypatch.setenv("AISTACK_PACK_APPROVALS", str(tmp_path / "approvals.json"))
    monkeypatch.setenv("AISTACK_PACK_FLOWS", str(tmp_path / "pack-workflows.json"))
    monkeypatch.setattr(PK, "sync_n8n", lambda: ["synced"])                          # no n8n here; the n8n tests below use a stand-in

    def pin(*lines):
        (tmp_path / "packs.txt").write_text("".join(f"{x}\n" for x in lines))
    return {"src": src, "pin": pin, "head": lambda: git(src, "rev-parse", "HEAD"), "tmp": tmp_path}


def test_an_unapproved_pack_does_not_run_and_waits_in_the_queue_with_its_manifest_prompts_commands_and_diff(home):
    home["pin"]("# the deployment's packs", f"toy {home['src']} {home['head']()}")
    got = PK.load()
    assert got["packs"] == [] and len(got["pending"]) == 1
    p = got["pending"][0]
    assert p["name"] == "toy" and p["runs"] == "" and p["version"] == "0.1.0" and p["problems"] == []
    assert {a["id"] for a in p["agents"]} == {"toy:intake", "toy:reproducer"} and "Ask for nothing" in p["agents"][0]["prompt"]
    assert p["jobs"][0]["kind"] == "toy.reproduce" and p["workflows"] == ["toy/bug", "toy/ticket", "toy/triage"] and p["skills"] == ["toy:triage"]
    assert "workflows/bug.json" in p["diff"]
    items = list(PK.decisions(lambda *a, **k: {"id": a[0], "cls": a[1], "what": a[2], **k}))
    assert len(items) == 1 and items[0]["cls"] == "pack-commit" and items[0]["what"].startswith("Run pack toy at ")


def test_an_approved_pack_adds_its_agents_skill_workflow_and_job_kind_from_a_read_only_checkout(home):
    head = home["head"]()
    home["pin"](f"toy {home['src']} {head[:10]}")                                        # a short commit is resolved
    assert PK.handle({"action": "pack_approve", "name": "toy", "commit": head})["ok"]
    got = PK.load()
    assert got["pending"] == [] and len(got["packs"]) == 1
    p = got["packs"][0]
    assert p["commit"] == head and Path(p["dir"]).name == f"toy@{head}" and not (Path(p["dir"]) / "stack.yaml").stat().st_mode & 0o222
    assert [a["id"] for a in p["agents"]] == ["toy:intake", "toy:reproducer"] and p["agents"][0]["harness"] == "claude-code"
    assert p["skills"][0]["id"] == "toy:triage" and p["exams"] == ["bugs"]
    assert p["jobs"][0]["kind"] == "toy.reproduce" and len(p["jobs"][0]["sha256"]) == 64          # its worker approves it by this hash
    assert PK.plugin_args(p) == ["--plugin-dir", p["dir"]]
    flows = {w["name"]: w for w in p["workflows"]}
    assert sorted(flows) == ["toy/bug", "toy/ticket", "toy/triage"] and flows["toy/bug"]["path"].startswith(p["dir"]) and flows["toy/bug"]["nodes"] == 3


def test_the_app_sees_each_pack_s_workflows_and_agents_but_no_folder_or_file_path(home):
    """The runner publishes the packs for the Stack page (ops/missions.py domain_state): what a pack brings, by name."""
    head = home["head"]()
    home["pin"](f"toy {home['src']} {head}")
    PK.approve("toy", head, "owner")
    v = PK.view()
    p = v["packs"][0]
    assert p["workflows"] == ["toy/bug", "toy/ticket", "toy/triage"] and p["skills"] == ["toy:triage"] and p["jobs"][0]["kind"] == "toy.reproduce"
    assert [a["id"] for a in p["agents"]] == ["toy:intake", "toy:reproducer"] and p["agents"][0]["prompt"]
    assert str(home["tmp"]) not in json.dumps(v) and v["pending"] == [] and v["refused"] == []
    import missions as MS
    assert set(MS.domain_state()) == {"packs", "trackers"} and MS.domain_state()["packs"]["packs"][0]["name"] == "toy"


def test_a_new_commit_leaves_the_old_one_running_and_puts_one_decision_in_the_queue_and_a_refusal_keeps_it_out(home):
    old = home["head"]()
    PK.approve("toy", old, "owner")
    wf = home["src"] / "workflows/bug.json"
    wf.write_text(wf.read_text().replace("Answer the reporter", "Answer the reporter kindly"))
    git(home["src"], "commit", "-q", "-am", "kinder")
    new = home["head"]()
    home["pin"](f"toy {home['src']} {new}")
    got = PK.load()
    assert [p["commit"] for p in got["packs"]] == [old] and [p["commit"] for p in got["pending"]] == [new]
    assert got["pending"][0]["runs"] == old and '+      "name": "Answer the reporter kindly"' in got["pending"][0]["diff"]
    PK.handle({"action": "pack_refuse", "name": "toy", "commit": new, "why": "not now"})
    got = PK.load()
    assert [p["commit"] for p in got["packs"]] == [old] and got["pending"] == []
    assert got["refused"][0]["why"] == f"pack toy: commit {new[:12]} was refused by owner: not now"


@pytest.mark.parametrize("line, words", [
    ("analyst {src} {head}", "a core agent or a name of the core has that name"),
    ("stack {src} {head}", "a core agent or a name of the core has that name"),
    ("home {src} {head}", "a core agent or a name of the core has that name"),     # the stack's own item workflows (item/home/...)
    ("item {src} {head}", "a core agent or a name of the core has that name"),     # n8n's webhook root of every item workflow
    ("Toy {src} {head}", "its name is letters, digits and dashes"),
    ("toy {src} 0000000000000000000000000000000000000000", "is not in"),
    ("toy {src} not-a-commit", "the commit is 7 to 40 hex digits"),
])
def test_a_pack_that_clashes_or_names_no_commit_of_its_source_is_refused_with_the_reason(home, line, words):
    home["pin"](line.format(src=home["src"], head=home["head"]()))
    got = PK.load()
    assert got["packs"] == [] and got["pending"] == [] and words in got["refused"][0]["why"]


def test_a_pack_with_a_link_is_refused_and_the_file_it_names_is_left_alone(home):
    """Review 10 Nov (DOM2-R1): an unapproved pack's agent file linked to one of the stack's files; loading it made that
    file read-only and put its text into the pending decision."""
    target = home["tmp"] / "stack-state.json"
    target.write_text('{"secret": true}')
    mode = target.stat().st_mode
    agent = next((home["src"] / "agents").glob("*.md"))
    agent.unlink()
    agent.symlink_to(target)
    git(home["src"], "add", "-A")
    git(home["src"], "commit", "-q", "-m", "link")
    home["pin"](f"toy {home['src']} {home['head']()}")
    got = PK.load()
    assert got["packs"] == [] and got["pending"] == [] and "holds links" in got["refused"][0]["why"]
    assert target.stat().st_mode == mode and '"secret"' not in json.dumps(got)


def test_an_artifact_id_is_a_sha256_and_never_a_path():
    """Review 10 Nov (DOM2-R2): 'artifact:./../x' reached a file outside the store, which a tracker step could attach."""
    from domain import artifacts as AR
    for bad in ("artifact:./../target.txt", "artifact:../../etc/passwd", "artifact:" + "a" * 63, "artifact:/etc/passwd"):
        assert AR.path_of(bad) is None, bad


def test_two_packs_of_one_name_and_a_manifest_naming_another_pack_are_refused(home):
    head = home["head"]()
    home["pin"](f"toy {home['src']} {head}", f"toy {home['src']} {head}")
    got = PK.load()
    assert len(got["pending"]) == 1 and "another pack in packs.txt has that name" in got["refused"][0]["why"]
    home["pin"](f"other {home['src']} {head}")
    p = PK.load()["pending"][0]
    assert "its manifest names it 'toy', and packs.txt names it 'other'" in p["problems"]
    assert any("a pack's workflow is named other/<something>" in x for x in p["problems"])
    assert any("its kind is named other.<something>" in x for x in p["problems"])


def test_home_without_packs_is_unchanged(home):
    assert PK.load() == {"packs": [], "pending": [], "refused": []}
    assert list(PK.decisions(lambda *a, **k: a)) == []


def test_a_pack_workflow_that_is_no_n8n_workflow_or_runs_a_shell_command_is_refused_with_the_reason(home):
    flows = home["src"] / "workflows"
    (flows / "broken.json").write_text("{not json")
    (flows / "list.json").write_text('{"name": "toy/list", "nodes": []}')
    shell = json.loads((flows / "bug.json").read_text())
    shell["name"] = "toy/shell"
    shell["nodes"].append({"name": "Run it", "type": "n8n-nodes-base.executeCommand", "parameters": {"command": "rm -rf /"}})
    (flows / "shell.json").write_text(json.dumps(shell))
    git(home["src"], "add", "-A")
    git(home["src"], "commit", "-q", "-m", "three bad workflows")
    home["pin"](f"toy {home['src']} {home['head']()}")
    p = PK.load()["pending"][0]
    assert p["workflows"] == ["toy/bug", "toy/ticket", "toy/triage"]                     # only the good ones count
    assert any(x.startswith("workflows/broken.json: not JSON") for x in p["problems"])
    assert "workflows/list.json: not an n8n workflow (it has no nodes and connections)" in p["problems"]
    assert any(x.startswith("workflows/shell.json: it uses n8n-nodes-base.executeCommand") and "a command runs at a place" in x for x in p["problems"])


def test_packs_are_the_apps_and_the_queues():
    js = (ROOT / "images/mission-control/web/static/app.js").read_text()          # the Stack page's Packs and trackers
    assert "function packsHtml(" in js and 'data-pk="pack_approve"' in js and 'data-pk="pack_refuse"' in js and "action: b.dataset.pk" in js
    assert 'S?.packs ||' in js and "p.workflows" in js and "templates" not in js
    assert '"pack_approve", "pack_refuse"' in (ROOT / "images/mission-control/server.py").read_text()
    import decisions as DQ
    assert DQ._packs in DQ.SOURCES
    cls = __import__("yaml").safe_load((ROOT / "config/autonomy.yaml").read_text())["classes"]["pack-commit"]
    assert cls["floor"] == "security" and cls["highest"] == 0
    assert json.loads((TOY / ".claude-plugin/plugin.json").read_text())["name"] == "toy"


def test_a_pack_agent_gets_exactly_its_grants_and_a_server_off_the_egress_list_is_refused():
    pack = {"name": "toy", "dir": str(TOY)}
    g = PK.grants(pack, "toy:intake", egress={"jira.example"})
    assert list(g["mcp"]["mcpServers"]) == ["tickets"] and g["tools"] == ["Read", "Grep", "mcp__tickets"]
    assert g["dropped"] == ["outside: its host outside.example is not on this deployment's egress list"]
    assert PK.grants(pack, "toy:reproducer", egress={"jira.example"}) == {"mcp": {"mcpServers": {}}, "tools": ["Read", "Bash"], "dropped": []}
    assert list(PK.grants(pack, "toy:intake", egress=None)["mcp"]["mcpServers"]) == ["tickets", "outside"]     # home names no egress list
    args = PK.plugin_args(pack, "toy:intake", egress={"jira.example"})
    assert args[:3] == ["--plugin-dir", str(TOY), "--strict-mcp-config"] and args[-2:] == ["--allowedTools", "Read,Grep,mcp__tickets"]
    assert json.loads(args[args.index("--mcp-config") + 1]) == {"mcpServers": {"tickets": {"command": "python3", "args": ["-m", "http.server", "--help"]}}}



# ---------- the deployment's node allowlist (GEN-42) ----------
def _logic():
    import dataguard as DG
    return set(DG.N8N_NODES)                         # the data guard's list is the one list (WFL-17)


LOGIC = _logic()


def test_a_pack_workflow_with_a_node_off_the_deployments_allowlist_is_refused_with_the_reason(home, monkeypatch):
    """N4.2: a customer-class deployment lists the nodes its n8n loads (N8N_NODES_INCLUDE, handed to n8n as
    NODES_INCLUDE, read through the data guard); a pack's workflow with any other node is refused at load, with the node
    and the reason. Without the line, today's rule. A webhook outside the pack's namespace is refused everywhere."""
    import dataguard as DG
    assert PK.n8n_nodes({"N8N_NODES_INCLUDE": json.dumps(sorted(LOGIC))}) == LOGIC
    assert PK.n8n_nodes({"N8N_NODES_INCLUDE": ""}) is None and PK.n8n_nodes({}) is None
    with pytest.raises(ValueError, match="no JSON list"):
        PK.n8n_nodes({"N8N_NODES_INCLUDE": "n8n-nodes-base.webhook, CUSTOM.aistackStep"})
    flows = home["src"] / "workflows"
    http = json.loads((flows / "triage.json").read_text())
    http["name"] = "toy/fetch"
    http["nodes"][0]["parameters"]["path"] = "item/toy/fetch"
    http["nodes"].append({"name": "Fetch", "type": "n8n-nodes-base.httpRequest", "parameters": {"url": "https://outside.example"}})
    (flows / "fetch.json").write_text(json.dumps(http))
    hook = json.loads((flows / "triage.json").read_text())
    hook["name"] = "toy/takeover"
    hook["nodes"][0]["parameters"]["path"] = "run/crew-checker"                         # the stack's own Run now hook
    (flows / "takeover.json").write_text(json.dumps(hook))
    git(home["src"], "add", "-A")
    git(home["src"], "commit", "-q", "-m", "an HTTP node and a hook outside the namespace")
    home["pin"](f"toy {home['src']} {home['head']()}")
    p = PK.load()["pending"][0]                                                          # home: no allowlist
    assert "toy/fetch" in p["workflows"] and "toy/takeover" not in p["workflows"]
    assert "workflows/takeover.json: its webhook path 'run/crew-checker' is outside the pack's namespace (item/toy/... or toy/...)" in p["problems"]
    monkeypatch.setitem(DG.DEPLOY.VALUES, "N8N_NODES_INCLUDE", json.dumps(sorted(LOGIC)))   # a customer deployment's list
    p = PK.load()["pending"][0]
    assert p["workflows"] == ["toy/bug", "toy/ticket", "toy/triage"]
    assert ("workflows/fetch.json: it uses n8n-nodes-base.httpRequest, which this deployment's n8n does not load "
            "(N8N_NODES_INCLUDE in its deployment.env)") in p["problems"]
    monkeypatch.setitem(DG.DEPLOY.VALUES, "N8N_NODES_INCLUDE", "webhook, aistackStep")      # a list the data guard refuses
    p = PK.load()["pending"][0]
    assert p["workflows"] == [] and any(x.startswith("workflows: N8N_NODES_INCLUDE is no JSON list") for x in p["problems"])


def test_the_toy_packs_item_workflow_is_a_whole_n8n_workflow_on_logic_nodes_only():
    """The toy pack's one item workflow: a webhook item/toy/ticket that answers with its execution, and AI Stack steps of
    the step service's kinds (agent, tracker, wait_item, command, build), with the IF on a wait's outcome, on the logic
    nodes a customer-class deployment loads, and nothing held as a placeholder."""
    import flows as FW
    wf = json.loads((TOY / "workflows/ticket.json").read_text())
    names = {n["name"] for n in wf["nodes"]}
    for src, outs in wf["connections"].items():
        assert src in names and all(c["node"] in names for o in outs["main"] for c in o)
    assert {n["type"] for n in wf["nodes"]} <= LOGIC and wf["active"] is True
    hook = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.webhook")
    assert hook["parameters"] == {"httpMethod": "POST", "path": "item/toy/ticket",
                                  "options": {"responseData": "={{ JSON.stringify({execution: $execution.id}) }}"}}
    steps = [n for n in wf["nodes"] if n["type"] == "CUSTOM.aistackStep"]
    assert all(n["parameters"]["kind"] in FW.KINDS and n["parameters"]["title"] == n["name"] for n in steps)
    assert {n["parameters"]["kind"] for n in steps} == {"agent", "tracker", "wait_item", "command", "build", "item"}
    assert "PLACEHOLDER" not in json.dumps(wf)
    loop = wf["connections"]["Timed out?"]["main"]                                 # remind twice, then stop waiting (G3)
    assert loop[0][0]["node"] == "Reminded twice?" and wf["connections"]["Remind the reporter"]["main"][0][0]["node"] == "Wait for the reply"
    assert [o[0]["node"] for o in wf["connections"]["Reminded twice?"]["main"]] == ["Stop waiting", "Remind the reporter"]
    assert "Stop waiting" not in wf["connections"]                                    # the run ends there
    assert PK.read("toy", "x", TOY, allow=LOGIC)["problems"] == []


# ---------- a pack's workflows in n8n (GEN-43) ----------
class FakeN8n:
    """n8n's command line as ops/n8n_sync.py uses it, over a dict: import (unpublished, as n8n 2.x imports), export by
    id, publish, unpublish, restart."""
    def __init__(self):
        self.store, self.restarts, self.calls = {}, 0, []

    def __call__(self, cmd, **k):
        import re
        import types
        self.calls.append(cmd)
        ok = lambda out="": types.SimpleNamespace(returncode=0, stdout=out, stderr="")   # noqa: E731
        if cmd[:2] == ["docker", "restart"]:
            self.restarts += 1
            return ok()
        last = cmd[-1]
        if "put.json" in last:
            wf = json.loads(k["input"])
            self.store[wf["id"]] = {**wf, "active": False}
            return ok("Successfully imported 1 workflow.")
        m = re.search(r"export:workflow --id=(\w+)", last)
        if m:
            wf = self.store.get(m.group(1))
            return ok(json.dumps([wf])) if wf else types.SimpleNamespace(returncode=1, stdout="", stderr="not found")
        if "publish:workflow" in cmd or "unpublish:workflow" in cmd:
            wid = cmd[-1].split("=", 1)[1]
            if wid in self.store:
                self.store[wid]["active"] = "publish:workflow" in cmd
        return ok()

    def by_name(self):
        return {w["name"]: w for w in self.store.values()}


@pytest.fixture
def n8n(home, monkeypatch):
    import n8n_sync as NS
    fake, sent = FakeN8n(), []
    propose = lambda pack, files: sent.append((pack["name"], files)) or {"branch": "ai/canvas-x", "pr": None}   # noqa: E731
    monkeypatch.setattr(PK, "sync_n8n", lambda: NS.sync_packs(PK.load(), run=fake, propose=propose))
    return {"fake": fake, "sent": sent, "NS": NS, "propose": propose}


def test_an_approved_packs_workflows_reach_n8n_under_ids_from_their_names_and_leave_when_the_pack_goes(home, n8n):
    """N1: the approval imports the running commit's workflows into n8n, named <pack>/<name>, each under an id made from
    its name (never one the file names), published as its file says, with one restart; removing the pack from
    packs.txt unpublishes them."""
    NS, fake = n8n["NS"], n8n["fake"]
    flows = home["src"] / "workflows"
    bug = json.loads((flows / "bug.json").read_text())
    bug["id"] = "aistackSelfTest1"                                                      # a pack cannot take the stack's id
    (flows / "bug.json").write_text(json.dumps(bug))
    git(home["src"], "commit", "-q", "-am", "names an id of the stack's")
    head = home["head"]()
    home["pin"](f"toy {home['src']} {head}")
    got = PK.handle({"action": "pack_approve", "name": "toy", "commit": head})
    assert got["ok"] and got["n8n"] == [f"{n}: imported at {head[:12]}" for n in ("toy/bug", "toy/ticket", "toy/triage")]
    held = fake.by_name()
    assert sorted(held) == ["toy/bug", "toy/ticket", "toy/triage"] and fake.restarts == 1
    assert all(w["id"] == NS.pack_id(n) and len(w["id"]) == 16 and w["id"].isalnum() for n, w in held.items())
    assert "aistackSelfTest1" not in fake.store and held["toy/ticket"]["active"] and not held["toy/bug"]["active"]
    step = next(n for n in held["toy/ticket"]["nodes"] if n["name"] == "Triage")
    assert step["webhookId"] and step["id"] == __import__("n8n_gen").node_id(NS.pack_id("toy/ticket"), "Triage")
    assert PK.sync_n8n() == [] and fake.restarts == 1                                  # nothing changed: no import, no restart
    home["pin"]("# toy is gone")
    assert PK.sync_n8n() == ["toy: the pack no longer runs, its workflows are unpublished (runs that wait still finish)"]
    assert not any(w["active"] for w in fake.store.values()) and fake.restarts == 2
    assert json.loads((home["tmp"] / "pack-workflows.json").read_text()) == {}


def test_a_new_commit_replaces_its_workflows_in_place_and_a_refusal_unpublishes_them(home, n8n):
    """N1, N8: an approved new commit replaces the workflows under the same ids (a run waiting in the old version
    finishes on it, docs/N8N-MIGRATION.md §11); refusing it brings the last approved commit's version back; refusing
    that one too takes the pack's workflows off n8n."""
    NS, fake = n8n["NS"], n8n["fake"]
    old = home["head"]()
    home["pin"](f"toy {home['src']} {old}")
    PK.handle({"action": "pack_approve", "name": "toy", "commit": old})
    wf = home["src"] / "workflows/ticket.json"
    wf.write_text(wf.read_text().replace("Fix what the reproduction showed", "Fix it with a test"))
    git(home["src"], "commit", "-q", "-am", "a test with the fix")
    new = home["head"]()
    home["pin"](f"toy {home['src']} {new}")
    assert PK.handle({"action": "pack_approve", "name": "toy", "commit": new})["n8n"] == [f"toy/ticket: imported at {new[:12]}"]
    ticket = fake.store[NS.pack_id("toy/ticket")]
    assert ticket["active"] and "Fix it with a test" in json.dumps(ticket) and len(fake.store) == 3
    assert PK.handle({"action": "pack_refuse", "name": "toy", "commit": new, "why": "not yet"})["n8n"] == [f"toy/ticket: imported at {old[:12]}"]
    assert "Fix what the reproduction showed" in json.dumps(fake.store[NS.pack_id("toy/ticket")]) and n8n["sent"] == []
    PK.handle({"action": "pack_refuse", "name": "toy", "commit": old, "why": "not at all"})
    assert not any(w["active"] for w in fake.store.values()) and PK.load()["packs"] == []


def test_a_canvas_edit_is_a_proposal_and_the_approved_version_keeps_running(home, n8n):
    """N1: an edit on the canvas does not change what runs: the next sync sends it to the pack's repository once and
    imports the approved version again; it runs only after a commit with it is approved."""
    NS, fake = n8n["NS"], n8n["fake"]
    head = home["head"]()
    home["pin"](f"toy {home['src']} {head}")
    PK.handle({"action": "pack_approve", "name": "toy", "commit": head})
    wid = NS.pack_id("toy/ticket")
    approved = NS.shape(fake.store[wid])
    edited = json.loads(json.dumps(fake.store[wid]))
    next(n for n in edited["nodes"] if n["name"] == "Triage")["parameters"]["brief"] = "Triage it, kindly"
    fake.store[wid] = {**edited, "updatedAt": "2026-11-10T12:00:00Z"}                   # the owner's edit on the canvas
    out = PK.sync_n8n()
    assert out == [f"toy/ticket: imported at {head[:12]}", "toy: canvas edit of toy/ticket sent to the pack's repository as ai/canvas-x"]
    assert NS.shape(fake.store[wid]) == approved and fake.store[wid]["active"]          # what runs is the approved version
    (pack, files), = n8n["sent"]
    assert pack == "toy" and list(files) == ["workflows/ticket.json"]
    sent = json.loads(files["workflows/ticket.json"])
    assert "Triage it, kindly" in json.dumps(sent) and "id" not in sent and all("webhookId" not in n and "id" not in n for n in sent["nodes"])
    fake.store[wid] = edited                                                             # the same edit again: not sent twice
    assert PK.sync_n8n() == [f"toy/ticket: imported at {head[:12]}"] and len(n8n["sent"]) == 1


def test_a_proposal_goes_to_the_packs_own_repository_as_a_branch_and_a_draft_pull_request(home):
    """N1: the edit lands on ai/canvas-<date> in the pack's repository, from the commit that runs; the pack's main branch
    stays as it is; the forge opens a draft when it knows the repository, else the branch is all."""
    import datetime as dt
    head = home["head"]()
    home["pin"](f"toy {home['src']} {head}")
    PK.approve("toy", head, "owner")
    pack = PK.load()["packs"][0]
    opened = []

    class Forge:
        def repo_of(self, origin):
            return ("PROJ", "toy") if origin == str(home["src"]) else None

        def open_pr(self, origin, head_, base, title, body, draft=False):
            opened.append({"origin": origin, "head": head_, "base": base, "title": title, "draft": draft})
            return {"url": "https://forge.example/pr/1", "number": 1}

    got = PK.propose(pack, {"workflows/ticket.json": '{"name": "toy/ticket", "edited": true}\n'}, forge=Forge())
    branch = f"ai/canvas-{dt.datetime.now():%Y-%m-%d}"
    assert got["branch"] == branch and got["pr"] == {"url": "https://forge.example/pr/1", "number": 1}
    assert opened == [{"origin": str(home["src"]), "head": branch, "base": "main", "title": "Canvas edit of ticket", "draft": True}]
    assert git(home["src"], "show", f"{branch}:workflows/ticket.json") == '{"name": "toy/ticket", "edited": true}'
    assert git(home["src"], "rev-parse", f"{branch}~1") == head and git(home["src"], "rev-parse", "main") == head
    again = PK.propose(pack, {"workflows/bug.json": "{}\n"}, forge=type("NoForge", (), {"repo_of": lambda self, o: None})())
    assert again["pr"] is None and git(home["src"], "rev-parse", f"{branch}~1") == got["commit"]   # the day's branch grows


def test_an_export_sends_a_packs_workflow_to_its_repository_never_into_the_stacks_git(home, n8n, tmp_path):
    """N1: `ops/n8n_sync.py export` writes the stack's workflows into git and routes a pack's (by its id, or a new one by
    its name under a running pack) to that pack's repository as a proposal; an unchanged pack workflow is not sent."""
    import types
    NS = n8n["NS"]
    head = home["head"]()
    home["pin"](f"toy {home['src']} {head}")
    PK.approve("toy", head, "owner")
    loaded = PK.load()
    ex = tmp_path / "n8n-export"
    ex.mkdir()
    stack = {"id": "aistackSelfTest1", "name": "Stack self-test", "active": True, "nodes": [], "connections": {}, "settings": {}}
    same = NS.prepared(TOY / "workflows/bug.json")
    edited = NS.prepared(TOY / "workflows/triage.json")
    edited["nodes"][1]["parameters"]["brief"] = "Answer with one word"
    new = {"id": "Xy12Xy12Xy12Xy12", "name": "toy/extra", "active": False, "nodes": [], "connections": {}, "settings": {}}
    for i, wf in enumerate((stack, same, edited, new)):
        (ex / f"{i}.json").write_text(json.dumps(wf))

    def run(cmd, **k):
        if cmd[:2] == ["docker", "cp"]:
            shutil.copytree(ex, cmd[-1], dirs_exist_ok=True)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    dest = tmp_path / "git"
    assert NS.export_all(dest, run=run, loaded=loaded, propose=n8n["propose"]) == 0
    assert sorted(p.name for p in dest.iterdir()) == ["stack-self-test.json"]
    (pack, files), = n8n["sent"]
    assert pack == "toy" and sorted(files) == ["workflows/extra.json", "workflows/triage.json"]
    assert "Answer with one word" in files["workflows/triage.json"]


def test_a_deploy_syncs_the_running_packs_before_its_one_restart(home, n8n, monkeypatch):
    """N1: `ops/n8n_sync.py import` (a deploy) imports the stack's workflows and then the running packs', and restarts
    n8n once."""
    monkeypatch.setenv("N8N_HOOK_TOKEN", "hook-test")          # SEC-27: the webhooks' credential is written first
    NS, fake = n8n["NS"], n8n["fake"]
    head = home["head"]()
    home["pin"](f"toy {home['src']} {head}")
    PK.approve("toy", head, "owner")
    assert NS.import_all(run=fake) == 0
    assert sorted(fake.by_name()) == ["toy/bug", "toy/ticket", "toy/triage"] and fake.restarts == 1
    assert fake.calls[-1] == ["docker", "restart", "aistack-n8n-1"]

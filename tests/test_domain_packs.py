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
    assert p["jobs"][0]["kind"] == "toy.reproduce" and p["workflows"] == ["toy/bug", "toy/triage"] and p["skills"] == ["toy:triage"]
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
    assert sorted(flows) == ["toy/bug", "toy/triage"] and flows["toy/bug"]["path"].startswith(p["dir"]) and flows["toy/bug"]["nodes"] == 3


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
    ("Toy {src} {head}", "its name is letters, digits and dashes"),
    ("toy {src} 0000000000000000000000000000000000000000", "is not in"),
    ("toy {src} not-a-commit", "the commit is 7 to 40 hex digits"),
])
def test_a_pack_that_clashes_or_names_no_commit_of_its_source_is_refused_with_the_reason(home, line, words):
    home["pin"](line.format(src=home["src"], head=home["head"]()))
    got = PK.load()
    assert got["packs"] == [] and got["pending"] == [] and words in got["refused"][0]["why"]


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
    assert p["workflows"] == ["toy/bug", "toy/triage"]                                   # only the good ones count
    assert any(x.startswith("workflows/broken.json: not JSON") for x in p["problems"])
    assert "workflows/list.json: not an n8n workflow (it has no nodes and connections)" in p["problems"]
    assert any(x.startswith("workflows/shell.json: it uses n8n-nodes-base.executeCommand") and "a command runs at a place" in x for x in p["problems"])


def test_packs_are_the_apps_and_the_queues():
    js = (ROOT / "images/mission-control/web/static/app-packs.js").read_text()
    assert "function vPacks(" in js and 'data-pk="pack_approve"' in js and 'data-pk="pack_refuse"' in js and "action: b.dataset.pk" in js
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


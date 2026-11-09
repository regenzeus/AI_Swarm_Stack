"""The template builder (GEN-34, docs/AI-STACK.md §5): templates listed with their spec or their problem, a save checked
by the graph model and kept as canonical YAML, a test run started only from what was saved, the agents a block may name,
and the builder being part of the app."""
import json
from pathlib import Path

import yaml

from engine import graph as G
from engine import templates as T

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "images/mission-control/web/static"
GOOD = {"template": "release-check", "about": "a release looked at twice", "budget": {"days": 2},
        "nodes": {"go": {"block": "start", "title": "By hand", "kind": "hand"},
                  "build": {"block": "change", "title": "Build it", "agent": "builder"},
                  "tests": {"block": "command", "title": "Run the tests", "kind": "demo.regress"},
                  "review": {"block": "agent", "title": "Review it", "agent": "scout"},
                  "judge": {"block": "agent", "title": "Judge both", "agent": "scout", "loop": {"to": "build", "max": 2}},
                  "ok": {"block": "gate", "title": "Release it", "role": "owner"},
                  "out": {"block": "end", "title": "Released", "kind": "done"}},
        "edges": [["go", "build"], ["build", "tests"], ["build", "review"], ["tests", "judge"], ["review", "judge"], ["judge", "ok"], ["ok", "out"]]}


def test_a_saved_template_is_its_canonical_yaml_with_its_fork_join_and_loop(tmp_path):
    r = T.save(GOOD, tmp_path)
    assert r["ok"] and r["name"] == "release-check"
    text = (tmp_path / "release-check.yaml").read_text()
    assert text == r["yaml"] and G.dump(G.canonical(text)) == text                       # what review reads is what was saved
    g = G.load(text)
    assert sorted(g.node("judge").after) == ["review", "tests"] and g.node("judge").loop_to == "build"


def test_a_template_with_a_fault_is_not_saved_and_the_graph_model_says_why(tmp_path):
    bad = {**GOOD, "nodes": {**GOOD["nodes"], "ok": {"block": "gate", "title": "Release it"}}}
    r = T.save(bad, tmp_path)
    assert r == {"ok": False, "error": "template release-check, node ok: a gate names the role that decides"}
    cyc = {**GOOD, "edges": GOOD["edges"] + [["ok", "build"]]}
    assert "cycle" in T.save(cyc, tmp_path)["error"]
    assert not list(tmp_path.glob("*.yaml"))


def test_the_list_shows_the_repositorys_templates_and_the_drafts_with_their_problems(tmp_path):
    T.save(GOOD, tmp_path)
    (tmp_path / "broken.yaml").write_text("template: broken\nnodes: {}\n")
    got = {t["name"]: t for t in T.listing(tmp_path)}
    assert got["demo/ticket"]["source"] == "repository" and got["demo/ticket"]["spec"]["template"] == "demo/ticket"
    assert got["release-check"]["source"] == "draft" and got["release-check"]["nodes"] == 7
    assert "has no nodes" in got["broken"]["problem"]                                     # shown with its reason, never hidden


def test_a_test_run_starts_only_from_what_was_saved_and_only_where_the_engine_runs(tmp_path):
    assert "save the template first" in T.handle({"action": "template_test", "name": "release-check"}, drafts=tmp_path)["error"]
    T.save(GOOD, tmp_path)
    assert "ENGINE=conductor" in T.handle({"action": "template_test", "name": "release-check"}, drafts=tmp_path)["error"]
    seen = []
    r = T.handle({"action": "template_test", "name": "release-check"}, start=lambda n, p: seen.append((n, p)) or "test/release-check:1", drafts=tmp_path)
    assert r == {"ok": True, "run": "test/release-check:1"} and seen == [("release-check", str(tmp_path / "release-check.yaml"))]


def test_a_block_may_name_only_agents_that_can_do_a_step():
    names = {a["id"] for a in T.agents()}
    reg = yaml.safe_load((ROOT / "config/agents.yaml").read_text())["agents"]
    assert names == {a["id"] for a in reg if G.runs_steps(a)} and names


def test_the_builder_is_part_of_the_app_reachable_from_tasks_and_drawn_on_the_first_state():
    assert '<script src="/static/app-templates.js"></script>' in (ROOT / "images/mission-control/web/index.html").read_text()
    js = (STATIC / "app-templates.js").read_text()
    for fn in ("function vTemplates(", "function tbEditor(", "import(`${FLOW}flow.js${q}`)", "F.mount(el, ", "action: \"template_save\"", "action: \"template_test\""):
        assert fn in js, fn
    assert "templates: vTemplates" in (STATIC / "app-base.js").read_text()
    assert 'href="#/templates">Templates</a>' in (STATIC / "app-tasks.js").read_text()
    assert '"file", "templates", "packs", "trackers", "runs"].includes(route.name)) return render(true);' in (STATIC / "app.js").read_text()
    srv = (ROOT / "images/mission-control/server.py").read_text()
    assert '"template_save", "template_test"' in srv



def test_the_editor_s_block_positions_are_kept_beside_the_template_and_listed_with_it(tmp_path):
    spec = {"template": "home/laid-out", "nodes": {"go": {"block": "start", "title": "By hand", "kind": "hand"},
                                                   "one": {"block": "agent", "title": "One", "agent": "analyst"},
                                                   "two": {"block": "end", "title": "Two", "kind": "done"}}, "edges": [["go", "one"], ["one", "two"]]}
    r = T.save(spec, tmp_path, {"one": {"x": 10.4, "y": 20}, "two": {"x": 300, "y": 20}, "gone": {"x": 1, "y": 1}})
    assert r["ok"], r
    lay = json.loads((tmp_path / "home-laid-out.layout.json").read_text())
    assert lay == {"one": {"x": 10, "y": 20}, "two": {"x": 300, "y": 20}}            # only its own blocks; never in the YAML
    assert "x:" not in r["yaml"]
    got = next(t for t in T.listing(tmp_path) if t["name"] == "home/laid-out")
    assert got["layout"]["two"] == {"x": 300.0, "y": 20.0}


def test_the_editor_is_workflow_builder_pinned_and_locked_and_offers_every_block_of_the_graph_model():
    flow = ROOT / "images/mission-control/flow"
    pkg = json.loads((flow / "package.json").read_text())
    pins = {**pkg["dependencies"], **pkg["devDependencies"]}
    assert pins["@workflowbuilder/sdk"] == "3.0.0" and all(v[0].isdigit() for v in pins.values()), pins     # exact versions only
    lock = json.loads((flow / "package-lock.json").read_text())
    assert all(p.get("integrity") for k, p in lock["packages"].items() if k)                              # every package hash-locked
    blocks = (flow / "src/blocks.js").read_text()
    for b in G.BLOCKS:
        assert f'type: "{b}"' in blocks, b
    assert "/app/web/static/vendor/flow" in (ROOT / "images/mission-control/Dockerfile").read_text()                   # the image builds it


DRAFT = {"about": "a report is fixed and approved", "nodes": {
    "report": {"block": "start", "title": "A report arrives", "kind": "item"},
    "triage": {"block": "branch", "title": "Bug or question", "agent": "analyst", "brief": "Answer with one of: bug, question"},
    "answer": {"block": "agent", "title": "Answer it", "agent": "analyst"},
    "fix": {"block": "change", "title": "Fix it", "agent": "builder", "brief": "Fix the bug"},
    "ok": {"block": "gate", "title": "Approve", "role": "owner"},
    "fixed": {"block": "end", "title": "Fixed", "kind": "done"},
    "answered": {"block": "end", "title": "Answered", "kind": "done"}},
    "edges": [["report", "triage"], ["triage", "answer", "question"], ["triage", "fix", "bug"], ["fix", "ok"], ["ok", "fixed"], ["answer", "answered"]]}


def test_a_description_becomes_a_checked_draft_named_as_the_owner_said(tmp_path):
    seen = []
    r = T.describe("When a bug is reported, fix it and let me approve.", "bug-fix", ask=lambda p: seen.append(p) or DRAFT, drafts=tmp_path)
    assert r["ok"] and r["drafted"] and r["name"] == "bug-fix", r
    assert r["spec"]["edges"][2] == ["triage", "fix", "bug"] and (tmp_path / "bug-fix.yaml").read_text() == r["yaml"]
    assert "When a bug is reported" in seen[0] and "- builder:" in seen[0] and "Its name: bug-fix" in seen[0]   # the agents it may name


def test_a_refused_draft_is_asked_for_again_with_the_refusal_and_a_second_refusal_is_said(tmp_path):
    bad = {**DRAFT, "edges": [e for e in DRAFT["edges"] if e != ["triage", "fix", "bug"]]}   # a branch with one way out
    answers, seen = [bad, DRAFT], []
    r = T.describe("fix bugs", "again", ask=lambda p: seen.append(p) or answers.pop(0), drafts=tmp_path)
    assert r["ok"] and len(seen) == 2 and "Your first draft was refused: " in seen[1] and "two or more" in seen[1]
    r = T.describe("fix bugs", "never", ask=lambda p: bad, drafts=tmp_path)
    assert not r["ok"] and r["error"].startswith("the drafts were refused: ") and not (tmp_path / "never.yaml").exists()


def test_a_description_needs_words_and_a_name_and_a_model_that_answers(tmp_path):
    assert "say in a sentence" in T.describe("  ", "x", ask=lambda p: DRAFT, drafts=tmp_path)["error"]
    assert "give it a name" in T.describe("fix bugs", "Bad Name", ask=lambda p: DRAFT, drafts=tmp_path)["error"]

    def down(p):
        raise ConnectionError("gateway down")
    assert "the model did not answer: ConnectionError" in T.describe("fix bugs", "x", ask=down, drafts=tmp_path)["error"]
    r = T.handle({"action": "template_describe", "text": "fix bugs", "name": "via-handle"}, drafts=tmp_path, ask=lambda p: DRAFT)
    assert r["ok"] and r["name"] == "via-handle"


def test_describe_is_on_the_templates_screen_and_an_action_of_the_app_and_the_runner():
    js = (STATIC / "app-templates.js").read_text()
    assert 'action: "template_describe"' in js and 'id="tbdraft"' in js and 'id="tbempty"' in js
    assert '"template_describe"' in (ROOT / "images/mission-control/server.py").read_text()
    assert '"template_describe"' in (ROOT / "ops/missions.requests.py").read_text()


def test_the_editor_undoes_the_wide_screen_zoom_at_every_width_so_its_arrows_meet_their_blocks():
    import re
    css = (STATIC / "app.css").read_text()
    page = dict(re.findall(r"@media \(min-width: (\d+)px\) \{ \.shell \{ zoom: ([\d.]+);", css))
    flow = dict(re.findall(r"@media \(min-width: (\d+)px\) \{ \.tb-flow \{ zoom: ([\d.]+);", css))
    assert page and set(page) == set(flow), (page, flow)
    assert all(abs(float(page[w]) * float(flow[w]) - 1) < 1e-4 for w in page)
    main = (ROOT / "images/mission-control/flow/src/main.jsx").read_text()
    assert "export function missing(" in main and "opts.onProblem?.(" in main and "onProblem: (why) => toast(why, true)" in (STATIC / "app-templates.js").read_text()

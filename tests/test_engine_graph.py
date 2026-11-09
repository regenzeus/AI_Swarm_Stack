"""The graph model (GEN-23, GEN-34, docs/AI-STACK-PLAN.md WP3): plans and templates become the one graph the runner runs.
A plan keeps the Conductor's checks and words (they moved here; the Conductor imports them), and a template is YAML in
one canonical form, so what the canvas saves is what review reads, byte for byte."""
import subprocess
import sys
from pathlib import Path

import pytest

from engine import graph as G
from engine import shapes

ROOT = Path(__file__).resolve().parents[1]
AGENTS = {"analyst": {"harness": "hermes", "model": "m"}, "judge": {"harness": "hermes", "step_kind": "check", "model": "m"},
          "builder": {"harness": "hermes", "step_kind": "build", "model": "m"}}

TOY = """template: toy/bug
about: A ticket from intake to an accepted fix
budget: {tokens: 2000000, days: 60}
nodes:
  arrives: {block: start, title: A ticket arrives, kind: item}
  intake: {block: agent, title: Read the item and ask what is missing, agent: 'toy:intake'}
  reply: {block: wait, title: Wait for the requester, for: requester, key: item, remind: [3d, 7d], timeout: 21d, then: triager}
  spec: {block: agent, title: Write acceptance criteria, agent: 'toy:analyst'}
  approve: {block: gate, title: Approve the spec, role: spec-approver}
  implement: {block: change, title: Implement, values: {base: item.version}}
  regress: {block: command, title: Regression, kind: toy.regress, each: spec.items, pool: tool}
  classify: {block: agent, title: Check regressions, agent: 'toy:classifier', loop: {to: implement, max: 3}}
  deliver: {block: tracker, title: Post the branch, kind: comment, role: delivery-approver}
  fixed: {block: end, title: Fixed, kind: done}
edges:
  - [arrives, intake]
  - [intake, reply]
  - [reply, spec]
  - [spec, approve]
  - [approve, implement]
  - [implement, regress]
  - [regress, classify]
  - [classify, deliver]
  - [deliver, fixed]
"""


def test_a_template_in_canonical_form_round_trips_byte_for_byte():
    g = G.canonical(TOY)
    assert G.dump(g) == TOY
    assert [n.id for n in g.nodes] == ["arrives", "intake", "reply", "spec", "approve", "implement", "regress", "classify", "deliver", "fixed"]
    assert g.node("reply").wait == {"for": "requester", "key": "item", "remind": [3 * 86400, 7 * 86400], "timeout": 21 * 86400, "then": "triager"}
    assert g.node("classify").loop_to == "implement" and g.node("classify").loop_max == 3
    assert g.node("regress").each == "spec.items" and g.node("regress").pool == "tool"


def test_a_template_that_is_not_canonical_is_refused_with_its_canonical_form():
    with pytest.raises(ValueError, match="not in its canonical form") as e:
        G.canonical(TOY.replace("  - [intake, reply]\n", "  - [ intake,   reply ]\n"))
    assert "- [intake, reply]" in str(e.value)


@pytest.mark.parametrize("change, words", [
    (("block: gate, title: Approve the spec, role: spec-approver", "block: gate, title: Approve the spec"), "a gate names the role"),
    (("timeout: 21d, ", ""), "a wait names for, key, timeout and then"),
    (("block: change", "block: magic"), "block must be one of"),
    (("  - [classify, deliver]\n", "  - [classify, nowhere]\n"), "joins nodes that are not in it"),
    (("  - [intake, reply]\n", "  - [intake, reply]\n  - [deliver, intake]\n"), "the plan has a cycle"),
    (("loop: {to: implement, max: 3}", "loop: {to: deliver, max: 3}"), "a loop goes back to a node before it"),
    (("each: spec.items", "each: deliver.items"), "which is not an earlier node's answer"),
    (("kind: comment", "kind: shout"), "a tracker block's kind is one of"),
    (("kind: toy.regress, ", ""), "a command block names its job kind"),
    (("remind: [3d, 7d]", "remind: [3 days]"), "is no duration"),
])
def test_a_template_is_refused_for_what_it_gets_wrong(change, words):
    with pytest.raises(ValueError, match=words):
        G.load(TOY.replace(*change))


def test_a_plan_converts_one_to_one_with_its_fan_out_and_its_loop():
    plan = [{"step": "Find the files", "agent": "analyst", "each": ["a.py", "b.py"]},
            {"step": "Build it", "agent": "builder", "after": [1]},
            {"step": "Check it", "agent": "judge", "after": [2], "loop": {"to": 2, "max": 9}}]
    g = G.from_plan(plan, AGENTS)
    assert [(n.id, n.after, n.harness) for n in g.nodes] == [("s1", [], "hermes"), ("s2", ["s1"], "build"), ("s3", ["s2"], "check")]
    assert g.node("s1").items == ["a.py", "b.py"] and g.source == "plan"
    assert g.node("s3").loop_to == "s2" and g.node("s3").loop_max == G.LOOP_MAX       # capped, as the Conductor capped it


def test_a_plan_is_refused_with_the_conductors_own_words():
    with pytest.raises(ValueError, match="step 2 waits for step 5, which is not another step of the plan"):
        G.from_plan([{"step": "a", "agent": "analyst"}, {"step": "b", "agent": "analyst", "after": [5]}], AGENTS)
    with pytest.raises(ValueError, match="is no agent that can do a step"):
        G.from_plan([{"step": "a", "agent": "nobody"}], AGENTS)
    with pytest.raises(ValueError, match="only a check loops"):
        G.from_plan([{"step": "a", "agent": "analyst"}, {"step": "b", "agent": "analyst", "after": [1], "loop": {"to": 1}}], AGENTS)
    with pytest.raises(ValueError, match="the plan has a cycle: step 1 → step 2 → step 1"):
        G.from_plan([{"step": "a", "agent": "analyst", "after": [2]}, {"step": "b", "agent": "analyst", "after": [1]}], AGENTS)


def test_the_conductor_uses_the_same_checks_until_it_is_retired():
    import conductor as CD
    assert CD.fold_builders is G.fold_builders and CD.runs_steps is G.runs_steps and CD.LOOP_MAX == G.LOOP_MAX
    steps = CD.graph([{"step": "Find", "agent": "analyst", "each": ["a", "b"]}, {"step": "Sum", "agent": "analyst", "after": [1]}], AGENTS)
    assert [s["title"] for s in steps] == ["Find — a", "Find — b", "Sum"] and steps[2]["after"] == [1, 2]


def test_the_graph_is_one_of_the_engines_known_shapes_and_needs_no_temporal():
    assert G.Graph in shapes.STRUCTURES and G.Node in shapes.STRUCTURES
    code = ("import sys; sys.modules['temporalio'] = None; sys.modules['cryptography'] = None; "
            f"sys.path.insert(0, {str(ROOT / 'ops')!r}); import engine.graph; print('ok')")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "ok", r.stderr                                       # the Conductor imports it on plain Python


def test_durations_read_seconds_minutes_hours_and_days():
    assert [G.duration(x) for x in ("45s", "30m", "12h", "21d")] == [45, 1800, 43200, 21 * 86400]


BRANCHY = """template: toy/branchy
nodes:
  begin: {block: start, title: Start, kind: hand}
  read: {block: agent, title: Read it, agent: analyst, brief: Say what it asks for}
  route: {block: branch, title: Which way, agent: analyst}
  a: {block: agent, title: Way A, agent: analyst}
  b: {block: agent, title: Way B, agent: analyst}
  done: {block: end, title: Done, kind: done}
edges:
  - [begin, read]
  - [read, route]
  - [route, a, 'yes']
  - [route, b, 'no']
  - [a, done]
  - [b, done]
"""


def test_a_branch_keeps_its_names_on_its_edges_and_a_brief_in_canonical_form():
    g = G.canonical(BRANCHY)
    assert g.node("route").branches == ["yes", "no"] and g.node("a").when == {"route": "yes"} and g.node("b").when == {"route": "no"}
    assert g.node("read").brief == "Say what it asks for" and G.dump(g) == BRANCHY


def test_a_branch_needs_named_edges_and_only_a_branch_names_them():
    with pytest.raises(ValueError, match="each with its own branch name"):
        G.load(BRANCHY.replace("  - [route, b, 'no']\n", "  - [route, b]\n"))
    with pytest.raises(ValueError, match="each with its own branch name"):
        G.load(BRANCHY.replace("[route, b, 'no']", "[route, b, 'yes']"))
    with pytest.raises(ValueError, match="a branch's name is text"):
        G.load(BRANCHY.replace("'yes'", "yes"))                                          # YAML reads a bare yes as true
    with pytest.raises(ValueError, match="only a branch block's edges do"):
        G.load(BRANCHY.replace("[read, route]", "[read, route, maybe]"))


ENDED = """template: toy/ended
nodes:
  go: {block: start, title: Every Monday, kind: schedule, trigger: 'weekly mon 08:00'}
  work: {block: agent, title: Do it, agent: analyst}
  tell: {block: notify, title: Tell me it failed, brief: The work failed, role: owner}
  done: {block: end, title: Done, kind: done}
  given-up: {block: end, title: Given up, kind: stopped}
edges:
  - [go, work]
  - [work, tell, failed]
  - [work, done]
  - [tell, given-up]
"""


def test_a_template_runs_from_one_start_to_its_ends_with_a_failure_path_and_a_notify():
    g = G.canonical(ENDED)
    assert g.node("go").kind == "schedule" and g.node("go").trigger == "weekly mon 08:00"
    assert g.node("tell").when == {"work": "failed"} and g.node("given-up").kind == "stopped" and G.dump(g) == ENDED


@pytest.mark.parametrize("change, words", [
    (("go: {block: start, title: Every Monday, kind: schedule, trigger: 'weekly mon 08:00'}", "go: {block: agent, title: Every Monday, agent: analyst}"), "needs exactly one start"),
    (("kind: schedule, trigger: 'weekly mon 08:00'", "kind: schedule"), "a start on a schedule names it"),
    (("kind: schedule, trigger: 'weekly mon 08:00'", "kind: whenever"), "says what starts a run"),
    (("given-up: {block: end, title: Given up, kind: stopped}", "given-up: {block: end, title: Given up, kind: maybe}"), "an end counts as one of"),
    (("brief: The work failed, role: owner", "role: owner"), "a notify names who hears it"),
    (("  - [tell, given-up]\n", ""), "tell: it leads nowhere"),
    (("  - [tell, given-up]\n", "  - [tell, given-up]\n  - [done, tell]\n"), "nothing comes after an end"),
    (("  - [go, work]\n", "  - [go, done]\n"), "work, tell, given-up cannot be reached from the start"),
    (("  - [work, done]\n", "  - [work, done, maybe]\n"), "only a branch block's edges do"),
])
def test_a_template_without_one_start_or_with_a_dead_end_is_refused_saying_what_to_draw(change, words):
    with pytest.raises(ValueError, match=words):
        G.load(ENDED.replace(*change))

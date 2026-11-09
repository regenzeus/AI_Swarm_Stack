"""The graph model (GEN-23, docs/AI-STACK.md §4, docs/AI-STACK-PLAN.md WP3): what the graph runner runs.

One shape for both kinds of work:
- **A plan** (the planner's or a fixed one, TSK-05) converts one to one: each step is a node, "after" becomes edges,
  "each" a fan-out, "loop" a loop back. The checks are the Conductor's own, moved here so there is one copy:
  plan_nodes() refuses a step that waits for a missing step, an agent that cannot do a step, a loop that is not a
  check's, and a cycle, with the same words as before; ops/conductor.py imports it until it is retired (GEN-35).
- **A branch** (a Decision in the editor) is a block whose agent answers which way the run goes: its arrows out carry
  the branch's names ([from, to, name] in the template), and the runner takes only the one it names (GEN-23).
- **Start and end** (the owner, 9 Nov 2026: "Shouldn't we always have a starting point? And an end point?"): a
  template has exactly one start, which says what starts a run (by hand, a schedule, a tracker item, an event), and one
  or more ends, each saying what the run delivers and whether reaching it counts as done or as stopped. Every block is
  reached from the start, and nothing leaves an end.
- **A failure path**: an arrow named "failed" ([from, to, failed]) is taken only when its block fails; the block's
  other arrows are then closed, and the run does not fail there. Without one, a failed block fails the run.
- **Notify** tells a role something and does not wait.
- **A template** (a pack's, or home's in config/templates/) is YAML in a canonical form, so what the canvas saves is
  what review reads: load() checks it, dump() writes it, and a template must equal dump(load(it)) byte for byte.
  Block positions on the canvas live in <name>.layout.json beside it, never in the template.

    plan_nodes(plan, agents, own_steps)    the Conductor's checks and folding -> nodes (dicts, 1-based "after")
    from_plan(plan, agents, ...)           -> Graph
    load(text) / dump(graph)               a template's YAML <-> Graph
    duration("21d")                        -> seconds
"""
import dataclasses
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import textcap as TC  # noqa: E402
from engine.shapes import structure  # noqa: E402  (no Temporal here: the Conductor imports this module)

NEW = "new"                                       # TSK-15: the intake's word for "no agent fits": a temporary agent is written
BUILDER = "builder"                               # its steps run as build assignments
HARNESSES = ("hermes", "claude-code", "python", "opencode")   # the harnesses a step can run on (TSK-07)
CARD_STEPS = ("build", "check")                   # TRL-07, TRL-08: a card's steps are builds in its lane, or the judge's checks
EACH = 50                                         # limit: refuses, a plan fanning out over more names the limit on the task: the pools pace the copies
# limit: stops, fix rounds a check may send back (TRL-08)
LOOP_MAX = 4
BLOCKS = ("start", "agent", "command", "change", "gate", "wait", "tracker", "branch", "notify", "end")
STARTS = ("hand", "schedule", "item", "event")       # what starts a run of a template
ENDS = ("done", "stopped")                           # what reaching an end counts as
FAILED = "failed"                                    # the name of an arrow taken only when its block fails
TRACKER_CALLS = ("comment", "summary", "attach", "link", "transition", "label")
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
NAME = re.compile(r"[a-z][a-z0-9-]*(?:[:/.][a-z0-9-]+)*")


def runs_steps(card):
    """Can this agent do a step? Its steps are builds or checks (TRL-07), or its harness has an adapter and a python agent
    has its own key."""
    if card.get("step_kind") in CARD_STEPS:
        return True
    return card.get("harness") in HARNESSES and (card["harness"] != "python" or card.get("key") not in (None, "none"))


# ---------- plans (TSK-05), the Conductor's checks moved here ----------
def fold_builders(plan):
    """Consecutive builder steps become one build, each a stage of its brief (TRL-10). Every builder step is a build and
    a build that commits nothing fails, so the first trial's plan (read the spec and plan; implement; run the tests and
    fix) failed at its first step though the builder did that work well (trial semver, 1 Nov 2026). A builder step
    whose only predecessor is a builder step that nothing else waits for joins it as its next stage."""
    steps = [dict(p, after=sorted({int(a) for a in p.get("after") or [] if str(a).isdigit()})) for p in plan]
    while True:
        for j, p in enumerate(steps, 1):
            k = p["after"][0] if len(p["after"]) == 1 else 0
            q = steps[k - 1] if 1 <= k <= len(steps) and k != j else None
            if (p.get("agent") != BUILDER or p.get("each") or not q or q.get("agent") != BUILDER or q.get("each")
                    or any(k in s["after"] for n, s in enumerate(steps, 1) if n != j)):
                continue
            stages = (q.get("stages") or [str(q.get("step", "")).strip()]) + [str(p.get("step", "")).strip()]
            joined = {**q, "stages": stages, "step": "; ".join(f"Stage {n}: {s}" for n, s in enumerate(stages, 1)),
                      "why": "; ".join(x for x in (q.get("why"), p.get("why")) if x)}
            out = []
            for n, s in enumerate(steps, 1):
                if n == j:
                    continue
                s = joined if n == k else s
                after = sorted({k if a == j else a for a in s["after"]})
                lp = s.get("loop")
                if isinstance(lp, dict) and str(lp.get("to", "")).isdigit():      # a check that loops to a folded stage loops to the build
                    to = k if int(lp["to"]) == j else int(lp["to"])
                    lp = {**lp, "to": to - (to > j)}
                out.append({**s, "after": [a - (a > j) for a in after], **({"loop": lp} if lp else {})})
            steps = out
            break
        else:
            return steps


def plan_nodes(plan, agents, own_steps=None):
    """The intake's plan -> its nodes, each {title, agent, after (1-based), items, harness, model, why, loop}, or
    ValueError: a step that waits for a step that is not there, an agent that cannot do a step, a loop that is not a
    check's, or a plan with a cycle, is refused."""
    own_steps = own_steps or {}
    n = len(plan)
    for i, p in enumerate(plan, 1):                      # a step that waits for one that is not there: refused before folding
        bad = [a for a in {int(a) for a in p.get("after") or [] if str(a).isdigit()} if not 1 <= a <= n or a == i]
        if bad:
            raise ValueError(f"step {i} waits for step {bad[0]}, which is not another step of the plan")
    plan = fold_builders(plan)
    nodes, n = [], len(plan)
    for i, p in enumerate(plan, 1):
        after = sorted({int(a) for a in p.get("after") or [] if str(a).isdigit()})
        bad = [a for a in after if not 1 <= a <= n or a == i]
        if bad:
            raise ValueError(f"step {i} waits for step {bad[0]}, which is not another step of the plan")
        a = p.get("agent")
        card = agents.get(a)
        if a == NEW:                                   # a temporary agent, written when the step starts (ops/staffing.py)
            card = {"harness": "temp", "model": "gpt-sub"}
        elif not card or not runs_steps(card):
            raise ValueError(f"step {i}: {a!r} is no agent that can do a step (one on {', '.join(HARNESSES)})")
        items = TC.limit_items([str(x).strip() for x in p.get("each") or [] if str(x).strip()], EACH, f"items to fan out in step {i}")
        harness = (p["harness"] if p.get("harness") in own_steps.get(a, ()) else "build" if a == BUILDER
                   else card["step_kind"] if card.get("step_kind") in CARD_STEPS else card["harness"])
        lp = p.get("loop")
        if lp is not None:                                 # TRL-08: a check may send failures back to an earlier step
            to, mx = lp.get("to") if isinstance(lp, dict) else None, lp.get("max", 2) if isinstance(lp, dict) else None
            if harness != "check" or not str(to).isdigit() or not 1 <= int(to) < i or not str(mx).isdigit():
                raise ValueError(f"step {i}: only a check loops, back to an earlier step, a few times")
            lp = {"to": int(to), "max": min(int(mx), LOOP_MAX)}
        model = p["model"] if p.get("model") and harness in ("python", "temp") else card.get("model")   # TSK-30: the owner's model where a
        nodes.append({"title": str(p.get("step", "")).strip() or f"Step {i}", "agent": a, "after": after, "items": items or [None],   # step makes its own call
                      "harness": harness, "model": model, "why": str(p.get("why", "")).strip(), "loop": lp})
    _acyclic({i: nd["after"] for i, nd in enumerate(nodes, 1)}, "step ")
    return nodes


def _acyclic(after, word):
    """after: node -> the nodes it waits for. A cycle is refused, naming it."""
    done = set()

    def visit(i, path):
        if i in path:
            raise ValueError(f"the plan has a cycle: {word}{(' → ' + word).join(map(str, path[path.index(i):] + [i]))}")
        if i in done:
            return
        for a in after[i]:
            visit(a, path + [i])
        done.add(i)
    for i in after:
        visit(i, [])


# ---------- the graph the runner runs ----------
@structure
@dataclasses.dataclass
class Node:
    id: str                                           # stable: a template's name for it, or "s<n>" for a plan's step n
    block: str                                        # one of BLOCKS
    title: str = ""
    after: list = dataclasses.field(default_factory=list)
    agent: str = ""                                   # agent: the card; a plan's step keeps its harness and model too
    brief: str = ""                                   # what the block is told to do, beyond its title (the editor's "What to do")
    harness: str = ""
    model: str = ""
    why: str = ""
    kind: str = ""                                    # command: the job kind; tracker: the call; start: STARTS; end: ENDS
    trigger: str = ""                                 # start: the schedule, the tracker's query or the event it waits for
    values: dict = dataclasses.field(default_factory=dict)
    items: list = dataclasses.field(default_factory=list)   # fan-out: the items, or empty
    each: str = ""                                    # fan-out: "<node>.<field>" of an earlier answer, resolved when it ends
    loop_to: str = ""
    loop_max: int = 0
    role: str = ""                                    # gate: who decides; also a gate on a tracker block
    wait: dict = dataclasses.field(default_factory=dict)    # wait: {for, key, remind: [seconds], timeout: seconds, then}
    pool: str = ""
    place: str = ""                                   # command: where its job runs (wsl, wsl-host, windows; GEN-22)
    when: dict = dataclasses.field(default_factory=dict)    # a branch before it -> the name of the branch it is on
    branches: list = dataclasses.field(default_factory=list)  # a branch block: the names of its branches, in order


@structure
@dataclasses.dataclass
class Graph:
    name: str
    source: str = ""                                  # a template's pack commit, or "plan"
    about: str = ""
    budget: dict = dataclasses.field(default_factory=dict)
    nodes: list[Node] = dataclasses.field(default_factory=list)     # typed: Temporal's decoder builds Nodes from it

    def node(self, nid):
        return next(n for n in self.nodes if n.id == nid)


def from_plan(plan, agents, own_steps=None, name="plan"):
    """A plan (TSK-05) as a graph: the same checks, one node per step (its items kept as a fan-out)."""
    out = []
    for i, nd in enumerate(plan_nodes(plan, agents, own_steps), 1):
        lp = nd["loop"] or {}
        out.append(Node(id=f"s{i}", block="agent", title=nd["title"], after=[f"s{a}" for a in nd["after"]], agent=nd["agent"] or "",
                        harness=nd["harness"] or "", model=nd["model"] or "", why=nd["why"],
                        items=[x for x in nd["items"] if x is not None], loop_to=f"s{lp['to']}" if lp else "", loop_max=lp.get("max", 0)))
    return Graph(name=name, source="plan", nodes=out)


def duration(text):
    """'21d', '12h', '30m', '45s' -> seconds."""
    m = re.fullmatch(r"(\d+)([smhd])", str(text).strip())
    if not m:
        raise ValueError(f"{text!r} is no duration: a number and one of s, m, h, d")
    return int(m[1]) * UNITS[m[2]]


def _span(seconds):
    for u, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % n == 0:
            return f"{seconds // n}{u}"
    return f"{seconds}s"


# ---------- templates: canonical YAML ----------
KEYS = ("block", "title", "agent", "brief", "kind", "trigger", "values", "each", "items", "role", "for", "key", "remind", "timeout", "then",
        "loop", "pool", "place", "why")


def load(text, source=""):
    """A template's YAML -> Graph, checked: known blocks, each block's own fields, edges between its nodes, loops back
    to an ancestor, no cycle."""
    d = yaml.safe_load(text) or {}
    name = str(d.get("template") or "")
    if not NAME.fullmatch(name):
        raise ValueError(f"a template needs a name of letters, digits, dashes and pack/ or pack: parts, not {name!r}")
    unknown = set(d) - {"template", "about", "budget", "nodes", "edges"}
    if unknown:
        raise ValueError(f"template {name}: unknown fields {', '.join(sorted(unknown))}")
    raw = d.get("nodes") or {}
    if not raw:
        raise ValueError(f"template {name} has no nodes")
    after = {nid: [] for nid in raw}
    when = {nid: {} for nid in raw}
    for e in d.get("edges") or []:
        if not (isinstance(e, list) and len(e) in (2, 3) and all(x in raw for x in e[:2])):
            raise ValueError(f"template {name}: edge {e!r} joins nodes that are not in it")
        if len(e) == 3:
            if not isinstance(e[2], str):
                raise ValueError(f"template {name}: edge {e!r}: a branch's name is text; write it in quotes ('yes', 'no')")
            if str(e[2]).strip() != FAILED and ((raw[e[0]] or {}).get("block") != "branch" or not str(e[2]).strip()):
                raise ValueError(f"template {name}: edge {e!r} names a branch, and only a branch block's edges do (or '{FAILED}', a failure path)")
            when[e[1]][e[0]] = str(e[2]).strip()
        after[e[1]].append(e[0])
    _acyclic(after, "node ")
    nodes = []
    for nid, f in raw.items():
        if not NAME.fullmatch(str(nid)):
            raise ValueError(f"template {name}: node name {nid!r}")
        f = dict(f or {})
        bad = set(f) - set(KEYS)
        if bad:
            raise ValueError(f"template {name}, node {nid}: unknown fields {', '.join(sorted(bad))}")
        b = f.get("block")
        if b not in BLOCKS:
            raise ValueError(f"template {name}, node {nid}: block must be one of {', '.join(BLOCKS)}")
        n = Node(id=nid, block=b, title=str(f.get("title") or ""), after=sorted(after[nid]), agent=str(f.get("agent") or ""),
                 brief=str(f.get("brief") or ""), when=when[nid], kind=str(f.get("kind") or ""), trigger=str(f.get("trigger") or ""), values=dict(f.get("values") or {}), each=str(f.get("each") or ""),
                 items=[str(x) for x in f.get("items") or []], role=str(f.get("role") or ""), pool=str(f.get("pool") or ""), place=str(f.get("place") or ""),
                 why=str(f.get("why") or ""))
        if b == "agent" and not n.agent:
            raise ValueError(f"template {name}, node {nid}: an agent block names its agent")
        if n.place and n.place not in ("wsl", "wsl-host", "windows"):
            raise ValueError(f"template {name}, node {nid}: a command runs at wsl, wsl-host or windows, not {n.place!r}")
        if b == "command" and not n.kind:
            raise ValueError(f"template {name}, node {nid}: a command block names its job kind")
        if b == "tracker" and n.kind not in TRACKER_CALLS:
            raise ValueError(f"template {name}, node {nid}: a tracker block's kind is one of {', '.join(TRACKER_CALLS)}")
        if b == "start" and n.kind not in STARTS:
            raise ValueError(f"template {name}, node {nid}: a start says what starts a run, one of {', '.join(STARTS)}")
        if b == "start" and n.kind in ("schedule", "event") and not n.trigger:
            raise ValueError(f"template {name}, node {nid}: a start on a {n.kind} names it (trigger)")
        if b == "end" and n.kind not in ENDS:
            raise ValueError(f"template {name}, node {nid}: an end counts as one of {', '.join(ENDS)}")
        if b == "notify" and not (n.role and n.brief):
            raise ValueError(f"template {name}, node {nid}: a notify names who hears it (role) and what (brief)")
        if b == "branch":
            outs = [e for e in d.get("edges") or [] if e[0] == nid and not (len(e) == 3 and e[2] == FAILED)]
            names = [str(e[2]).strip() if len(e) == 3 else "" for e in outs]
            if not n.agent or len(outs) < 2 or "" in names or len(set(names)) != len(names):
                raise ValueError(f"template {name}, node {nid}: a branch names the agent who decides and has two or more "
                                 "edges out, each with its own branch name")
            n.branches = names
        if b == "gate" and not n.role:
            raise ValueError(f"template {name}, node {nid}: a gate names the role that decides")
        if b == "wait":
            if not f.get("for") or not f.get("key") or not f.get("timeout") or not f.get("then"):
                raise ValueError(f"template {name}, node {nid}: a wait names for, key, timeout and then (who hears of a timeout)")
            n.wait = {"for": str(f["for"]), "key": str(f["key"]), "remind": [duration(x) for x in f.get("remind") or []],
                      "timeout": duration(f["timeout"]), "then": str(f["then"])}
        if f.get("loop") is not None:
            lp = f["loop"]
            if not isinstance(lp, dict) or lp.get("to") not in raw or not str(lp.get("max", "")).isdigit():
                raise ValueError(f"template {name}, node {nid}: a loop is {{to: <an earlier node>, max: <rounds>}}")
            n.loop_to, n.loop_max = lp["to"], min(int(lp["max"]), LOOP_MAX)
        if n.each and n.items:
            raise ValueError(f"template {name}, node {nid}: fan out over listed items or over an earlier answer, not both")
        nodes.append(n)
    g = Graph(name=name, source=source, about=str(d.get("about") or ""), budget=dict(d.get("budget") or {}), nodes=nodes)
    _ends(g, name)
    for n in g.nodes:                                  # a loop goes back to an ancestor; a fan-out reads an ancestor
        anc = ancestors(g, n.id)
        if n.loop_to and n.loop_to not in anc:
            raise ValueError(f"template {name}, node {n.id}: a loop goes back to a node before it, and {n.loop_to} is not")
        if n.each and n.each.split(".")[0] not in anc:
            raise ValueError(f"template {name}, node {n.id}: it fans out over {n.each}, which is not an earlier node's answer")
    return g


def _ends(g, name):
    """A template starts at one start and runs to its ends: one start, nothing into it, nothing out of an end, every
    block reached from the start, and an end reached from every block (no block that leads nowhere)."""
    starts = [n.id for n in g.nodes if n.block == "start"]
    ends = {n.id for n in g.nodes if n.block == "end"}
    if len(starts) != 1:
        raise ValueError(f"template {name} needs exactly one start (it has {len(starts)}): the start says what starts a run")
    if not ends:
        raise ValueError(f"template {name} needs an end: it says what a run delivers")
    outs = {n.id: [] for n in g.nodes}
    for n in g.nodes:
        for a in n.after:
            outs[a].append(n.id)
    for n in g.nodes:
        if n.block == "start" and n.after:
            raise ValueError(f"template {name}, node {n.id}: nothing comes before the start")
        if n.block == "end" and outs[n.id]:
            raise ValueError(f"template {name}, node {n.id}: nothing comes after an end")
        if n.block != "end" and not outs[n.id]:
            raise ValueError(f"template {name}, node {n.id}: it leads nowhere; draw an arrow from it to the next block or to an end")
    seen, todo = set(), [starts[0]]
    while todo:
        k = todo.pop()
        if k not in seen:
            seen.add(k)
            todo.extend(outs[k])
    lost = [n.id for n in g.nodes if n.id not in seen]
    if lost:
        raise ValueError(f"template {name}: {', '.join(lost)} cannot be reached from the start")


def ancestors(g, nid):
    seen, todo = set(), list(g.node(nid).after)
    while todo:
        a = todo.pop()
        if a not in seen:
            seen.add(a)
            todo.extend(g.node(a).after)
    return seen


def _flow(v):
    s = yaml.safe_dump(v, default_flow_style=True, width=10**6, sort_keys=False, allow_unicode=True).strip()
    return s[:-4].rstrip() if s.endswith("\n...") else s      # a plain scalar gets YAML's document-end marker


def dump(g):
    """Graph -> the template's canonical YAML: fields in one order, one node per line, edges in node order."""
    out = [f"template: {g.name}"]
    if g.about:
        out.append(f"about: {_flow(g.about)}")
    if g.budget:
        out.append(f"budget: {_flow(g.budget)}")
    out.append("nodes:")
    for n in g.nodes:
        f = {"block": n.block, "title": n.title, "agent": n.agent, "brief": n.brief, "kind": n.kind, "trigger": n.trigger, "values": n.values, "each": n.each,
             "items": n.items, "role": n.role}
        if n.wait:
            f.update({"for": n.wait["for"], "key": n.wait["key"], "remind": [_span(x) for x in n.wait["remind"]],
                      "timeout": _span(n.wait["timeout"]), "then": n.wait["then"]})
        if n.loop_to:
            f["loop"] = {"to": n.loop_to, "max": n.loop_max}
        f.update({"pool": n.pool, "place": n.place, "why": n.why})
        f = {k: f[k] for k in KEYS if f.get(k) not in (None, "", [], {})}
        out.append(f"  {n.id}: {_flow(f)}")
    edges = [[a, n.id, n.when[a]] if a in n.when else [a, n.id] for n in g.nodes for a in n.after]
    if edges:
        out.append("edges:")
        out += [f"  - {_flow(e)}" for e in edges]
    return "\n".join(out) + "\n"


def canonical(text):
    """Refuses a template that is not in its canonical form, saying what its canonical form is."""
    g = load(text)
    if dump(g) != text:
        raise ValueError(f"template {g.name} is not in its canonical form; it should read:\n{dump(g)}")
    return g

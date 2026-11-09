"""The graph runner (GEN-23, GEN-24, GEN-37, GEN-38, docs/AI-STACK.md §4, docs/AI-STACK-PLAN.md WP4): one Temporal
workflow that runs any graph, a plan's or a template's.

What it does, block by block:
- agent: one activity ("step"), on the node's pool as its task queue;
- command: one activity ("command") on its place's task queue (place-wsl, place-wsl-host, place-windows): the job of
  the worker protocol, with a heartbeat while it runs (GEN-22);
- tracker: one activity ("tracker_write") with a write id, so a retry writes nothing twice; in shadow it writes nothing
  outward (GEN-25);
- change, and every fan-out item: a child workflow (NodeRun), so their rounds and retries fill their own histories;
- gate: an activity puts a decision for the node's role in the queue and names the role's people; the run waits for
  the signal "decide", and an answer from anyone outside the role is refused, recorded on the node, and waited past;
- wait: the run waits for the signal "event" with the node's key; reminders and the timeout are durable timers; a
  timeout puts a decision for the role named in "then" in the queue and waits for it;
- a node with loop_to whose answer says pass: false sends the run back to that node, up to loop_max rounds, with the
  answer's reference as the feedback;
- branch: its agent's answer names one of its branches; a node on another branch is skipped, and so is a node whose
  every way in is skipped. A join after a branch runs when the branch taken reaches it;
- start and end settle at once: the start records what started the run, an end what the run delivered; a run that
  reaches only ends that count as stopped finishes as stopped;
- an arrow named "failed" is taken only when its block fails: the block's other arrows close and the run goes on down
  the failure path instead of failing;
- notify: one activity, as an agent step, that tells a role and does not wait.

What it keeps (the query "state", read by the projector and the canvas): each node's status, its start, its end, what
it waits for, its rounds, and its answer's reference, so every block's timing is shown as it happens.

Rules: no I/O here (Temporal replays this code); everything passed is a reference (GEN-36); the graph is loaded once
by an activity from the commit pinned at the start (GEN-37); the run continues as new when Temporal suggests it or a
long wait has ended, carrying its state, whenever no activity or child is running (GEN-38).
"""
import asyncio
import dataclasses
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from engine.graph import FAILED, Graph, Node
    from engine.shapes import structure
    import textcap as TC

QUEUE = "aistack"                                 # the default task queue; a node's pool or place names its own
STEP_TIMEOUT = timedelta(minutes=40)              # limit: stops, one step past this counts as failed (as the Conductor's STEP_TIMEOUT)
HEARTBEAT = timedelta(minutes=2)                  # an activity that stops heartbeating is lost and tried again
ATTEMPTS = 2                                      # limit: stops, a step that failed twice fails its run, with the reason
CHILD_BATCH = 20                                  # limit: paces, fan-out children started at once; the pools pace the rest
LONG_WAIT = timedelta(hours=1)                    # a wait at least this long continues the run as new when it ends
STEP_QUEUE = "steps"                              # plan steps: the engine worker runs as many at once as the Conductor's SLOTS
POLL_FIRST, POLL_MAX = 20, 300                    # limit: paces, a waiting step is asked again after 20 s, then less often, up to 5 minutes


@structure
@dataclasses.dataclass
class RunInput:
    task: str                                     # the task's id (the app's), or the item key a template runs for
    ref: dict                                     # what load_graph pins: {"kind": "template", "name", "commit"} or {"kind": "plan", "task"}
    graph: Optional[Graph] = None                 # the pinned graph, carried over by continue-as-new
    nodes: Optional[dict] = None                  # the carried state of every node
    started: str = ""


@structure
@dataclasses.dataclass
class StepInput:
    task: str
    run: str                                      # the workflow id
    node: Node
    item: str = ""
    round: int = 0
    inputs: dict = dataclasses.field(default_factory=dict)   # node id -> its answer's reference
    feedback: dict = dataclasses.field(default_factory=dict)  # a loop's: the answer that sent the run back
    ref: dict = dataclasses.field(default_factory=dict)       # the run's graph reference: a plan's task and run, or a template


@structure
@dataclasses.dataclass
class Look:
    """The checkpoint's answer (TRL-08): whether the plan changed, its new graph and the nodes it dropped."""
    changed: bool
    graph: Optional[Graph] = None
    skipped: list[str] = dataclasses.field(default_factory=list)


async def _do(inp, st=None):
    """A node's work: a command's job at its place, or a step."""
    if inp.node.block == "command" and workflow.patched("command-place"):        # runs started before keep the step activity
        return await workflow.execute_activity("command", {"place": inp.node.place or "wsl", "kind": inp.node.kind, "values": inp.node.values,
                                                           "item": inp.item, "task": inp.task, "run": inp.run, "node": inp.node.id,
                                                           "ref": inp.ref, "round": inp.round},
                                               task_queue=f"place-{inp.node.place or 'wsl'}", start_to_close_timeout=STEP_TIMEOUT,
                                               heartbeat_timeout=HEARTBEAT, retry_policy=_retry(), result_type=dict)
    return await _step(inp, st)


async def _step(inp, st=None):
    """Runs a step to its answer. A step that must wait (work elsewhere, a limit, no headroom) answers {"waiting": why}:
    the run sleeps on a durable timer, holding no slot, and asks again, less often each time."""
    pause = POLL_FIRST
    while True:
        answer = await workflow.execute_activity("step", inp, task_queue=inp.node.pool or STEP_QUEUE, start_to_close_timeout=STEP_TIMEOUT,
                                                 heartbeat_timeout=HEARTBEAT, retry_policy=_retry(), result_type=dict)
        if not answer.get("waiting"):
            if st is not None:
                st.update(status="running", waiting_for="")
            return answer
        if st is not None:
            st.update(status="waiting", waiting_for=answer["waiting"])
        await workflow.sleep(timedelta(seconds=int(answer.get("again") or pause)))
        pause = min(pause * 2, POLL_MAX)


def _fresh():
    return {"status": "pending", "started": "", "ended": "", "waiting_for": "", "round": 0, "answer": {}, "error": "",
            "items": [], "reminded": 0}


def _retry():
    return RetryPolicy(maximum_attempts=ATTEMPTS, initial_interval=timedelta(seconds=30), backoff_coefficient=2.0,
                       non_retryable_error_types=["ContentRefused", "Refused"])


@workflow.defn(name="node-run")
class NodeRun:
    """One node's work for one item or one change: its own history (GEN-38)."""

    @workflow.run
    async def run(self, inp: StepInput) -> dict:
        return await _do(inp)


@workflow.defn(name="graph-run")
class GraphRun:
    def __init__(self):
        self.nodes = {}
        self.graph = None
        self.events = {}                          # key -> the event references received
        self.decisions = {}                       # node id -> {"answer", "who"}
        self.cancelled = ""
        self.long_wait_ended = False
        self.looked_after = ()                    # the done nodes when the Orchestrator last looked (a plan's checkpoint)

    # ---------- what the app reads ----------
    @workflow.query
    def state(self) -> dict:
        """What the app draws: the graph's blocks and edges, each node's status and timing, and the run's own."""
        shape = [{"id": n.id, "block": n.block, "title": n.title, "agent": n.agent, "after": n.after, "role": n.role,
                  "loop_to": n.loop_to, "when": n.when} for n in (self.graph.nodes if self.graph else [])]
        return {"graph": self.graph.name if self.graph else "", "source": self.graph.source if self.graph else "",
                "shape": shape, "nodes": self.nodes, "cancelled": self.cancelled}

    # ---------- what reaches the run from outside ----------
    @workflow.signal
    def event(self, key: str, ref: dict):
        self.events.setdefault(key, []).append(ref)

    @workflow.signal
    def decide(self, node: str, answer: str, who: str):
        self.decisions[node] = {"answer": answer, "who": who}

    @workflow.signal
    def cancel(self, why: str):
        self.cancelled = why or "cancelled"

    # ---------- the run ----------
    @workflow.run
    async def run(self, inp: RunInput) -> dict:
        self.graph = inp.graph or await workflow.execute_activity(
            "load_graph", inp.ref, start_to_close_timeout=timedelta(minutes=2), retry_policy=_retry(), result_type=Graph)
        self.nodes = inp.nodes or {n.id: _fresh() for n in self.graph.nodes}
        started = inp.started or workflow.now().isoformat()
        budget_days = (self.graph.budget or {}).get("days")
        deadline = _when(started) + timedelta(days=int(budget_days)) if budget_days else None
        running = {}                               # node id -> its asyncio task
        cancel_watch = asyncio.ensure_future(workflow.wait_condition(lambda: bool(self.cancelled)))
        while True:
            if self.graph.source == "plan" and not running:
                await self._look(inp)
            self._prune()
            for n in self.graph.nodes:
                st = self.nodes[n.id]
                if st["status"] in ("pending", "waiting") and n.id not in running and self._ready(n):
                    running[n.id] = asyncio.ensure_future(self._node(inp, n))
            if not running:
                failed = [k for k, v in self.nodes.items() if v["status"] == "failed" and not self._rescued(k)]
                if failed:
                    return await self._finish(inp, "failed", f"{failed[0]}: {self.nodes[failed[0]]['error']}")
                if all(v["status"] in ("done", "skipped") or self._rescued(k) for k, v in self.nodes.items()):
                    ends = [n for n in self.graph.nodes if n.block == "end" and self.nodes[n.id]["status"] == "done"]
                    if ends and all(n.kind == "stopped" for n in ends):
                        return await self._finish(inp, "stopped", f"ended at {ends[0].title or ends[0].id}")
                    return await self._finish(inp, "done", f"ended at {', '.join(n.title or n.id for n in ends)}" if ends else "")
                return await self._finish(inp, "failed", "no node can start: a node waits for one that failed")
            left = (deadline - workflow.now()) if deadline else None
            if left is not None and left.total_seconds() <= 0:     # limit: stops, the template's budget of days
                for t in running.values():
                    t.cancel()
                await asyncio.gather(*running.values(), return_exceptions=True)
                return await self._finish(inp, "failed", f"the run's budget of {budget_days} days is spent")
            done, _ = await workflow.wait([*running.values(), cancel_watch], timeout=left.total_seconds() if left else None,
                                          return_when=asyncio.FIRST_COMPLETED)
            if self.cancelled:
                for t in running.values():
                    t.cancel()
                await asyncio.gather(*running.values(), return_exceptions=True)    # each block settles before the run ends
                return await self._finish(inp, "cancelled", self.cancelled)
            for nid in [k for k, t in running.items() if t in done]:
                running.pop(nid).result()
            busy = any(self.nodes[k]["status"] == "running" for k in running)
            if not busy and (workflow.info().is_continue_as_new_suggested() or self.long_wait_ended):
                for t in running.values():
                    t.cancel()                     # waits and gates only: their state is data and resumes in the new run
                for k in running:
                    self.nodes[k]["status"] = "waiting"
                workflow.continue_as_new(RunInput(task=inp.task, ref=inp.ref, graph=self.graph, nodes=self.nodes, started=started))

    async def _look(self, inp):
        """Between two waves of a plan, the Orchestrator may look again (TRL-08); the activity applies the Conductor's own
        rule and code, and a changed plan becomes this run's graph: new rows are new nodes, dropped rows are skipped."""
        done = tuple(sorted(k for k, v in self.nodes.items() if v["status"] == "done"))
        if not done or done == self.looked_after or not any(v["status"] == "pending" for v in self.nodes.values()):
            return
        self.looked_after = done
        look = await workflow.execute_activity("checkpoint", {"ref": inp.ref}, start_to_close_timeout=STEP_TIMEOUT,
                                               heartbeat_timeout=HEARTBEAT, retry_policy=_retry(), result_type=Look)
        if not look.changed or look.graph is None:
            return
        self.graph = look.graph
        for n in self.graph.nodes:
            self.nodes.setdefault(n.id, _fresh())
        for k in look.skipped:
            if self.nodes.get(k, {}).get("status") == "pending":
                self.nodes[k]["status"] = "skipped"

    def _rescued(self, a):
        """Has a failed with a failure path out of it (an arrow named "failed"), so the run goes on that way?"""
        return self.nodes[a]["status"] == "failed" and any(x.when.get(a) == FAILED for x in self.graph.nodes)

    def _dead(self, a, n):
        """Is the way from a into n closed: a was skipped, a is a branch that went another way, a failure path from a
        that did not fail, or an ordinary way from a that failed onto its failure path?"""
        sa = self.nodes[a]
        if sa["status"] == "skipped":
            return True
        name = n.when.get(a)
        if name == FAILED:
            return sa["status"] == "done"
        if self._rescued(a):
            return True
        return bool(name) and sa["status"] == "done" and (sa["answer"] or {}).get("branch") != name

    def _prune(self):
        """Skips every pending node all of whose ways in are closed, until none is left (GEN-23's branches)."""
        more = True
        while more:
            more = False
            for n in self.graph.nodes:
                if self.nodes[n.id]["status"] == "pending" and n.after and all(self._dead(a, n) for a in n.after):
                    self.nodes[n.id].update(status="skipped", ended=workflow.now().isoformat(), waiting_for="")
                    more = True

    def _ready(self, n):
        return all(self.nodes[a]["status"] in ("done", "skipped") or self._rescued(a) for a in n.after)

    async def _finish(self, inp, status, why):
        """The run's end: the finish activity does what the stack does at a task's end (a plan's: the Conductor's finish)."""
        await workflow.execute_activity("finish", {"ref": inp.ref, "task": inp.task, "status": status, "why": why},
                                        start_to_close_timeout=timedelta(minutes=5), retry_policy=_retry(), result_type=dict)
        return {"status": status, "why": why, "nodes": self.nodes}

    async def _node(self, inp, n):
        st = self.nodes[n.id]
        st.update(status="running" if n.block not in ("gate", "wait") else "waiting", started=st["started"] or workflow.now().isoformat())
        inputs = {a: self.nodes[a]["answer"] for a in n.after}
        if n.block in ("start", "end"):                # nothing to do: what started the run, or what it delivered
            answer = {"pass": True, "trigger": n.kind, "item": inp.task} if n.block == "start" else {"pass": True, "outcome": n.kind}
            st.update(status="done", ended=workflow.now().isoformat(), answer=answer, waiting_for="")
            return
        try:
            if n.block == "gate":
                answer = await self._gate(inp, n, n.role)
            elif n.block == "wait":
                answer = await self._wait(inp, n)
            else:
                answer = await self._work(inp, n, inputs)
        except (ActivityError, ChildWorkflowError) as e:
            st.update(status="failed", ended=workflow.now().isoformat(), error=TC.cut(str(e.cause or e), 300))   # cap: preview, the run's history has all
            return
        if answer.get("refused"):
            st.update(status="failed", ended=workflow.now().isoformat(), error=answer.get("why", "refused"))
            return
        if n.block == "branch" and answer.get("branch") not in n.branches:
            st.update(status="failed", ended=workflow.now().isoformat(), answer=answer,
                      error=f"the decision named no branch of {', '.join(n.branches)}: {TC.cut(str(answer.get('branch')), 80)}")   # cap: preview
            return
        if answer.get("pass") is False:            # a check that found problems: back to loop_to while rounds are left
            if n.loop_to and st["round"] < n.loop_max:
                st.update(status="done", ended=workflow.now().isoformat(), answer=answer, waiting_for="")
                self._loop_back(n, answer)
                return
            rounds = f" after {st['round']} rounds" if n.loop_to else ""
            st.update(status="failed", ended=workflow.now().isoformat(), answer=answer,
                      error=f"{answer.get('problems', 'its')} problems remain{rounds}")
            return
        st.update(status="skipped" if answer.get("skipped") else "done", ended=workflow.now().isoformat(), answer=answer, waiting_for="")

    def _loop_back(self, n, answer):
        """Sends the run back to n.loop_to: it and every node between it and n run again, with the answer as feedback."""
        back = {n.loop_to} | {x.id for x in self.graph.nodes if n.loop_to in _anc(self.graph, x.id) and x.id in _anc(self.graph, n.id) | {n.id}}
        rnd = self.nodes[n.id]["round"] + 1
        for k in back:
            self.nodes[k].update(status="pending", ended="", answer={}, error="", round=rnd)
        self.nodes[n.loop_to]["feedback"] = answer

    async def _work(self, inp, n, inputs):
        st = self.nodes[n.id]
        base = StepInput(task=inp.task, run=workflow.info().workflow_id, node=n, round=st["round"], inputs=inputs,
                         feedback=st.get("feedback") or {}, ref=inp.ref)
        items = n.items or (_items(self.nodes, n.each) if n.each else [])
        if n.block == "tracker" and not items and workflow.patched("tracker-write"):   # runs started before it kept the step activity
            return await workflow.execute_activity("tracker_write", {
                "tracker": (inp.ref or {}).get("tracker") or n.values.get("tracker", ""), "kind": n.kind, "key": inp.task,
                "write_id": f"{base.run}/{n.id}/r{st['round']}", "run": base.run, "node": n.id,
                "body": n.brief or n.title, "inputs": {k: (v or {}).get("ref", "") for k, v in inputs.items()}},
                start_to_close_timeout=timedelta(minutes=5), retry_policy=_retry(), result_type=dict)
        if not items and n.block != "change":
            return await _do(base, st)
        if not items:                              # a change: its own history
            return await workflow.execute_child_workflow(NodeRun.run, base, id=f"{base.run}/{n.id}/r{st['round']}")
        st["items"] = [{"item": i, "status": "pending"} for i in items]
        answers = []
        for start in range(0, len(items), CHILD_BATCH):
            batch = items[start:start + CHILD_BATCH]
            for k in range(start, start + len(batch)):
                st["items"][k]["status"] = "running"
            got = await asyncio.gather(*[workflow.execute_child_workflow(
                NodeRun.run, dataclasses.replace(base, item=i), id=f"{base.run}/{n.id}/r{st['round']}/{start + j}")
                for j, i in enumerate(batch)])
            for k, a in enumerate(got, start):
                st["items"][k]["status"] = "done"
            answers += got
        return {"items": answers, "pass": all(a.get("pass", True) is not False for a in answers),
                "problems": sum(int(a.get("problems", 0) or 0) for a in answers)}

    async def _gate(self, inp, n, role):
        st = self.nodes[n.id]
        st["waiting_for"] = f"the decision of {role}"
        asked = await workflow.execute_activity("decision", {"task": inp.task, "run": workflow.info().workflow_id, "node": n.id,
                                                             "role": role, "title": n.title}, start_to_close_timeout=timedelta(minutes=2),
                                                retry_policy=_retry(), result_type=dict)
        people = asked.get("people") or []                # GEN-27: who may decide (none named: anyone in the app, as before roles)
        st["people"] = people
        while True:
            await workflow.wait_condition(lambda: n.id in self.decisions)
            d = self.decisions.pop(n.id)
            if not people or d["who"] in people:
                break
            st.setdefault("refused", []).append({"who": d["who"], "answer": d["answer"], "at": workflow.now().isoformat()})
        if d["answer"] != "yes":
            return {"refused": True, "why": f"{role} said no ({d['who']})", "who": d["who"]}
        return {"pass": True, "who": d["who"]}

    async def _wait(self, inp, n):
        st = self.nodes[n.id]
        w = n.wait
        key = _key(inp, w["key"])
        st["waiting_for"] = f"{w['for']} on {key}"
        since = _when(st["started"])
        reminders = sorted(w.get("remind") or [])
        while key not in self.events and st["reminded"] < len(reminders):
            left = timedelta(seconds=reminders[st["reminded"]]) - (workflow.now() - since)
            if left.total_seconds() > 0 and await _arrived(self, key, left):
                break
            await workflow.execute_activity("remind", {"task": inp.task, "node": n.id, "key": key, "for": w["for"],
                                                       "number": st["reminded"] + 1},
                                            start_to_close_timeout=timedelta(minutes=2), retry_policy=_retry(), result_type=dict)
            st["reminded"] += 1
        if key not in self.events:
            left = timedelta(seconds=w["timeout"]) - (workflow.now() - since)
            if left.total_seconds() <= 0 or not await _arrived(self, key, left):
                st["waiting_for"] = f"{w['then']}: {w['for']} did not answer on {key}"
                answer = await self._gate(inp, n, w["then"])
                return {**answer, "timed_out": True}
        ev = self.events[key].pop(0)
        if not self.events[key]:
            del self.events[key]
        if workflow.now() - since >= LONG_WAIT:
            self.long_wait_ended = True
        return {"pass": True, "event": ev}


async def _arrived(run, key, left):
    try:
        await workflow.wait_condition(lambda: key in run.events, timeout=left)
        return True
    except asyncio.TimeoutError:
        return False


def _key(inp, spec):
    """A wait's key: "item" is the run's own item (inp.task), anything else is taken as written."""
    return inp.task if spec == "item" else spec


def _items(nodes, each):
    nid, _, field = each.partition(".")
    got = (nodes.get(nid) or {}).get("answer", {}).get(field or "items") or []
    return [str(x) for x in got]


def _anc(g, nid):
    seen, todo = set(), list(g.node(nid).after)
    while todo:
        a = todo.pop()
        if a not in seen:
            seen.add(a)
            todo.extend(g.node(a).after)
    return seen


def _when(iso):
    from datetime import datetime
    return datetime.fromisoformat(iso)

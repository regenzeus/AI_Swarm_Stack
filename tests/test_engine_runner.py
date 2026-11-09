"""The graph runner (GEN-23, GEN-24, GEN-37, GEN-38, docs/AI-STACK-PLAN.md WP4): the toy template run end to end on
Temporal's test server, with the clock in the test's hand: gates wait for their role, a wait wakes only on its own key,
reminders and the timeout come on time, a check loops back, a fan-out runs as children, the run survives a new worker,
keeps every block's timing, and replays against the code."""
import asyncio
import contextlib
import os
from datetime import timedelta

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowExecutionStatus
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

with workflow.unsafe.imports_passed_through():
    from engine import graph as G
    from engine import runner as R

TOY = """template: toy/bug
budget: {days: 60}
nodes:
  arrives: {block: start, title: A ticket arrives, kind: item}
  intake: {block: agent, title: Read the item, agent: 'toy:intake'}
  reply: {block: wait, title: Wait for the requester, for: requester, key: item, remind: [3d, 7d], timeout: 21d, then: triager}
  spec: {block: agent, title: Write the criteria, agent: 'toy:analyst'}
  approve: {block: gate, title: Approve the spec, role: spec-approver}
  implement: {block: change, title: Implement, values: {base: item.version}}
  regress: {block: command, title: Regression, kind: toy.regress, each: spec.items}
  classify: {block: agent, title: Check regressions, agent: 'toy:classifier', loop: {to: implement, max: 3}}
  fixed: {block: end, title: Fixed, kind: done}
edges:
  - [arrives, intake]
  - [intake, reply]
  - [reply, spec]
  - [spec, approve]
  - [approve, implement]
  - [implement, regress]
  - [regress, classify]
  - [classify, fixed]
"""


class Fake:
    """The activities, as the test wants them: what each step answers, and what reached the queue and the requester."""

    def __init__(self, items=5, fail_rounds=0, text=None, branch="", people=None, fail=()):
        self.items, self.fail_rounds, self.text, self.branch, self.people, self.fail = items, fail_rounds, text or TOY, branch, people or {}, set(fail)
        self.calls, self.decisions, self.reminders, self.finished = [], [], [], []

    def acts(self):
        @activity.defn(name="load_graph")
        async def load_graph(ref: dict) -> G.Graph:
            return G.load(self.text, source=ref.get("commit", ""))

        @activity.defn(name="step")
        async def step(inp: R.StepInput) -> dict:
            self.calls.append((inp.node.id, inp.item, inp.round))
            if inp.node.id in self.fail:
                raise ApplicationError(f"{inp.node.id} broke", non_retryable=True)
            if inp.node.block == "branch":
                return {"ref": "artifact:route", "pass": True, "branch": self.branch}
            if inp.node.id == "spec":
                return {"ref": "artifact:spec", "items": [f"case-{i}" for i in range(self.items)], "pass": True}
            if inp.node.id == "classify":
                return {"ref": "artifact:verdict", "pass": inp.round >= self.fail_rounds, "problems": 0 if inp.round >= self.fail_rounds else 2}
            return {"ref": f"artifact:{inp.node.id}", "pass": True}

        @activity.defn(name="command")
        async def command(d: dict) -> dict:
            self.calls.append((d["node"], d.get("item", ""), d.get("round", 0)))
            return {"ref": f"job:{d['place']}/{d['node']}", "pass": True}

        @activity.defn(name="decision")
        async def decision(d: dict) -> dict:
            self.decisions.append((d["node"], d["role"]))
            return {"queued": True, "people": self.people.get(d["role"], [])}

        @activity.defn(name="remind")
        async def remind(d: dict) -> dict:
            self.reminders.append(d["number"])
            return {"sent": True}

        @activity.defn(name="finish")
        async def finish(d: dict) -> dict:
            self.finished.append(d["status"])
            return {"finished": True}
        return [load_graph, step, command, decision, remind, finish]


def env():
    return WorkflowEnvironment.start_time_skipping(download_dest_dir=os.environ.get("TEMPORAL_DOWNLOAD_DIR"))


@contextlib.asynccontextmanager
async def worker(e, fake, cache=True):
    """The engine's two queues, as the runner serves them. cache=False: no run stays in memory, so every step rebuilds
    the run from its history, as after a restart."""
    kw = {} if cache else {"max_cached_workflows": 0}
    async with Worker(e.client, task_queue=R.QUEUE, workflows=[R.GraphRun, R.NodeRun], activities=fake.acts(), **kw), \
            Worker(e.client, task_queue=R.STEP_QUEUE, activities=fake.acts()),             Worker(e.client, task_queue="place-wsl", activities=fake.acts()):
        yield


async def until(cond, e, limit=150):
    """Polls in real time (0.2 s, up to 30 s): reaching a state needs no clock; the tests move the clock on purpose."""
    for _ in range(limit):
        if await cond():
            return True
        await asyncio.sleep(0.2)
    return False


async def nodes(h):
    return (await h.query(R.GraphRun.state))["nodes"]


async def start(e, item="T-1", first=False):
    """Starts the run for an item. The handle follows the run by its id (a run that continues as new keeps it, GEN-38);
    first=True also returns the first run's own handle."""
    h = await e.client.start_workflow(R.GraphRun.run, R.RunInput(task=item, ref={"kind": "template", "name": "toy/bug", "commit": "abc"}),
                                      id=f"toy/bug:{item}", task_queue=R.QUEUE)
    latest = e.client.get_workflow_handle(f"toy/bug:{item}")
    return (latest, e.client.get_workflow_handle(f"toy/bug:{item}", run_id=h.first_execution_run_id)) if first else latest


def test_a_template_runs_to_the_end_through_its_wait_its_gate_its_fan_out_and_its_loop():
    fake = Fake(items=5, fail_rounds=2)

    async def go():
        async with await env() as e, worker(e, fake):
            h = await start(e)
            assert await until(lambda: _status(h, "reply", "waiting"), e)
            await h.signal(R.GraphRun.event, args=["T-2", {"ref": "comment:9"}])          # another item's reply: not ours
            await e.sleep(timedelta(hours=1))
            assert (await nodes(h))["reply"]["status"] == "waiting"
            await h.signal(R.GraphRun.event, args=["T-1", {"ref": "comment:10"}])
            assert await until(lambda: _status(h, "approve", "waiting"), e)
            await h.signal(R.GraphRun.decide, args=["approve", "yes", "owner"])
            out = await h.result()
            assert out["status"] == "done", out
            st = out["nodes"]
            assert st["classify"]["round"] == 2 and [c for c in fake.calls if c[0] == "implement"] == [("implement", "", 0), ("implement", "", 1), ("implement", "", 2)]
            assert len(st["regress"]["items"]) == 5 and all(i["status"] == "done" for i in st["regress"]["items"])
            assert fake.decisions == [("approve", "spec-approver")] and st["approve"]["answer"]["who"] == "owner"
            assert all(st[k]["started"] and st[k]["ended"] for k in st)                       # every block's timing, for the canvas
            assert st["reply"]["answer"]["event"] == {"ref": "comment:10"}
    asyncio.run(go())


def test_reminders_come_on_time_and_a_timeout_asks_the_role_named_for_it():
    fake = Fake()

    async def go():
        async with await env() as e:
            with e.auto_time_skipping_disabled():
                async with worker(e, fake):
                    h = await start(e, "T-3")
                    assert await until(lambda: _status(h, "reply", "waiting"), e)
                    await e.sleep(timedelta(days=2, hours=23))
                    assert fake.reminders == []
                    await e.sleep(timedelta(hours=2))
                    assert fake.reminders == [1]                                          # day 3
                    await e.sleep(timedelta(days=4))
                    assert fake.reminders == [1, 2]                                       # day 7
                    await e.sleep(timedelta(days=14, hours=1))
                    assert ("reply", "triager") in fake.decisions                         # day 21: the triager is asked
                    assert "triager" in (await nodes(h))["reply"]["waiting_for"]
    asyncio.run(go())


def test_a_check_that_still_fails_after_its_rounds_fails_the_run_with_the_reason():
    fake = Fake(items=1, fail_rounds=99)

    async def go():
        async with await env() as e, worker(e, fake):
            h = await start(e, "T-4")
            assert await until(lambda: _status(h, "reply", "waiting"), e)
            await h.signal(R.GraphRun.event, args=["T-4", {}])
            assert await until(lambda: _status(h, "approve", "waiting"), e)
            await h.signal(R.GraphRun.decide, args=["approve", "yes", "owner"])
            out = await h.result()
            assert out["status"] == "failed" and "problems remain after 3 rounds" in out["why"]
    asyncio.run(go())


def test_a_gate_answered_no_fails_the_run_and_says_who():
    fake = Fake()

    async def go():
        async with await env() as e, worker(e, fake):
            h = await start(e, "T-5")
            assert await until(lambda: _status(h, "reply", "waiting"), e)
            await h.signal(R.GraphRun.event, args=["T-5", {}])
            assert await until(lambda: _status(h, "approve", "waiting"), e)
            await h.signal(R.GraphRun.decide, args=["approve", "no", "owner"])
            out = await h.result()
            assert out["status"] == "failed" and "spec-approver said no (owner)" in out["why"]
    asyncio.run(go())


def test_the_run_is_rebuilt_from_its_history_at_every_step_as_after_a_restart_and_a_cancel_ends_it():
    fake = Fake()

    async def go():
        async with await env() as e, worker(e, fake, cache=False):                       # nothing kept in memory
            h = await start(e, "T-6")
            assert await until(lambda: _status(h, "reply", "waiting"), e)
            await h.signal(R.GraphRun.event, args=["T-6", {}])
            assert await until(lambda: _status(h, "approve", "waiting"), e)
            assert (await nodes(h))["spec"]["answer"]["items"] == [f"case-{i}" for i in range(5)]   # rebuilt, not remembered
            await h.signal(R.GraphRun.cancel, "the owner stopped it")
            out = await h.result()
            assert out["status"] == "cancelled" and out["why"] == "the owner stopped it"
    asyncio.run(go())


def test_a_long_wait_continues_the_run_as_new_and_signals_still_find_it_and_it_replays():
    fake = Fake(items=3)

    async def go():
        async with await env() as e, worker(e, fake):
            h, first = await start(e, "T-7", first=True)
            assert await until(lambda: _status(h, "reply", "waiting"), e)
            await e.sleep(timedelta(days=2))
            await h.signal(R.GraphRun.event, args=["T-7", {}])                            # ends a wait of 2 days: continue as new
            assert await until(lambda: _status(h, "approve", "waiting"), e)
            assert (await first.describe()).status == WorkflowExecutionStatus.CONTINUED_AS_NEW
            await e.client.get_workflow_handle("toy/bug:T-7").signal(R.GraphRun.decide, args=["approve", "yes", "owner"])
            out = await e.client.get_workflow_handle("toy/bug:T-7").result()
            assert out["status"] == "done" and out["nodes"]["intake"]["status"] == "done"   # the state came across
            histories = [await first.fetch_history(), await e.client.get_workflow_handle("toy/bug:T-7").fetch_history()]
            events = sum(len(x.events) for x in histories)
            assert events < 5120, events                                                    # a tenth of the history limit
            for hist in histories:                                                         # the code replays what it wrote
                await Replayer(workflows=[R.GraphRun, R.NodeRun]).replay_workflow(hist)
    asyncio.run(go())


async def _status(h, node, status):
    try:
        return (await nodes(h))[node]["status"] == status
    except Exception:                       # the run is starting, or continuing as new: not yet
        return False


@pytest.mark.skipif(not os.environ.get("ENGINE_LOAD"), reason="ENGINE_LOAD=1 runs the 300-item fan-out")
def test_a_fan_out_of_300_items_stays_small_in_the_parents_history():
    fake = Fake(items=300)

    async def go():
        async with await env() as e, worker(e, fake):
            h = await start(e, "T-8")
            assert await until(lambda: _status(h, "reply", "waiting"), e)
            await h.signal(R.GraphRun.event, args=["T-8", {}])
            assert await until(lambda: _status(h, "approve", "waiting"), e)
            await h.signal(R.GraphRun.decide, args=["approve", "yes", "owner"])
            assert (await h.result())["status"] == "done"
            assert len((await h.fetch_history()).events) < 5120
    asyncio.run(go())


TRIAGE = """template: toy/triage
nodes:
  begin: {block: start, title: Start, kind: hand}
  read: {block: agent, title: Read the request, agent: 'toy:a'}
  route: {block: branch, title: Decide what it is, agent: 'toy:a'}
  fix: {block: change, title: Fix it}
  plan: {block: agent, title: Plan it, agent: 'toy:a'}
  tell: {block: agent, title: Tell the requester, agent: 'toy:a'}
  close: {block: agent, title: Close it, agent: 'toy:a'}
  done: {block: end, title: Done, kind: done}
edges:
  - [begin, read]
  - [read, route]
  - [route, fix, bug]
  - [route, plan, feature]
  - [plan, tell]
  - [fix, close]
  - [tell, close]
  - [close, done]
"""


def test_a_branch_takes_the_way_its_agent_names_skips_the_others_and_the_join_after_still_runs():
    fake = Fake(text=TRIAGE, branch="feature")

    async def go():
        async with await env() as e, worker(e, fake):
            out = await (await start(e, "T-20")).result()
            st = out["nodes"]
            assert out["status"] == "done", out
            assert st["route"]["answer"]["branch"] == "feature"
            assert [st[k]["status"] for k in ("plan", "tell", "fix", "close")] == ["done", "done", "skipped", "done"]
            assert "fix" not in [c[0] for c in fake.calls]                 # the way not taken never ran
    asyncio.run(go())


def test_a_branch_answer_that_names_no_branch_fails_the_run_with_the_branches_it_has():
    fake = Fake(text=TRIAGE, branch="maybe")

    async def go():
        async with await env() as e, worker(e, fake):
            out = await (await start(e, "T-21")).result()
            assert out["status"] == "failed" and "named no branch of bug, feature: maybe" in out["why"], out
    asyncio.run(go())


TWO_GATES = """template: toy/two-gates
nodes:
  begin: {block: start, title: Start, kind: hand}
  draft: {block: agent, title: Draft it, agent: 'toy:a'}
  legal: {block: gate, title: Legal looks, role: legal}
  release: {block: gate, title: Release it, role: release-manager}
  done: {block: end, title: Done, kind: done}
edges:
  - [begin, draft]
  - [draft, legal]
  - [legal, release]
  - [release, done]
"""


def test_two_gates_wait_for_their_own_roles_and_an_answer_from_outside_a_role_is_refused_and_recorded():
    fake = Fake(text=TWO_GATES, people={"legal": ["lena"], "release-manager": ["rob", "owner"]})

    async def go():
        async with await env() as e, worker(e, fake):
            h = await start(e, "T-30")
            assert await until(lambda: _status(h, "legal", "waiting"), e)
            await h.signal(R.GraphRun.decide, args=["legal", "yes", "rob"])                # not legal's: refused, still waiting
            assert await until(lambda: _refused(h, "legal", 1), e)
            st = (await nodes(h))["legal"]
            assert st["status"] == "waiting" and st["people"] == ["lena"] and st["refused"][0]["who"] == "rob"
            await h.signal(R.GraphRun.decide, args=["legal", "yes", "lena"])
            assert await until(lambda: _status(h, "release", "waiting"), e)
            await h.signal(R.GraphRun.decide, args=["release", "yes", "owner"])
            out = await h.result()
            assert out["status"] == "done" and out["nodes"]["legal"]["answer"]["who"] == "lena" and out["nodes"]["release"]["answer"]["who"] == "owner"
            assert fake.decisions == [("legal", "legal"), ("release", "release-manager")]
    asyncio.run(go())


async def _refused(h, node, n):
    return len((await nodes(h))[node].get("refused") or []) >= n


ENDED = """template: toy/ended
nodes:
  go: {block: start, title: By hand, kind: hand}
  work: {block: agent, title: Do it, agent: 'toy:a'}
  tell: {block: notify, title: Tell me it failed, brief: The work failed, role: owner}
  done: {block: end, title: Done, kind: done}
  given-up: {block: end, title: Given up, kind: stopped}
edges:
  - [go, work]
  - [work, tell, failed]
  - [work, done]
  - [tell, given-up]
"""


def test_a_failed_block_with_a_failure_path_goes_down_it_and_the_run_ends_as_stopped_not_failed():
    fake = Fake(text=ENDED, fail={"work"})

    async def go():
        async with await env() as e, worker(e, fake):
            out = await (await start(e, "T-40")).result()
            st = out["nodes"]
            assert out["status"] == "stopped" and out["why"] == "ended at Given up", out
            assert [st[k]["status"] for k in ("go", "work", "tell", "done", "given-up")] == ["done", "failed", "done", "skipped", "done"]
            assert st["go"]["answer"] == {"pass": True, "trigger": "hand", "item": "T-40"} and "work broke" in st["work"]["error"]
    asyncio.run(go())


def test_a_block_that_succeeds_closes_its_failure_path_and_the_run_ends_done():
    fake = Fake(text=ENDED)

    async def go():
        async with await env() as e, worker(e, fake):
            out = await (await start(e, "T-41")).result()
            st = out["nodes"]
            assert out["status"] == "done" and out["why"] == "ended at Done", out
            assert [st[k]["status"] for k in ("work", "tell", "done", "given-up")] == ["done", "skipped", "done", "skipped"]
            assert "tell" not in [c[0] for c in fake.calls]
    asyncio.run(go())

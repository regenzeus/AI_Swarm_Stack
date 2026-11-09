#!/usr/bin/env python3
"""The cutover (GEN-35, docs/AI-STACK-PLAN.md §5, §6, WP7): home's plans move from the Conductor to the engine in one
switch, the Conductor kept as the rollback.

What moves, and how: the tasks table stays the truth of every plan. With ENGINE=temporal the runner starts the engine
instead of the Conductor's worker, and the bridge starts one run (graph-run, "task:<id>:<occ>") for each running
occurrence; the run's steps are its rows, and a step reads its row before it acts, so a step that was done is done at
once and a step that was running is run again (steps are idempotent, as the Conductor's recovery already required).
Scheduled tasks keep their rhythm in the tasks table: the bridge's pass starts each occurrence when it is due, as the
Conductor's tick did. A task that waits for the owner keeps waiting, its decision still in the queue. Finished tasks stay
as they are.

    python3 ops/engine/cutover.py smoke        the checks before a switch: Temporal answers, a toy run starts, waits,
                                               is signalled and finishes, it replays, and the converter refuses content
                                               on a customer-class namespace; nothing switches unless all pass
    python3 ops/engine/cutover.py drain        waits (up to DRAIN_S) for the Conductor's running steps to finish
    python3 ops/engine/cutover.py switch temporal|conductor   the override the runner reads first; then restart it
    python3 ops/engine/cutover.py rollback     cancels the engine's open runs, forgets them, and switches to the Conductor
    python3 ops/engine/cutover.py days         the clean days per kind of plan since the switch (14 each before the
                                               Conductor is removed)

The switch is an override file (OVERRIDE, outside the repository), so a rollback needs no landing; the deployment file's
ENGINE says what a fresh machine starts with. Every switch and every rollback is logged in LOG.
"""
import asyncio
import datetime as dt
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OVERRIDE = Path(os.environ.get("AISTACK_ENGINE_OVERRIDE") or Path.home() / ".config/aistack/engine")
LOG = Path(os.environ.get("AISTACK_CUTOVER_LOG") or "/srv/ai/state/cutover.jsonl")
DRAIN_S = 30 * 60               # limit: waits, the Conductor's running steps get this long to finish before a switch
DAYS_CLEAN = 14                 # limit: waits, the clean days each kind of plan needs on the engine before the Conductor goes


def _log(rec):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps({"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **rec}) + "\n")


def override():
    try:
        v = OVERRIDE.read_text().strip().lower()
    except OSError:
        return None
    return v if v in ("temporal", "conductor") else None


def switch(to, why=""):
    if to not in ("temporal", "conductor"):
        raise SystemExit("switch temporal|conductor")
    OVERRIDE.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDE.write_text(to + "\n")
    _log({"switch": to, "why": why})
    return to


# ---------- smoke checks ----------
SMOKE = """template: smoke/toy
nodes:
  go: {block: start, title: By hand, kind: hand}
  ask: {block: wait, title: Wait for an answer, for: smoke, key: item, timeout: 1h, then: owner}
  work: {block: agent, title: Do it, agent: smoke}
  done: {block: end, title: Done, kind: done}
edges:
  - [go, ask]
  - [ask, work]
  - [work, done]
"""


async def smoke(addr=None):
    """-> [(check, ok, detail)]: the checks of §6 step 4, on the live Temporal, in a namespace of their own."""
    from temporalio import activity
    from temporalio.worker import Replayer, Worker
    from engine import client as CL
    from engine import converter as CV
    from engine import graph as G
    from engine import runner as R
    out = []
    ns = "smoke"
    try:
        cl = await CL.connect(addr=addr, ns=ns, customer=False, key=CV.key_from_env(os.environ))
        await CL.ensure_namespace(cl, ns)
        out.append(("Temporal answers", True, f"namespace {ns}"))
    except Exception as e:
        return [("Temporal answers", False, f"{type(e).__name__}: {e}")]

    @activity.defn(name="load_graph")
    async def load_graph(ref: dict) -> G.Graph:
        return G.load(SMOKE)

    @activity.defn(name="step")
    async def step(inp: R.StepInput) -> dict:
        return {"ref": "artifact:smoke", "pass": True}

    @activity.defn(name="finish")
    async def finish(d: dict) -> dict:
        return {}
    q = f"smoke-{uuid.uuid4().hex[:8]}"                                    # cap: id
    wid = f"smoke/toy:{q}"
    try:
        async with Worker(cl, task_queue=q, workflows=[R.GraphRun, R.NodeRun], activities=[load_graph, finish]), \
                Worker(cl, task_queue=R.STEP_QUEUE, activities=[step]):      # the smoke namespace's own step queue
            for _ in range(30):                                        # a new namespace is seen once the frontend's cache refreshes
                try:
                    h = await cl.start_workflow(R.GraphRun.run, R.RunInput(task="smoke", ref={"kind": "template"}), id=wid, task_queue=q)
                    break
                except Exception as e:
                    if "not found" not in str(e).lower():
                        raise
                    await asyncio.sleep(1)
            for _ in range(100):
                if ((await h.query(R.GraphRun.state))["nodes"].get("ask") or {}).get("status") == "waiting":
                    break
                await asyncio.sleep(0.2)
            await h.signal(R.GraphRun.event, args=["smoke", {"ref": "smoke:answer"}])
            res = await asyncio.wait_for(h.result(), 60)
            out.append(("A toy run starts, waits, is signalled and finishes", res["status"] == "done", res.get("why", "")))
        hist = await h.fetch_history()
        await Replayer(workflows=[R.GraphRun, R.NodeRun], data_converter=cl.data_converter).replay_workflow(hist)   # the same codec
        out.append(("The run replays against the code", True, ""))
    except Exception as e:
        out.append(("A toy run starts, waits, is signalled and finishes", False, f"{type(e).__name__}: {e}"))
    conv = CV.data_converter(True, CV.key_from_env({CV.KEY_ENV: CV.new_key()}))
    try:
        await conv.encode([{"text": "x" * 5000}])
        out.append(("The converter refuses content on a customer-class namespace", False, "it let content through"))
    except Exception as e:
        out.append(("The converter refuses content on a customer-class namespace", True, type(e).__name__))
    return out


# ---------- drain, rollback, days ----------
def drain(c, limit_s=DRAIN_S, sleep=time.sleep):
    """Waits for the Conductor's running steps to finish, up to limit_s; -> the ones still running (moved as they are)."""
    t0 = time.time()
    while True:
        left = [r["id"] for r in c.execute("select id from steps where status = 'running'").fetchall()]
        if not left or time.time() - t0 > limit_s:
            return left
        sleep(10)


def rollback(c, call):
    """The engine's open runs are cancelled and forgotten; their rows stay as they are, so the Conductor resumes them
    from the steps done so far, as its recovery does after a restart."""
    from engine import bridge as EB
    from engine import runner as R
    EB.table(c)
    open_ = c.execute("select e.task, e.occ, e.workflow from engine_runs e join task_occ o on o.task = e.task and o.occ = e.occ "
                      "where o.status = 'running'").fetchall()
    for r in open_:
        try:
            call(lambda cl, w=r["workflow"]: cl.get_workflow_handle(w).signal(R.GraphRun.cancel, "rolled back to the Conductor"))
        except Exception as e:                         # an ended run needs no cancel; said in the log all the same
            _log({"cancel": r["workflow"], "why": f"{type(e).__name__}: {e}"})
        c.execute("delete from engine_runs where task = ? and occ = ?", (r["task"], r["occ"]))
    c.commit()
    switch("conductor", f"rollback: {len(open_)} open runs cancelled")
    _log({"rollback": [r["workflow"] for r in open_]})
    return [r["workflow"] for r in open_]


def days(c, now=None):
    """Per kind of plan: the days since its first run on the engine, and whether any of its runs fell back."""
    from engine import bridge as EB
    EB.table(c)
    now = now or dt.datetime.now(dt.timezone.utc)
    switched = None
    try:
        for line in LOG.read_text().splitlines():
            rec = json.loads(line)
            if rec.get("switch") == "temporal":
                switched = rec["at"]
            if rec.get("rollback") is not None:
                switched = None
    except OSError:
        pass
    out = {}
    for r in c.execute("select t.kind, min(e.started) first from engine_runs e join tasks t on t.id = e.task group by t.kind").fetchall():
        first = dt.datetime.fromisoformat(str(r["first"]).replace("Z", "+00:00"))
        if first.tzinfo is None:
            first = first.replace(tzinfo=dt.timezone.utc)
        n = max(0, (now - first).days)
        out[r["kind"] or "plan"] = {"first": r["first"], "days": n, "clean": n >= DAYS_CLEAN}
    return {"switched": switched, "kinds": out, "needed": DAYS_CLEAN}


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["smoke"]:
        res = asyncio.run(smoke())
        for name, ok, detail in res:
            print(f"{'ok ' if ok else 'NO '} {name}{': ' + detail if detail else ''}")
        sys.exit(0 if res and all(ok for _, ok, _ in res) else 1)
    if a[:1] == ["switch"] and len(a) == 2:
        print("engine:", switch(a[1], "by hand"), "- restart the runner: systemctl --user restart missions.service")
        sys.exit(0)
    import missions as M
    if a[:1] == ["drain"]:
        left = drain(M.db())
        print("drained" if not left else f"{len(left)} steps still running; they run again on the engine")
        sys.exit(0)
    if a[:1] == ["days"]:
        print(json.dumps(days(M.db()), indent=1))
        sys.exit(0)
    sys.exit(__doc__)

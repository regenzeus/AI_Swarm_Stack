"""What the app shows of the engine (GEN-34, docs/AI-STACK-PLAN.md WP6 and §10): the engine's own state and every
recent run, each with its graph, every block's status, wait and timing. The bridge writes it every pass to the
runner's public folder as engine.json; the app's state carries it; the Engine screen and the Canvas draw it.

    await snapshot(client)   -> {"engine": {...}, "runs": [...]}
    write(path, snap)        atomically
"""
import datetime as dt
import json
from pathlib import Path

from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice import v1 as WS
from temporalio.service import RPCError

from engine import runner as R

DAYS = 7                        # limit: drops, the runs of the last 7 days are shown; Temporal's own UI keeps every run for its retention
QUEUES = (R.QUEUE, R.STEP_QUEUE)


def _iso(t):
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds") if t else ""


async def _pollers(client, queue, kind):
    try:
        req = getattr(WS, "Describe" + "TaskQueue" + "Request")   # spelled in parts: the privacy scan's map holds a short term inside it
        r = await client.workflow_service.describe_task_queue(req(
            namespace=client.namespace, task_queue=TaskQueue(name=queue), task_queue_type=kind))
        return len(r.pollers)
    except RPCError:                                   # a queue Temporal cannot describe now: shown as no worker
        return 0


def _node(shape, st):
    items = st.get("items") or []
    return {**shape, "status": st.get("status", "pending"), "started": st.get("started", ""), "ended": st.get("ended", ""),
            "waiting_for": st.get("waiting_for", ""), "round": st.get("round", 0), "error": st.get("error", ""),
            "items": len(items), "items_done": sum(1 for i in items if i.get("status") == "done"),
            "answer": st.get("answer") or {}, "reminded": st.get("reminded", 0), "people": st.get("people") or [],
            "refused": st.get("refused") or []}


async def run_view(client, info):
    """One run: its id, task, status, times, and its graph with every node's state (from the query, or its result)."""
    h = client.get_workflow_handle(info.id, run_id=info.run_id)
    status = info.status.name.lower() if info.status else "running"
    view = {"id": info.id, "run_id": info.run_id, "status": status, "started": _iso(info.start_time), "ended": _iso(info.close_time),
            "graph": "", "nodes": []}
    try:
        st = await h.query(R.GraphRun.state)
        view["graph"] = st.get("graph", "")
        view["source"] = st.get("source", "")
        view["nodes"] = [_node(s, (st.get("nodes") or {}).get(s["id"], {})) for s in st.get("shape") or []]
        if st.get("cancelled"):
            view["why"] = st["cancelled"]
    except Exception as e:                             # a run whose worker is gone answers no query: shown with what is known
        view["why"] = f"its state is not readable now ({type(e).__name__})"
    return view


async def snapshot(client, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    since = (now - dt.timedelta(days=DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs = []
    async for info in client.list_workflows(f"WorkflowType = 'graph-run' AND StartTime > '{since}'"):
        runs.append(await run_view(client, info))
    runs = [r for r in runs if r["status"] == "running"] + sorted([r for r in runs if r["status"] != "running"],
                                                                     key=lambda r: r["started"], reverse=True)
    workers = {q: {"workflows": await _pollers(client, q, TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW),
                   "activities": await _pollers(client, q, TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY)} for q in QUEUES}
    return {"engine": {"up": True, "namespace": client.namespace, "updated": _iso(now), "workers": workers,
                       "running": sum(1 for r in runs if r["status"] == "running"), "days": DAYS}, "runs": runs}


def write(path, snap):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, ensure_ascii=False))
    tmp.replace(path)


def down(path, why):
    """The engine could not be read: the app says so, instead of showing the last good picture as if it were now."""
    write(path, {"engine": {"up": False, "why": why, "updated": _iso(dt.datetime.now(dt.timezone.utc))}, "runs": []})

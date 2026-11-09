"""The bridge between the app and the engine (GEN-35, docs/AI-STACK-PLAN.md WP6).

Everything that starts a plan run stays as it is: tasks.py and changes.py call CD.start, which makes the run's rows,
and CD.tick_starts starts a scheduled task when it is due and a task's next run for the oldest event waiting for it.
What moves is the running of the steps: with ENGINE=temporal, the bridge sees each running occurrence and starts its
workflow (graph-run, id "task:<id>:<run>") once, and the engine runs it. A cancel (CD.cancel) also tells the workflow.

    on()                  is ENGINE=temporal set for this deployment (default: the Conductor, until the cutover)
    sync(c, call)         one pass: start the workflow of every running occurrence that has none
    start(M)              in the host runner: the engine thread and the bridge's pass every 5 s, instead of CD.worker
"""
import os
import threading

import conductor as CD
import deployment as DEPLOY

PASS_S = 5                                         # limit: paces, the bridge looks for runs to start every 5 s (as the Conductor's tick)


def on(env=os.environ):
    """The cutover's override (ops/engine/cutover.py switch) first, then ENGINE, then the deployment's file."""
    from engine import cutover as CO
    value = CO.override() or env.get("ENGINE") or DEPLOY.load(env=env).get("ENGINE") or "conductor"
    return value.strip().lower() == "temporal"


def table(c):
    c.execute("create table if not exists engine_runs (task integer, occ integer, workflow text, started text, primary key (task, occ))")


def workflow_id(task, occ):
    return f"task:{task}:{occ}"


def sync(c, call):
    """Starts the workflow of each running occurrence that has none. call(fn) runs fn(client) on the engine's loop."""
    from engine import runner as R
    from temporalio.exceptions import WorkflowAlreadyStartedError
    table(c)
    started = []
    for r in c.execute("select o.task, o.occ from task_occ o join tasks t on t.id = o.task where o.status = 'running' and t.door = 'plan' "
                       "and not exists (select 1 from engine_runs e where e.task = o.task and e.occ = o.occ)").fetchall():
        task, occ = r["task"], r["occ"]
        wid = workflow_id(task, occ)
        inp = R.RunInput(task=str(task), ref={"kind": "plan", "task": task, "occ": occ})
        try:
            call(lambda cl, inp=inp, wid=wid: cl.start_workflow(R.GraphRun.run, inp, id=wid, task_queue=R.QUEUE))
        except WorkflowAlreadyStartedError:
            pass                                    # it runs already (a restart between the start and the record)
        c.execute("insert or ignore into engine_runs (task, occ, workflow, started) values (?,?,?,?)", (task, occ, wid, CD.now()))
        c.commit()
        started.append(wid)
    return started


def cancel_hook(call):
    """CD.cancel's hook: the run's workflow ends too (its steps already stopped in the rows)."""
    from engine import runner as R

    def hook(c, t, occ):
        call(lambda cl: cl.get_workflow_handle(workflow_id(t["id"], occ)).signal(R.GraphRun.cancel, "cancelled by the owner"))
    return hook


ENGINE = None                                       # the running engine, once start() made it


def decide(req):
    """The app's Approve or Refuse on a gate (engine_decide): the run's gate hears it as the signal decide. Until
    sign-in exists every answer in the app is the owner's. The run itself checks the role (GEN-27): an answer from
    outside it is refused and recorded there, so the app says so too."""
    if ENGINE is None:
        return {"ok": False, "error": "the engine does not run on this deployment (ENGINE=conductor)"}
    from engine import runner as R
    answer = "yes" if req.get("answer") == "yes" else "no"
    from engine import roles as RL
    who = req.get("who") or "owner"
    ENGINE.call(lambda cl: cl.get_workflow_handle(str(req["run"])).signal(R.GraphRun.decide, args=[str(req["node"]), answer, who]))
    if req.get("role") and not RL.may(req["role"], who):
        return {"ok": False, "error": f"{who} is not one of {req['role']}'s people ({', '.join(RL.people(req['role']))}): the run recorded the refusal"}
    return {"ok": True, "answer": answer}


def start(M):
    """In the host runner, when on(): the engine thread with the graph runner and the activities, and the bridge's pass."""
    from engine import activities as A
    from engine import runner as R
    from engine import worker as EW
    from engine import places as PL
    eng = EW.Engine(workflows=[R.GraphRun, R.NodeRun], activities=A.ALL, queues=PL.queues({R.QUEUE: 4, R.STEP_QUEUE: CD.SLOTS})).start()
    threading.Thread(target=PL.worker_loop, args=(M.stop,), daemon=True, name="place-wsl").start()   # the wsl place's worker (GEN-22)
    global ENGINE
    ENGINE = eng
    CD.ON_CANCEL.append(cancel_hook(eng.call))

    from engine import projector as P
    from engine import forgework as FW
    from engine import packs as PK
    from engine import templates as T
    from engine import trackers as TR
    shown = M.PUBLIC / "engine.json"                 # the app's state carries it (server.py), the Engine screen draws it

    def loop():
        c = M.db()
        CD.table(c)
        while not M.stop.is_set():
            try:
                with CD.lock:
                    CD.tick_starts(c)
                    sync(c, eng.call)
            except Exception as e:                  # the next pass tries again; it is logged
                M.log(f"engine bridge: {type(e).__name__}: {e}")
            try:
                snap = eng.call(P.snapshot)
                loaded = PK.load()                                               # the deployment's packs (GEN-21)
                try:                                                             # the trackers and the pull requests (GEN-25, GEN-26)
                    eng.call(lambda cl: TR.poll(cl, start=TR.starter(loaded["packs"])))
                    import forge as FG
                    eng.call(lambda cl: FW.poll_prs(cl, FG.FORGE))
                except Exception as e:
                    M.log(f"engine: trackers: {type(e).__name__}: {e}")
                snap["trackers"] = TR.view()
                PL.sync_jobs(loaded["packs"])                                    # the packs' job kinds at each place, to approve there
                snap["templates"], snap["agents"] = T.listing(packs=loaded["packs"]), T.agents(loaded["packs"])   # the builder's (GEN-34)
                snap["packs"] = loaded
                from engine import cutover as CO
                snap["cutover"] = CO.days(c)                                  # the clean days per kind of plan (§6 step 8)
                P.write(shown, snap)
            except Exception as e:                  # the app says the engine is not readable, not an old picture
                P.down(shown, f"{type(e).__name__}: {e}")
            M.stop.wait(PASS_S)
    threading.Thread(target=loop, daemon=True, name="engine-bridge").start()
    return eng

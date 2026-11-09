"""The cutover (GEN-35, docs/AI-STACK-PLAN.md §5, §6, WP7): the smoke checks pass on a real Temporal before anything
switches; the switch is an override the bridge reads first, so a rollback needs no landing; a rollback cancels the
engine's open runs and forgets them, so the Conductor resumes from the rows; the clean days are counted per kind."""
import asyncio
import datetime as dt
import json
import os
import sqlite3

from temporalio.testing import WorkflowEnvironment

from engine import bridge as EB
from engine import converter as CV
from engine import cutover as CO


def test_the_switch_is_an_override_the_bridge_reads_before_the_deployment_and_each_switch_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(CO, "OVERRIDE", tmp_path / "engine")
    monkeypatch.setattr(CO, "LOG", tmp_path / "cutover.jsonl")
    env = {"ENGINE": "conductor"}
    assert CO.override() is None and not EB.on(env)
    CO.switch("temporal", "the cutover")
    assert EB.on(env) and EB.on({"ENGINE": ""})
    CO.switch("conductor", "a rollback")
    assert not EB.on({"ENGINE": "temporal"})
    log = [json.loads(x) for x in (tmp_path / "cutover.jsonl").read_text().splitlines()]
    assert [r["switch"] for r in log] == ["temporal", "conductor"] and log[0]["why"] == "the cutover"


def test_the_smoke_checks_pass_on_a_real_temporal(monkeypatch):
    monkeypatch.setenv(CV.KEY_ENV, CV.new_key())

    async def go():
        async with await WorkflowEnvironment.start_local(namespace="default", download_dest_dir=os.environ.get("TEMPORAL_DOWNLOAD_DIR")) as e:
            return await CO.smoke(addr=e.client.service_client.config.target_host)
    res = asyncio.run(go())
    assert [name for name, ok, _ in res] == ["Temporal answers", "A toy run starts, waits, is signalled and finishes",
                                             "The run replays against the code", "The converter refuses content on a customer-class namespace"]
    assert all(ok for _, ok, _ in res), res


def test_the_smoke_checks_say_no_when_temporal_does_not_answer(monkeypatch):
    monkeypatch.setenv(CV.KEY_ENV, CV.new_key())
    res = asyncio.run(CO.smoke(addr="127.0.0.1:1"))
    assert res[0][0] == "Temporal answers" and res[0][1] is False and len(res) == 1


def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("create table tasks (id integer, kind text)")
    c.execute("create table task_occ (task integer, occ integer, status text)")
    EB.table(c)
    return c


def test_a_rollback_cancels_the_open_runs_forgets_them_and_switches_to_the_conductor(tmp_path, monkeypatch):
    monkeypatch.setattr(CO, "OVERRIDE", tmp_path / "engine")
    monkeypatch.setattr(CO, "LOG", tmp_path / "cutover.jsonl")
    c = db()
    c.executemany("insert into task_occ values (?,?,?)", [(1, 1, "running"), (2, 1, "done")])
    c.executemany("insert into engine_runs values (?,?,?,?)", [(1, 1, "task:1:1", "2026-11-09"), (2, 1, "task:2:1", "2026-11-09")])
    signalled = []

    def call(fn):
        class H:
            def __init__(self, w):
                self.w = w

            async def signal(self, *a):
                signalled.append(self.w)

        class Cl:
            def get_workflow_handle(self, w):
                return H(w)
        return asyncio.run(fn(Cl()))
    assert CO.rollback(c, call) == ["task:1:1"] and signalled == ["task:1:1"]
    assert [r[0] for r in c.execute("select workflow from engine_runs")] == ["task:2:1"]          # the ended run stays recorded
    assert CO.override() == "conductor"


def test_the_clean_days_are_counted_per_kind_of_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(CO, "LOG", tmp_path / "cutover.jsonl")
    c = db()
    now = dt.datetime(2026, 11, 30, tzinfo=dt.timezone.utc)
    c.executemany("insert into tasks values (?,?)", [(1, "research"), (2, "coding")])
    c.executemany("insert into engine_runs values (?,?,?,?)", [(1, 1, "task:1:1", "2026-11-10T08:00:00+00:00"), (2, 1, "task:2:1", "2026-11-25T08:00:00+00:00")])
    d = CO.days(c, now)
    assert d["kinds"]["research"]["clean"] and d["kinds"]["research"]["days"] == 19
    assert not d["kinds"]["coding"]["clean"] and d["kinds"]["coding"]["days"] == 4 and d["needed"] == 14

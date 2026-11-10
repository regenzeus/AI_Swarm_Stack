"""WFL-09, WFL-12: n8n is the one scheduler. Every scheduled job has its workflow, whose cron says when it runs and runs
next; one switch turns a job on or off on n8n; a task that gets a schedule gets its workflow once, and a cancelled one's
goes off; n8n starts one run of a task and gets its answer when it has finished; nothing else in the repository starts
work on a schedule but the kept timers (the backup, the restore drill, the boot check)."""
import datetime as dt
import json
import sqlite3
import types
from pathlib import Path

import pytest

import conductor as CD
import crew as CR
import flows as FW
import n8n_gen as G
import n8n_jobs as NJ
import n8n_switch as SW
import n8n_sync as NS
import tasks as TK

ROOT = Path(__file__).resolve().parent.parent
KEPT = {"backup.timer", "restore-drill.timer", "stack-ready.timer"}


def fake_run(calls, code=0):
    return lambda cmd, **k: calls.append(cmd) or types.SimpleNamespace(returncode=code, stdout="", stderr="refused" if code else "")


def test_a_jobs_schedule_and_next_run_come_from_its_workflows_cron():
    berlin = dt.timezone(dt.timedelta(hours=1))
    at = dt.datetime(2026, 11, 10, 12, 2, tzinfo=berlin)                                       # a Tuesday
    nxt = lambda cron: NJ.next_fire(cron, at, "Europe/Berlin").strftime("%a %d %H:%M")
    assert [nxt(c) for c in ("* * * * *", "*/10 * * * *", "0 * * * *", "0 */6 * * *", "30 4 * * *", "30 4 * * 1", "0 6 02 * *", "0 8 * * 1-5")] == \
        ["Tue 10 12:03", "Tue 10 12:10", "Tue 10 13:00", "Tue 10 18:00", "Wed 11 04:30", "Mon 16 04:30", "Wed 02 06:00", "Wed 11 08:00"]
    spring = NJ.next_fire("30 6 * * *", dt.datetime(2027, 3, 27, 12, 0, tzinfo=berlin), "Europe/Berlin")   # the clocks go forward that night
    assert (spring.hour, spring.minute, spring.utcoffset()) in ((6, 30, dt.timedelta(hours=2)), (6, 30, dt.timedelta(hours=1)))
    assert NJ.every("*/5 * * * *", at) == 300 and NJ.every("30 4 * * 1", at) == 7 * 86400 and NJ.next_fire("not a cron", at) is None
    assert [NJ.words(c) for c in ("30 4 * * *", "*/5 * * * *", "30 4 * * 1", "0 9 01 * *")] == \
        ["daily 04:30", "every 5 minutes", "Mondays 04:30", "monthly on day 1, 09:00"]
    assert [NJ.cron_of_rhythm(s) for s in ("daily 06:30", "weekdays 07:00", "weekly mon,thu 08:15", "every 6h", "every 1h", "manual")] == \
        ["30 6 * * *", "0 7 * * 1-5", "15 8 * * 1,4", "0 */6 * * *", "0 * * * *", ""]
    idx = NJ.index(ROOT / "n8n/workflows", ROOT / "no-such-folder")
    assert NJ.schedule("crew", "memory", idx) == "daily 04:30" and NJ.of("crew", "memory", idx)["file"] == "memory-keeper.json"
    assert NJ.next_run("crew", "memory", at, idx) == "2026-11-11T04:30+01:00"
    assert NJ.schedule("crew", "vault-ingest", idx) not in (None, "switched off")                    # on n8n since 10 Nov 2026
    off = {**idx, ("crew", "vault-ingest"): {**idx[("crew", "vault-ingest")], "active": False}}     # a job taken back
    assert NJ.schedule("crew", "vault-ingest", off) == "switched off" and NJ.next_run("crew", "vault-ingest", at, off) is None
    assert NJ.schedule("crew", "backup", idx) is None                                     # a kept timer's job has no workflow


def test_a_generated_workflow_is_inactive_and_goes_through_the_step_service(tmp_path):
    wf = G.workflow("crew", "doctor", "Crew: Health doctor", "0 */6 * * *", {"kind": "crew", "job": "doctor"}, "the crew job")
    assert "saveDataSuccessExecution" not in wf["settings"]
    assert G.settings("*/5 * * * *")["saveDataSuccessExecution"] == "none"          # a sync every few minutes keeps only failures
    assert wf["active"] is False and len(wf["id"]) == 16 and wf["id"] == G.wid("crew", "doctor")
    trig, step, now = wf["nodes"]
    assert trig["parameters"]["rule"]["interval"][0]["expression"] == "0 */6 * * *" == NJ.cron_of(wf)
    assert now["name"] == "Run now" and now["parameters"]["path"] == "run/crew-health-doctor"                  # WFL-13
    assert wf["connections"]["Run now"]["main"][0][0]["node"] == step["name"] == wf["connections"][trig["name"]]["main"][0][0]["node"]
    assert step["type"] == "CUSTOM.aistackStep" and step["webhookId"]
    assert step["parameters"] == {"kind": "crew", "job": "doctor", "title": "Crew: Health doctor"}
    assert NJ.target(wf) == ("crew", "doctor")
    t = G.workflow("task", 2, "Task #2: a briefing", "30 6 * * *", {"kind": "task", "task": 2}, "its schedule")
    assert NJ.target(t) == ("task", 2)
    p = G.crew("rotation", "0 1 * * *", out=tmp_path)                                 # a new crew job's workflow, inactive
    made = json.loads(p.read_text())
    assert p.name == "crew-trial-rotation.json" and made["active"] is False and NJ.target(made) == ("crew", "rotation")
    assert G.crew("rotation", "0 1 * * *", out=tmp_path) is None                      # an existing file stays as it is


def test_regenerating_adds_run_now_once_and_keeps_each_files_id_and_active(tmp_path):
    """WFL-13: the generator gives an existing crew or task file its Run now trigger and leaves everything else as it is
    (a switched-on job stays on); other files are not its own."""
    old = G.workflow("crew", "checker", "Crew: Checker", "0 * * * *", {"kind": "crew", "job": "checker"}, "")
    old["nodes"] = old["nodes"][:2]
    old["connections"].pop("Run now")
    old["active"], old["id"] = True, "aisc884734674816"
    (tmp_path / "crew-checker.json").write_text(json.dumps(old))
    (tmp_path / "stack-self-test.json").write_text(json.dumps({"id": "aistackSelfTest1", "nodes": [], "connections": {}}))
    assert G.add_run_now(tmp_path) == ["crew-checker.json"] and G.add_run_now(tmp_path) == []
    got = json.loads((tmp_path / "crew-checker.json").read_text())
    assert (got["active"], got["id"], len(got["nodes"])) == (True, "aisc884734674816", 3)
    assert next(n for n in got["nodes"] if n["name"] == "Run now")["parameters"]["path"] == "run/crew-checker"
    assert json.loads((tmp_path / "stack-self-test.json").read_text())["nodes"] == []


def test_one_switch_turns_a_job_on_and_off_on_n8n(tmp_path):
    calls = []
    p = tmp_path / "crew-doctor.json"
    p.write_text(json.dumps(G.workflow("crew", "doctor", "Crew: Health doctor", "0 */6 * * *", {"kind": "crew", "job": "doctor"}, "")))
    assert "on, n8n starts it" in SW.switch(p, True, run=fake_run(calls))
    ex = ["docker", "exec", "-u", "node", "aistack-n8n-1", "n8n"]
    assert calls == [ex + ["publish:workflow", f"--id={G.wid('crew', 'doctor')}"], ["docker", "restart", "aistack-n8n-1"]]
    assert json.loads(p.read_text())["active"] is True
    calls.clear()
    SW.switch(p, False, run=fake_run(calls))
    assert calls[0] == ex + ["unpublish:workflow", f"--id={G.wid('crew', 'doctor')}"] and json.loads(p.read_text())["active"] is False


def tasks_db(tmp_path):
    c = sqlite3.connect(tmp_path / "m.sqlite")
    c.row_factory = sqlite3.Row
    TK.table(c)
    for tid, door, status, rhythm in ((40, "plan", "scheduled", {"type": "schedule", "schedule": "weekly mon 08:00"}),
                                      (41, "mission", "scheduled", {"type": "schedule", "schedule": "daily 07:00"}),
                                      (42, "mission", "done", {"type": "schedule", "schedule": "daily 06:30"}),        # an archived mission
                                      (43, "plan", "scheduled", {"type": "once"}),
                                      (44, "plan", "running", {"type": "schedule", "schedule": "sometimes"})):
        c.execute("insert into tasks (id, title, door, ref, status, rhythm) values (?,?,?,?,?,?)",
                  (tid, f"Task {tid}", door, f"m{tid}", status, json.dumps(rhythm)))
    c.commit()
    return c


def test_a_task_that_gets_a_schedule_gets_its_workflow_once_and_a_cancelled_ones_goes_off(tmp_path):
    repo, made = tmp_path / "repo", tmp_path / "made"
    repo.mkdir()
    c = tasks_db(tmp_path)
    calls, said = [], []
    done = NJ.reconcile(c, run=fake_run(calls), say=said.append, repo=repo, made=made)
    assert sorted(p.name for p in made.glob("*.json")) == ["task-40-task-40.json", "task-41-task-41.json"]
    assert done[0] == "task #40 runs from its n8n workflow task-40-task-40.json (Mondays 08:00)"
    wf = json.loads((made / "task-40-task-40.json").read_text())
    assert wf["active"] is True and NJ.cron_of(wf) == "0 8 * * 1" and NJ.target(wf) == ("task", 40)
    put = [x for x in calls if x[:3] == ["docker", "exec", "-i"]]
    assert len(put) == 2 and "n8n import:workflow" in put[0][-1]                          # into n8n, then published, then n8n reloads
    assert ["docker", "exec", "-u", "node", "aistack-n8n-1", "n8n", "publish:workflow", f"--id={wf['id']}"] in calls
    assert said == ["task #44: its n8n workflow was not made yet: ValueError: its schedule 'sometimes' is not one n8n can take"]
    import flows_view as FV                                                         # the app's pages know it before an export
    assert FW.catalog(repo, made)["jobs"]["task:41"]["active"] is True
    assert {w["for"] for w in FV.view(repo, seen={}, done=tmp_path, made=made)["workflows"]} == {"task:40", "task:41"}
    calls.clear()
    assert NJ.reconcile(c, run=fake_run(calls), say=said.append, repo=repo, made=made) == [] and calls == []   # once, and said once
    assert NJ.next_run("task", 40, dt.datetime(2026, 11, 10, 12, 0).astimezone(), NJ.index(repo, made)).startswith("2026-11-16T08:00")
    c.execute("update tasks set status='cancelled' where id=40")
    c.commit()
    assert NJ.reconcile(c, run=fake_run(calls), say=said.append, repo=repo, made=made) == \
        ["task #40 is cancelled: its n8n workflow task-40-task-40.json is off"]
    assert json.loads((made / "task-40-task-40.json").read_text())["active"] is False and NJ.next_run("task", 40, idx=NJ.index(repo, made)) is None
    calls.clear()
    c.execute("update tasks set status='scheduled', rhythm=? where id=44", (json.dumps({"type": "schedule", "schedule": "daily 09:00"}),))
    c.commit()
    assert NJ.reconcile(c, run=fake_run(calls, code=1), say=said.append, repo=repo, made=made) == []   # n8n refuses: nothing kept, said once
    assert not (made / "task-44-task-44.json").exists() and said[-1].startswith("task #44: its n8n workflow was not made yet")
    no_publish = lambda cmd, **k: types.SimpleNamespace(returncode=1 if "publish:workflow" in cmd else 0, stdout="", stderr="no")
    assert NJ.reconcile(c, run=no_publish, say=said.append, repo=repo, made=made) == []          # imported but not published:
    assert not (made / "task-44-task-44.json").exists()                                           # no file, made again next pass


def test_the_runners_word_wins_until_git_holds_it_and_a_deploy_keeps_it(tmp_path):
    repo, made = tmp_path / "repo", tmp_path / "made"
    repo.mkdir()
    made.mkdir()
    wf = G.workflow("task", 7, "Task #7: News", "30 6 * * *", {"kind": "task", "task": 7}, "")
    wf["active"] = True
    (repo / "task-7-news.json").write_text(json.dumps(wf))
    c = tasks_db(tmp_path)
    c.execute("insert into tasks (id, title, door, status, rhythm) values (7, 'News', 'plan', 'cancelled', ?)", (json.dumps({"type": "schedule", "schedule": "daily 06:30"}),))
    c.commit()
    calls = []
    assert NJ.retire({"id": 7}, run=fake_run(calls), repo=repo, made=made) == "task-7-news.json"
    assert json.loads((repo / "task-7-news.json").read_text())["active"] is True        # the repository's file is never edited
    assert NJ.of("task", 7, NJ.index(repo, made))["active"] is False                   # the runner's word wins
    calls.clear()
    assert NS.import_all(repo=repo, run=fake_run(calls), made=made) == 0
    ex = ["docker", "exec", "-u", "node", "aistack-n8n-1", "n8n"]
    assert ex + ["unpublish:workflow", f"--id={wf['id']}"] in calls                     # a deploy never switches it back on
    wf["active"] = False
    (repo / "task-7-news.json").write_text(json.dumps(wf))                              # an export landed: git says the same
    assert NJ.settled(repo, made) == ["task-7-news.json"] and not list(made.glob("*.json"))


def test_n8n_starts_one_occurrence_of_a_plan_task_and_gets_its_answer_when_it_has_finished(K, monkeypatch):
    K.c.execute("update tasks set status='scheduled', rhythm=? where id=?", (json.dumps({"type": "schedule", "schedule": "daily 06:30"}), K.tid))
    K.c.commit()
    occs = []
    real_start = CD.start

    def start(c, t, trigger="start", event=None):
        occs.append(trigger)
        ref = real_start(c, t, trigger=trigger, event=event)
        o = CD.occ_of(c, t["id"])
        c.execute("update task_occ set status='done', result='the briefing' where task=? and occ=?", (t["id"], o))   # the occurrence ran
        return ref
    monkeypatch.setattr(CD, "start", start)
    FW.M = types.SimpleNamespace(db=K.conn, stop=CD.M.stop, log=print, notify=lambda *a: None, event=lambda *a, **k: None)
    a = FW.run_task(K.c, "r1", K.tid, sleep=lambda s: None)
    assert a["status"] == "done" and a["output"] == "the briefing" and occs == ["n8n"]
    again = FW.run_task(K.c, "r1", K.tid, sleep=lambda s: None)                          # after a restart: not started twice
    assert again["occ"] == a["occ"] and occs == ["n8n"]
    assert FW.validate({"kind": "task", "task": "2"}, {}, {}) == "a task step names its plan task by number"
    K.c.execute("update tasks set status='cancelled' where id=?", (K.tid,))
    K.c.commit()
    assert FW.run_task(K.c, "r2", K.tid, sleep=lambda s: None) == {"status": "refused", "error": f"task #{K.tid} is cancelled, not waiting for a run"}
    assert occs == ["n8n"] and FW.run_task(K.c, "r3", 999, sleep=lambda s: None)["status"] == "refused"


def test_n8n_starts_one_run_of_a_missions_task_and_waits_for_it(runner):
    c = runner.db()
    TK.table(c)
    c.execute("insert into tasks (id, title, door, ref, status, rhythm) values (5, 'Lithium', 'mission', 'lithium', 'scheduled', ?)",
              (json.dumps({"type": "schedule", "schedule": "daily 07:00"}),))
    c.commit()
    FW.M = runner
    looked = []

    def sleep(s):                                   # the mission's run finishes while the step waits
        looked.append(s)
        c.execute("update runs set status='ok', summary='three new items' where slug='lithium'")
        c.commit()
    a = FW.run_task(c, "r9", 5, sleep=sleep)
    assert a["status"] == "done" and a["output"] == "three new items" and looked == [FW.WAIT_AGAIN_S]
    assert [tuple(r) for r in c.execute("select slug, trigger from runs")] == [("lithium", "n8n")]
    assert FW.run_task(c, "r9", 5, sleep=sleep)["run"] == a["run"]                    # the same request: the same run, not a second


def test_nothing_but_n8n_and_the_kept_timers_starts_work_on_a_schedule():
    """WFL-12: the crew's timers, the Conductor's schedule path, the missions' own schedules and the event bus's time
    source are gone; every crew job that ran on a timer has its workflow; what systemd still starts says why."""
    timers = {p.name for p in (ROOT / "ops/systemd").glob("*.timer")}
    assert timers == KEPT
    guide = (ROOT / "ops/systemd/AGENTS.md").read_text()
    assert all(t.removesuffix(".timer") in guide for t in KEPT) and "must run when n8n is down" in guide
    assert not hasattr(CD, "due") and not hasattr(CD, "next_run") and "due(" not in (ROOT / "ops/conductor.py").read_text()
    import missions as MM
    import events as EV
    assert not hasattr(MM, "check_schedules") and not hasattr(MM, "next_due") and "schedule" not in EV.SOURCES
    idx = NJ.index(ROOT / "n8n/workflows", ROOT / "no-such-folder")
    timed = {a["id"] for a in CR.CREW if a.get("unit") and not a.get("oneoff")} - {"backup", "restore-drill"}
    later = {n["parameters"]["job"] for p in (ROOT / "n8n/workflows").glob("*.json") for n in json.loads(p.read_text())["nodes"]
             if n["parameters"].get("kind") == "crew"} - {key for kind, key in idx if kind == "crew"}
    assert later == {"tax-file"}                     # TAX-08: a crew job that runs as a later step of the tax desk's workflow
    assert {key for kind, key in idx if kind == "crew"} | later == timed
    assert all((ROOT / "ops/systemd" / f"{CR.BY_ID[j]['unit']}.service").exists() for j in timed)   # the step service starts each unit
    assert not any("timer" in (w.get("notes") or "") for p in (ROOT / "n8n/workflows").glob("*.json") for w in json.loads(p.read_text())["nodes"])


def test_a_missions_schedule_goes_to_its_task_and_then_its_workflow_holds_it(runner, monkeypatch):
    """A mission given a schedule hands it to its task, which gets its workflow; once it has one, the schedule is n8n's
    and the mission's form refuses to change it (the owner changes it on the canvas, under Workflows)."""
    c = runner.db()
    slug = runner.handle({"action": "create", "type": "task", "title": "Lithium news", "run_now": False}, {}, c)["slug"]
    TK.table(c)
    c.execute("insert into tasks (id, title, door, ref, status, rhythm) values (8, 'Lithium news', 'mission', ?, 'scheduled', ?)",
              (slug, json.dumps({"type": "once"})))
    c.commit()
    r = runner.handle({"action": "update", "slug": slug, "fields": {"schedule": "daily 07:00"}}, runner.load_missions(), c)
    assert r["changed"] == ["schedule"]
    assert json.loads(c.execute("select rhythm from tasks where id=8").fetchone()[0]) == {"type": "schedule", "schedule": "daily 07:00"}
    assert [t["id"] for t, _ in NJ.wants(c, ROOT / "no-such-folder", ROOT / "no-such-folder")] == [8]
    monkeypatch.setattr(NJ, "of", lambda kind, key, idx=None: {"active": True} if (kind, key) == ("task", 8) else None)
    with pytest.raises(ValueError, match="open Workflows"):
        runner.handle({"action": "update", "slug": slug, "fields": {"schedule": "daily 09:00"}}, runner.load_missions(), c)
    same = runner.handle({"action": "update", "slug": slug, "fields": {"schedule": "daily 07:00", "goal": "Lithium prices"}}, runner.load_missions(), c)
    assert same["changed"] == ["goal"]                                                # the form sends the schedule it shows: no change

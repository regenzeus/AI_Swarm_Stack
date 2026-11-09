"""A start of the PC (FND-119, PLT-28 to PLT-30): Docker never gives up, nothing starts against a stack that is not up,
nothing the PC slept through counts as a failure. Fakes for Docker and the gateway; the live proof is docs/PROBES.md P8."""
import configparser
import json
import re
import threading
import time
from pathlib import Path

import pytest

import deploy as D
import observe as O
import stack_gate as G
import stack_ready as SR

ROOT = Path(__file__).resolve().parent.parent
UNITS = ROOT / "ops/systemd"
UP = {s: "running" for s in G.NEEDED}


@pytest.fixture
def stack(monkeypatch, tmp_path):
    """A stack that is up; a test changes what it is about."""
    ready = tmp_path / "ready"
    ready.write_text("1")
    monkeypatch.setattr(G, "READY", ready)
    monkeypatch.setattr(G, "states", lambda timeout=5: dict(UP))
    monkeypatch.setattr(G, "gateway", lambda timeout=5: True)
    monkeypatch.setattr(G, "uptime", lambda: 7200.0)
    return ready


def unit(name):
    c = configparser.RawConfigParser(strict=False, delimiters=("=",))
    c.optionxform = str
    c.read_string((UNITS / name).read_text())
    return c


def seconds(text):
    return sum(int(n) * {"h": 3600, "min": 60}[u] for n, u in re.findall(r"(\d+)(h|min)", text))


def test_the_gate_opens_only_when_docker_the_services_and_the_gateway_are_up(stack, monkeypatch):
    assert G.why_down() == ""
    monkeypatch.setattr(G, "states", lambda timeout=5: {**UP, "hermes": "paused"})   # the backup pauses Hermes
    assert G.why_down() == "hermes is paused"
    monkeypatch.setattr(G, "states", lambda timeout=5: {k: v for k, v in UP.items() if k != "swarm"})
    assert G.why_down() == "swarm is missing"
    monkeypatch.setattr(G, "states", lambda timeout=5: dict(UP))
    monkeypatch.setattr(G, "gateway", lambda timeout=5: False)
    assert "LiteLLM" in G.why_down()

    def refused(timeout=5):
        raise ConnectionRefusedError(111, "refused")
    monkeypatch.setattr(G, "states", refused)
    assert G.why_down() == "Docker is not running"


def test_the_backup_waits_only_for_its_databases(stack, monkeypatch):
    """Review OPS-R4: a crash-looping app skipped the night's backup, and the skip counted as ok."""
    monkeypatch.setattr(G, "states", lambda timeout=5: {**UP, "mission-control": "restarting", "swarm": "exited"})
    monkeypatch.setattr(G, "gateway", lambda timeout=5: False)
    assert G.why_down() and G.why_down(("postgres", "hindsight-db"), False) == ""
    assert G.main(["--need", "postgres,hindsight-db", "--no-gateway"]) == 0
    assert "--need postgres,hindsight-db --no-gateway" in (UNITS / "backup.service").read_text()
    backup = (UNITS.parent / "backup.sh").read_text()
    assert "docker pause $PAUSED" in backup and "status=running" in backup     # only what runs is paused


def test_the_gate_stays_shut_until_the_boot_check_is_done_and_opens_by_itself_later(stack, monkeypatch):
    stack.unlink()
    monkeypatch.setattr(G, "uptime", lambda: 120.0)
    assert G.why_down() == "the stack is still starting"          # its restart of Hermes must not hit a run
    monkeypatch.setattr(G, "uptime", lambda: float(G.SETTLED_S))  # a boot check that never ended holds nothing back for ever
    assert G.why_down() == ""


def test_wait_returns_when_the_stack_comes_up_gives_up_after_its_time_and_stops_on_request(stack, monkeypatch):
    answers = ["Docker is not running", "the stack is still starting", ""]
    monkeypatch.setattr(G, "why_down", lambda: answers.pop(0))
    assert G.wait(60, sleep=lambda s: None) is True and answers == []
    monkeypatch.setattr(G, "why_down", lambda: "Docker is not running")
    assert G.wait(0, sleep=lambda s: None) is False
    stop = threading.Event()
    stop.set()
    assert G.wait(600, stop=stop, sleep=lambda s: None) is False


def test_the_cli_exits_1_when_the_stack_is_down_so_systemd_skips_the_job(stack, monkeypatch, capsys):
    assert G.main([]) == 0
    monkeypatch.setattr(G, "why_down", lambda: "Docker is not running")
    assert G.main([]) == 1
    assert capsys.readouterr().out == "stack gate: skipped: Docker is not running\n"


def test_every_scheduled_job_waits_for_the_stack_except_the_job_that_brings_it_up():
    timers = [t.stem for t in UNITS.glob("*.timer")]
    assert len(timers) > 20
    for name in timers:
        text = (UNITS / f"{name}.service").read_text()
        if name == "stack-ready":
            assert "ExecCondition" not in text
            continue
        lines = [ln for ln in text.splitlines() if ln.startswith("ExecCondition=")]
        assert lines and "%h/ai-stack/ops/stack_gate.py" in lines[0], name
        assert text.index("ExecCondition=") < text.index("ExecStart="), name


def test_each_job_s_start_timeout_has_room_for_its_slot_and_the_wait():
    for f in UNITS.glob("*.service"):
        text = f.read_text()
        m = re.search(r"stack_gate\.py(.*)", text)
        t = re.search(r"^TimeoutStartSec=(.+)$", text, re.M)
        if not m or not t:
            continue
        wait = re.search(r"--wait (\d+)", m[1])
        slot = re.search(r"--slot (\d+)", m[1])
        need = (int(wait[1]) if wait else 0) + (int(slot[1]) * 60 if slot else 0)
        assert seconds(t[1]) - need >= 1800 or not need, f"{f.name}: {t[1]} leaves the job too little after {need} s of waiting"


def test_jobs_that_run_every_few_minutes_skip_at_once_and_catch_ups_each_get_their_own_slot():
    frequent = ("swarm-sync", "skills-sync", "vault-ingest", "graphify-sync", "memory-review", "crew-checker", "crew-doctor")
    for n in frequent:
        assert "--wait" not in (UNITS / f"{n}.service").read_text(), n          # the next run is minutes away
    slots = {}
    for t in UNITS.glob("*.timer"):
        if "Persistent=true" in t.read_text():
            m = re.search(r"--slot (\d+)", (UNITS / f"{t.stem}.service").read_text())
            if t.stem != "recycle":
                assert m, t.stem
                slots.setdefault(int(m[1]), []).append(t.stem)
    assert all(len(v) == 1 for v in slots.values()), slots                     # never two heavy jobs at one time
    order = sorted(slots, key=int)
    names = [slots[s][0] for s in order]
    assert names.index("backup") < names.index("crew-journeys") < names.index("restore-drill")


def test_docker_never_gives_up_and_warms_what_containerd_needs():
    text = (UNITS / "docker-boot.conf").read_text()
    assert re.search(r"^StartLimitIntervalSec=0$", text, re.M)                  # systemd's default gave up after 3 starts in a minute
    assert re.search(r"^RestartSec=\d+$", text, re.M)
    pre = next(ln for ln in text.splitlines() if ln.startswith("ExecStartPre="))
    assert pre.startswith("ExecStartPre=-") and "meta.db" in pre                # "-": a failed warm-up must not stop Docker


def test_a_deploy_installs_the_drop_in_for_docker_and_a_new_machine_too(tmp_path):
    assert D.unit_target("ops/systemd/docker-boot.conf", tmp_path) == tmp_path / "docker.service.d/boot.conf"
    assert D.unit_target("ops/systemd/backup.timer", tmp_path) == tmp_path / "backup.timer"
    for script in ("ops/new-machine.sh", "ops/bootstrap-wsl-2-user.sh"):
        assert "docker-boot.conf" in (ROOT / script).read_text()


def journal(monkeypatch, entries):
    out = "\n".join(json.dumps({"USER_INVOCATION_ID": inv, "__REALTIME_TIMESTAMP": str(int(t * 1e6)), "MESSAGE": msg}) for inv, t, msg in entries)
    monkeypatch.setattr(O.subprocess, "run", lambda *a, **k: type("P", (), {"stdout": out})())


def test_a_run_the_gate_skipped_is_no_run_and_its_wait_is_not_its_run_time(monkeypatch):
    journal(monkeypatch, [("a", 100, "Starting Crew job..."), ("a", 400, "stack gate: ready after 300 s"),
                          ("a", 410, "did the work"), ("a", 420, "x.service: Deactivated successfully."), ("a", 420, "Finished Crew job."),
                          ("b", 500, "Starting Crew job..."), ("b", 500, "stack gate: skipped: Docker is not running"),
                          ("b", 500, "x.service: Skipped due to 'exec-condition'."), ("b", 500, "Condition check resulted in Crew job being skipped.")])
    runs = O.crew_history("x")
    assert [(r["state"], r["start"], r["seconds"]) for r in runs] == [("ok", 400, 20.0)]
    assert runs[0]["log"] == ["did the work"]


def test_the_hours_the_pc_was_off_do_not_make_a_job_overdue():
    now = time.time()
    run = [{"start": now - 15 * 3600, "seconds": 3, "state": "ok"}]
    assert any(i["kind"] == "overdue" for i in O.judge("x", "crew", run, now=now, interval=300)["issues"])
    assert not O.judge("x", "crew", run, now=now, interval=300, up_since=now - 600)["issues"]
    assert any(i["kind"] == "overdue" for i in O.judge("x", "crew", run, now=now, interval=300, up_since=now - 3 * 3600)["issues"])


def test_no_health_alert_while_the_stack_starts_or_is_down(stack, monkeypatch):
    import crew as CR
    assert not CR.quiet()
    monkeypatch.setattr(G, "uptime", lambda: 300.0)
    assert CR.quiet()
    monkeypatch.setattr(G, "uptime", lambda: 7200.0)
    monkeypatch.setattr(G, "why_down", lambda: "Docker is not running")
    assert CR.quiet()


def test_a_job_waiting_its_turn_is_not_charged_with_its_last_run_s_failure(monkeypatch, tmp_path):
    import crew as CR
    now = time.time()
    runs = [{"state": "running", "start": now, "seconds": 0, "log": []}, {"state": "failed", "start": now - 9000, "seconds": 1, "error": "refused", "log": []}]
    monkeypatch.setattr(O, "crew_history", lambda unit: [dict(r) for r in runs])
    monkeypatch.setattr(CR, "CREW", [{"id": "x", "name": "X", "unit": "x", "agent": True}])
    monkeypatch.setattr(CR, "agent_file", lambda aid: {"result": "failed: refused"})
    monkeypatch.setattr(CR, "schedule_of", lambda unit: "daily 04:00")
    monkeypatch.setattr(CR, "payoff_of", lambda c, aid: {})
    monkeypatch.setattr(CR, "OUT", tmp_path)
    monkeypatch.setattr(CR, "_hist_t", {"t": 0})
    CR.refresh_history(None)
    assert not [i for i in CR._hist["x"]["issues"] if i["kind"] == "failing"]     # one failure, not two in a row


def test_a_skipped_job_does_not_show_as_failed(monkeypatch):
    import crew as CR
    monkeypatch.setattr(CR, "schedule_of", lambda unit: "every 1h")
    svc = {"LoadState": "loaded", "ActiveState": "inactive", "SubState": "dead", "Result": "exec-condition", "ExecMainStartTimestamp": "@100"}
    assert CR.unit_status({"unit": "x"}, {"x.service": svc})["state"] == "ok"


@pytest.fixture
def mission_env(runner, monkeypatch):
    """The runner with one mission, its run record and journal switched off. -> (module, db, mission)."""
    M = runner
    for name in ("set_ref", "start", "end", "stage", "emit"):
        monkeypatch.setattr(M.RTM, name, lambda *a, **k: None)
    monkeypatch.setattr(M.J, "begin", lambda *a, **k: None)
    monkeypatch.setattr(M.J, "after_run", lambda *a, **k: None)
    monkeypatch.setattr(M.SW, "paused", lambda card: False)
    return M, M.db(), {"slug": "m1", "title": "M one", "type": "task", "deliver": []}


def make_run(M, c, slug="m1"):
    c.execute("insert into runs (slug, trigger, status) values (?, 'schedule', 'queued')", (slug,))
    c.commit()
    return c.execute("select * from runs order by id desc limit 1").fetchone()


def test_a_run_the_stack_went_away_under_waits_and_runs_again_and_alarms_nobody(mission_env, monkeypatch):
    M, c, m = mission_env
    monkeypatch.setattr(M.G, "why_down", lambda: "Docker is not running")
    monkeypatch.setattr(M, "run_task", lambda *a, **k: ("failed", "no answer", ""))
    events = []
    monkeypatch.setattr(M, "event", lambda *a, **k: events.append((a, k)))
    M.execute(c, make_run(M, c), {"m1": m})
    r = c.execute("select status, retry_at, attempts, summary from runs").fetchone()
    assert r["status"] == "waiting" and int(r["attempts"]) == 1 and "Docker is not running" in r["summary"]
    assert [k.get("push") for a, k in events if a[0] == "waiting"] == [False]
    assert not [a for a, k in events if a[0] == "run_failed"]


def test_a_real_failure_is_still_a_failure_while_the_stack_is_up(mission_env, monkeypatch):
    M, c, m = mission_env
    monkeypatch.setattr(M.G, "why_down", lambda: "")
    monkeypatch.setattr(M, "run_task", lambda *a, **k: ("failed", "the model said no", ""))
    monkeypatch.setattr(M, "event", lambda *a, **k: None)
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    monkeypatch.setattr(M.X, "telegram", lambda *a, **k: None, raising=False)
    M.execute(c, make_run(M, c), {"m1": m})
    assert c.execute("select status from runs").fetchone()["status"] == "failed"


def test_a_log_that_names_a_paused_container_counts_as_the_stack_s_doing(mission_env, monkeypatch):
    M, _, _ = mission_env
    monkeypatch.setattr(M.G, "why_down", lambda: "")
    assert M.stack_gone("Error response from daemon: Container aistack-hermes-1 is paused") == "the stack was restarting"
    assert M.stack_gone("Traceback: the model said no") == ""


def test_queued_runs_stay_queued_while_the_stack_is_down(mission_env, monkeypatch):
    M, c, m = mission_env
    make_run(M, c)
    started = []
    monkeypatch.setattr(M, "_run_thread", lambda row: started.append(row["id"]) or M.slot.release())
    monkeypatch.setattr(M.G, "why_down", lambda: "Docker is not running")
    M.stop.clear()
    t = threading.Thread(target=M.worker, daemon=True)
    t.start()
    time.sleep(0.5)
    assert started == []
    monkeypatch.setattr(M.G, "why_down", lambda: "")
    for _ in range(50):
        if started:
            break
        time.sleep(0.1)
    M.stop.set()
    t.join(5)
    M.stop.clear()
    assert started == [1]


def test_the_owner_hears_once_after_ten_minutes_and_once_when_it_is_back(mission_env, monkeypatch):
    M, _, _ = mission_env
    said = []
    monkeypatch.setattr(M, "notify", lambda text, category="system": said.append(text))
    since, told = M.stack_watch_step("Docker is not running", None, None, 1000)
    assert (since, told) == (1000, None) and said == []
    since, told = M.stack_watch_step("hermes is paused", since, told, 1300)     # a short pause (the backup) says nothing
    assert said == []
    since, told = M.stack_watch_step("Docker is not running", since, told, 1600)
    since, told = M.stack_watch_step("Docker is not running", since, told, 1900)
    assert told and len(said) == 1 and "10 min: Docker is not running" in said[0]
    assert M.stack_watch_step("", since, told, 2000) == (None, None)
    assert said[1:] == ["The AI stack is back."]
    assert M.stack_watch_step("", None, None, 2100) == (None, None) and len(said) == 2


@pytest.fixture
def ready_env(stack, monkeypatch, tmp_path):
    """stack_ready.main with everything outside faked. -> what it did."""
    stack.unlink()
    did = {"restarts": 0, "said": []}
    monkeypatch.setattr(SR, "BOOTS", tmp_path / "boots.jsonl")
    monkeypatch.setattr(SR, "tools", lambda: set(SR.EXPECTED))
    monkeypatch.setattr(SR, "restart_hermes", lambda: did.__setitem__("restarts", did["restarts"] + 1))
    monkeypatch.setattr(SR, "hermes_live", lambda: True)
    monkeypatch.setattr(SR, "docker_tries", lambda: 0)
    monkeypatch.setattr(SR, "notify", lambda text: did["said"].append(text))
    monkeypatch.setattr(G, "uptime", lambda: 180.0)
    monkeypatch.setattr(G, "booted", lambda: 1000.0)
    return did


def test_the_first_check_of_a_boot_restarts_hermes_opens_the_gate_logs_it_and_says_so_once(ready_env, stack):
    SR.main()
    assert stack.exists() and ready_env["restarts"] == 1
    row = json.loads(SR.BOOTS.read_text())
    assert (row["running"], row["total"], row["ready_s"], row["boot"]) == (len(G.NEEDED), len(G.NEEDED), 180, 1000.0)
    assert ready_env["said"] == [f"AI stack online 3 min after the start: {len(G.NEEDED)} of {len(G.NEEDED)} services running."]
    SR.main()                                        # again in the same boot (a deploy restarts the timer): Hermes is left alone
    assert ready_env["restarts"] == 1 and len(ready_env["said"]) == 1 and len(SR.BOOTS.read_text().splitlines()) == 1


def test_missing_tools_still_open_the_gate_say_what_is_missing_and_fail_the_unit(ready_env, stack, monkeypatch):
    monkeypatch.setattr(SR, "tools", lambda: {"qmd-query"})
    monkeypatch.setattr(SR, "WAIT_S", 0)
    with pytest.raises(SystemExit):
        SR.main()
    assert stack.exists() and ready_env["restarts"] == 0
    assert "graphify-query_graph" in ready_env["said"][0] and ready_env["said"][0].startswith("⚠️")


def test_the_message_names_services_that_did_not_come_up_and_a_slow_docker():
    row = {"ready_s": 300, "running": 27, "total": 28, "down": ["qmd"], "missing": [], "docker_tries": 3}
    assert SR.line(row) == "⚠️ AI stack started 5 min ago, with 1 of 28 services not running: qmd. Docker needed 4 tries."

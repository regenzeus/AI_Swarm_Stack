"""QA-26 (GEN-01): a check that could not run reports unknown and shows on the health board, never pass or silence. One test
breaks each place the audit of 7 Nov 2026 found. Everything external is a fake: no Docker, ssh, NAS or runtime database."""
import pysrc
import webjs
import datetime as dt
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import types
from pathlib import Path

import pytest

import builds as B
import checker as CK
import crew
import decisions as DQ
import keeper as K
import postmaster as PM
import trials as T

ROOT = Path(__file__).resolve().parent.parent
DAY = 86400
NOW = 1_800_000_000


def art(check, since=NOW - 30 * DAY, id=1):
    return {"id": id, "version": 3, "title": "An idea", "owner": "doctor", "check": check, "state_since": since, "evidence": []}


def real_facts(tmp_path, monkeypatch, state=None):
    """The real Facts on a state file that holds `state`, or is not there; `state` as bytes is written as it is."""
    monkeypatch.setattr(CK, "PUBLIC", tmp_path)
    monkeypatch.setattr(CK, "STACK", tmp_path / "nowhere")
    if state is not None:
        (tmp_path / "state.json").write_bytes(state if isinstance(state, bytes) else json.dumps(state).encode())
    return CK.Facts()


# ---------------------------------------------------------------- checker.py: the board and what the checks read
@pytest.mark.parametrize("state, says", [(None, "could not be read (FileNotFoundError)"), (b"{half a fi", "could not be read (JSONDecodeError)"),
                                         ({"health": {}}, "holds no health board")])
def test_a_board_that_cannot_be_read_proves_nothing_and_reopens_nothing(tmp_path, monkeypatch, state, says):
    f = real_facts(tmp_path, monkeypatch, state)
    assert says in f.unread and f.alerts == 0
    for check in ({"type": "health_issue_absent", "keys": ["crew:backup:failed"], "days": 7},                         # zero issues: a pass, once aged
                  {"type": "metric", "name": "health_alerts", "op": "<=", "value": 0, "days": 1},                    # zero alerts: the same
                  {"type": "ci_green"}):                                                                             # no CI row: a fail, once aged
        verdict, why = CK.evaluate(art(check), f, NOW)
        assert verdict == "unknown" and says in why


def test_a_readable_board_still_passes_and_fails(tmp_path, monkeypatch):
    f = real_facts(tmp_path, monkeypatch, {"health": {"items": [{"issues": [{"key": "crew:x:failed", "kind": "failed", "severity": "alert"}]}]}})
    assert f.unread == "" and f.alerts == 1
    assert CK.evaluate(art({"type": "health_issue_absent", "keys": ["crew:y:failed"], "days": 7}), f, NOW)[0] == "pass"
    assert CK.evaluate(art({"type": "health_issue_absent", "keys": ["crew:x:failed"], "days": 7}), f, NOW)[0] == "fail"


def test_a_check_that_cannot_read_its_logs_or_metric_is_unknown():
    class Facts:
        unread = ""
        alerts = 0
        log_count = staticmethod(lambda *a: None)
        failed_runs = staticmethod(lambda since: None)
    logs = {"type": "log_count", "container": "aistack-hermes-1", "pattern": "x", "max": 0, "hours": 1}
    assert CK.evaluate(art(logs), Facts, NOW) == ("unknown", "the logs of aistack-hermes-1 could not be read")
    assert CK.evaluate(art({"type": "metric", "name": "failed_runs", "op": "<=", "value": 0}), Facts, NOW)[0] == "unknown"
    assert CK.evaluate(art({"type": "something new"}), Facts, NOW)[0] == "unknown"


def test_the_checker_s_unknown_reaches_its_card_on_the_board(tmp_path, monkeypatch):
    """check_all moves nothing, and the sentence with the ideas it holds back lands where the board reads it."""
    f = real_facts(tmp_path, monkeypatch)
    moves = []

    def send(op, args, who):
        if op == "artifacts_in":
            return {"result": [art({"type": "health_issue_absent", "keys": ["k"], "days": 7}, id=11 if "checking" in args["states"] else 12)]}
        if op == "transition":
            moves.append(args)
        return {"ok": True}
    monkeypatch.setattr(CK.SW, "_save", lambda *a: None)
    unread = {}
    assert CK.check_all(f, NOW, send, unread) == (0, 0, 1) and not moves
    assert list(unread.values()) == [[11, 12]] and "could not be read" in next(iter(unread))


def test_a_job_s_unknown_is_one_alert_on_its_card_and_its_next_clean_run_clears_it(tmp_path, monkeypatch):
    monkeypatch.setattr(crew, "OUT", tmp_path)
    crew.save("checker", unknown=["the app's state file could not be read (OSError), so this check could not run (idea #4)", "the logs of x could not be read (idea #5)"])
    [i] = crew.job_unknown("checker")
    assert i["kind"] == "check-unknown" and "check-unknown" in crew.ALERTS and "idea #4" in i["text"] and "idea #5" in i["text"]
    crew.save("checker", unknown=[])
    assert crew.job_unknown("checker") == []
    assert crew.job_unknown("never-ran") == []
    assert "+ job_unknown(a[\"id\"]) if a.get(\"enabled\", True)" in (ROOT / "ops/crew.py").read_text()


# ---------------------------------------------------------------- crew.py: the logs, Docker, memory
def drill():
    return {"kind": "crew", "id": "restore-drill", "name": "Restore drill", "issues": []}


def alarms(it, log):
    return crew.recovery_alarms([it], now=NOW, backups=log, meminfo="", drift="", nets=[], phone={})


def test_an_unreadable_backup_log_is_an_alert_on_the_drill_and_one_bad_line_costs_one_line(tmp_path):
    log = tmp_path / "backups.jsonl"
    it = drill()
    alarms(it, log)
    assert [i["kind"] for i in it["issues"]] == ["report-none"] and "report-none" not in crew.ALERTS     # never run: told, not alarmed
    log.mkdir()                                                                                          # a read that fails
    it = drill()
    alarms(it, log)
    assert [i["kind"] for i in it["issues"]] == ["check-unknown"] and "The backup log could not be read (IsADirectoryError)" in it["issues"][0]["text"]
    log.rmdir()
    log.write_text("{half a line\n")
    it = drill()
    alarms(it, log)
    assert [i["kind"] for i in it["issues"]] == ["check-unknown"] and "none of its 1 lines" in it["issues"][0]["text"]
    log.write_text(json.dumps({"ts": NOW - 20 * DAY, "kind": "restore-drill", "result": "ok"}) + "\n[1, 2\n" + json.dumps({"ts": NOW - DAY, "kind": "backup", "size": "9M"}) + "\n")
    it = drill()
    alarms(it, log)
    assert [i["kind"] for i in it["issues"]] == ["report-partial", "drill-old"]                          # the drill's alert still comes
    assert "1 of its 3 lines could not be read" in it["issues"][0]["text"] and "report-partial" not in crew.ALERTS


def test_one_bad_line_in_the_app_s_errors_keeps_the_alert_and_says_so(tmp_path):
    f = tmp_path / "client-errors.jsonl"
    f.write_text("not json\n" + json.dumps({"ts": NOW - 60, "msg": "x is null", "url": "#/wiki"}) + "\n")
    [item] = crew.app_errors(NOW, f)
    assert [i["kind"] for i in item["issues"]] == ["app-error", "report-partial"]                        # the audit: one bad line, no alert at all
    f.write_text("not json\n")
    [item] = crew.app_errors(NOW, f)
    assert [i["kind"] for i in item["issues"]] == ["check-unknown"] and "whether the app hit errors is not known" in item["issues"][0]["text"]
    f.unlink()
    f.mkdir()
    assert crew.app_errors(NOW, f)[0]["issues"][0]["kind"] == "check-unknown"
    f.rmdir()
    assert crew.app_errors(NOW, f) == []                                                                 # no log yet: the app hit nothing


@pytest.mark.parametrize("error", [OSError("no docker"), subprocess.TimeoutExpired("docker", 30), subprocess.CalledProcessError(1, "docker")])
def test_docker_failing_is_a_note_then_an_alert_and_never_no_cut_networks(monkeypatch, error):
    monkeypatch.setattr(crew, "_net_unread", {"since": None})

    def broken(*a):
        raise error
    [first] = crew.cut_networks(run=broken, now=NOW)
    assert first["kind"] == "network-unread" and "network-unread" not in crew.ALERTS and "whether a container lost the network it shares is not known" in first["text"]
    [later] = crew.cut_networks(run=broken, now=NOW + crew.NET_UNREAD_S)
    assert later["kind"] == "network-unknown" and "network-unknown" in crew.ALERTS and later["at"] == NOW
    assert crew.cut_networks(run=lambda *a: "", now=NOW + 700) == [] and crew._net_unread["since"] is None
    assert crew.cut_networks(run=broken, now=NOW + 800)[0]["kind"] == "network-unread"                    # a new episode starts over


def test_the_default_docker_call_treats_a_failed_exit_as_a_failure(monkeypatch):
    """docker's non-zero exit printed nothing on stdout, which read as no containers and no cut networks."""
    monkeypatch.setattr(crew, "_net_unread", {"since": None})
    seen = []

    def run(cmd, **k):
        seen.append(k.get("check"))
        raise subprocess.CalledProcessError(1, cmd)
    monkeypatch.setattr(crew.subprocess, "run", run)
    assert crew.cut_networks(now=NOW)[0]["kind"] == "network-unread" and seen == [True]


def test_memory_that_cannot_be_read_is_an_alert_on_this_pc(tmp_path):
    [pc] = crew.recovery_alarms([], now=NOW, backups=tmp_path / "none", meminfo="MemTotal: nonsense kB\n", drift="", nets=[], phone={})
    assert pc["name"] == "This PC" and [i["kind"] for i in pc["issues"]] == ["check-unknown"]
    assert "The PC's memory could not be read (ValueError), so whether it is running short is not known" == pc["issues"][0]["text"]


# ---------------------------------------------------------------- keeper.py
def test_a_runtime_database_error_is_reported_and_reaches_the_memory_keeper_s_card(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_DB_HOST", str(tmp_path / "gone.db"))
    with pytest.raises(sqlite3.Error):
        K.recently_read()
    import mission_extras as X
    import wikis as W
    monkeypatch.setattr(K, "M", types.SimpleNamespace())
    monkeypatch.setattr(W, "M", W.M or K.M)
    monkeypatch.setattr(X, "M", X.M or K.M)
    monkeypatch.setattr(W, "roots", lambda: [("missions/m/wiki", "M")])
    monkeypatch.setattr(K, "disputes", lambda *a: {"open": 0, "tasks": [], "settled": 0})
    monkeypatch.setattr(K, "facts", lambda: [])
    monkeypatch.setattr(K, "gate", lambda: (False, "closed"))
    rep = K.run_pass(None, deep=False, send=lambda *a: {}, create=lambda *a: 1)
    assert "error" in rep["rechecks"]
    [said] = K.unknown(rep)
    assert said.startswith("The check of stale pages agents still read could not run (OperationalError") and said.endswith("is not known")
    assert "1 part could not run" in K.summary(rep)
    assert K.unknown({"rechecks": [], "disputes": {"open": 0}}) == []


# ---------------------------------------------------------------- trials.py
def test_code_that_cannot_be_read_is_no_zero_similarity(tmp_path):
    up, bad, some, none = tmp_path / "up", tmp_path / "bad", tmp_path / "some", tmp_path / "none"
    for d in (up, bad, some, none):
        d.mkdir()
    src = "def compare(a, b):\n    if a < b:\n        return -1\n    return 1 if a > b else 0\n"
    broken = "def compare(a, b):\n    return (a,\n"                    # an open bracket at the end: tokenize gives up
    (up / "v.py").write_text(src)
    (bad / "mine.py").write_text(broken)
    (some / "ok.py").write_text(src)
    (some / "bad.py").write_text(broken)
    assert T.fingerprints(broken) is None and T.fingerprints("x = 1\n") == set()     # too short to hash is not unreadable
    got = T.similarity(bad, up)
    assert got["share"] is None and got["unread"] == ["mine.py"] and T.similar_text(got) == "not known"
    got = T.similarity(some, up)
    assert got["share"] == 1.0 and got["unread"] == ["bad.py"] and T.similar_text(got) == "100%"
    got = T.similarity(some, none)
    assert got["share"] is None                                         # no reference: nothing to compare with
    assert T.similarity(none, up) == {"share": 0.0, "files": [], "unread": []}    # no code at all was delivered: nothing copied
    r = {"run": "r", "started_at": "s", "task": 1, "repo": "x", "dir": "/d", "over_budget": False, "asked": 0, "builds": [], "build": None,
         "score": T.summarise({"cases": [], "error": None}), "audit": {"ok": True, "forbidden": []},
         "similarity": {"share": None, "files": [], "unread": ["mine.py"]}, "metrics": {"status": "done", "error": None, "minutes": 1, "steps": 0, "plan": [], "calls": 0, "tokens": 0, "builder_tokens": 0}}
    rep = T.report(T.load("semver"), r)
    assert "Similarity to the upstream implementation: **not known**" in rep and "mine.py" in rep and "0% of the delivered" not in rep


# ---------------------------------------------------------------- builds.py and decisions.py: the review
@pytest.fixture
def builds_mod(monkeypatch):
    monkeypatch.setattr(B, "M", types.SimpleNamespace(now=lambda: dt.datetime(2026, 11, 7, 12, 0), event=lambda *a, **k: None))
    return B


def lens(name, verdict=None, **k):
    return {"lens": name, "engine": "claude", **({"verdict": verdict, "summary": "ok", "findings": []} if verdict else {"error": "review not done: boom"}), **k}


def test_a_review_with_a_lens_not_done_is_incomplete_and_not_approved(builds_mod):
    r = B.combine([lens("requirements", "approve"), lens("security")])
    assert r["verdict"] == "incomplete" and r["missing"] == ["security"] and B.review_open(r)
    assert B.combine([lens("requirements", "changes"), lens("security")])["verdict"] == "changes"       # a worse word stands, and says what is missing
    assert B.combine([lens("requirements", "block"), lens("security")])["missing"] == ["security"]
    whole = B.combine([lens("requirements", "approve"), lens("security", "approve")])
    assert whole["verdict"] == "approve" and whole["missing"] == [] and not B.review_open(whole)
    none = B.combine([lens("requirements"), lens("security")])
    assert not none.get("verdict") and B.review_open(none)
    assert B.review_open({"pending": True}) and not B.review_open(None)


def test_the_queue_does_not_recommend_a_review_with_a_lens_not_done():
    b = {"id": 3, "status": "review", "checks_ok": True, "checks": "x", "ci": "success", "title": "t", "updated": NOW}
    for rv in ({"verdict": "incomplete", "missing": ["security"]}, {"verdict": "approve", "missing": ["security"]}):     # the second: a record from before this change
        [d] = list(DQ._builds({"builds": [{**b, "ai_review": rv}]}))
        assert d["recommend"]["answer"] == "no" and "not done: security" in d["why"]
    [d] = list(DQ._builds({"builds": [{**b, "ai_review": {"verdict": "approve", "missing": []}}]}))
    assert d["recommend"]["answer"] == "yes" and "not done:" not in d["why"]


def test_the_build_page_shows_an_incomplete_review_and_counts_it_out():
    app = webjs.app_js()
    assert 'incomplete: ["paused", "Review incomplete"]' in app and "Not reviewed: ${r.missing.map(" in app
    assert 'b.ai_review?.verdict !== "block" && !reviewOpen(b.ai_review)' in app
    assert '"incomplete"' in pysrc.server()
    if shutil.which("node"):                                              # the page's own rule, run
        rule = next(ln for ln in app.splitlines() if ln.startswith("const reviewOpen"))
        out = subprocess.run(["node", "-e", rule + '\nconsole.log([{missing:["s"]},{pending:true},{error:"x"},{verdict:"approve",missing:[]},null].map(reviewOpen).join())'],
                             capture_output=True, text=True, timeout=30).stdout
        assert out.strip() == "true,true,true,false,false"


# ---------------------------------------------------------------- check.sh
def fake_tools(tmp_path, *present):
    """A bin folder with passing stand-ins for what ops/check.sh calls, and a copy of the script to run with only that on PATH."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    bash = shutil.which("bash")
    for tool in ("shellcheck", "ruff", "python3", "pytest", "sh", *present):
        (bin_ / tool).write_text(f"#!{bash}\nexit 0\n")
        (bin_ / tool).chmod((bin_ / tool).stat().st_mode | stat.S_IEXEC)
    os.symlink(shutil.which("dirname"), bin_ / "dirname")
    (tmp_path / "ops").mkdir()
    shutil.copy(ROOT / "ops/check.sh", tmp_path / "ops/check.sh")
    return bash, bin_


def run_checks(tmp_path, *present, **env):
    bash, bin_ = fake_tools(tmp_path, *present)
    return subprocess.run([bash, str(tmp_path / "ops/check.sh")], capture_output=True, text=True, timeout=60,
                          env={"PATH": str(bin_), "ESLINT_HOME": str(tmp_path / "no-eslint"), "CHECK_NOT_HERE": "", **env})


def test_a_missing_tool_fails_the_checks_unless_this_place_lacks_it_and_the_summary_says_so(tmp_path):
    p = run_checks(tmp_path)
    assert p.returncode == 1 and "ALL CHECKS PASSED" not in p.stdout and "SOME CHECKS FAILED" in p.stdout
    assert "FAILED: security patterns (semgrep): semgrep is missing, so this check could not run" in p.stdout and "skipped" not in p.stdout


def test_the_summary_line_names_what_a_place_lacks_on_purpose(tmp_path):
    p = run_checks(tmp_path, CHECK_NOT_HERE="node eslint semgrep docker-compose")
    assert p.returncode == 0
    assert p.stdout.strip().splitlines()[-1] == ("ALL CHECKS PASSED, but not run here: app javascript parses, app scripts: no undefined names, "
                                                 "security patterns (semgrep), compose files valid")


def test_the_builder_lacks_compose_on_purpose_and_nothing_else_may_be_missing():
    """The builder has no compose by design, and land.sh and the builds still read its summary as a pass."""
    src = (ROOT / "ops/check.sh").read_text()
    assert '[ -x /opt/tools/bin/pytest ]; then CHECK_NOT_HERE="docker-compose"' in src
    assert 'grep -q "ALL CHECKS PASSED"' in (ROOT / "ops/land.sh").read_text()
    assert "shellcheck" in (ROOT / "images/ci-runner/Dockerfile").read_text() and "docker-compose" in (ROOT / "images/ci-runner/Dockerfile").read_text()


# ---------------------------------------------------------------- improve.py
def test_the_self_review_says_what_it_could_not_read(runner, tmp_path, monkeypatch):
    import improve
    monkeypatch.setattr(improve, "M", runner)
    (tmp_path / "docs").mkdir(exist_ok=True)
    monkeypatch.setattr(improve, "STACK", tmp_path)
    monkeypatch.setattr(improve, "STATE", tmp_path / "improve.json")
    monkeypatch.setattr(runner, "sh", lambda *a, **k: "")
    c = runner.db()
    import builds
    builds.table(c)

    def no_ci():
        raise OSError("no state")
    monkeypatch.setattr(runner, "stack_info", no_ci)

    def no_run(*a, **k):
        raise subprocess.TimeoutExpired("upgrade_check", 180)
    monkeypatch.setattr(improve.subprocess, "run", no_run)
    assert improve.scan(c) == 0
    s = improve.last_scan()
    assert "CI's status could not be read (OSError: no state)" in s["unknown"][0] and "The upgrade check could not run (TimeoutExpired" in s["unknown"][1]
    assert "nothing to improve this week, but 2 could not be read" in s["result"]
    monkeypatch.setattr(crew, "I", improve)
    [i] = crew.job_unknown("self-review")
    assert i["kind"] == "report-partial" and "CI's status" in i["text"]                # a note: a NAS asleep at that hour does not alert for a week
    monkeypatch.setattr(runner, "stack_info", lambda: {"ci": [{"repo": "ai-stack", "status": "unknown", "sha": ""}]})  # how missions.stack_info says Forgejo did not answer
    monkeypatch.setattr(improve.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout="x -> y", returncode=2))
    unread = []
    sig = improve.signals(c, unread)
    assert any("newer releases" in x for x in sig)
    assert "CI's status of ai-stack could not be read" in unread[0] and "exit code 2" in unread[1]


# ---------------------------------------------------------------- postmaster.py
def ssh_says(monkeypatch, code, err="", out=""):
    monkeypatch.setattr(PM.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], code, out, err))


@pytest.mark.parametrize("err", ["ssh: connect to host synology port 22: Connection timed out", "ssh: connect to host synology port 22: Operation timed out",
                                 "ssh: connect to host synology port 22: No route to host", "ssh: connect to host synology port 22: Host is down"])
def test_a_nas_that_gives_no_answer_stays_quiet_and_any_other_ssh_failure_is_unknown(monkeypatch, err):
    ssh_says(monkeypatch, 255, err + "\n")
    assert PM.fetch("status.json") is None                                             # asleep
    ssh_says(monkeypatch, 1, "cat: /volume1/docker/mailvault/data/census.json: No such file or directory\n")
    assert PM.fetch("census.json") is None                                             # nothing there yet
    ssh_says(monkeypatch, 0, "", '{"at": 1}')
    assert PM.fetch("status.json") == '{"at": 1}'
    for code, said in ((255, "someone@nas: Permission denied (publickey,password)."), (255, "Host key verification failed."), (255, "ssh: Could not resolve hostname synology"),
                       (255, "ssh: connect to host synology port 22: Connection refused"), (1, "cat: status.json: Permission denied")):
        ssh_says(monkeypatch, code, said + "\n")
        with pytest.raises(PM.CopyUnread, match="could not be read") as e:
            PM.fetch("status.json")
        assert said in str(e.value) and "so the state of the copy is not known" in str(e.value)


def test_a_nas_that_took_the_connection_and_stopped_answering_is_not_asleep(monkeypatch):
    def hung(*a, **k):
        raise subprocess.TimeoutExpired("ssh", 120)
    monkeypatch.setattr(PM.subprocess, "run", hung)
    with pytest.raises(PM.CopyUnread, match="did not answer in 120 s"):
        PM.fetch("status.json")


def test_the_postmaster_s_unknown_reaches_its_card_on_the_board(tmp_path, monkeypatch):
    monkeypatch.setattr(PM, "OUT", tmp_path / "mail")
    monkeypatch.setattr(crew, "OUT", tmp_path / "crew")
    monkeypatch.setattr(PM, "C", crew)
    monkeypatch.setattr(PM.IN, "granted", lambda scope="read": False)
    ssh_says(monkeypatch, 255, "Permission denied (publickey).\n")
    PM.run(None)
    [i] = crew.job_unknown("postmaster")
    assert i["kind"] == "check-unknown" and "Permission denied" in i["text"] and "status.json" in i["text"]
    assert "Permission denied" in crew.agent_file("postmaster")["result"]
    ssh_says(monkeypatch, 255, "ssh: connect to host synology port 22: No route to host\n")
    PM.run(None)
    assert crew.job_unknown("postmaster") == []                                          # asleep: quiet, and the last sentence is gone

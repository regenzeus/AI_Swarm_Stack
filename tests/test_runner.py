"""ops/missions.py: schedule words, request validation, duplicate guard, pause detection, queueing."""
import datetime as dt
import json

import pytest


@pytest.mark.parametrize("s,ok", [
    ("daily 06:30", True), ("weekdays 07:00", True), ("weekly mon,thu 08:15", True), ("every 6h", True),
    ("manual", True), ("daily 24:00", False), ("daily 6:30", False), ("weekly funday 08:00", False),
    ("every 0h", False), ("every 25h", False), ("", False), ("hourly", False)])
def test_valid_schedule(runner, s, ok):
    assert runner.valid_schedule(s) is ok


@pytest.mark.parametrize("s,text", [("daily 06:30", "Daily 06:30"), ("weekdays 07:00", "Weekdays 07:00"),
                                    ("weekly mon,thu 08:00", "Mon, Thu 08:00"), ("every 4h", "Every 4 h"),
                                    ("manual", "On demand")])
def test_schedule_text(runner, s, text):
    assert runner.schedule_text(s) == text


def test_enqueue_dedup_but_events_always_queue(runner):
    c = runner.db()
    assert runner.enqueue(c, "a", "manual") is True
    assert runner.enqueue(c, "a", "manual") is False          # already queued
    assert runner.enqueue(c, "a", "event", event={"kind": "news"}) is True
    assert runner.enqueue(c, "a", "event", event={"kind": "news"}) is False   # the same event again: a loop, not news
    assert runner.enqueue(c, "a", "event", event={"kind": "news", "summary": "price fell"}) is True


@pytest.mark.parametrize("text,paused", [
    ("model call failed: HTTP Error 429: Too Many Requests", True),
    ('{"error":{"type":"usage_limit_reached","message":"The usage limit has been reached"}}', True),
    ("No deployments available for selected model", True),
    ("litellm.RateLimitError: RateLimitError: ChatgptException", True), ("You've hit your limit · resets 3am", True),
    ("KeyError: 'steps'", False), ("planning failed", False), ("", False),
    # review RUN-R3: what a run wrote about limits is no limit (builds #44, #50 and #7 re-ran up to 12 times)
    ("ALL CHECKS PASSED (1051 tests). Fixed the label of builds waiting on a usage limit.", False),
    ("No fault found in the usage-limit waiting label", False), ("Kazakhstan cut its copper export quota", False),
    ("the price watch's cooldown is 6 hours", False)])
def test_paused(runner, text, paused):
    assert runner.paused(text) is paused


def test_create_task_writes_mission_and_queues_first_run(runner):
    c = runner.db()
    r = runner.handle({"action": "create", "type": "task", "title": "Watch lithium prices", "description": "weekly",
                       "schedule": "weekly mon 08:00", "deliver": ["app", "fax"], "run_now": True}, {}, c)
    m = runner.load_missions()[r["slug"]]
    assert (m["type"], m["schedule"], m["deliver"]) == ("task", "weekly mon 08:00", ["app"])
    assert c.execute("select count(*) from runs where slug=? and status='queued'", (r["slug"],)).fetchone()[0] == 1
    events = [json.loads(x) for x in (runner.PUBLIC / "events.jsonl").read_text().splitlines()]
    assert events[-1]["kind"] == "created"


def test_create_refuses_a_duplicate_within_30_minutes(runner):
    c = runner.db()
    first = runner.handle({"action": "create", "type": "task", "title": "Beta Materials investment news", "run_now": False}, {}, c)
    again = runner.handle({"action": "create", "type": "task", "title": "Beta Materials (ASPI) investment news briefing",
                           "run_now": False}, runner.load_missions(), c)
    assert again["duplicate"] is True and again["slug"] == first["slug"]


@pytest.mark.parametrize("req", [
    {"action": "create", "type": "task", "title": "x"},                              # title too short
    {"action": "create", "type": "robot", "title": "Something"},                      # unknown type
    {"action": "create", "type": "task", "title": "Something", "schedule": "often"},  # bad schedule
    {"action": "nuke", "slug": "a"}])
def test_create_and_unknown_actions_are_validated(runner, req):
    with pytest.raises(ValueError):
        runner.handle(req, {"a": {"slug": "a", "title": "A", "type": "task"}}, runner.db())


def test_update_validates_and_resume_skips_catch_up(runner, monkeypatch, at):
    c = runner.db()
    slug = runner.handle({"action": "create", "type": "task", "title": "Some task", "run_now": False}, {}, c)["slug"]
    ms = runner.load_missions()
    with pytest.raises(ValueError):
        runner.handle({"action": "update", "slug": slug, "fields": {"schedule": "sometimes"}}, ms, c)
    r = runner.handle({"action": "update", "slug": slug, "fields": {"schedule": "daily 07:00", "goal": "new goal",
                       "triggers": [{"type": "news", "query": "lithium"}]}}, ms, c)
    assert set(r["changed"]) == {"schedule", "goal", "event triggers"}
    monkeypatch.setattr(runner, "now", lambda: at)
    runner.handle({"action": "pause", "slug": slug}, runner.load_missions(), c)
    runner.handle({"action": "resume", "slug": slug}, runner.load_missions(), c)
    assert runner.load_missions()[slug]["created"] == at.isoformat(timespec="seconds")


def test_slugify_is_unique_and_ascii(runner):
    assert runner.slugify("Uran-Märkte & Öl!", {}) == "uran-maerkte-oel"
    assert runner.slugify("Copper", {"copper": {}}) == "copper-2"


@pytest.mark.parametrize("s,hours,label", [("daily 06:30", 36, "Daily"), ("weekly mon 08:00", 180, "Weekly"),
                                           ("weekly mon,thu 08:00", 96, "Weekly"), ("manual", 36, "Daily")])
def test_a_briefing_reads_the_news_of_its_schedule_s_window(runner, s, hours, label):
    """FND-77: a weekly briefing read only 36 hours of news."""
    assert runner.window_hours(s) == hours and runner.period({"schedule": s}) == label


def test_section_parsing(runner):
    out = "## Result\nfound it\n\n## Notes\n- a\n## Summary\nshort"
    assert runner.section(out, "Result") == "found it"
    assert runner.section(out, "Summary") == "short"
    assert runner.section(out, "Missing") == ""


def test_spend_window_query_window_is_utc(runner, monkeypatch):
    seen = {}
    def fake_sh(*cmd, **kw):
        seen["sql"] = cmd[-1]
        return "3|1200|0|gpt-sub\n"
    monkeypatch.setattr(runner, "sh", fake_sh)
    start = dt.datetime(2026, 10, 27, 7, 0, tzinfo=dt.timezone(dt.timedelta(hours=1)))
    assert runner.calls_of("vk-desk", start, start + dt.timedelta(minutes=5)) == (3, 1200, 0.0, "gpt-sub")
    assert "'2026-10-27 06:00:00'" in seen["sql"] and "key_alias = 'vk-desk'" in seen["sql"]


def test_a_paused_agents_runs_are_skipped(runner, monkeypatch):
    """SWM-26: while the owner has paused the mission agent (or all agents) its runs do not start."""
    import swarm_client as SW
    c = runner.db()
    c.execute("insert into runs (slug, trigger, status, started) values ('u', 'manual', 'queued', ?)", (runner.now().isoformat(),))
    row = c.execute("select * from runs where slug='u'").fetchone()
    monkeypatch.setattr(runner, "event", lambda *a, **k: None)
    monkeypatch.setattr(SW, "paused", lambda agent: agent == "mission")
    runner.execute(c, row, {"u": {"slug": "u", "title": "U", "type": "task"}})
    assert tuple(c.execute("select status, summary from runs where slug='u'").fetchone()) == ("skipped", "paused by the owner")


def test_a_briefing_that_hangs_is_stopped_at_its_deadline(runner, tmp_path, monkeypatch):
    """Review RUN-R16: the loop over the pipeline's output waited for an end that a hung step never gave; one run slot."""
    import time
    ops = tmp_path / "ops"
    ops.mkdir()
    (ops / "desk.sh").write_text("echo starting\nsleep 60\necho filed: never\n")
    monkeypatch.setattr(runner, "OPS", ops)
    monkeypatch.setattr(runner, "TASK_TIMEOUT", 1)
    t0 = time.time()
    state, why, _ = runner.run_briefing({"slug": "u", "topic": "u"}, tmp_path / "run.log")
    assert time.time() - t0 < 20 and state == "failed" and "stopped: the briefing pipeline ran past" in (tmp_path / "run.log").read_text()


def test_one_runner_at_a_time(runner, tmp_path):
    """Review RUN-R26: nothing stopped a second runner, which would run every queued run and build twice."""
    first = runner.single_runner(tmp_path / "runner.lock")
    with pytest.raises(SystemExit):
        runner.single_runner(tmp_path / "runner.lock")
    first.close()
    runner.single_runner(tmp_path / "runner.lock").close()          # free again once the first has gone


def test_a_run_a_restart_cut_off_says_why_and_waits_for_the_stack(runner, monkeypatch):
    """Review RUN-R25: Hermes' stderr and exit code were dropped, so a run cut off by a restart was "failed: no answer"."""
    import types
    monkeypatch.setattr(runner.J, "take", lambda p: p)
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        returncode=1, stdout="", stderr="Error response from daemon: Container 4f2a is restarting, wait until the container is running"))
    out = runner.hermes_z("Do the research")
    status, why, _ = runner.file_task_result({"slug": "u", "title": "U"}, out)
    assert status == "failed" and "Hermes exited 1" in why and runner.stack_gone(why)       # the stack's doing: it waits


def test_a_write_that_fails_on_a_lock_gives_up_its_transaction(tmp_path):
    """Overnight exercise, 8 Nov 2026: a commit failed on a lock and left its write transaction open; every other writer
    in the runner then failed for 40 minutes. A failed write on the runner's connection rolls back."""
    import sqlite3
    import missions as M
    f = tmp_path / "m.sqlite"
    a = sqlite3.connect(f, timeout=0.2, factory=M.Robust)
    a.execute("create table t (x integer)")
    a.execute("insert into t values (1)")
    a.commit()
    reader = sqlite3.connect(f, timeout=0.2)
    cur = reader.execute("select x from t")                                    # a reader that keeps its statement open
    cur.fetchone()
    a.execute("update t set x = 2")                                            # a's write transaction
    try:
        a.commit()                                                             # cannot get past the reader
    except sqlite3.OperationalError:
        pass
    assert not a.in_transaction                                                # given up, not held
    cur.close()
    reader.close()
    other = sqlite3.connect(f, timeout=0.2)
    other.execute("update t set x = 3")                                        # another writer gets through
    other.commit()
    assert other.execute("select x from t").fetchone()[0] == 3


def test_a_burst_of_locks_writes_who_held_what_once(tmp_path, monkeypatch):
    """Overnight 9 Nov 2026 the runner held its database again for half an hour, from inside itself, and nothing said who:
    three lock failures within ten minutes write every thread's stack and each connection in a transaction with the
    code that opened it, at most once an hour."""
    import sqlite3
    import missions as M
    monkeypatch.setattr(M, "DB", tmp_path / "x.db")
    monkeypatch.setattr(M, "LOCKS_SEEN", [])
    monkeypatch.setattr(M, "_stacks_at", [0.0])
    holder = sqlite3.connect(tmp_path / "x.db", factory=M.Robust)
    holder.execute("create table t (x)")
    holder.execute("insert into t values (1)")                  # a write transaction left open
    M.lock_seen(100000.0)
    M.lock_seen(100100.0)
    assert not (tmp_path / "lock-stacks").exists()
    M.lock_seen(100200.0)
    files = list((tmp_path / "lock-stacks").iterdir())
    assert len(files) == 1
    text = files[0].read_text()
    assert "opened by thread" in text and "test_a_burst_of_locks_writes_who_held_what_once" in text and "Every thread:" in text
    M.lock_seen(100300.0)
    assert len(list((tmp_path / "lock-stacks").iterdir())) == 1  # once an hour at most
    holder.rollback()
    holder.close()



def test_a_pass_that_leaves_a_write_open_is_committed_and_named(tmp_path, monkeypatch):
    """10 Nov 2026: the Conductor's connection slept between passes inside a transaction it never committed, and every
    other writer in the runner failed on a lock for 18 minutes. A loop's pause ends the pass: what was left open is
    committed and the log says which write it was."""
    import sqlite3
    import missions as M
    said = []
    monkeypatch.setattr(M, "log", lambda *a: said.append(" ".join(map(str, a))))
    f = tmp_path / "m.sqlite"
    c = sqlite3.connect(f, timeout=0.2, factory=M.Robust)
    c.execute("create table t (x integer)")
    c.commit()

    def a_pass_that_forgets_its_commit(c):
        c.execute("insert into t values (7)")
    a_pass_that_forgets_its_commit(c)
    assert c.in_transaction and c.first_write[0] == "insert into t values (7)"
    assert "a_pass_that_forgets_its_commit" in c.first_write[1]
    other = sqlite3.connect(f, timeout=0.2)
    try:
        other.execute("insert into t values (8)")                 # held: the forgotten write blocks every other writer
        raise AssertionError("the open write should block another writer")
    except sqlite3.OperationalError:
        other.rollback()
    monkeypatch.setattr(M.stop, "wait", lambda s: False)
    M.rest(c, "conductor", 5)
    assert not c.in_transaction and c.first_write is None
    assert any("conductor: a pass left a write uncommitted" in s and "insert into t values (7)" in s
               and "a_pass_that_forgets_its_commit" in s for s in said)
    other.execute("insert into t values (8)")                     # the next writer gets through
    other.commit()
    assert sorted(r[0] for r in other.execute("select x from t")) == [7, 8]
    said.clear()
    M.rest(c, "conductor", 5)                                     # a clean pass says nothing
    assert said == []
    plain = sqlite3.connect(f, timeout=0.2)                       # a plain connection (tests) is committed too
    plain.execute("insert into t values (9)")
    M.rest(plain, "events", 1)
    assert not plain.in_transaction


def test_every_loop_that_keeps_one_connection_rests_through_end_pass():
    """Each runner loop that opens its connection once and keeps it pauses with rest(c, ...), never a bare stop.wait,
    so no pass can leave the database held while the loop sleeps."""
    import ast
    import pathlib
    ops = pathlib.Path(__file__).resolve().parent.parent / "ops"
    loose = []
    for p in sorted(ops.glob("*.py")):
        src = p.read_text()
        lines = src.splitlines()
        for n in ast.walk(ast.parse(src)):
            if not isinstance(n, ast.FunctionDef):
                continue
            body = lines[n.lineno - 1:n.end_lineno]
            loop = next((i for i, l in enumerate(body) if "while not" in l and "stop.is_set()" in l), None)
            keeps = loop is not None and any(l.strip().startswith(("c = M.db()", "c = db()", "c = c or M.db()"))
                                             for l in body[:loop])      # opened once, before the loop (one per pass is closed)
            if keeps:
                bare = [l.strip() for l in body if "stop.wait(" in l]
                rests = [l.strip() for l in body if "rest(c, " in l]
                if bare or not rests:
                    loose.append(f"{p.name}:{n.lineno} {n.name}: {bare or 'no rest(c, ...)'}")
    assert not loose, loose


def test_the_lock_report_names_each_connection_s_open_write(tmp_path, monkeypatch):
    import sqlite3
    import missions as M
    monkeypatch.setattr(M, "DB", tmp_path / "x.db")
    holder = sqlite3.connect(tmp_path / "x.db", factory=M.Robust)
    holder.execute("create table t (x)")
    holder.execute("update t set x = 1 where x = 0")             # the open write
    text = M.lock_stacks().read_text()
    assert "its first open write: update t set x = 1 where x = 0" in text
    assert "test_the_lock_report_names_each_connection_s_open_write" in text
    holder.rollback()
    assert holder.first_write is None
    holder.close()


def test_the_title_repair_commits_what_it_changed(tmp_path):
    """APP-57's repair of cut titles runs in tasks.table(), which every loop calls; it commits its own change instead of
    leaving it open on the caller's connection."""
    import sqlite3
    import tasks as TK
    c = sqlite3.connect(tmp_path / "t.sqlite")
    c.row_factory = sqlite3.Row
    TK.table(c)
    whole = "Find a quiet external drive enclosure for the NAS backup disks and compare the three best on noise"
    c.execute("insert into tasks (text, title, status) values (?,?,?)", (whole, whole[:30] + " …", "planned"))
    c.commit()
    TK.table(c)
    assert not c.in_transaction
    assert not c.execute("select title from tasks").fetchone()[0].endswith("…")

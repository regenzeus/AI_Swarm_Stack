"""ops/missions.py: schedules, request validation, duplicate guard, pause detection, queueing."""
import datetime as dt
import json

import pytest


@pytest.mark.parametrize("s,ok", [
    ("daily 06:30", True), ("weekdays 07:00", True), ("weekly mon,thu 08:15", True), ("every 6h", True),
    ("manual", True), ("daily 24:00", False), ("daily 6:30", False), ("weekly funday 08:00", False),
    ("every 0h", False), ("every 25h", False), ("", False), ("hourly", False)])
def test_valid_schedule(runner, s, ok):
    assert runner.valid_schedule(s) is ok


def test_due_times_and_next(runner, at):
    days = runner.due_times("weekdays 07:00", at)
    assert all(d.weekday() < 5 and d.hour == 7 for d in days)
    assert runner.next_due("daily 06:30", at) == at.replace(day=28, hour=6, minute=30)
    assert runner.next_due("weekly fri 09:00", at).weekday() == 4
    assert runner.next_due("manual", at) is None
    assert {d.hour for d in runner.due_times("every 6h", at)} == {0, 6, 12, 18}


@pytest.mark.parametrize("s,text", [("daily 06:30", "Daily 06:30"), ("weekdays 07:00", "Weekdays 07:00"),
                                    ("weekly mon,thu 08:00", "Mon, Thu 08:00"), ("every 4h", "Every 4 h"),
                                    ("manual", "On demand")])
def test_schedule_text(runner, s, text):
    assert runner.schedule_text(s) == text


def test_check_schedules_catches_up_once_and_not_before_created(runner, at, monkeypatch):
    monkeypatch.setattr(runner, "now", lambda: at)
    c = runner.db()
    m = {"slug": "u", "status": "active", "schedule": "daily 06:30", "created": "2026-10-20T00:00:00+00:00"}
    runner.check_schedules({"u": m}, c)
    runner.check_schedules({"u": m}, c)                       # same due time: no second run
    rows = c.execute("select trigger, due from runs").fetchall()
    assert [r["trigger"] for r in rows] == ["schedule"]
    new = dict(m, slug="n", created=at.isoformat())          # created after today's 06:30: nothing to catch up
    runner.check_schedules({"n": new}, c)
    assert c.execute("select count(*) from runs where slug='n'").fetchone()[0] == 0


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
    ("KeyError: 'steps'", False), ("planning failed", False), ("", False)])
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
    first = runner.handle({"action": "create", "type": "task", "title": "ASP Isotopes investment news", "run_now": False}, {}, c)
    again = runner.handle({"action": "create", "type": "task", "title": "ASP Isotopes (ASPI) investment news briefing",
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
    assert runner.slugify("Uranium", {"uranium": {}}) == "uranium-2"


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

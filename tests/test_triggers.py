"""ops/mission_extras.py: trigger validation and the event watcher (baseline first, then fire once)."""
import json
import types

import pytest


def test_clean_triggers(runner):
    import mission_extras as X
    t = X.clean_triggers([{"type": "sec_filing", "tickers": ["aspi", "bad ticker!"]},
                          {"type": "price_move", "symbol": "acme", "pct": 8},
                          {"type": "news", "query": "  Beta Materials  "}])
    assert t[0] == {"type": "sec_filing", "tickers": ["ASPI"], "forms": X.DEFAULT_FORMS}
    assert t[1] == {"type": "price_move", "symbol": "ACME", "pct": 8.0}
    assert t[2]["query"] == "Beta Materials"
    assert X.trigger_text(t[1]) == "ACME moves ±8 % in a day"


@pytest.mark.parametrize("bad", [[{"type": "sec_filing", "tickers": []}], [{"type": "price_move", "symbol": "ACME", "pct": 90}],
                                 [{"type": "news", "query": "x"}], [{"type": "weather"}]])
def test_clean_triggers_rejects(runner, bad):
    import mission_extras as X
    with pytest.raises(ValueError):
        X.clean_triggers(bad)


def test_check_events_baseline_then_fire(runner, monkeypatch):
    import mission_extras as X
    filings = [{"id": "0001-26-000001", "form": "8-K", "filed": "2026-10-26T12:00:00", "title": "Beta Materials filed 8-K", "url": "https://sec.gov/x"}]
    watch = {"sec": {"ASPI": filings}, "prices": {"ASPI": {"last": 2.2, "prev": 2.0, "pct": 10.0, "currency": "USD", "date": "2026-10-27"}},
             "news": {}}
    monkeypatch.setattr(X.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=json.dumps(watch), stderr=""))
    m = {"slug": "aspi", "title": "ASPI", "status": "active",
         "triggers": [{"type": "sec_filing", "tickers": ["ASPI"], "forms": ["8-K"]}, {"type": "price_move", "symbol": "ASPI", "pct": 8}]}
    c = runner.db()
    X._last_watch["t"] = 0
    X.check_events({"aspi": m}, c)                           # first look: only remember what exists
    assert c.execute("select count(*) from runs").fetchone()[0] == 0
    filings.append({"id": "0001-26-000002", "form": "8-K", "filed": "2026-10-27T09:00:00", "title": "Beta Materials filed 8-K again", "url": "https://sec.gov/y"})
    X._last_watch["t"] = 0
    X.check_events({"aspi": m}, c)
    rows = [json.loads(r["event"]) for r in c.execute("select event from runs where trigger='event'")]
    assert [r["kind"] for r in rows] == ["sec_filing"]       # the new filing; the 10 % move was already seen at baseline
    assert "again" in rows[0]["summary"]
    X._last_watch["t"] = 0
    X.check_events({"aspi": m}, c)                           # nothing new: no more runs
    assert c.execute("select count(*) from runs where trigger='event'").fetchone()[0] == 1


def test_a_task_s_trigger_starts_the_task_s_next_run_not_a_mission_run(runner, monkeypatch):
    """TSK-21: an event-triggered task under the Conductor is watched with the missions' triggers; its event is queued
    for the task's next occurrence."""
    import mission_extras as X
    import tasks as TK
    news = [{"id": "n1", "title": "Acme Mining signs a supply deal", "url": "https://news.example/1"}]
    monkeypatch.setattr(X.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=json.dumps({"sec": {}, "prices": {}, "news": {"Acme Mining": news}}), stderr=""))
    c = runner.db()
    TK.table(c)
    t0 = TK.now()
    tid = c.execute("insert into tasks (text, title, goal, kind, door, ref, done, effort, autonomy, rhythm, spec, questions, answers, status, source, created, updated) "
                    "values ('x','Acme Mining deals','say what it means','research','plan','1','[\"names the deal\"]','standard','auto',?,'{}','[]','[]','scheduled','app',?,?)",
                    (json.dumps({"type": "event", "triggers": [{"type": "news", "query": "Acme Mining"}]}), t0, t0)).lastrowid
    c.commit()
    X._last_watch["t"] = 0
    X.check_events({}, c)                                    # first look: only remember what exists
    news.append({"id": "n2", "title": "Acme Mining signs again", "url": "https://news.example/2"})
    X._last_watch["t"] = 0
    X.check_events({}, c)
    evs = [json.loads(r["event"]) for r in c.execute("select event from task_events where task=?", (tid,))]
    assert [e["summary"] for e in evs] == ["1 new article(s) about “Acme Mining”: Acme Mining signs again"] and evs[0]["trigger"] == "News about “Acme Mining”"
    assert c.execute("select count(*) from runs").fetchone()[0] == 0

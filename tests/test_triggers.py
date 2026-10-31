"""ops/mission_extras.py: trigger validation and the event watcher (baseline first, then fire once)."""
import json
import types

import pytest


def test_clean_triggers(runner):
    import mission_extras as X
    t = X.clean_triggers([{"type": "sec_filing", "tickers": ["aspi", "bad ticker!"]},
                          {"type": "price_move", "symbol": "ccj", "pct": 8},
                          {"type": "news", "query": "  ASP Isotopes  "}])
    assert t[0] == {"type": "sec_filing", "tickers": ["ASPI"], "forms": X.DEFAULT_FORMS}
    assert t[1] == {"type": "price_move", "symbol": "CCJ", "pct": 8.0}
    assert t[2]["query"] == "ASP Isotopes"
    assert X.trigger_text(t[1]) == "CCJ moves ±8 % in a day"


@pytest.mark.parametrize("bad", [[{"type": "sec_filing", "tickers": []}], [{"type": "price_move", "symbol": "CCJ", "pct": 90}],
                                 [{"type": "news", "query": "x"}], [{"type": "weather"}]])
def test_clean_triggers_rejects(runner, bad):
    import mission_extras as X
    with pytest.raises(ValueError):
        X.clean_triggers(bad)


def test_check_events_baseline_then_fire(runner, monkeypatch):
    import mission_extras as X
    filings = [{"id": "0001-26-000001", "form": "8-K", "filed": "2026-10-26T12:00:00", "title": "Asp Isotopes filed 8-K", "url": "https://sec.gov/x"}]
    watch = {"sec": {"ASPI": filings}, "prices": {"ASPI": {"last": 2.2, "prev": 2.0, "pct": 10.0, "currency": "USD", "date": "2026-10-27"}},
             "news": {}}
    monkeypatch.setattr(X.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=json.dumps(watch), stderr=""))
    m = {"slug": "aspi", "title": "ASPI", "status": "active",
         "triggers": [{"type": "sec_filing", "tickers": ["ASPI"], "forms": ["8-K"]}, {"type": "price_move", "symbol": "ASPI", "pct": 8}]}
    c = runner.db()
    X._last_watch["t"] = 0
    X.check_events({"aspi": m}, c)                           # first look: only remember what exists
    assert c.execute("select count(*) from runs").fetchone()[0] == 0
    filings.append({"id": "0001-26-000002", "form": "8-K", "filed": "2026-10-27T09:00:00", "title": "Asp Isotopes filed 8-K again", "url": "https://sec.gov/y"})
    X._last_watch["t"] = 0
    X.check_events({"aspi": m}, c)
    rows = [json.loads(r["event"]) for r in c.execute("select event from runs where trigger='event'")]
    assert [r["kind"] for r in rows] == ["sec_filing"]       # the new filing; the 10 % move was already seen at baseline
    assert "again" in rows[0]["summary"]
    X._last_watch["t"] = 0
    X.check_events({"aspi": m}, c)                           # nothing new: no more runs
    assert c.execute("select count(*) from runs where trigger='event'").fetchone()[0] == 1

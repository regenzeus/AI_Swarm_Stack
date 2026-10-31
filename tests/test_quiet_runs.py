"""An empty briefing stays in the app (MIS-15, FND-60): no Telegram and no e-mail for a run the desk chose no news for;
the next full delivery names the quiet days instead."""
import json

EMPTY = """---
topic: job-report
date: 2026-10-30
type: daily-briefing
headline: "First briefing: no verified vacancies to rank"
stats: {"items": 0, "new": 0, "events": 0, "chosen": 0, "sources": 0}
---

# First briefing: no verified vacancies to rank
"""


def test_a_briefing_with_no_news_chosen_is_empty_and_prices_alone_do_not_count(runner):
    import mission_extras as X
    assert X.briefing_empty(EMPTY)
    assert not X.briefing_empty(EMPTY.replace('"chosen": 0', '"chosen": 3'))
    assert not X.briefing_empty("# a mission log without stats")


def test_an_empty_run_is_not_sent_and_the_next_full_one_names_its_day(runner, monkeypatch):
    import mission_extras as X
    sent = []
    monkeypatch.setattr(X, "telegram", lambda text, buttons=(): sent.append(("telegram", text)) or True)
    monkeypatch.setattr(X, "email", lambda subject, md, kicker, url: sent.append(("email", kicker)))
    m = {"slug": "job-report", "title": "Job report", "deliver": ["app", "telegram", "email"]}
    assert X.deliver(m, "No vacancies", "short", "topics/job-report/2026-10-30.md", "Daily briefing · 30 Oct 2026", EMPTY, empty=True) is False
    assert sent == []
    day = f"{runner.now():%d %b}"
    assert json.loads(X.quiet_file().read_text()) == {"job-report": [day]}
    assert X.deliver(m, "Three roles", "short", "topics/job-report/2026-10-31.md", "Daily briefing · 31 Oct 2026", "# full") is True
    assert [k for k, _ in sent] == ["telegram", "email"]
    assert f"Daily briefing · 31 Oct 2026 · nothing new on {day}" in sent[0][1] and sent[1][1].endswith(f"nothing new on {day}")
    assert json.loads(X.quiet_file().read_text()) == {}                       # named once, then forgotten
    X.deliver(m, "Again", "short", "p", "Daily briefing · 1 Nov 2026", "# full")
    assert "nothing new" not in sent[2][1]


def test_the_briefing_run_asks_whether_the_report_is_empty():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "ops/missions.py").read_text()
    assert "empty=X.briefing_empty(text)" in src and "Nothing new: kept in the app" in src

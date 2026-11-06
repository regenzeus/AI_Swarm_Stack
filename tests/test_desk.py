"""images/desk/desk.py: text helpers that need no network (filed-release text, SSRF guard, the English price table)."""
import pytest


def test_release_text_skips_filing_boilerplate(desk):
    t = "EX-99.1 2 x.htm EX-99.1 Exhibit 99.1. NEWS RELEASE. Acme Mining reports record output. Production rose 5%."
    assert desk.release_text(t).startswith("Acme Mining reports record output.")


@pytest.mark.parametrize("url,ok", [("http://127.0.0.1/x", False), ("http://192.168.1.10:3000/", False),
                                    ("file:///etc/passwd", False), ("ftp://example.com", False)])
def test_public_url_refuses_private_targets(desk, url, ok):
    assert desk.public_url(url) is ok


def test_every_briefing_is_english_even_for_a_topic_once_marked_german(desk):
    """DEC-02, CST-09, FND-21: no German path is left; the price table is English."""
    t = desk.price_table([{"name": "Copper", "symbol": "SRUUF", "last": 1234.5, "currency": "USD", "day": 1.25, "month": -3.0, "proxy": "spot"}])
    assert "| Copper (spot proxy) · SRUUF | 1,234.50 USD | +1.2 % | -3.0 % |" in t and "Kurs" not in t and "Näherung" not in t
    assert not hasattr(desk, "german") and "Preise" not in open(desk.__file__).read()


def test_the_price_note_names_proxies_only_when_a_row_is_one(desk):
    """FND-77: a car-makers' table carried the copper briefing's note on the Sprott trust."""
    t = desk.price_table([{"name": "BYD", "symbol": "1211.HK", "last": 68.25, "currency": "HKD", "day": -0.6, "month": -9.7, "proxy": ""}])
    assert t.endswith("_Closing prices, source Yahoo Finance._") and "Sprott" not in t and "proxy" not in t


def test_google_news_searches_in_the_query_s_language_over_the_brief_s_window(desk):
    """FND-77: Chinese queries went to US-English Google News with when:1d added to their own when:7d."""
    import urllib.parse as up
    zh = up.unquote(desk.gnews_url("中国 汽车 (销量 OR 出口) when:7d", 180))
    assert "hl=zh-CN&gl=CN&ceid=CN:zh-Hans" in zh and zh.count("when:") == 1 and "when:7d" in zh
    assert "when:7d" in up.unquote(desk.gnews_url("Acme Mining copper", 180)) and "hl=en-US" in desk.gnews_url("Acme Mining copper")
    assert "when:1d" in up.unquote(desk.gnews_url("Acme Mining", 36)) and "hl=de" in desk.gnews_url("Uran Preis")


def test_the_email_puts_the_headline_in_its_header_and_fits_a_phone(desk, monkeypatch, capsys):
    """FND-79: the blank line after the front matter hid the headline, so the kicker showed twice and the headline came
    as an unstyled giant h1; a fixed 640 px table made phone apps scale the text up."""
    import json, sys, types
    monkeypatch.setitem(sys.modules, "markdown", types.SimpleNamespace(markdown=lambda t, extensions=(): "<p>" + t + "</p>"))
    report = "---\ntopic: x\ndate: 2026-10-31\n---\n\n# Battery Recycling Weekly | Oct 24–31\n\n**In 60 seconds:** VW profit fell.\n"
    desk.email({"markdown": report, "kicker": "Weekly briefing · 31 Oct 2026", "url": "https://app/#/read"})
    h = json.loads(capsys.readouterr().out)["html"]
    assert ">Battery Recycling Weekly | Oct 24–31</div>" in h and "# China" not in h and h.count("Weekly briefing · 31 Oct 2026") == 1
    assert 'name="viewport"' in h and 'width="640"' not in h and "max-width:640px" in h


def test_the_collected_events_survive_the_hand_over_and_each_finding_cites_its_links(desk):
    """TSK-22: the collecting step saves its chosen events for the writing step (times and all), and each scout's
    finding becomes an event whose sources are the links it names."""
    import datetime as dt, json
    when = dt.datetime(2026, 10, 30, 8, 0, tzinfo=dt.timezone.utc)
    chosen = [({"words": {"vw", "profit"}, "items": [{"title": "VW profit", "url": "https://caixin.com/1", "source": "财新", "published": when}],
                "text": "VW's profit fell."}, {"questions": [1]})]
    back = desk.thaw(json.loads(json.dumps(desk.freeze(chosen))))
    assert back[0][0]["items"][0]["published"] == when and back[0][1] == {"questions": [1]} and back[0][0]["text"] == "VW's profit fell."
    ev = desk.research_events([{"question": "Who sells most EVs abroad?", "text": "BYD leads exports (https://cpca.cn/a.html). See also https://x.cn/b."},
                               {"question": "Recalls?", "text": "No recall this week."}])
    assert [it["url"] for it in ev[0][0]["items"]] == ["https://cpca.cn/a.html", "https://x.cn/b"] and ev[0][0]["text"].startswith("BYD leads")
    assert ev[1][0]["items"][0]["title"] == "Research: Recalls?" and ev[1][0]["items"][0]["url"] == ""


def test_a_weekly_brief_keeps_a_week_of_news_and_a_daily_one_36_hours(desk):
    import datetime as dt, sqlite3
    db = sqlite3.connect(":memory:")
    db.execute("create table seen (id text primary key, first_seen text, title text)")
    old = [{"title": f"News {d} days ago about BYD sales", "url": f"https://x.cn/{d}", "source": "x", "summary": "", "via": "gnews",
            "published": desk.NOW - dt.timedelta(days=d)} for d in (1, 3, 6)]
    desk.WINDOW_H = 36
    assert len(desk.events([dict(i) for i in old], db)[0]) == 1
    desk.WINDOW_H = 180
    assert len(desk.events([dict(i) for i in old], db)[0]) == 3

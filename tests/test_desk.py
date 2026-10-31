"""images/desk/desk.py: text helpers that need no network (filed-release text, SSRF guard, the English price table)."""
import pytest


def test_release_text_skips_filing_boilerplate(desk):
    t = "EX-99.1 2 x.htm EX-99.1 Exhibit 99.1. NEWS RELEASE. Cameco reports record output. Production rose 5%."
    assert desk.release_text(t).startswith("Cameco reports record output.")


@pytest.mark.parametrize("url,ok", [("http://127.0.0.1/x", False), ("http://192.168.1.80:3000/", False),
                                    ("file:///etc/passwd", False), ("ftp://example.com", False)])
def test_public_url_refuses_private_targets(desk, url, ok):
    assert desk.public_url(url) is ok


def test_every_briefing_is_english_even_for_a_topic_once_marked_german(desk):
    """DEC-02, CST-09, FND-21: no German path is left; the price table is English."""
    t = desk.price_table([{"name": "Uranium", "symbol": "SRUUF", "last": 1234.5, "currency": "USD", "day": 1.25, "month": -3.0, "proxy": "spot"}])
    assert "| Uranium (spot proxy) · SRUUF | 1,234.50 USD | +1.2 % | -3.0 % |" in t and "Kurs" not in t and "Näherung" not in t
    assert not hasattr(desk, "german") and "Preise" not in open(desk.__file__).read()

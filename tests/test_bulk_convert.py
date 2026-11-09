"""converters/bulk_convert.py: a mail's body is kept up to a real quoted reply, and a long one is cut with a marker
(review IMG-R9: a "From:" line in a mail's own text dropped the rest, and bodies were cut at 20,000 characters silently)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "converters"))
import bulk_convert as B  # noqa: E402


def test_a_mail_body_stops_only_at_a_real_quote_and_a_long_one_says_it_was_cut():
    own = "Hi,\n\nFrom: the shop's form we got this:\nplease call back.\n\nBest"
    assert "please call back." in B.clean_body(own)
    outlook = "Thanks!\n\nFrom: Anna <anna@example.com>\nSent: Monday\nTo: me\nSubject: x\n\nold text"
    assert B.clean_body(outlook) == "Thanks!"
    assert B.clean_body("Ok\n\nAm 3. Nov. 2026 schrieb Ben:\n> old") == "Ok"
    long = "a" * (B.MAX_BODY + 500)
    body = B.clean_body(long, "mail/all.mbox")
    assert body.startswith("a" * B.MAX_BODY) and "500 more characters cut" in body and "mail/all.mbox" in body
    assert B.clean_body("short") == "short"

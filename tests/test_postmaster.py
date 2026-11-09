"""ops/postmaster.py (CNX-08): only the stack's own mail moves, by its exact sender, and the owner hears about the copy."""
import pysrc
import webjs
import json
import time
import types
from pathlib import Path

import pytest

import postmaster as PM

ROOT = Path(__file__).resolve().parent.parent
ME = "me" + "@example.com"


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("GMAIL_ADDRESS", ME)
    monkeypatch.setattr(PM, "OUT", tmp_path)
    saved = {}
    monkeypatch.setattr(PM, "C", types.SimpleNamespace(agent_file=lambda a: dict(saved), save=lambda a, **k: saved.update(k)))
    monkeypatch.setattr(PM.IN, "granted", lambda scope="read": True)
    return saved


def row(sender, subject="A report", date="Thu, 05 Nov 2026 10:00:00 +0100"):
    return {"id": "1", "from": sender, "subject": subject, "date": date}


def test_only_the_stack_s_exact_sender_counts_as_its_mail(env):
    assert PM.own(row("AI Stack <" + ME + ">"))
    assert not PM.own(row(ME), )                              # what the owner mails himself: papers, tickets
    assert not PM.own(row("Me <" + ME + ">", "Steuerbescheinigung.pdf"))
    assert not PM.own(row("AI Stack <news" + "@other.example>"))     # someone else calling himself that
    assert not PM.own(row("Jenova AI <c" + "@jenova.example>", "Your AI stack"))
    assert PM.own(row(ME, "Mission Control: e-mail works"))   # the setup's test mail, by its exact subject


LINE = "- id 1852 · Thu, 05 Nov 2026 10:00:00 +0100 · AI Stack <" + ME + "> · Boss reports · unread · 77 KB · PROTECTED (bank/security)\n"


def test_the_listing_is_read_with_a_protected_mark_too():
    r = PM.rows_of("3 messages match in all; newest 3:\n" + LINE)
    assert r and r[0]["id"] == "1852" and r[0]["from"] == "AI Stack <" + ME + ">" and r[0]["subject"] == "Boss reports"


def test_a_row_continued_over_two_lines_is_read_whole():
    """8 Nov 2026: two of the stack's mails had folded subjects; the row went on over a line starting with a space, none
    of the day's rows parsed, and (since IMG-R3) every hourly run stopped."""
    text = ("2 messages match in all; newest 2:\n"
            "- id 1858 · Fri, 06 Nov 2026 07:02:11 -0800 (PST) · AI Stack <" + ME + "> · Price watch: Centrus LEU 4.1%;\n"
            " enrichment back to normal [… 31 more characters cut] · 9 KB\n"
            "- id 1859 · Fri, 06 Nov 2026 08:02:11 -0800 (PST) · AI Stack <" + ME + "> · Weekly · 12 KB\n")
    rows = PM.rows_of(text)
    assert [r["id"] for r in rows] == ["1858", "1859"] and rows[0]["subject"].startswith("Price watch: Centrus LEU 4.1%; enrichment")
    with pytest.raises(RuntimeError, match="0 rows of the listing could be read"):
        import datetime as dt
        PM.stack_mail(dt.date.today().strftime("%Y/%m/%d"), lambda n, a: "2 messages match in all; newest 2:\n- garbled\n- garbled\n")


def test_the_mail_tool_unfolds_a_long_header():
    src =(ROOT / "images/mail/mail.py").read_text()
    fn = src[src.index("def hdr(v):"):src.index("def fetch_headers")]
    ns = {"email": __import__("email.header"), "re": __import__("re")}
    exec(fn, ns)
    assert ns["hdr"]("Price watch: Centrus LEU 4.1%;\r\n enrichment back") == "Price watch: Centrus LEU 4.1%; enrichment back"


def test_more_mail_than_the_tool_lists_is_read_day_by_day(env, monkeypatch):
    """Review IMG-R3: one search read the newest 100 and the rest were missed without a word."""
    import datetime as dt
    days = []

    def tool(name, args):
        q = args["query"]
        if "before:" not in q:
            return "250 messages match in all; newest 100:\n" + LINE * 100
        days.append(q.split("after:")[1].split()[0])
        return "1 messages match in all; newest 1:\n" + LINE
    since = (dt.date.today() - dt.timedelta(days=2)).strftime("%Y/%m/%d")
    assert len(PM.stack_mail(since, tool)) == 3 and len(days) == 3          # the two days before today, and today
    with pytest.raises(RuntimeError, match="more than the mail tool lists"):
        PM.stack_mail(since, lambda name, args: "150 messages match in all; newest 100:\n" + LINE * 100)


def test_new_stack_mail_is_filed_and_older_mail_waits_for_the_owner(env, monkeypatch):
    env["since"] = time.time() - 3600
    new = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(time.time() - 60))
    old = "Thu, 05 Nov 2026 10:00:00 +0100"
    listing = (f"- id 2 · {new} · AI Stack <{ME}> · New report · 77 KB\n- id 3 · {old} · AI Stack <{ME}> · Old report · 77 KB\n"
               f"- id 4 · {new} · {ME} · Steuerbescheinigung.pdf · 300 KB\n")
    calls = []

    def tool(name, args):
        calls.append((name, args))
        return listing if name == "mail-mail_search" else "ok"

    monkeypatch.setattr(PM, "call", tool)
    monkeypatch.setattr(PM, "fetch", lambda name: None)
    assert PM.run(None) == 0
    moved = [a for n, a in calls if n == "mail-mail_label"]
    assert moved == [{"ids": ["2"], "label": "AI Stack"}] and ("mail-mail_archive", {"ids": ["2"]}) in calls
    # only what is still in the inbox needs filing: 8 Nov 2026 a day of 102 self-mails stopped every hourly run
    assert all(a["query"].endswith(" in:inbox") for n, a in calls if n == "mail-mail_search")
    calls.clear()
    PM.run(None)                                             # filed once
    assert not [a for n, a in calls if n == "mail-mail_label"]
    assert not any(n == "mail-mail_trash" for n, _ in calls)


def test_the_past_is_only_listed_until_the_owner_says_so(env, capsys):
    calls = []

    def tool(name, args):
        calls.append(name)
        return f"- id 3 · Thu, 05 Nov 2026 10:00:00 +0100 · AI Stack <{ME}> · Old report · 77 KB\n" if name == "mail-mail_search" else "ok"

    PM.past("list", tool)
    assert calls == ["mail-mail_search"] and "Old report" in capsys.readouterr().out
    PM.past("file", tool)
    assert "mail-mail_label" in calls and "mail-mail_archive" in calls


def test_without_a_grant_nothing_moves_and_it_says_so(env, monkeypatch):
    monkeypatch.setattr(PM.IN, "granted", lambda scope="read": scope != "organize")
    monkeypatch.setattr(PM, "call", lambda *a: pytest.fail("no mail tool without the grant"))
    monkeypatch.setattr(PM, "fetch", lambda name: None)
    PM.run(None)
    assert "not granted" in env["result"]


def test_the_copy_s_files_come_over_whole_and_a_bad_one_changes_nothing(env):
    good = {"at": 1, "state": "copying", "total": 5, "copied": 2}
    assert PM.bring_over(lambda n: json.dumps(good) if n == "status.json" else None)["copied"] == 2
    with pytest.raises(ValueError):
        PM.bring_over(lambda n: '{"at": 1, "sta')
    assert json.loads((PM.OUT / "status.json").read_text())["copied"] == 2


def test_the_owner_hears_of_a_stopped_copy_and_of_the_end_of_the_first_one(env):
    sent = []
    send = lambda text, key: sent.append((key, text))
    now = 1_000_000.0
    st = {"at": now, "state": "failed", "why": "Gmail refused the app password", "total": 10, "copied": 2}
    assert "failed" in PM.say_copy(st, {}, now, send) and sent[-1][0] == "mailvault:failed"
    assert "refused" in sent[-1][1]
    PM.say_copy({**st, "state": "copying", "at": now - PM.STALE_S - 3600}, {}, now, send)
    assert sent[-1][0] == "mailvault:stale"
    sent.clear()
    assert "waits" in PM.say_copy({**st, "state": "waiting", "at": now}, {}, now, send) and not sent
    assert "of 10" in PM.say_copy({**st, "state": "copying", "at": now}, {}, now, send) and not sent
    PM.say_copy({**st, "state": "current", "at": now, "copied": 10}, {}, now, send)
    assert sent[-1][0] == "mailvault:done"
    sent.clear()
    PM.say_copy({**st, "state": "current", "at": now, "copied": 10}, {"copy_done": now}, now, send)
    assert not sent


def test_the_connector_files_the_stack_s_own_mail_though_its_subject_looks_protected():
    src = (ROOT / "images/mail/mail.py").read_text()
    assert 'if op == "archive" and protected(it) and not stack_mail(it):' in src


def test_the_app_shows_the_copy_and_the_report():
    app = webjs.app_js()
    assert "async function vMail()" in app and "mail: vMail" in app
    server = pysrc.server()
    assert 'Route("/api/mail", api_mail)' in server

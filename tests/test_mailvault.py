"""nas/mailvault/vault.py (CNX-07): the mail copy: one way, read-only, checked, nothing ever deleted. With a fake Gmail."""
import gzip
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("vault", ROOT / "nas/mailvault/vault.py")
V = importlib.util.module_from_spec(spec)
sys.modules["vault"] = V
spec.loader.exec_module(V)
ME = "me" + "@example.com"


def mail(sender, subject="Hello", to=ME, extra=""):
    return f"From: {sender}\r\nTo: {to}\r\nSubject: {subject}\r\n{extra}\r\nThe text.\r\n".encode()


class FakeGmail:
    """All Mail with X-GM attributes. It refuses every command that could change a mail: the copy must never send one."""
    def __init__(self, msgs):
        self.msgs = msgs                                 # uid -> {id, raw, labels, seen, thread, cat}
        self.readonly = None

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\All \\HasNoChildren) "/" "[Gmail]/Alle Nachrichten"']

    def login(self, a, p):
        return "OK", []

    def select(self, name, readonly=False):
        self.readonly = readonly
        assert readonly, "All Mail must be opened read-only"
        return "OK", [b"1"]

    def response(self, name):
        return name, [b"7"]

    def logout(self):
        return "BYE", []

    def uid(self, cmd, *a):
        assert cmd in ("SEARCH", "FETCH"), f"{cmd} could change Gmail"
        if cmd == "SEARCH":
            if a[0] == "X-GM-RAW":
                cat = a[1].strip('"').split(":")[1]
                return "OK", [" ".join(str(u) for u, m in self.msgs.items() if m.get("cat") == cat).encode()]
            low = int(re.search(r"UID (\d+):", a[1])[1])
            return "OK", [" ".join(str(u) for u in sorted(self.msgs) if u >= low).encode()]
        which, what = a
        assert "BODY[" not in what, "a read that is no PEEK marks a mail as read"
        uids = sorted(self.msgs) if which == "1:*" else [int(x) for x in which.split(",")]
        out = []
        for u in uids:
            if u not in self.msgs:
                continue
            m = self.msgs[u]
            flags = "\\Seen" if m.get("seen") else ""
            meta = f'{u} (X-GM-THRID {m.get("thread", 1)} X-GM-MSGID {m["id"]} X-GM-LABELS ({m.get("labels", "")}) UID {u} FLAGS ({flags}) RFC822.SIZE {len(m["raw"])} INTERNALDATE "05-Nov-2026 10:00:00 +0000" '
            if "BODY.PEEK[]" in what:
                out += [(f'{u} (X-GM-MSGID {m["id"]} UID {u} BODY[] {{{len(m["raw"])}}}'.encode(), m["raw"]), b")"]
            elif "HEADER.FIELDS" in what:
                head = m["raw"].split(b"\r\n\r\n")[0] + b"\r\n\r\n"
                out += [((meta + f"BODY[HEADER.FIELDS] {{{len(head)}}}").encode(), head), b")"]
            else:
                out.append((meta + ")").encode())
        return "OK", out


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "DATA", tmp_path)
    msgs = {1: {"id": "101", "raw": mail("Shop <news" + "@shop.example>", "Sale", extra="List-Unsubscribe: <x>\r\n"), "cat": "promotions", "labels": '"\\\\Inbox"'},
            2: {"id": "102", "raw": mail("Anna <anna" + "@example.com>", "Lunch"), "seen": 1, "cat": "primary", "labels": '"\\\\Inbox"'},
            3: {"id": "103", "raw": mail("Me <" + ME + ">", "Re: Lunch", to="anna" + "@example.com"), "seen": 1, "cat": "primary", "labels": '"\\\\Sent"'}}
    g = FakeGmail(msgs)
    monkeypatch.setattr(V, "connect", lambda a, p: g)
    return type("B", (), {"g": g, "msgs": msgs, "c": V.db()})


def test_every_mail_is_copied_exactly_and_can_be_checked(box):
    V.one_pass(box.c, ME, "pw")
    rows = box.c.execute("select * from messages order by uid").fetchall()
    assert [r["id"] for r in rows] == ["101", "102", "103"]
    for r in rows:
        raw = box.msgs[r["uid"]]["raw"]
        with gzip.open(V.DATA / r["path"]) as f:
            assert f.read() == raw
        assert r["sha256"] == hashlib.sha256(raw).hexdigest()
    assert rows[0]["sender"] == "Shop" and rows[0]["addr"] == "news" + "@shop.example" and rows[0]["list"] == 1 and rows[0]["seen"] == 0


def test_the_second_pass_fetches_only_what_is_new(box):
    V.one_pass(box.c, ME, "pw")
    before = V.spent(box.c)
    box.msgs[4] = {"id": "104", "raw": mail("New <n" + "@x.example>"), "labels": ""}
    V.one_pass(box.c, ME, "pw")
    assert box.c.execute("select count(*) from messages where path is not null").fetchone()[0] == 4
    assert V.spent(box.c) - before < 400                     # one message, not all four again


def test_a_mail_that_leaves_gmail_stays_on_the_nas_marked_as_gone(box):
    V.one_pass(box.c, ME, "pw")
    path = V.DATA / box.c.execute("select path from messages where id='101'").fetchone()[0]
    del box.msgs[1]
    V.refresh(box.c, box.g)
    r = box.c.execute("select * from messages where id='101'").fetchone()
    assert r["gone"] and path.exists()
    box.msgs[1] = {"id": "101", "raw": mail("Shop <news" + "@shop.example>", "Sale")}
    V.refresh(box.c, box.g)
    assert box.c.execute("select gone from messages where id='101'").fetchone()[0] is None   # it came back from Trash


def test_a_broken_answer_marks_nothing_as_gone(box):
    V.one_pass(box.c, ME, "pw")
    box.msgs.clear()
    V.refresh(box.c, box.g)
    assert box.c.execute("select count(*) from messages where gone is not null").fetchone()[0] == 0


def test_the_daily_allowance_is_kept_and_the_rest_follows_tomorrow(box, monkeypatch):
    size = sum(len(m["raw"]) for m in box.msgs.values())
    V.new_headers(box.c, box.g)
    monkeypatch.setattr(V, "DAILY_BYTES", V.spent(box.c) + size // 2)
    assert V.copy_bodies(box.c, box.g) < 3
    monkeypatch.setattr(V, "DAILY_BYTES", 2_000_000_000)
    assert V.copy_bodies(box.c, box.g) >= 1
    assert box.c.execute("select count(*) from messages where path is null").fetchone()[0] == 0


def test_the_allowance_stays_under_google_s_limit():
    assert V.DAILY_BYTES < 2_500_000_000


def test_a_bad_copy_is_never_kept(box, monkeypatch):
    V.new_headers(box.c, box.g)
    row = box.c.execute("select * from messages where id='101'").fetchone()
    box.msgs[row["uid"]]["raw"] += b"more than Gmail said"
    with pytest.raises(RuntimeError, match="Gmail says"):
        V.copy_one(box.c, box.g, row)
    assert box.c.execute("select path from messages where id='101'").fetchone()[0] is None


def test_the_census_says_who_writes_and_whom_you_answer_from_headers_alone(box):
    V.new_headers(box.c, box.g)
    V.refresh(box.c, box.g)
    V.census(box.c, ME)
    rows = {r["addr"]: r for r in json.loads((V.DATA / "census.json").read_text())["senders"]}
    assert rows["news" + "@shop.example"]["list"] == 1 and rows["news" + "@shop.example"]["unread"] == 1 and rows["news" + "@shop.example"]["wrote_to"] == 0
    assert rows["news" + "@shop.example"]["category"] == "promotions"
    assert rows["anna" + "@example.com"]["wrote_to"] == 1 and rows["anna" + "@example.com"]["unread"] == 0
    assert "The text" not in (V.DATA / "census.json").read_text()      # no message text


def test_a_refused_password_is_said_not_asked_again_at_once(box, monkeypatch):
    def refuse(a, p):
        raise V.imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
    monkeypatch.setattr(V, "connect", refuse)
    monkeypatch.setattr(V, "secret", lambda: (ME, "wrong"))
    assert V.main(["vault", "--once"]) == 0
    st = json.loads((V.DATA / "status.json").read_text())
    assert st["state"] == "failed" and "refused" in st["why"] and "wrong" not in json.dumps(st)


def test_without_a_password_it_waits_and_says_so(box, monkeypatch):
    monkeypatch.setattr(V, "secret", lambda: ("", ""))
    assert V.main(["vault", "--once"]) == 2
    assert json.loads((V.DATA / "status.json").read_text())["state"] == "waiting"


def test_it_protects_the_same_mail_as_the_connector_and_runs_sealed():
    connector = (ROOT / "images/mail/mail.py").read_text()
    copy = (ROOT / "nas/mailvault/vault.py").read_text()
    pick = lambda t: re.search(r"PROTECTED = re\.compile\(\n(.*?)\n\s+re\.I\)", t, re.S)[1]
    assert pick(connector) == pick(copy)
    compose = (ROOT / "nas/mailvault/compose.yaml").read_text()
    assert "read_only: true" in compose and "cap_drop: [ALL]" in compose and "ports" not in compose and "@sha256:" in compose
    assert "/secret:ro" in compose
    for bad in ("STORE", "EXPUNGE", '"MOVE"', "smtplib", "urllib"):
        assert bad not in copy

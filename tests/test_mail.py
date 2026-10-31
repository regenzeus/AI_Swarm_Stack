"""images/mail/mail.py: the Gmail connector's guards, with a fake IMAP server (no network)."""
import asyncio
import importlib
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "images" / "mail"))


class FakeIMAP:
    """Two folders; messages {msgid: (folder, uid, from, subject)}; records MOVE/STORE; no EXPUNGE support at all."""
    def __init__(self, box):
        self.box, self.sel, self.ops = box, None, []

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"',
                      b'(\\Junk \\HasNoChildren) "/" "[Gmail]/Spam"', b'(\\Trash \\HasNoChildren) "/" "[Gmail]/Trash"']

    def select(self, name, readonly=False):
        self.sel = name.strip('"')
        return "OK", [b"1"]

    def uid(self, cmd, *a):
        fold = {"INBOX": "inbox", "[Gmail]/All Mail": "all", "[Gmail]/Spam": "spam", "[Gmail]/Trash": "trash"}[self.sel]
        if cmd == "SEARCH" and a[0] == "X-GM-MSGID":
            return "OK", [" ".join(str(u) for i, (f, u, *_ ) in self.box.items() if str(i) == a[1] and f == fold).encode()]
        if cmd == "SEARCH":
            return "OK", [" ".join(str(u) for f, u, *_ in self.box.values() if f == fold).encode()]
        if cmd == "FETCH":
            out = []
            for i, (f, u, frm, subj) in self.box.items():
                if f == fold and str(u) in a[0].split(","):
                    out.append((f"1 (X-GM-MSGID {i} UID {u} FLAGS () RFC822.SIZE 2048 BODY[HEADER.FIELDS] {{1}}".encode(),
                                f"From: {frm}\r\nSubject: {subj}\r\n\r\n".encode()))
            return "OK", out
        if cmd == "MOVE":
            dest = {"\"[Gmail]/Trash\"": "trash", "\"INBOX\"": "inbox", "\"[Gmail]/Spam\"": "spam"}[a[1]]
            for i, (f, u, frm, subj) in list(self.box.items()):
                if f == fold and str(u) == a[0]:
                    self.box[i] = (dest, u, frm, subj)
            self.ops.append(("MOVE", a[0], dest))
            return "OK", [b""]
        self.ops.append((cmd, *a))
        return "OK", [b""]

    def logout(self):
        pass


@pytest.fixture
def mail(tmp_path, monkeypatch):
    monkeypatch.setenv("CONN_DIR", str(tmp_path))
    import mail as M
    M = importlib.reload(M)
    box = {101: ("spam", 1, "Spammer <x@spam.ru>", "You won $500"), 102: ("spam", 2, "PayPal <service@paypal.de>", "Your receipt"),
           103: ("all", 7, "News <n@shop.de>", "Sale")}
    fake = FakeIMAP(box)
    monkeypatch.setattr(M, "imap", lambda: fake)
    M.WAIT = 60                    # the answer comes as soon as the card exists; this is only the bound
    M.box, M.fake = box, fake
    return M


def grant(M, *scopes):
    (M.D / "grants.json").write_text(json.dumps({"gmail": {s: {"until": time.time() + 600, "at": "g1"} for s in scopes}}))


def answer(M, allow):
    """The owner's answer to the next approval card, as soon as the card exists. It waits for the card, not for a
    time window, so a busy machine cannot turn a yes into "no answer" (FND-27)."""
    import threading
    done = threading.Event()
    def go():
        while not done.wait(0.02):
            p = list(M.PENDING.glob("*.json"))
            if p:
                (M.DECISIONS / p[0].name).write_text(json.dumps({"allow": allow}))
                return
    threading.Thread(target=go, daemon=True).start()
    return done


def test_nothing_without_a_grant(mail):
    assert "Not allowed" in asyncio.run(mail.mail_search("in:spam", "spam"))
    assert "Not allowed" in asyncio.run(mail.mail_trash(["101"], "spam"))
    assert not mail.fake.ops


def test_search_is_marked_untrusted_and_flags_protected(mail):
    grant(mail, "read")
    out = asyncio.run(mail.mail_search("", "spam"))
    assert out.startswith("<untrusted_email>") and "PROTECTED" in out and "You won" in out


def test_trash_asks_first_keeps_bank_mail_and_can_be_undone(mail):
    grant(mail, "read", "trash")
    answer(mail, False)
    assert "did not OK" in asyncio.run(mail.mail_trash(["101", "102"], "spam"))
    assert mail.box[101][0] == "spam"                                     # declined: nothing moved
    answer(mail, True)
    out = asyncio.run(mail.mail_trash(["101", "102"], "obvious spam", "spam-cleanup"))
    assert "Moved 1" in out and "protected" in out
    assert mail.box[101][0] == "trash" and mail.box[102][0] == "spam"     # the PayPal mail is never trashed
    assert not any(o[0] in ("EXPUNGE", "STORE") for o in mail.fake.ops)  # Trash only, never deleted for good
    bid = out.split("batch ")[1].split(";")[0]
    assert "1 of 1" in asyncio.run(mail.mail_untrash(bid)) and mail.box[101][0] == "spam"
    mail.box[101] = ("spam", 1, "Spammer <x@spam.ru>", "You won $500")
    assert "Moved 1" in asyncio.run(mail.mail_trash(["101"], "again"))     # the OK covers this grant's later batches
    log = [json.loads(x)["action"] for x in (mail.D / "log.jsonl").read_text().splitlines()]
    assert "trash-declined" in log and log.count("trash") == 2 and "untrash" in log


def test_mail_tools_cannot_send(mail):
    tools = {t.name for t in asyncio.run(mail.mcp.list_tools())}
    assert tools == {"mail_access", "mail_search", "mail_read", "mail_label", "mail_archive", "mail_mark", "mail_trash", "mail_untrash"}

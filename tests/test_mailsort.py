"""The mail sorter (CNX-10 to CNX-13): worthless bulk mail under one label, only after the owner's tap per sender.
Made-up mail only: a synthetic copy's index, a fake Gmail, fake ssh; nothing here reaches Gmail, the NAS or the network."""
import ast
import asyncio
import base64
import importlib
import importlib.util
import json
import re
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

import pysrc
import webjs

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "images" / "mail"))
spec = importlib.util.spec_from_file_location("vault", ROOT / "nas/mailvault/vault.py")
V = importlib.util.module_from_spec(spec)
sys.modules.setdefault("vault", V)
spec.loader.exec_module(V)

import mailsort as MS            # noqa: E402
import mailsort_nas as NAS       # noqa: E402

ME = "me" + "@example.com"
NOW = 1_800_000_000
OLD = NOW - 400 * 86400
INBOX, SENT = '"\\\\Inbox"', '"\\\\Sent"'


def row(i, addr, name="", subject="An offer", at=OLD, labels=INBOX, lst=1, attach=0, cat="promotions", thread=None, recipients=ME, size=1000):
    return {"id": str(i), "thread": thread or f"t{i}", "uid": i, "at": at, "sender": name, "addr": addr, "recipients": recipients,
            "subject": subject, "size": size, "labels": labels, "seen": 0, "list": lst, "attach": attach, "category": cat}


def mailbox():
    """A made-up mailbox: one sure sender with a mail for every guard, one social sender, one likely one, and the senders
    that are never proposed (a friend the owner writes to, a bank, a travel sender, one with few mails, a starred one)."""
    rows, i = [], 0

    def add(**k):
        nonlocal i
        i += 1
        rows.append(row(i, **k))
        return str(i)
    deals = "deals" + "@shop.example"
    plain = [add(addr=deals, name="Deals Weekly", subject=f"Sale number {n}") for n in range(6)]
    add(addr=deals, name="Deals Weekly", subject="Important", labels=INBOX + ' "\\\\Important"')
    add(addr=deals, name="Deals Weekly", subject="Kept by you", labels=INBOX + " Receipts")
    add(addr=deals, name="Deals Weekly", subject="Your invoice 77")
    add(addr=deals, name="Deals Weekly", subject="Your verification code")
    add(addr=deals, name="Deals Weekly", subject="Forwarded to a friend", thread="tfw")
    add(addr=deals, name="Deals Weekly", subject="Fresh offer", at=NOW - 3 * 86400)
    add(addr=deals, name="Deals Weekly", subject="Sorted last week", labels='"AI Stack/Deletable"')
    social = [add(addr="notify" + "@social.example", name="Social", subject=f"Someone liked a post {n}", lst=0, cat="social", labels="") for n in range(6)]
    for n in range(20):
        add(addr="news" + "@app.example", name="App News", subject=f"Product update {n}", cat="updates", attach=int(n == 0))
    for n in range(6):
        add(addr="pal" + "@mail.example", name="A Friend", subject=f"Weekend {n}", lst=0, cat="primary")
        add(addr="info" + "@bank.example", name="Some Bank", subject=f"Offer {n}")
        add(addr="hello" + "@travel.example", name="Trips", subject=f"Deals {n}")
        add(addr="stars" + "@club.example", name="Club", subject=f"Club news {n}", labels=INBOX + (' "\\\\Starred"' if n == 0 else ""))
    for n in range(3):
        add(addr="few" + "@little.example", name="Little", subject=f"Hello {n}")
    add(addr=ME, name="Me", subject="Re: weekend", labels=SENT, recipients="pal" + "@mail.example", lst=0, cat="primary")
    add(addr=ME, name="Me", subject="Fwd: look", labels=SENT, recipients="pal" + "@mail.example", lst=0, cat="primary", thread="tfw")
    add(addr=ME, name="AI Stack", subject="A report", labels=SENT, recipients=ME, lst=0, cat="primary")
    return rows, {"deals": deals, "plain": plain, "social": social}


def index(tmp_path, rows):
    d = tmp_path / "copy"
    d.mkdir(exist_ok=True)
    V.DATA = d
    c = V.db()
    c.executemany("insert into messages (id, thread, uid, at, sender, addr, recipients, subject, size, labels, seen, list, attach, category) "
                  "values (:id,:thread,:uid,:at,:sender,:addr,:recipients,:subject,:size,:labels,:seen,:list,:attach,:category)", rows)
    c.commit()
    c.close()
    return d / "index.sqlite"


def fake_ssh(db, calls=None):
    """ssh to the NAS, played by this machine: the same script on stdin and the same argument, on the made-up index."""
    def run(cmd, input=None, **kw):
        assert cmd[:4] == ["ssh", "-o", "ConnectTimeout=20", MS.SSH_HOST] and cmd[4].startswith("python3 - ")
        if calls is not None:
            calls.append(json.loads(base64.b64decode(cmd[4].split()[2])))
        return subprocess.run([sys.executable, "-", cmd[4].split()[2], "--db", str(db)], input=input, **kw)
    return run


def look(tmp_path, approve=(), kept=(), rows=None):
    rows = rows or mailbox()[0]
    import sqlite3
    c = sqlite3.connect(f"file:{index(tmp_path, rows)}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return NAS.analyse(c, {"me": ME, "label": "AI Stack/Deletable", "kept": list(kept), "approve": list(approve), "now": NOW})


# ---------------------------------------------------------------- CNX-10: the look, from headers alone
def test_the_look_proposes_bulk_senders_the_owner_never_answered_in_two_tiers(tmp_path):
    p = look(tmp_path)
    tiers = {s["addr"]: s["tier"] for s in p["senders"]}
    assert tiers == {"deals" + "@shop.example": "high", "notify" + "@social.example": "high", "news" + "@app.example": "likely"}
    assert p["left"] == {"you wrote to them": 6, "banks and security": 6, "the sender's name may matter later": 6,
                         "you starred one of their mails": 6, "fewer than 5 mails": 3}
    assert p["mails"] == 69 and p["moves"] == {}                       # nobody approved: no mail is listed to move


def test_every_mail_of_a_chosen_sender_is_checked_again_and_each_guard_counted(tmp_path):
    rows, m = mailbox()
    p = look(tmp_path, approve=[m["deals"]], rows=rows)
    s = next(x for x in p["senders"] if x["addr"] == m["deals"])
    assert s["kept"] == {"important": 1, "one of your labels": 1, "words that may matter": 1, "banks and security": 1,
                         "a thread you wrote in": 1, "younger than 30 days": 1, "already sorted": 1}
    assert s["movable"] == 6 and s["inbox"] == 6 and sorted(x[0] for x in p["moves"][m["deals"]]) == sorted(m["plain"])
    assert len(s["samples"]) == 3 and all(x.startswith("Sale number") for x in s["samples"])
    assert p["guards"]["younger than 30 days"] == 1
    ok = row(1, "x" + "@y.example")
    for labels, want in ((INBOX + ' "\\\\Starred"', "starred"), (INBOX, None)):     # a starred mail stays, whoever sent it
        assert NAS.guard({**ok, "labels": labels}, {ME}, "AI Stack/Deletable", set(), NOW) == want
    assert NAS.guard({**ok, "addr": ME, "sender": "AI Stack"}, {ME}, "AI Stack/Deletable", set(), NOW) == "the stack's own mail"
    assert NAS.guard({**ok, "attach": 1}, {ME}, "AI Stack/Deletable", set(), NOW) == "an attachment"


def test_a_sender_that_relays_people_s_messages_is_never_sure_and_such_a_mail_stays(tmp_path):
    """The lead's review, 10 Nov 2026: a site's notifications that carry "X sent you a message" are a person's words."""
    rows, i = [], 0
    for n in range(12):                                               # its name says so: at most likely, unticked
        i += 1
        rows.append(row(i, "inbox" + "@network.example", "Network Messages", subject=f"Weekly digest {n}", cat="social"))
    for n in range(10):                                               # 2 of 10 subjects relay a person: at most likely
        i += 1
        subject = ["Alex sent you a message", "Kim hat dir eine Nachricht gesendet"][n] if n < 2 else f"Offers {n}"
        rows.append(row(i, "news" + "@dating.example", "Dates", subject=subject, cat="promotions"))
    for n in range(25):                                               # 1 of 25 is under the share: sure, but that mail stays
        i += 1
        rows.append(row(i, "hello" + "@forum.example", "Forum", subject="Sam replied to your post" if n == 0 else f"Top threads {n}"))
    p = look(tmp_path, approve=["news" + "@dating.example", "hello" + "@forum.example"], rows=rows)
    tiers = {s["addr"]: s["tier"] for s in p["senders"]}
    assert tiers == {"inbox" + "@network.example": "likely", "news" + "@dating.example": "likely", "hello" + "@forum.example": "high"}
    dating = next(s for s in p["senders"] if s["addr"] == "news" + "@dating.example")
    assert dating["kept"] == {"a message from someone": 2} and dating["relays"] and dating["movable"] == 8
    assert "passes on messages from people" in " ".join(MS.why(dating))
    assert not any("replied" in x[2] for x in p["moves"]["hello" + "@forum.example"])
    for word in ("linkedin", "facebook", "parship", "xing"):              # SEC-22: generic words only
        assert word not in NAS.RELAY.pattern.lower() + NAS.RELAY_SENDER.pattern.lower()


def test_the_look_reads_the_copy_read_only_on_the_nas_python_and_writes_nothing(tmp_path):
    src = (ROOT / "ops/mailsort_nas.py").read_text()
    ast.parse(src, feature_version=(3, 8))                              # the NAS's python3 is 3.8
    assert "mode=ro" in src and not re.search(r"\b(insert|update|delete|create|drop|alter)\s", src.split('"""', 2)[2], re.I)
    assert NAS.PROTECTED.pattern == V.PROTECTED.pattern                  # the connector's protected mail (test_mailvault keeps them equal)
    db = index(tmp_path, mailbox()[0])
    before = sorted((p.name, p.stat().st_mtime_ns) for p in db.parent.iterdir())
    p = MS.nas({"me": ME, "label": "L", "kept": [], "approve": [], "now": NOW}, ssh=fake_ssh(db))
    assert len(p["senders"]) == 3 and sorted((x.name, x.stat().st_mtime_ns) for x in db.parent.iterdir()) == before
    for word in ("sparkasse", "lufthansa", "telekom", "allianz"):           # SEC-22: generic words only, no company or place
        assert word not in NAS.KEEP.pattern


def test_an_asleep_nas_is_said_and_never_taken_for_nothing_to_sort(tmp_path, monkeypatch):
    monkeypatch.setattr(MS, "OUT", tmp_path / "sort")
    saved = {}
    monkeypatch.setattr(MS, "C", types.SimpleNamespace(save=lambda a, **k: saved.update(k)))
    asleep = lambda cmd, **kw: types.SimpleNamespace(returncode=255, stdout="", stderr="ssh: connect to host synology port 22: Connection timed out")
    calls = []
    MS.run(None, tool=lambda n, a: calls.append(n), ssh=asleep, granted=lambda s: True)
    assert calls == [] and "the NAS did not answer" in saved["result"] and saved["unknown"]


# ---------------------------------------------------------------- CNX-11: the owner decides, per sender, once
@pytest.fixture
def sorter(tmp_path, monkeypatch):
    rows, m = mailbox()
    db = index(tmp_path, rows)
    monkeypatch.setattr(MS, "OUT", tmp_path / "sort")
    monkeypatch.setenv("GMAIL_ADDRESS", ME)
    saved, started, rested = {}, [], []
    monkeypatch.setattr(MS, "C", types.SimpleNamespace(save=lambda a, **k: saved.update(k)))
    monkeypatch.setattr(MS, "M", types.SimpleNamespace(rest=lambda c, who, s: rested.append(s) or False))
    import crew as CR
    monkeypatch.setattr(CR, "OUT", tmp_path / "crew")
    sent = []
    gmail = {r["id"]: {"labels": {"inbox"} if "Inbox" in r["labels"] else set()} for r in rows}   # id -> its labels in the fake Gmail

    def tool(name, args):
        sent.append((name, args))
        if name == MS.TOOL_OUT:
            done = [i for i in args["ids"] if i not in m.get("protected_ids", ())]
            was = [i for i in done if "inbox" in gmail.setdefault(i, {"labels": {"inbox"}})["labels"]]
            for i in done:
                gmail[i]["labels"] = (gmail[i]["labels"] - {"inbox"}) | {args["label"]}
            return f"sort-out: {len(done)} done.\n" + json.dumps({"done": done, "inbox": was, "protected": [], "missing": []})
        if name == MS.TOOL_BACK:
            for i in args["ids"]:
                gmail[i]["labels"].discard(args["label"])
            for i in args["to_inbox"]:
                gmail[i]["labels"].add("inbox")
            return "sort-back.\n" + json.dumps({"done": args["ids"], "inbox": args["to_inbox"], "missing": []})
        raise AssertionError(name)
    return types.SimpleNamespace(m=m, db=db, ssh=fake_ssh(db), saved=saved, sent=sent, tool=tool, gmail=gmail, rested=rested,
                                 run=lambda **k: MS.run(None, tool=tool, ssh=fake_ssh(db), granted=k.get("granted", lambda s: True)),
                                 start=lambda cmd, **kw: started.append(cmd) or types.SimpleNamespace(returncode=0, stderr=""), started=started)


def test_nothing_moves_before_the_owner_s_tap(sorter):
    sorter.run()
    assert not sorter.sent and "nothing new to sort out" in sorter.saved["result"]
    p = json.loads((MS.OUT / "proposal.json").read_text())
    assert [s["new"] for s in p["senders"]] == [True, True, True] and "moves" not in p
    assert "3 senders wait for your look" in sorter.saved["result"]
    assert all("Sale" in x and len(x) <= MS.SAMPLE for s in p["senders"][:1] for x in s["samples"])
    assert p["label"] == MS.LABEL == "AI Stack/Deletable"


def test_a_long_sample_subject_is_cut_and_marked(sorter, tmp_path):
    rows = [row(i, "loud" + "@shop.example", "Loud", subject="Sale " + "x" * 300) for i in range(1, 8)]
    (tmp_path / "other").mkdir()
    db = index(tmp_path / "other", rows)
    MS.publish(MS.nas({"me": ME, "label": MS.LABEL, "kept": [], "approve": [], "now": NOW}, ssh=fake_ssh(db)), MS.decisions())
    s = json.loads((MS.OUT / "proposal.json").read_text())["senders"][0]
    assert all("more characters cut" in x for x in s["samples"]) and len(s["samples"]) == 3


def test_the_owner_s_tap_approves_the_ticked_senders_and_starts_the_sorter(sorter):
    sorter.run()
    p = json.loads((MS.OUT / "proposal.json").read_text())
    with pytest.raises(ValueError, match="the proposal changed"):
        MS.handle({"action": "mailsort_go", "at": p["at"] - 1}, run=sorter.start)
    with pytest.raises(ValueError, match="not in the proposal"):
        MS.handle({"action": "mailsort_go", "at": p["at"], "also": ["someone" + "@else.example"]}, run=sorter.start)
    social = "notify" + "@social.example"
    r = MS.handle({"action": "mailsort_go", "at": p["at"], "except": [social]}, run=sorter.start)   # high ticked, one unticked
    d = MS.decisions()
    assert set(d["approved"]) == {sorter.m["deals"]} and r == {"approved": 1, "mails": 6}
    assert set(d["seen"]) == {sorter.m["deals"], social, "news" + "@app.example"} and MS.pending() == []
    assert sorter.started and sorter.started[0][-1] == "crew-mail-sort.service"
    assert not sorter.sent                                                   # the tap starts the job; the job moves


def test_keep_this_sender_is_for_good(sorter):
    sorter.run()
    MS.handle({"action": "mailsort_keep", "addr": sorter.m["deals"]})
    assert sorter.m["deals"] in MS.decisions()["kept"]
    assert sorter.m["deals"] not in [s["addr"] for s in json.loads((MS.OUT / "proposal.json").read_text())["senders"]]
    calls = []
    MS.run(None, tool=sorter.tool, ssh=fake_ssh(sorter.db, calls), granted=lambda s: True)
    assert sorter.m["deals"] in calls[0]["kept"] and sorter.m["deals"] not in calls[0]["approve"]
    assert sorter.m["deals"] not in [s["addr"] for s in json.loads((MS.OUT / "proposal.json").read_text())["senders"]]


def test_needs_you_asks_once_for_new_senders(sorter):
    import decisions as DQ
    assert list(DQ._mail_sort({})) == []                              # nothing looked at yet
    sorter.run()
    (d,) = DQ._mail_sort({})
    assert d["cls"] == "mail-sort" and d["href"] == "#/mail" and d["what"].startswith("3 senders send mail you could delete")
    p = json.loads((MS.OUT / "proposal.json").read_text())
    MS.handle({"action": "mailsort_go", "at": p["at"], "except": [s["addr"] for s in p["senders"] if s["tier"] == "high"]}, run=sorter.start)
    assert list(DQ._mail_sort({})) == []                              # looked at, none ticked: no card until a new sender
    assert "mail-sort" in (ROOT / "config/autonomy.yaml").read_text()


# ---------------------------------------------------------------- CNX-12: the move, recorded, paced, undoable; weekly
def test_the_move_goes_in_recorded_paced_batches_and_never_twice(sorter, monkeypatch):
    monkeypatch.setattr(MS, "BATCH", 4)
    sorter.run()
    p = json.loads((MS.OUT / "proposal.json").read_text())
    MS.handle({"action": "mailsort_go", "at": p["at"]}, run=sorter.start)           # both sure senders
    sorter.run()
    outs = [a for n, a in sorter.sent if n == MS.TOOL_OUT]
    assert [len(a["ids"]) for a in outs] == [4, 4, 4] and all(a["label"] == "AI Stack/Deletable" for a in outs)
    assert sorter.rested == [MS.PAUSE_S, MS.PAUSE_S]                                 # paced between batches
    moved = {i for a in outs for i in a["ids"]}
    assert moved == set(sorter.m["plain"]) | set(sorter.m["social"])
    bs = MS.batches()
    assert len(bs) == 3 and all({"id", "sender", "subject", "inbox"} <= set(i) for b in bs for i in b["items"])
    assert sum(i["inbox"] for b in bs for i in b["items"]) == 6                       # the social mails were archived already
    (r,) = MS.runs()
    assert r["mails"] == 12 and r["inbox"] == 6 and "12 mails of 2 senders sorted out under AI Stack/Deletable" in sorter.saved["result"]
    sorter.sent.clear()
    sorter.run()                                                                       # the weekly run: nothing twice
    assert not [n for n, _ in sorter.sent if n == MS.TOOL_OUT] and "nothing new to sort out" in sorter.saved["result"]


def test_new_mail_of_an_approved_sender_is_sorted_weekly_and_an_unapproved_one_never(sorter, tmp_path):
    sorter.run()
    p = json.loads((MS.OUT / "proposal.json").read_text())
    MS.handle({"action": "mailsort_go", "at": p["at"], "except": ["notify" + "@social.example"]}, run=sorter.start)
    sorter.run()
    rows, m = mailbox()
    rows += [row(900 + n, m["deals"], "Deals Weekly", subject=f"New sale {n}") for n in range(2)]
    rows += [row(950 + n, "notify" + "@social.example", "Social", lst=0, cat="social") for n in range(2)]
    (tmp_path / "week2").mkdir()
    db = index(tmp_path / "week2", rows)
    sorter.sent.clear()
    MS.run(None, tool=sorter.tool, ssh=fake_ssh(db), granted=lambda s: True)
    ids = [i for n, a in sorter.sent if n == MS.TOOL_OUT for i in a["ids"]]
    assert sorted(ids) == ["900", "901"]


def test_undo_puts_the_mail_back_and_withdraws_the_approval(sorter):
    sorter.run()
    p = json.loads((MS.OUT / "proposal.json").read_text())
    MS.handle({"action": "mailsort_go", "at": p["at"]}, run=sorter.start)
    sorter.run()
    (r,) = MS.runs()
    MS.handle({"action": "mailsort_undo", "run": r["run"]}, run=sorter.start)
    with pytest.raises(ValueError, match="no such sorting run"):
        MS.handle({"action": "mailsort_undo", "run": "nope"}, run=sorter.start)
    sorter.run()
    back = [a for n, a in sorter.sent if n == MS.TOOL_BACK]
    assert {i for a in back for i in a["ids"]} == set(sorter.m["plain"]) | set(sorter.m["social"])
    assert {i for a in back for i in a["to_inbox"]} == set(sorter.m["plain"])        # only what was in the inbox goes back there
    assert all("inbox" in sorter.gmail[i]["labels"] for i in sorter.m["plain"]) and all(MS.LABEL not in g["labels"] for g in sorter.gmail.values())
    assert MS.decisions()["approved"] == {} and MS.runs()[0]["undone"] and all(b["undone"] for b in MS.batches())
    assert "mails put back, as you asked" in sorter.saved["result"]
    assert len([n for n, _ in sorter.sent if n == MS.TOOL_OUT]) == 1                  # the run after the undo moved nothing again


def test_without_organize_nothing_moves_and_it_says_so(sorter):
    sorter.run()
    p = json.loads((MS.OUT / "proposal.json").read_text())
    MS.handle({"action": "mailsort_go", "at": p["at"]}, run=sorter.start)
    sorter.run(granted=lambda s: False)
    assert not sorter.sent and "Gmail organize is not granted" in sorter.saved["result"] and sorter.saved["unknown"]


def test_a_refusal_by_the_connector_stops_the_run_and_is_said(sorter):
    sorter.run()
    p = json.loads((MS.OUT / "proposal.json").read_text())
    MS.handle({"action": "mailsort_go", "at": p["at"]}, run=sorter.start)
    with pytest.raises(RuntimeError, match="Not allowed right now"):
        MS.run(None, tool=lambda n, a: "Not allowed right now: the owner has not granted Gmail 'organize'", ssh=sorter.ssh, granted=lambda s: True)
    assert MS.batches() == []


def test_the_sorter_is_a_weekly_crew_job_on_n8n_and_the_runner_takes_the_taps():
    import crew as CR
    ag = CR.BY_ID["mail-sort"]
    assert ag["unit"] == "crew-mail-sort" and (ROOT / "ops/systemd/crew-mail-sort.service").exists()
    unit = (ROOT / "ops/systemd/crew-mail-sort.service").read_text()
    assert "python3 ops/crew.py mail-sort" in unit and "# feature: mail" in unit and "stack_gate.py --wait" in unit
    wf = json.loads((ROOT / "n8n/workflows/crew-mail-sorter.json").read_text())
    step = next(n for n in wf["nodes"] if n["type"] == "CUSTOM.aistackStep")
    trig = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger")
    assert step["parameters"]["job"] == "mail-sort" and trig["parameters"]["rule"]["interval"][0]["expression"].endswith("* * 6")
    assert "crew-mail-sorter" in (ROOT / "deployments/home/workflows.yaml").read_text()
    assert '"mail-sort": MSORT.run' in (ROOT / "ops/crew.py").read_text()
    assert "MSORT.handle(req) if a in MSORT.ACTIONS" in pysrc.missions()
    assert all(f'"{a}"' in pysrc.server() for a in MS.ACTIONS)


# ---------------------------------------------------------------- CNX-13: the connector's sort-out and its undo
class FakeGmail:
    """All Mail with labels; records every STORE; has no MOVE, EXPUNGE or delete at all."""
    def __init__(self, box):
        self.box, self.ops = box, []                         # msgid -> {"uid", "from", "subject", "labels": set}

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"',
                      b'(\\Junk \\HasNoChildren) "/" "[Gmail]/Spam"', b'(\\Trash \\HasNoChildren) "/" "[Gmail]/Trash"']

    def select(self, name, readonly=False):
        assert name == '"[Gmail]/All Mail"'
        return "OK", [b"1"]

    def uid(self, cmd, *a):
        if cmd == "SEARCH":
            return "OK", [" ".join(str(m["uid"]) for i, m in self.box.items() if i == a[1]).encode()]
        if cmd == "FETCH":
            out = []
            for i, m in self.box.items():
                if str(m["uid"]) in a[0].split(","):
                    labels = " ".join(f'"{x}"' if not x.startswith("\\") else '"\\' + x + '"' for x in sorted(m["labels"]))
                    out.append((f"1 (X-GM-MSGID {i} X-GM-LABELS ({labels}) UID {m['uid']} FLAGS () RFC822.SIZE 2048 BODY[HEADER.FIELDS] {{1}}".encode(),
                                f"From: {m['from']}\r\nSubject: {m['subject']}\r\n\r\n".encode()))
            return "OK", out
        if cmd == "STORE":
            uids, how, what = a
            self.ops.append((uids, how, what))
            name = what.strip('"()')
            for m in self.box.values():
                if str(m["uid"]) in uids.split(","):
                    (m["labels"].add if how.startswith("+") else m["labels"].discard)(name)
            return "OK", [b""]
        raise AssertionError(f"the sorter never sends {cmd}")

    def logout(self):
        pass


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CONN_DIR", str(tmp_path))
    import mail as M
    M = importlib.reload(M)
    box = {"201": {"uid": 1, "from": "Deals <deals" + "@shop.example>", "subject": "Sale", "labels": {"\\Inbox"}},
           "202": {"uid": 2, "from": "Deals <deals" + "@shop.example>", "subject": "Old sale", "labels": set()},
           "203": {"uid": 3, "from": "Some Bank <info" + "@bank.example>", "subject": "Statement", "labels": {"\\Inbox"}}}
    fake = FakeGmail(box)
    monkeypatch.setattr(M, "imap", lambda: fake)
    M.box, M.fake = box, fake
    return M


def test_the_connector_sorts_out_in_one_step_and_leaves_protected_mail_alone(conn):
    assert "Not allowed" in asyncio.run(conn.mail_sort_out(["201"], "AI Stack/Deletable")) and not conn.fake.ops
    (conn.D / "grants.json").write_text(json.dumps({"gmail": {"organize": {"until": time.time() + 600}}}))
    assert asyncio.run(conn.mail_sort_out(["201"], "Bad\r\nA1 EXPUNGE")).startswith("Refused: the label")
    out = asyncio.run(conn.mail_sort_out(["201", "202", "203", "999"], "AI Stack/Deletable"))
    res = json.loads(out.splitlines()[-1])
    assert res == {"done": ["201", "202"], "inbox": ["201"], "protected": ["203"], "missing": ["999"]}
    assert conn.box["201"]["labels"] == {"AI Stack/Deletable"} and conn.box["202"]["labels"] == {"AI Stack/Deletable"}
    assert conn.box["203"]["labels"] == {"\\Inbox"}                                   # the bank's mail: no label, still in the inbox
    assert conn.fake.ops == [("1,2", "+X-GM-LABELS", '"AI Stack/Deletable"'), ("1,2", "-X-GM-LABELS", "(\\Inbox)")]
    log = [json.loads(x) for x in (conn.D / "log.jsonl").read_text().splitlines()]
    assert log[-1]["action"] == "sort-out" and log[-1]["skipped"] == ["203"]
    back = json.loads(asyncio.run(conn.mail_sort_back(["201", "202"], "AI Stack/Deletable", ["201"])).splitlines()[-1])
    assert back["done"] == ["201", "202"] and back["inbox"] == ["201"]
    assert conn.box["201"]["labels"] == {"\\Inbox"} and conn.box["202"]["labels"] == set()


# ---------------------------------------------------------------- the page
def test_your_mail_shows_the_proposal_with_ticks_and_one_button():
    app = webjs.app_js()
    for part in ("function sortHtml()", "Mail you could delete", 'data-mst="', "Keep this sender", 'id="msgo"', "mailsort_go", "mailsort_undo",
                 "mailsort_keep", 'explain("mail-sort-how"', "Likely: look before you tick", 'x.tier === "high" || !!x.approved',
                 '<details class="grow sortd"', "Tick all", "Untick all", 'data-msall="'):
        assert part in app, part
    assert '<div class="section" id="mailsort">${sortHtml()}</div>' in app
    server = pysrc.server()
    assert '"sort": {"proposal": read("sort/proposal.json")' in server
    assert '"mail-sort": "trash"' in (ROOT / "images/mission-control/web/static/app-tasks.js").read_text()

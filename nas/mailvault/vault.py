#!/usr/bin/env python3
"""The mail copy on the NAS (CNX-07): every Gmail message as a file, kept current, one way only.

Gmail -> NAS, never back. Gmail's All Mail is opened read-only (EXAMINE, BODY.PEEK), so nothing here can change, mark or
move a mail. A mail that leaves Gmail stays on the NAS, marked as gone: a copy that follows deletions is no backup.

Every 15 minutes: the headers of new mail, then the bodies not copied yet, newest first. Once a day: labels and read
state, and which mails have left Gmail. Headers come first, so the sender report (census.json) is there long before the
first copy is finished. Google suspends an account past 2,500 MB of IMAP downloads a day, so this takes 2,000 MB a day
and goes on the next. The stack's own mail tools use the same allowance.

  /data/index.sqlite                every message: sender, subject, labels, read state, where its copy is, its checksum
  /data/eml/<year>/<month>/<id>.eml.gz   the message exactly as Gmail holds it
  /data/status.json, census.json    what the stack reads over ssh (ops/postmaster.py)
  /secret/address, /secret/password an app password of its own (make mailvault-password), never logged

Mail is data here: nothing in it is run, opened or sent to a model. Python's standard library only.
  python3 vault.py                     the loop, in its container
  python3 vault.py --once --headers-only   one pass (a test, or a first report)
"""
import collections
import email
import email.header
import email.policy
import email.utils
import gzip
import hashlib
import imaplib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

DATA = Path(os.environ.get("VAULT_DATA", "/data"))
SECRET = Path(os.environ.get("VAULT_SECRET", "/secret"))
HOST = "imap.gmail.com"
EVERY = 15 * 60
BATCH = 500
# limit: paces, Google suspends an account past 2,500 MB of IMAP downloads a day; the rest follows the next day
DAILY_BYTES = 2_000_000_000
# limit: paces, one pass copies bodies this long, then new mail gets its turn
PASS_S = 30 * 60
CATEGORIES = ("promotions", "social", "updates", "forums", "primary")
FIELDS = "FROM TO CC DATE SUBJECT LIST-UNSUBSCRIBE CONTENT-TYPE"
# As images/mail/mail.py (tests/test_mailvault.py keeps them equal): what the cleanup never offers.
PROTECTED = re.compile(
    r"bank|sparkasse|volksbank|raiffeisen|comdirect|consorsbank|\bdkb\b|\bing\b|n26|revolut|paypal|klarna|"
    r"trade ?republic|scalable|broker|depot|finanzamt|elster|"
    r"security alert|sicherheits(hinweis|warnung)|new sign-in|neue anmeldung|verification code|bestätigungscode|"
    r"verifizierungscode|sicherheitscode|one-time|einmal(code|passwort)|\b2fa\b|two-factor|zwei-faktor|"
    r"password reset|passwort zurücksetzen|reset your password|login code|anmeldecode|google account|google-konto",
    re.I)


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def db():
    c = sqlite3.connect(DATA / "index.sqlite")
    c.row_factory = sqlite3.Row
    c.executescript("""
      create table if not exists messages (id text primary key, thread text, uid integer, at integer, sender text, addr text,
        recipients text, subject text, size integer, labels text, seen integer, list integer, attach integer, category text,
        path text, sha256 text, copied integer, gone integer);
      create index if not exists to_copy on messages (at) where path is null and gone is null;
      create index if not exists by_addr on messages (addr);
      create table if not exists kv (k text primary key, v text);""")
    return c


def kv(c, k, default=None):
    r = c.execute("select v from kv where k=?", (k,)).fetchone()
    return r[0] if r else default


def put(c, k, v):
    c.execute("insert into kv values (?,?) on conflict(k) do update set v=excluded.v", (k, str(v)))
    c.commit()


def spent(c):
    """Bytes downloaded today."""
    today = time.strftime("%Y-%m-%d")
    if kv(c, "day") != today:
        put(c, "day", today)
        put(c, "day_bytes", 0)
    return int(kv(c, "day_bytes", 0))


def spend(c, n):
    put(c, "day_bytes", spent(c) + n)


def text_of(v):
    try:
        return str(email.header.make_header(email.header.decode_header(v or ""))).strip()
    except Exception:
        return str(v or "").strip()


def responses(data):
    """imaplib's FETCH answer -> [(what it says about the message, its literal or b"")], wherever the server put the literal."""
    out = []
    for part in data or []:
        if isinstance(part, tuple):
            out.append([part[0], part[1]])
        elif part and part != b")":
            if out and not re.match(rb"\d+ \(", part):
                out[-1][0] += part
            else:
                out.append([part, b""])
    return [(m.decode(errors="replace"), raw) for m, raw in out]


def parse_meta(meta):
    grab = lambda rx: (re.search(rx, meta) or [None, ""])[1]
    internal = imaplib.Internaldate2tuple(meta.encode()) if "INTERNALDATE" in meta else None
    return {"id": grab(r"X-GM-MSGID (\d+)"), "thread": grab(r"X-GM-THRID (\d+)"), "uid": int(grab(r"UID (\d+)") or 0),
            "labels": grab(r"X-GM-LABELS \((.*?)\)"), "seen": int("\\Seen" in grab(r"FLAGS \((.*?)\)")),
            "size": int(grab(r"RFC822\.SIZE (\d+)") or 0), "at": int(time.mktime(internal)) if internal else 0}


def parse_head(raw):
    h = email.message_from_bytes(raw, policy=email.policy.compat32)
    name, addr = email.utils.parseaddr(text_of(h.get("From")))
    to = [a.lower() for _, a in email.utils.getaddresses([text_of(h.get("To")), text_of(h.get("Cc"))]) if a]
    return {"sender": name, "addr": addr.lower(), "recipients": ",".join(to), "subject": text_of(h.get("Subject")),
            "list": int(bool(h.get("List-Unsubscribe"))), "attach": int("multipart/mixed" in str(h.get("Content-Type", "")).lower())}


def all_mail(m):
    """Gmail's folder names are localised: All Mail by its special-use flag."""
    for line in m.list()[1]:
        s = line.decode(errors="replace")
        if "\\All" in s:
            return s.rsplit(' "/" ', 1)[-1].strip().strip('"')
    raise RuntimeError("no All Mail folder: is it shown in IMAP? (Gmail settings, Labels)")


def connect(address, password):
    m = imaplib.IMAP4_SSL(HOST, 993, timeout=120)
    m.login(address, password)
    m.select('"' + all_mail(m) + '"', readonly=True)
    return m


def new_headers(c, m):
    """The headers of everything after the last message seen. A changed UIDVALIDITY only means all UIDs are looked at again."""
    validity = (m.response("UIDVALIDITY")[1] or [b"0"])[0].decode()
    last = int(kv(c, "last_uid", 0)) if kv(c, "uidvalidity") == validity else 0
    uids = [int(x) for x in (m.uid("SEARCH", None, f"UID {last + 1}:*")[1][0] or b"").split()]
    uids = [u for u in uids if u > last]
    for i in range(0, len(uids), BATCH):
        part = uids[i:i + BATCH]
        typ, data = m.uid("FETCH", ",".join(map(str, part)), f"(X-GM-MSGID X-GM-THRID X-GM-LABELS FLAGS RFC822.SIZE INTERNALDATE BODY.PEEK[HEADER.FIELDS ({FIELDS})])")
        n = 0
        for meta, raw in responses(data):
            d = parse_meta(meta)
            if not d["id"]:
                continue
            d.update(parse_head(raw))
            n += len(raw) + len(meta)
            c.execute("""insert into messages (id, thread, uid, at, sender, addr, recipients, subject, size, labels, seen, list, attach)
                         values (:id,:thread,:uid,:at,:sender,:addr,:recipients,:subject,:size,:labels,:seen,:list,:attach)
                         on conflict(id) do update set uid=excluded.uid, labels=excluded.labels, seen=excluded.seen, gone=null""", d)
        c.commit()
        spend(c, n)
        put(c, "uidvalidity", validity)
        put(c, "last_uid", part[-1])
        log(f"headers: {min(i + BATCH, len(uids))} of {len(uids)} new")
    return len(uids)


def copy_path(row):
    t = time.gmtime(row["at"] or 0)
    return Path("eml") / f"{t.tm_year:04d}" / f"{t.tm_mon:02d}" / f"{row['id']}.eml.gz"


def copy_one(c, m, row):
    """One message's file, checked, then put in place: a half-written copy never counts. -> bytes, or None if Gmail has no such uid now."""
    typ, data = m.uid("FETCH", str(row["uid"]), "(X-GM-MSGID BODY.PEEK[])")
    got = [(meta, raw) for meta, raw in responses(data) if raw]
    if not got or parse_meta(got[0][0])["id"] != row["id"]:
        return None
    raw = got[0][1]
    if row["size"] and len(raw) != row["size"]:
        raise RuntimeError(f"message {row['id']}: {len(raw)} bytes, Gmail says {row['size']}")
    rel = copy_path(row)
    dest = DATA / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    with gzip.open(tmp, "wb", compresslevel=6) as f:
        f.write(raw)
    sha = hashlib.sha256(raw).hexdigest()
    with gzip.open(tmp, "rb") as f:
        if hashlib.sha256(f.read()).hexdigest() != sha:
            raise RuntimeError(f"message {row['id']}: the copy does not read back the same")
    tmp.replace(dest)
    c.execute("update messages set path=?, sha256=?, copied=? where id=?", (str(rel), sha, int(time.time()), row["id"]))
    c.commit()
    return len(raw)


def copy_bodies(c, m, deadline=None):
    """Bodies not copied yet, newest first, within today's allowance. -> how many."""
    n = 0
    deadline = deadline or time.time() + PASS_S
    while time.time() < deadline:
        rows = c.execute("select * from messages where path is null and gone is null order by at desc limit 200").fetchall()  # cap: parse (200 a pass; the loop takes the rest)
        if not rows:
            break
        moved = False
        for row in rows:
            if time.time() >= deadline or spent(c) + (row["size"] or 0) > DAILY_BYTES:
                return n
            got = copy_one(c, m, row)
            if got is None:                                 # its uid changed or it left: the daily look settles which
                c.execute("update messages set gone=? where id=?", (int(time.time()), row["id"]))
                c.commit()
                continue
            spend(c, got)
            n += 1
            moved = True
        if not moved:
            break
    return n


def refresh(c, m):
    """Once a day: labels and read state of everything, categories, and which mails have left Gmail (they stay here, marked)."""
    typ, data = m.uid("FETCH", "1:*", "(X-GM-MSGID X-GM-LABELS FLAGS)")
    seen, n = set(), 0
    for meta, _ in responses(data):
        d = parse_meta(meta)
        if d["id"]:
            seen.add(d["id"])
            n += len(meta)
            c.execute("update messages set uid=?, labels=?, seen=?, gone=null where id=?", (d["uid"], d["labels"], d["seen"], d["id"]))
    known = c.execute("select count(*) from messages where gone is null").fetchone()[0]
    if len(seen) >= known * 0.5:                            # a broken answer must not mark half the mailbox as gone
        now = int(time.time())
        for r in c.execute("select id from messages where gone is null").fetchall():
            if r["id"] not in seen:
                c.execute("update messages set gone=? where id=?", (now, r["id"]))
    for cat in CATEGORIES:
        uids = (m.uid("SEARCH", "X-GM-RAW", f'"category:{cat}"')[1][0] or b"").split()
        n += sum(len(u) + 1 for u in uids)
        for u in uids:
            c.execute("update messages set category=? where uid=?", (cat, int(u)))
    c.commit()
    spend(c, n)
    put(c, "refreshed", int(time.time()))


def census(c, me):
    """One line per sender, from the headers alone: what the cleanup and the labels start from. No model, no message text."""
    wrote_to = collections.Counter()
    for r in c.execute("select recipients from messages where addr=?", (me,)):
        wrote_to.update(a for a in (r["recipients"] or "").split(",") if a and a != me)
    rows = []
    for r in c.execute("""select addr, count(*) n, coalesce(sum(size),0) bytes, sum(1-seen) unread, sum(list) lists, sum(attach) attach, min(at) first, max(at) last,
                          sum(gone is not null) gone, sum(labels like '%Inbox%') inbox, sum(labels like '%Starred%') starred from messages group by addr order by n desc"""):
        names = collections.Counter(x["sender"] for x in c.execute("select sender from messages where addr=? order by at desc limit 50", (r["addr"],)) if x["sender"])  # cap: parse (the names in an address's newest 50 mails)
        cats = collections.Counter(x["category"] for x in c.execute("select category from messages where addr=? and category is not null", (r["addr"],)))
        subject = (c.execute("select subject from messages where addr=? order by at desc limit 1", (r["addr"],)).fetchone() or {"subject": ""})["subject"]
        rows.append({"addr": r["addr"], "name": names.most_common(1)[0][0] if names else "", "n": r["n"], "bytes": r["bytes"], "unread": r["unread"] or 0,
                     "list": r["lists"] or 0, "attach": r["attach"] or 0, "first": r["first"], "last": r["last"], "gone": r["gone"], "inbox": r["inbox"] or 0,
                     "starred": r["starred"] or 0, "wrote_to": wrote_to.get(r["addr"], 0), "category": cats.most_common(1)[0][0] if cats else "",
                     "protected": bool(PROTECTED.search(f"{r['addr']} {names.most_common(1)[0][0] if names else ''} {subject}"))})
    write(DATA / "census.json", {"at": int(time.time()), "senders": rows})


def write(path, doc):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False))
    tmp.replace(path)


def status(c, state, why="", remaining=None):
    one = lambda q: c.execute(q).fetchone()[0] or 0
    doc = {"at": int(time.time()), "state": state, "why": why, "total": one("select count(*) from messages"), "copied": one("select count(*) from messages where path is not null"),
           "total_bytes": one("select sum(size) from messages where gone is null or path is not null"), "copied_bytes": one("select sum(size) from messages where path is not null"),
           "gone": one("select count(*) from messages where gone is not null"), "today_bytes": spent(c), "daily_bytes": DAILY_BYTES,
           "refreshed": int(kv(c, "refreshed", 0) or 0), "newest": one("select max(at) from messages")}
    write(DATA / "status.json", doc)
    return doc


def secret():
    address = os.environ.get("GMAIL_ADDRESS") or (SECRET / "address").read_text().strip() if (SECRET / "address").exists() or os.environ.get("GMAIL_ADDRESS") else ""
    password = os.environ.get("GMAIL_APP_PASSWORD") or (SECRET / "password").read_text().strip() if (SECRET / "password").exists() or os.environ.get("GMAIL_APP_PASSWORD") else ""
    return address, password


def one_pass(c, address, password, bodies=True, daily=False):
    m = connect(address, password)
    try:
        status(c, "running")
        fresh = new_headers(c, m)
        due = time.time() - int(kv(c, "refreshed", 0) or 0) > 86000
        if due or daily:
            refresh(c, m)
        if fresh or due or daily or not (DATA / "census.json").exists():
            census(c, address.lower())
        copied = copy_bodies(c, m) if bodies else 0
        log(f"{fresh} new, {copied} copied, {spent(c) // 1_000_000} MB today")
    finally:
        try:
            m.logout()
        except Exception:
            pass


def main(argv):
    DATA.mkdir(parents=True, exist_ok=True)
    c = db()
    once, headers = "--once" in argv, "--headers-only" in argv
    while True:
        address, password = secret()
        if not (address and password):
            status(c, "waiting", "no app password yet: make mailvault-password")
            log("no app password yet")
            if once:
                return 2
            time.sleep(EVERY)
            continue
        try:
            one_pass(c, address, password, bodies=not headers)
            left = c.execute("select count(*) from messages where path is null and gone is null").fetchone()[0]
            status(c, "copying" if left else "current")
        except imaplib.IMAP4.error as e:
            refused = "AUTHENTICATIONFAILED" in str(e).upper() or "Invalid credentials" in str(e)
            status(c, "failed", "Gmail refused the app password" if refused else f"IMAP: {type(e).__name__}")
            log("failed:", "login refused" if refused else type(e).__name__)
            if refused and not once:
                time.sleep(3600)                            # a wrong password, asked again and again, locks the account
        except Exception as e:                              # the network, or a mail that did not copy: the next pass goes on
            status(c, "failed", f"{type(e).__name__}: {e}")
            log("failed:", type(e).__name__, e)
        if once:
            return 0
        time.sleep(EVERY)


if __name__ == "__main__":
    sys.exit(main(sys.argv))

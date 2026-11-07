"""The Postmaster (crew, hourly; CNX-08): looks after the owner's Gmail, carefully. Phase 1: it files the stack's own mail and
reports on the copy; it reads no message text, calls no model and removes nothing.

  1. The stack's own mail goes to the label "AI Stack", out of the inbox. Its mark is its exact sender, "AI Stack <the
     address>". from:me to:me is no such mark: it also holds what the owner mails himself, like papers and tickets.
     Mail from before the Postmaster's first run stays where it is until the owner says so (past file).
  2. The mail copy on the NAS (nas/mailvault): status.json and census.json come over to /srv/ai/missions/mail for the app. A
     copy that stops, or a refused password, is said once a day; the end of the first copy once.

  python3 ops/crew.py postmaster            (crew-postmaster.service, hourly)
  python3 ops/postmaster.py past list       the stack's past mail, read-only
  python3 ops/postmaster.py past file       file it (on the owner's word)
"""
import email.utils
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import inbox as IN
import notify as N
import textcap as TC

C = M = None                                         # ops/crew.py and ops/missions.py (set by crew.run)
OUT = Path(os.environ.get("POSTMASTER_OUT", "/srv/ai/missions/mail"))
NAS = "/volume1/docker/mailvault/data"
LABEL = "AI Stack"
TEST_SUBJECT = "Mission Control: e-mail works"      # ops/email-setup.sh sends this one with the plain address
SINCE = "2026/09/01"                                # the stack's first mail is after this: no need to look further back
ROW = re.compile(r"^- id (\S+) · ([^·]*) · (.*?) · (.*?)(?: · unread)?(?: · newsletter)? · \d+ KB(?: · PROTECTED.*)?$", re.M)
LISTED = 100                                         # the mail tool's own limit
STALE_S = 26 * 3600                                  # limit: paces, a copy silent this long is said once a day


def own(row, address=None, listed_subject=True):
    """The stack's own mail, by its exact sender: nothing else ever moves."""
    address = (address or os.environ.get("GMAIL_ADDRESS", "")).lower()
    who = email.utils.parseaddr(row["from"])
    return bool(address) and who[1].lower() == address and (who[0] == LABEL or (listed_subject and row["subject"] == TEST_SUBJECT))


def rows_of(text):
    return [{"id": m[1], "date": m[2].strip(), "from": m[3].strip(), "subject": m[4].strip()} for m in ROW.finditer(text or "")]


def when(row):
    try:
        return email.utils.parsedate_to_datetime(row["date"]).timestamp()
    except (TypeError, ValueError):
        return 0


def search(query, tool=None):
    return rows_of((tool or call)("mail-mail_search", {"query": query, "folder": "all", "limit": LISTED}))


def call(name, args):
    return IN.mcp(name, args, key=os.environ["VK_POSTMASTER"])


def stack_mail(since, tool=None, folder_query=""):
    """The stack's own mail since a date, split by day so that the tool's limit never hides any."""
    return [r for r in search(f"from:me to:me after:{since}{folder_query}", tool) if own(r)]


def file_mail(rows, tool=None):
    """-> how many went to the label and out of the inbox."""
    tool = tool or call
    ids = [r["id"] for r in rows]
    if not ids:
        return 0
    tool("mail-mail_label", {"ids": ids, "label": LABEL})
    tool("mail-mail_archive", {"ids": ids})
    return len(ids)


def fetch(name):
    """One file of the copy, over ssh -> its text, or None (the NAS asleep, nothing there yet)."""
    try:
        p = subprocess.run(["ssh", "-o", "ConnectTimeout=20", "synology", f"cat {NAS}/{name}"], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):       # no ssh here, or no answer: the same as the NAS asleep
        return None
    return p.stdout if p.returncode == 0 and p.stdout.strip() else None


def bring_over(get=fetch):
    """-> the copy's status, kept for the app."""
    OUT.mkdir(parents=True, exist_ok=True)
    OUT.chmod(0o755)
    st = None
    for name in ("status.json", "census.json"):
        text = get(name)
        if text:
            json.loads(text)                             # a half-read file never replaces a good one
            tmp = OUT / f".{name}"
            tmp.write_text(text)
            tmp.chmod(0o644)
            tmp.replace(OUT / name)
    try:
        st = json.loads((OUT / "status.json").read_text())
    except (OSError, ValueError):
        pass
    return st


def say_copy(st, cur, now=None, send=None):
    """What the owner hears about the copy: a problem once a day, the end of the first copy once. -> a line for the result."""
    now, send = now or time.time(), send or (lambda text, key: N.send(text, "health", by="postmaster", title="Mail copy", key=key))
    if not st:
        return "the mail copy on the NAS has not reported yet"
    done = f"{st['copied']:,} of {st['total']:,} mails copied"
    if st["state"] == "waiting":
        return "the mail copy waits for its app password (make mailvault-password)"
    if st["state"] == "failed":
        send(f"The mail copy on the NAS stopped: {TC.fit(str(st.get('why')), 800)}. {done}. Nothing is lost; it goes on when this is mended.", "mailvault:failed")  # cap: api
        return f"the mail copy failed: {st.get('why')}; {done}"
    if now - st["at"] > STALE_S:
        send(f"The mail copy on the NAS has not reported for {int((now - st['at']) // 3600)} hours. {done}.", "mailvault:stale")
        return f"the mail copy has been silent since {time.strftime('%d %b %H:%M', time.localtime(st['at']))}; {done}"
    if st["state"] == "current" and not cur.get("copy_done"):
        send(f"Your Gmail is now copied to the NAS: {st['total']:,} mails. It stays current every 15 minutes.", "mailvault:done")
        C.save("postmaster", copy_done=now)
    return done


def run(c):
    cur = C.agent_file("postmaster")
    now = time.time()
    if not cur.get("since"):                             # from now on: what came before waits for the owner
        cur["since"] = now
        C.save("postmaster", since=now)
    filed = 0
    said = []
    if IN.granted("read") and IN.granted("organize"):
        day = time.strftime("%Y/%m/%d", time.localtime(max(cur["since"], now - 3 * 86400) - 86400))
        fresh = [r for r in stack_mail(day) if when(r) >= cur["since"] and r["id"] not in set(cur.get("filed") or [])]
        filed = file_mail(fresh)
        if filed:
            C.save("postmaster", filed=((cur.get("filed") or []) + [r["id"] for r in fresh])[-500:], total_filed=(cur.get("total_filed") or 0) + filed)  # cap: rotate (ids already handled)
            said.append(f"{filed} of the stack's mails filed under {LABEL}")
    else:
        said.append("Gmail read and organize are not granted, so the stack's mail stays in the inbox")
    said.append(say_copy(bring_over(), cur, now))
    C.save("postmaster", result="; ".join(said), last=time.time())
    return 0                                             # no push of its own: say_copy tells what matters


def past(cmd, tool=None):
    """The stack's mail from before the Postmaster's first run: listed, and filed only on the owner's word."""
    rows = stack_mail(SINCE, tool)
    print(f"{len(rows)} mails from the stack since {SINCE}:")
    for r in rows:
        print(f"  {r['date'][:22]} · {r['subject']}")  # cap: id (a date in a terminal list)
    if cmd == "file":
        print(f"filed {file_mail(rows, tool)} under {LABEL}")
    return rows


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "past" and sys.argv[2] in ("list", "file"):
        class _Quiet:                                    # outside a crew run there is no run record to write to
            stage = staticmethod(lambda *a, **k: None)
        IN.RTM = _Quiet
        past(sys.argv[2])
    else:
        sys.exit(__doc__)

#!/usr/bin/env python3
"""The mail sorter's look at the mail copy (CNX-10), run on the NAS. ops/mailsort.py sends this file over ssh to the
NAS's own python3 (`ssh <nas> python3 - <args>`): nothing is installed there, and nothing is written there.

It opens the copy's index read-only (nas/mailvault: one row per mail, its headers only; there is no message text in
it) and prints one JSON document: the senders whose mail is worthless bulk, with high confidence or likely, why, what
each per-mail guard kept, three sample subjects per sender, and for the senders the owner approved the mails to sort
out (id, whether it is in the inbox, subject). No model. Python 3.8's standard library (the NAS's python3).

  ssh <nas> python3 - <base64 of {"me", "label", "kept", "approve", "now"}> < ops/mailsort_nas.py
  python3 ops/mailsort_nas.py <args> --db <index.sqlite>       (the tests, on a made-up index)
"""
import base64
import collections
import json
import re
import sqlite3
import sys
import time

INDEX = "/volume1/docker/mailvault/data/index.sqlite"
# As images/mail/mail.py (tests/test_mailsort.py keeps them equal): the connector never archives this mail, so the
# sorter never offers it.
PROTECTED = re.compile(
    r"bank|sparkasse|volksbank|raiffeisen|comdirect|consorsbank|\bdkb\b|\bing\b|n26|revolut|paypal|klarna|"
    r"trade ?republic|scalable|broker|depot|finanzamt|elster|"
    r"security alert|sicherheits(hinweis|warnung)|new sign-in|neue anmeldung|verification code|bestätigungscode|"
    r"verifizierungscode|sicherheitscode|one-time|einmal(code|passwort)|\b2fa\b|two-factor|zwei-faktor|"
    r"password reset|passwort zurücksetzen|reset your password|login code|anmeldecode|google account|google-konto",
    re.I)
# What a person may need years later, in generic words (no company, no place: SEC-22): money, orders and parcels,
# contracts and accounts, health, the state, travel, home, school and work. A sender or a subject that names one stays.
KEEP = re.compile(
    r"rechnung|invoice|receipt|quittung|beleg|\border|bestell|versand|shipping|shipment|deliver|liefer|tracking|paket|parcel|"
    r"ticket|booking|buchung|reserv|\bflug|flight|airline|boarding|\bbahn\b|\bzug\b|train\b|hotel|reise|travel|"
    r"versicher|insur|kranken|arzt|praxis|klinik|apothe|pharm|health|gesundheit|"
    r"steuer|\btax|finanz|\bamt\b|\bgov\b|\.gov|behoerde|behörde|polizei|police|gericht|court|"
    r"vertrag|contract|kündig|kuendig|cancel|\babo\b|subscription|konto|account|billing|payment|zahlung|lastschrift|mahnung|"
    r"refund|erstattung|garantie|warranty|"
    r"vermiet|miete|\brent\b|strom|energie|electric|wasser|heizung|"
    r"schule|school|\buni\b|universit|hochschule|\bjob|bewerbung|application|career|personal\b",
    re.I)
# A sender that relays what people write (a site's message, a reply, a comment, a mention), in generic words (SEC-22): it is
# never high confidence, and each such mail stays where it is.
RELAY_SENDER = re.compile(r"message|inmail|chat|nachricht", re.I)
RELAY = re.compile(
    r"sent you a message|sent you|messaged you|wrote to you|wrote you|new message from|you have a new message|"
    r"replied to|replied|commented|mentioned you|"
    r"hat dir|hat ihnen|eine nachricht|neue nachricht|nachricht von|antwortete|hat geantwortet|kommentiert|erwähnt|erwaehnt",
    re.I)
RELAY_SHARE = 0.05            # a sender relays people's messages when this share of its subjects says so (a dating site's
                              # notices were 9 % in the dry run of 10 Nov 2026; each such mail stays anyway)
CATEGORY_BULK = ("promotions", "social")
# limit: drops, a sender with fewer mails is never proposed; Your mail's list of senders still shows it
MIN_MAILS = 5
BULK_SHARE = 0.8              # a sender is bulk when this share of its mail is a mailing list (List-Unsubscribe)
HIGH_FILES, LIKELY_FILES = 0.02, 0.05    # the share of a sender's mail with attachments that each tier allows
# limit: waits, a mail younger than this stays where it is; a later run sorts it once it is older
YOUNG_S = 30 * 86400
STACK_NAME = "AI Stack"       # the stack's own mail: its exact sender (ops/postmaster.py, CNX-08)
# The per-mail guards, in the order a kept mail is counted under (the first that holds).
GUARDS = ("the stack's own mail", "banks and security", "starred", "important", "one of your labels", "an attachment",
          "a message from someone", "words that may matter", "a thread you wrote in", "younger than 30 days")
TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|(\S+)')


def labels_of(raw):
    """Gmail's X-GM-LABELS as the copy keeps it (`"\\\\Inbox" "\\\\Starred" Receipts "AI Stack"`) -> the labels."""
    out = []
    for quoted, bare in TOKEN.findall(raw or ""):
        name = re.sub(r"\\(.)", r"\1", quoted) if quoted else bare
        if name:
            out.append(name)
    return out


def own_labels(labels, label):
    """The owner's own labels: not Gmail's system ones (a backslash first) and not the sorter's."""
    return [x for x in labels if not x.startswith("\\") and x != label]


def tier(n, lists, attach, category, relays=False):
    """-> "high", "likely" or None, from the sender's headers. A sender that relays people's messages is at most likely."""
    bulk = lists / n >= BULK_SHARE or category in CATEGORY_BULK
    files = attach / n
    if bulk and files <= HIGH_FILES and category in CATEGORY_BULK and not relays:
        return "high"
    if bulk and files <= LIKELY_FILES:
        return "likely"
    return None


def guard(m, me, label, owner_threads, now):
    """The first per-mail guard that keeps this mail, or None (it may go). m: a row of the index."""
    labels = set(labels_of(m["labels"]))
    who = "{} <{}>".format(m["sender"] or "", m["addr"] or "")
    if m["addr"] in me and (m["sender"] or "") == STACK_NAME:
        return "the stack's own mail"
    if PROTECTED.search("{} {}".format(who, m["subject"] or "")):
        return "banks and security"
    if "\\Starred" in labels:
        return "starred"
    if "\\Important" in labels:
        return "important"
    if own_labels(labels, label):
        return "one of your labels"
    if m["attach"]:
        return "an attachment"
    if RELAY.search(m["subject"] or ""):
        return "a message from someone"
    if KEEP.search(m["subject"] or ""):
        return "words that may matter"
    if m["thread"] and m["thread"] in owner_threads:
        return "a thread you wrote in"
    if (m["at"] or 0) > now - YOUNG_S:
        return "younger than 30 days"
    return None


def analyse(c, args):
    now = int(args.get("now") or time.time())
    label = args.get("label") or ""
    kept, approve = set(args.get("kept") or []), set(args.get("approve") or [])
    rows = c.execute("select id, thread, at, sender, addr, recipients, subject, size, labels, list, attach, category, gone "
                     "from messages order by at desc").fetchall()
    # the owner: the configured address and every address Gmail filed a sent mail from
    me = {a for a in [str(args.get("me") or "").lower()] if a}
    me |= {r["addr"] for r in rows if "\\Sent" in labels_of(r["labels"]) and r["addr"]}
    wrote_to, owner_threads, by = set(), set(), collections.OrderedDict()
    for r in rows:
        if r["addr"] in me:
            wrote_to.update(a for a in (r["recipients"] or "").split(",") if a)
            if r["thread"]:
                owner_threads.add(r["thread"])
        elif r["addr"]:
            by.setdefault(r["addr"], []).append(r)
    left = collections.Counter()                  # mails of senders never proposed, by the reason
    kept_all, gone = collections.Counter(), 0
    senders, moves = [], {}
    for addr, ms in by.items():
        n = len(ms)
        names = collections.Counter(m["sender"] for m in ms[:50] if m["sender"])  # cap: parse (the name in its newest 50 mails, as the census)
        name = names.most_common(1)[0][0] if names else ""
        cats = collections.Counter(m["category"] for m in ms if m["category"])
        category = cats.most_common(1)[0][0] if cats else ""
        lists, attach = sum(m["list"] or 0 for m in ms), sum(m["attach"] or 0 for m in ms)
        starred = any("\\Starred" in labels_of(m["labels"]) for m in ms)
        if addr in kept:
            left["you keep this sender"] += n
            continue
        if PROTECTED.search("{} {} {}".format(addr, name, ms[0]["subject"] or "")):
            left["banks and security"] += n
            continue
        if addr in wrote_to:
            left["you wrote to them"] += n
            continue
        if starred:
            left["you starred one of their mails"] += n
            continue
        if KEEP.search("{} {}".format(name, addr)):
            left["the sender's name may matter later"] += n
            continue
        if n < MIN_MAILS:
            left["fewer than {} mails".format(MIN_MAILS)] += n
            continue
        relayed = sum(bool(RELAY.search(m["subject"] or "")) for m in ms)
        relays = bool(RELAY_SENDER.search("{} {}".format(name, addr))) or relayed / n >= RELAY_SHARE
        t = tier(n, lists, attach, category, relays)
        if not t:
            left["not clearly bulk"] += n
            continue
        go, held = [], collections.Counter()
        for m in ms:
            if m["gone"]:
                gone += 1
                continue
            if label and label in labels_of(m["labels"]):
                held["already sorted"] += 1
                continue
            g = guard(m, me, label, owner_threads, now)
            if g:
                held[g] += 1
            else:
                go.append(m)
        kept_all.update({k: v for k, v in held.items() if k != "already sorted"})
        if not go:
            left["every mail kept by a guard or sorted already"] += n
            continue
        senders.append({"addr": addr, "name": name, "tier": t, "n": n, "list": lists, "attach": attach, "category": category,
                        "relays": relays, "relayed": relayed,
                        "movable": len(go), "inbox": sum("\\Inbox" in labels_of(m["labels"]) for m in go),
                        "bytes": sum(m["size"] or 0 for m in go), "first": ms[-1]["at"], "last": ms[0]["at"],
                        "kept": dict(held), "samples": [m["subject"] or "" for m in go[:3]]})  # cap: top (three samples of what would go, newest first)
        if addr in approve:
            moves[addr] = [[m["id"], int("\\Inbox" in labels_of(m["labels"])), m["subject"] or ""] for m in go]
    senders.sort(key=lambda s: (s["tier"] != "high", -s["movable"], s["addr"]))
    return {"at": now, "label": label, "mails": len(rows), "senders_all": len(by), "senders": senders,
            "left": dict(left), "guards": dict(kept_all), "gone": gone, "moves": moves}


def main(argv):
    args = json.loads(base64.b64decode(argv[1]).decode()) if len(argv) > 1 else {}
    db = argv[argv.index("--db") + 1] if "--db" in argv else INDEX
    c = sqlite3.connect("file:{}?mode=ro".format(db), uri=True, timeout=60)    # read-only: the copy is never changed
    c.row_factory = sqlite3.Row
    try:
        out = analyse(c, args)
    finally:
        c.close()
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

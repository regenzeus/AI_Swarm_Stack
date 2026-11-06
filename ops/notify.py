#!/usr/bin/env python3
"""The one notification path (OBS-16, SN-18): every message the stack sends the owner, on Telegram or as a push,
goes through send(), which applies the owner's preferences per category, quiet hours and once per key, and logs
each decision. Nothing else talks to Telegram (tests/test_notify.py checks it).

    python3 ops/notify.py send --category system "text"     (ops/notify.sh, for shell jobs)

Approvals (the AI phone, Gmail, purchases) are always sent, also in quiet hours: they expire if nobody sees them.
Telegram goes through the Bot API when the token is in the environment (the runner), otherwise through Hermes'
own sender (shell jobs without secrets). A push is an event the app turns into a web push."""
import fcntl
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

STATE = Path("/srv/ai/state")
PREFS, LOG, HELD, KEYS = (STATE / "notify-prefs.json", STATE / "notifications.jsonl", STATE / "notify-held.jsonl",
                          STATE / "notify-keys.json")
EVENTS = Path("/srv/ai/missions/public/events.jsonl")         # the app reads it and pushes what is marked push
TOLD = Path("/srv/ai/missions/public/told.jsonl")             # SWM-113: who told the owner what, for the map (this log's state folder isn't mounted there)
CATEGORIES = {
    "approval": "Approvals: the AI phone, Gmail, purchases (always sent, also in quiet hours)",
    "result": "Results: briefings, mission reports, digests, chat answers that waited",
    "alert": "Event alerts: triggers, price drops, orders and deliveries",
    "health": "Agent health alerts",
    "build": "Builds and deploys",
    "swarm": "The swarm: Board messages, ideas, autonomy",
    "system": "Stack upkeep: upgrades, connections, errors",
}
CHANNELS = ("telegram", "push")
# the activity feed's event kinds -> category, for events that ask for a push (missions.event)
KIND = {"build": "build", "health": "health", "triggered": "alert", "price_drop": "alert", "shop_proposal": "approval",
        "shop_over": "approval", "shop_bought": "alert", "shop_stopped": "alert", "shop_delivered": "alert",
        "run_failed": "result", "budget": "result", "waiting": "result", "delivered": "result", "swarm": "swarm",
        "autonomy": "swarm", "error": "system", "system": "system", "house": "system", "claude": "system"}
TELEGRAM_MAX = 4096                                           # Telegram's message limit (characters)


def prefs():
    """{telegram: {category: bool}, push: {category: bool}, quiet: {from, to} or None}; everything on by default."""
    try:
        p = json.loads(PREFS.read_text())
    except (OSError, ValueError):
        p = {}
    return {ch: {c: bool((p.get(ch) or {}).get(c, True)) or c == "approval" for c in CATEGORIES} for ch in CHANNELS} | {
        "quiet": p.get("quiet") if isinstance(p.get("quiet"), dict) else None}


def set_prefs(raw):
    """The owner's preferences from the app (request notify_prefs), validated; approvals stay on."""
    out = {ch: {c: bool((raw.get(ch) or {}).get(c, True)) or c == "approval" for c in CATEGORIES} for ch in CHANNELS}
    q = raw.get("quiet")
    if q:
        if not (isinstance(q, dict) and all(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(q.get(k, ""))) for k in ("from", "to"))):
            raise ValueError("quiet hours need a start and an end as HH:MM")
        if q["from"] == q["to"]:
            raise ValueError("quiet hours need a start and an end that differ")
        out["quiet"] = {"from": q["from"], "to": q["to"]}
    else:
        out["quiet"] = None
    STATE.mkdir(parents=True, exist_ok=True)
    PREFS.write_text(json.dumps(out))
    return out


def quiet(p=None, now=None):
    """True inside the owner's quiet hours (they may run over midnight)."""
    q = (p or prefs())["quiet"]
    if not q:
        return False
    t = time.strftime("%H:%M", time.localtime(now or time.time()))
    return q["from"] <= t < q["to"] if q["from"] < q["to"] else (t >= q["from"] or t < q["to"])


def category_of(kind, title=""):
    return KIND.get(kind) or ("swarm" if title in ("Swarm", "Autonomy") else "system")


def _log(**row):
    STATE.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"ts": int(time.time()), **row}, ensure_ascii=False) + "\n"
    with LOG.open("a") as f:
        f.write(line)
    try:
        with TOLD.open("a") as f:
            f.write(line)
    except OSError as e:                                 # the map's copy must never stop a message
        print(f"notify: {TOLD} not written ({type(e).__name__})", file=sys.stderr)


def record(channel, category, title, text, decision, by="mission"):
    """A delivery made outside send() (the e-mail of a report) goes into the same log, so the app shows it was sent."""
    _log(channel=channel, category=category, title=title, text=text, decision=decision, by=by)


def _once(key, every, now):
    """True the first time a key is sent within `every` seconds (the same issue is not sent twice a day)."""
    STATE.mkdir(parents=True, exist_ok=True)
    with open(KEYS.with_suffix(".lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)                  # the runner and the shell jobs share this file
        try:
            seen = json.loads(KEYS.read_text())
        except (OSError, ValueError):
            seen = {}
        if now - seen.get(key, 0) < every:
            return False
        seen[key] = now
        KEYS.write_text(json.dumps({k: v for k, v in seen.items() if now - v < 7 * 86400}))
        return True


def decide(channel, category, p=None, now=None):
    """-> 'send', 'off' (the owner turned it off) or 'held' (quiet hours; approvals are never held)."""
    p = p or prefs()
    if category == "approval":
        return "send"
    if not p[channel].get(category, True):
        return "off"
    return "held" if quiet(p, now) else "send"


def push_allowed(kind, text, title="", category=None, by=""):
    """missions.event(push=True): the push only if the owner's preferences and quiet hours allow it; logged."""
    cat = category or category_of(kind, title)
    d = decide("push", cat)
    _log(channel="push", category=cat, title=title, text=text, decision="sent" if d == "send" else d, by=by)
    return d == "send"


def _telegram_bot(text_html, buttons):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), (os.environ.get("TELEGRAM_ALLOWED_USERS") or "").split(",")[0]
    if not (tok and chat):
        return False
    body = {"chat_id": chat, "text": text_html, "parse_mode": "HTML", "disable_web_page_preview": True}
    if buttons:
        body["reply_markup"] = {"inline_keyboard": [[{"text": t, "url": u} for t, u in row] for row in buttons]}
    try:
        req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        return bool(json.load(urllib.request.urlopen(req, timeout=30)).get("ok"))
    except Exception as e:                               # noqa: BLE001 - any failure falls back to Hermes' sender
        print(f"notify: Telegram Bot API failed ({type(e).__name__}), sending through Hermes", file=sys.stderr)
        return False


def telegram_document(name, data, caption="", mime="text/plain"):
    """MIS-25: a mission's file as a Telegram document (the Bot API's sendDocument, multipart). Sent only after the
    result's own message went out (send() applied the owner's policy to that one). True when Telegram took it."""
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), (os.environ.get("TELEGRAM_ALLOWED_USERS") or "").split(",")[0]
    if not (tok and chat):
        return False
    b = "aistack" + uuid.uuid4().hex
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat}\r\n'.encode()]
    if caption:
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{caption[:1000]}\r\n'.encode())  # cap: api (Telegram's caption limit is 1024)
    parts += [f'--{b}\r\nContent-Disposition: form-data; name="document"; filename="{name}"\r\nContent-Type: {mime}\r\n\r\n'.encode(),
              data, f"\r\n--{b}--\r\n".encode()]
    try:
        req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendDocument", data=b"".join(parts),
                                     headers={"Content-Type": f"multipart/form-data; boundary={b}"})
        return bool(json.load(urllib.request.urlopen(req, timeout=60)).get("ok"))
    except Exception as e:                               # noqa: BLE001 - the file stays in the app; the card says not sent
        print(f"notify: Telegram document {name} failed ({type(e).__name__})", file=sys.stderr)
        return False


def _telegram_hermes(text):
    env = {**os.environ, "DOCKER_HOST": os.environ.get("DOCKER_HOST", "unix:///run/user/1000/docker.sock")}
    r = subprocess.run(["docker", "exec", "-u", "hermes", "aistack-hermes-1", "sh", "-c",
                        'hermes send -t "telegram:$TELEGRAM_ALLOWED_USERS" "$0"', text], capture_output=True, timeout=60, env=env)
    return r.returncode == 0


def _fit(text_html):
    """Telegram takes 4096 characters; a longer message says where the whole text is instead of ending mid-word."""
    if len(text_html) <= TELEGRAM_MAX:
        return text_html
    note = "\n… (longer than Telegram allows: the whole message is in the app's notification log)"
    return re.sub(r"<[^>]*$", "", text_html[:TELEGRAM_MAX - len(note)]) + note       # cap: api (Telegram's limit)


def telegram(text_html, buttons=()):
    """Deliver one message now (no policy: send() decides). True when it went out."""
    t = _fit(text_html)
    return _telegram_bot(t, buttons) or _telegram_hermes(re.sub(r"<[^>]+>", "", html.unescape(t)))


def _event(kind, slug, text, push, title):
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, "slug": slug, "title": title,
                            "text": text, "push": push}, ensure_ascii=False) + "\n")


def send(text, category="system", *, by="stack", title="", slug="", buttons=(), key=None, every=86400, telegram_on=True,
         push_on=False, event_kind=None, is_html=False, now=None):
    """One notification. by: who sends it, an agent's id or "stack" (every caller names it: tests/test_interactions.py).
    text is plain unless is_html (Telegram's HTML subset). push_on also shows it in the activity feed (event_kind) and
    pushes it when allowed. key: the same key is sent at most once per `every` seconds. -> {channel: decision}."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown notification category {category!r}")
    now = now or time.time()
    plain = re.sub(r"<[^>]+>", "", html.unescape(text)) if is_html else text
    if key and not _once(f"{category}:{key}", every, now):
        _log(channel="any", category=category, title=title, text=plain, decision="duplicate", key=key, by=by)
        return {"telegram": "duplicate", "push": "duplicate"}
    p, out = prefs(), {}
    if push_on:
        d = decide("push", category, p, now)
        _event(event_kind or category, slug, plain, d == "send", title)
        out["push"] = "sent" if d == "send" else d
        _log(channel="push", category=category, title=title, text=plain, decision=out["push"], by=by)
    if telegram_on:
        d = decide("telegram", category, p, now)
        body = text if is_html else html.escape(text)
        if title and is_html is False:
            body = f"<b>{html.escape(title)}</b>\n{body}"
        if d == "held":
            with HELD.open("a") as f:
                f.write(json.dumps({"ts": int(now), "category": category, "title": title, "text": plain}, ensure_ascii=False) + "\n")
            out["telegram"] = "held"
        elif d == "off":
            out["telegram"] = "off"
        else:
            out["telegram"] = "sent" if telegram(_fit(body), buttons) else "failed"
        _log(channel="telegram", category=category, title=title, text=plain, decision=out["telegram"], by=by)
    return out


def flush(now=None):
    """After quiet hours: what was held goes out as one message (the runner calls this every few seconds)."""
    if quiet(now=now) or not HELD.exists():
        return 0
    tmp = HELD.with_suffix(".sending")
    HELD.replace(tmp)
    rows = [json.loads(x) for x in tmp.read_text().splitlines() if x.strip()]
    if rows:
        lines = "\n".join(f"• <b>{html.escape(r['title'])}</b>: {html.escape(r['text'])}" if r.get("title") else f"• {html.escape(r['text'])}"
                          for r in rows)
        ok = telegram(f"🌙 <b>During quiet hours ({len(rows)})</b>\n{lines}")
        _log(channel="telegram", category="system", title="During quiet hours", text=f"{len(rows)} held messages",
             decision="sent" if ok else "failed", by="stack")
    tmp.unlink()
    return len(rows)


def state(n=50):
    """For the app's Notifications section: preferences, categories, how many wait for the end of quiet hours, and
    the newest decisions."""
    try:
        recent = [json.loads(x) for x in LOG.read_text().splitlines()[-n:]][::-1]    # cap: list (the app shows the newest 50)
    except (OSError, ValueError):
        recent = []
    try:
        held = sum(1 for x in HELD.read_text().splitlines() if x.strip())
    except OSError:
        held = 0
    return {"notify": {"prefs": prefs(), "categories": CATEGORIES, "quiet_now": quiet(), "held": held, "recent": recent}}


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "send":
        args = sys.argv[2:]
        cat = "system"
        if args[:1] == ["--category"]:
            cat, args = args[1], args[2:]
        if args[:1] == ["--"]:
            args = args[1:]
        res = send(" ".join(args), cat, by=os.environ.get("NOTIFY_BY") or "stack")
        sys.exit(0 if res.get("telegram") in ("sent", "held", "off", "duplicate") else 1)
    sys.exit(__doc__)

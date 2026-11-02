"""The AI phone: Hermes' hands on one Android phone (the old test phone), through ADB over Tailscale.

MCP tools (via LiteLLM, key vk-main): phone_look (screen as a numbered list of elements), phone_tap, phone_type,
phone_swipe, phone_key, phone_open, phone_apps. Safety, in this order:
  - Stop: /phone/STOP (Mission Control's Phone page) refuses every tool and disconnects.
  - Block list (/phone/blocklist.txt): banking, investment, payment, password and settings apps are never read
    or touched; if one comes to the front, the phone is sent to the home screen.
  - Approval: every action that changes something waits for the owner's tap in Mission Control (push to the
    main phone), unless the owner allowed actions for a few minutes. No answer in 15 minutes = no.
  - Money guard: a tap on anything that buys, pays, orders or subscribes always waits for its own approval (a time
    window never covers it); password, card and bank fields are never typed into: the owner does that himself.
  - Purchases: the one exception to "every money tap asks". When the owner approved a shopping proposal in Mission
    Control, the runner writes /phone/purchases/<id>.json (item, variant, seller, ceiling, address words, 45 min).
    While it is open, steps inside that shop's app run without asking, typing is refused, and taps that change the
    address or payment method are refused. The final buy button is tapped only if the final screen passes a
    deterministic check (final_check: item, variant, seller, total <= ceiling, address, no login/code/captcha/
    3-D Secure); then exactly once, logged as approved by that proposal. Anything else: stop, screenshot, ask.
  - Log: every call, decision and result in /phone/log.jsonl, with a screenshot of what was approved.
The container can reach this one phone and nothing else (entrypoint.sh firewall).
  - Cleanup steps: the owner approves one step at a time on the Phone cleanup agent's page (ops/phone_agents.py);
    the runner writes /phone/cleanup/<step>-<n>.json and the phone runs exactly that step once within 30 minutes
    (cleanup_do: delete files by age at a deletable path, uninstall an app the owner installed, or trim caches), with the
    block list and path checks of the tools, and leaves <step>-<n>.result.json with the space freed.
State for the app: /phone/state.json; pending approvals /phone/pending; decisions /phone/decisions; requests from
the app (pair, connect) /phone/control.
"""
import asyncio, io, json, os, re, subprocess, time, uuid, xml.etree.ElementTree as ET
import textcap as TC                              # visible caps (AGENTS.md, truncation)
from pathlib import Path

import uvicorn
from mcp.server.mcpserver import Image, MCPServer
from mcp.server.transport_security import TransportSecuritySettings

D = Path(os.environ.get("PHONE_DIR", "/phone"))
HOST = os.environ.get("PHONE_HOST", "")                 # the phone's Tailscale IP
PENDING, DECISIONS, CONTROL, SHOTS, DONE = D / "pending", D / "decisions", D / "control", D / "shots", D / "done"
PURCHASES, RESEARCH = D / "purchases", D / "research"     # the owner's approved purchases (runner); app look-ups
CLEANUP = D / "cleanup"                                  # the owner's approved cleanup steps (runner, ops/phone_agents.py)
CLEANUP_ID = re.compile(r"^c-[0-9a-f]{10}-\d{1,3}$")
WAIT = 900                                               # 15 min for the owner's OK: they may be busy (no answer = no)
DEFAULT_BLOCK = """# Apps the AI phone never reads or touches (one per line: a package name, or a word that appears in it).
# Edit freely; it is read on every call.
bank
banking
invest
broker
trading
trade
finanz
sparkasse
volksbank
comdirect
com.ing
n26
revolut
paypal
klarna
wallet
pay
crypto
coinbase
binance
bitpanda
trade.republic
traderepublic
scalable
authenticator
authy
password
1password
bitwarden
lastpass
keepass
com.android.settings
com.samsung.android.settings
com.android.vending
com.google.android.gms.wallet
com.samsung.android.spay
com.osp.app.signin
com.google.android.apps.accountsettings
# the voice satellite (docs/HOME-VOICE.md, VOI-07): its sign-in reaches the house, the FRITZ!Box and the NAS, so only
# a task the owner approved that names it opens it ("task:" = blocked except inside such a task)
task:homeassistant
"""
for d in (PENDING, DECISIONS, CONTROL, SHOTS, DONE):
    d.mkdir(parents=True, exist_ok=True)
for d in (DECISIONS, CONTROL):                           # Mission Control (another user) writes the owner's answers here
    d.chmod(0o1777)
DONE.chmod(0o777)                                        # the host runner sends these to Telegram and removes them
if not (D / "blocklist.txt").exists():
    (D / "blocklist.txt").write_text(DEFAULT_BLOCK)

S = {"connected": False, "serial": "", "model": "", "android": "", "foreground": "", "paired": False,
     "trust_until": 0, "error": "", "phone_host": HOST}
# Paired before (ADB keeps the phone it trusts): after a restart of this container (every deploy) it reconnects by
# itself within a minute, instead of staying dark until someone presses Connect; the screen-awake loop needs it too.
S["paired"] = (Path(os.environ.get("HOME", str(D / "home"))) / ".android" / "adb_known_hosts.pb").exists()
# PHN-21: the owner's free mode and an approved task outlive a restart (every deploy); Stop still ends both
try:
    _was = json.loads((D / "state.json").read_text())
    if not (D / "STOP").exists():
        S["trust_until"] = _was.get("trust_until", 0) if _was.get("trust_until", 0) > time.time() else 0
        S["task"] = _was.get("task") if (_was.get("task") or {}).get("until", 0) > time.time() else None
except (OSError, ValueError):
    pass
elements = []                                            # the last phone_look, for phone_tap(element=n)

# ---------- the money guard ----------
# Labels of buttons that spend money (English and German shop wording). A tap on one always needs its own approval.
MONEY = re.compile(r"\b(buy|pay|paying|purchase|order|place\s+order|checkout|check\s+out|proceed\s+to\s+(checkout|payment)|"
                   r"subscribe|subscription|confirm\s+(payment|purchase|order)|book\s+now|rent|donate|1-click|one-click|"
                   r"kaufen|jetzt\s+kaufen|bezahlen|zahlen|zahlungspflichtig|bestellen|bestellung\s+abschicken|zur\s+kasse|kasse|"
                   r"abonnieren|abschließen|buchen|jetzt\s+buchen|spenden|in\s+den\s+warenkorb\s+und\s+kaufen)\b", re.I)
# Fields the AI never types into: passwords, card, bank and security codes. The owner types those himself.
SECRET_FIELD = re.compile(r"(passw|kennwort|passcode|\bpin\b|card|karte|kreditkarte|cvc|cvv|security\s*code|prüfnummer|"
                          r"iban|bic|account\s*number|kontonummer|sort\s*code|routing|expir|ablauf|gültig|one[- ]time|otp|tan\b|2fa)", re.I)
CARDLIKE = re.compile(r"(\d[ -]?){13,19}|\b[A-Z]{2}\d{2}[ ]?(\w{4}[ ]?){3,7}\b")   # card or IBAN-shaped text


# ---------- approved purchases (ops/shopping.py): the final-screen check ----------
# Buttons that place the order on the review screen, and steps toward it that spend nothing yet.
FINAL = re.compile(r"\b(jetzt\s+kaufen|zahlungspflichtig\s+bestellen|kaufen\s+und\s+bezahlen|bestellung\s+(aufgeben|abschicken)|"
                   r"place\s+(your\s+)?order|buy\s+now|complete\s+purchase)\b", re.I)
STEP = re.compile(r"\b(zur\s+kasse|weiter\s+zur\s+kasse|proceed\s+to\s+checkout|in\s+den\s+einkaufswagen|add\s+to\s+(cart|basket))\b", re.I)
# Taps that would change where it goes or how it is paid: refused during a purchase.
CHANGE = re.compile(r"(ändern|change|bearbeiten|edit|neue\s+adresse|adresse\s+hinzufügen|add\s+(a\s+)?(new\s+)?(address|card|payment)|"
                    r"zahlungsart|zahlungsmethode|payment\s+method|lieferadresse\s+wählen|choose\s+(an?\s+)?address|gutschein|voucher)", re.I)
BLOCKER = re.compile(r"(captcha|roboter|not\s+a\s+robot|einmal-?(code|passwort|kennwort)|bestätigungscode|verification\s+code|"
                     r"one[- ]time|\botp\b|\btan\b|3-?d[- ]?secure|securecode|verified\s+by\s+visa|id\s+check|passwor|kennwort|"
                     r"anmelden|sign[- ]in|einloggen|kartenprüfnummer|\bcvc\b|\bcvv\b)", re.I)
TOTAL = re.compile(r"(gesamtsumme|gesamtbetrag|bestellsumme|zu\s+zahlender\s+betrag|order\s+total|summe\s+inkl|^summe)", re.I)
EUR = re.compile(r"(?:€\s*(\d{1,5}(?:[.,]\d{3})*[.,]\d{2})|(\d{1,5}(?:[.,]\d{3})*[.,]\d{2})\s*(?:€|EUR))")
ORDER_NO = re.compile(r"\b(\d{3}-\d{7}-\d{7})\b|(?:bestellnummer|order\s*(?:number|#|nr\.?))\W{0,3}\s*([A-Z0-9-]{6,})", re.I)


def eur(text):
    v = text.replace(".", "").replace(",", ".") if re.search(r",\d{2}$", text) else text.replace(",", "")
    try:
        return round(float(v), 2)
    except ValueError:
        return None


def norm(s):
    return re.sub(r"[^a-z0-9äöüß€]", "", (s or "").lower())


def order_total(els):
    """The order total on a review screen: the amount in or beside (same row) its label; None if there is none."""
    for e in els:
        if TOTAL.search(e["label"]) and "zwischen" not in e["label"].lower():
            near = [e] + sorted((o for o in els if o is not e and abs(o["y"] - e["y"]) < 45), key=lambda o: abs(o["x"] - e["x"]))
            for o in near:
                if (m := EUR.search(o["label"])) and (v := eur(m.group(1) or m.group(2))):
                    return v
    return None


def final_check(els, pa):
    """(True, why) when the screen is exactly the approved order; (False, why) on a mismatch or a blocker (stop the
    purchase); (None, why) when this is not the review screen yet."""
    text = "\n".join(e["label"] for e in els)
    flat = norm(text)
    if any(e["kind"] == "secret" for e in els):
        return False, "a password, card or code field is on the screen: the owner does that himself"
    if (b := BLOCKER.search(text)):
        return False, f"the screen asks for “{b.group(0)}” (sign-in, code, captcha or card check): the owner does that himself"
    total = order_total(els)
    if total is None:
        return None, "this is not the order review screen (no order total on it): use the cart and checkout first"
    missing = [w for w in pa.get("item_words", []) + pa.get("variant_words", []) if norm(w) not in flat]
    if missing:
        return False, f"the item or variant differs: {', '.join(missing)} not on the final screen"
    if pa.get("seller_words") and not any(norm(w) in flat for w in pa["seller_words"]):
        return False, f"the seller differs: {', '.join(pa['seller_words'])} not on the final screen"
    if not pa.get("address_words") or not all(norm(w) in flat for w in pa["address_words"]):
        return False, "the delivery address differs from the one the owner set for checking"
    if total > pa["max_total_eur"]:
        return False, f"the total {total:.2f} € is above the approved {pa['max_total_eur']:.2f} €"
    return True, f"item {', '.join(pa['item_words'])}, total {total:.2f} € ≤ {pa['max_total_eur']:.2f} €, address and seller as approved"


def active_purchase():
    """The owner's approved purchase the AI phone is completing now, or None (unused, not expired, not stopped)."""
    for f in sorted(PURCHASES.glob("p-*.json")) if PURCHASES.exists() else []:
        if f.name.endswith(".result.json"):
            continue
        try:
            pa = json.loads(f.read_text())
        except ValueError:
            continue
        if not pa.get("used") and time.time() < pa.get("expires", 0):
            return pa
    return None


def purchase_done(pa, **result):
    """Close the approval (one tap only) and leave the result for the runner."""
    pa["used"] = True
    (PURCHASES / f"{pa['id']}.json").write_text(json.dumps(pa, ensure_ascii=False))
    (PURCHASES / f"{pa['id']}.result.json").write_text(json.dumps({"id": pa["id"], "at": now(), **result}, ensure_ascii=False))


def spends_money(label):
    return bool(label and MONEY.search(label))


def element_at(els, x, y):
    """The smallest element whose box contains (x, y)."""
    hits = [e for e in els if e.get("box") and e["box"][0] <= x <= e["box"][2] and e["box"][1] <= y <= e["box"][3]]
    return min(hits, key=lambda e: (e["box"][2] - e["box"][0]) * (e["box"][3] - e["box"][1]), default=None)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def save_state():
    S["stopped"], S["updated"] = stopped(), now()
    tmp = D / "state.tmp"
    tmp.write_text(json.dumps(S))
    tmp.replace(D / "state.json")


def log(**e):
    with open(D / "log.jsonl", "a") as f:
        f.write(json.dumps({"ts": now(), **e}, ensure_ascii=False) + "\n")
    rt_emit(e)


# ---------- the agent runtime record (images/mission-control/runrecord.py): this service's actions, live ----------
# Spooled as JSONL into /phone/runtime; the runner forwards it (this container can't reach Mission Control). A pause
# of more than 15 minutes closes a session; the next action opens a new one. The runtime closes an idle session as done.
_rt = {"run": None, "last": 0.0}


def rt_emit(log_entry):
    try:
        t = time.time()
        d = D / "runtime"
        d.mkdir(exist_ok=True)
        d.chmod(0o777)                                   # the runner (another user) claims and deletes the files
        out = []
        if not _rt["run"] or t - _rt["last"] > 900:
            _rt["run"] = f"phone:{time.strftime('%Y%m%d-%H%M%S')}"
            out.append({"run": _rt["run"], "kind": "run", "agent": "ai-phone", "source": "ai-phone", "ts": t, "title": "started",
                        "run_title": "AI phone", "data": {"manifest": {"agent": "ai-phone", "idle_end": True}}})
        _rt["last"] = t
        e = {k: v for k, v in log_entry.items() if k not in ("ts", "at")}
        kind = "result" if e.get("result") is not None else "stage" if e.get("decision") else "call"
        out.append({"run": _rt["run"], "kind": kind, "agent": "ai-phone", "source": "ai-phone", "ts": t,
                    "title": str(e.get("tool") or e.get("action") or e.get("op") or "action")[:120],  # cap: id
                    "detail": TC.cut(json.dumps(e, ensure_ascii=False, default=str), 20000),  # cap: store
                    "status": "failure" if str(e.get("result", "")).startswith(("refused", "error", "Refused")) else None})
        with open(d / f"phone-{time.strftime('%Y%m%d')}.jsonl", "a") as f:
            for x in out:
                f.write(json.dumps({k: v for k, v in x.items() if v is not None}, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def stopped():
    return (D / "STOP").exists()


def adb(*args, timeout=30, binary=False):
    cmd = ["adb", *(["-s", S["serial"]] if S["serial"] and args[0] not in ("connect", "pair", "disconnect", "devices") else []), *args]
    p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return p.stdout if binary else (p.stdout.decode(errors="replace") + p.stderr.decode(errors="replace")).strip()


def blocklist():
    return [ln.strip().lower() for ln in (D / "blocklist.txt").read_text().splitlines() if ln.strip() and not ln.startswith("#")]


def blocked(pkg, hard=False):
    """The block-list word in pkg, or None. A word written "task:homeassistant" blocks that app except inside a task the
    owner approved that names it (VOI-07); hard=True asks only about the words no task can open."""
    pkg = (pkg or "").lower()
    if not pkg:
        return None
    t = active_task()
    for b in blocklist():
        word, task_only = (b[5:], True) if b.startswith("task:") else (b, False)
        if word in pkg and not (task_only and (hard or (t and pkg in t["apps"]))):
            return word
    return None


def foreground():
    out = adb("shell", "dumpsys", "activity", "activities", timeout=15)
    m = re.search(r"(?:topResumedActivity|mResumedActivity|ResumedActivity)[^\n]*?\s([\w.]+)/", out)
    S["foreground"] = m.group(1) if m else ""
    return S["foreground"]


def wake():
    """A sleeping phone shows a black screen and a lock screen: wake it, dismiss a swipe-only lock. A PIN, pattern or
    password lock stays: the AI phone never enters one. None if ready, else why not."""
    if "mWakefulness=Awake" not in adb("shell", "dumpsys power | grep mWakefulness=", timeout=15):
        adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
        time.sleep(0.8)
    if "isKeyguardShowing=true" in adb("shell", "dumpsys window | grep isKeyguardShowing", timeout=15):
        adb("shell", "wm", "dismiss-keyguard")
        time.sleep(0.8)
        if "isKeyguardShowing=true" in adb("shell", "dumpsys window | grep isKeyguardShowing", timeout=15):
            return ("The AI phone is locked with a PIN, pattern or password, and it never enters one. Ask the owner to "
                    "unlock it, or to set its screen lock to Swipe or None (it is a test phone).")
    hold_screen(SCREEN_HOLD, "the agents are working")
    return None


# PHN-17: the owner watches the agents work; idle, the screen is off (it drained the battery when kept on, 2026-10-29)
SCREEN_HOLD = 120                    # s the screen stays on after the agents' last action
SCREEN_WAIT_MAX = 15 * 60            # s it stays on while an action waits for the owner's OK (= the approval's own wait)
SCREEN_OWNER_MAX = 60                # minutes the owner can keep it on from the Phone page


def hold_screen(seconds, why, now=None):
    """Keep the screen on for the next `seconds`; screen_tick lets it sleep afterwards. Android's own 30 s timeout is
    moved out of the way while held (one setting, not on every action)."""
    now = now or time.time()
    if now + seconds > S.get("screen_until", 0):
        S["screen_until"], S["screen_why"] = now + seconds, why
    if not S.get("screen_held"):
        adb("shell", "settings", "put", "system", "screen_off_timeout", str(SCREEN_WAIT_MAX * 1000 + 60000))
        S["screen_held"] = True


def screen_tick(now=None):
    """Every pass of the control loop: an action waiting for the owner's OK keeps the screen on (up to SCREEN_WAIT_MAX);
    once nothing holds it, the 30 s timeout is back and the screen goes off at once."""
    now = now or time.time()
    if S.get("screen_held") and any(now - p.stat().st_mtime < SCREEN_WAIT_MAX for p in PENDING.glob("*.json")):
        hold_screen(10, "an action waits for your OK", now)
    if S.get("screen_held") and now > S.get("screen_until", 0):
        let_screen_sleep()
        if "mWakefulness=Awake" in adb("shell", "dumpsys power | grep mWakefulness=", timeout=15):
            adb("shell", "input", "keyevent", "KEYCODE_SLEEP")
        S.update(screen_held=False, screen_until=0, screen_why="")


def owner_screen(minutes):
    """The Phone page: keep the screen on for `minutes` (up to SCREEN_OWNER_MAX) to watch, or 0 = off now."""
    minutes = max(0, min(SCREEN_OWNER_MAX, int(minutes)))
    if minutes:
        err = wake()
        if err:
            return err
        S["screen_until"], S["screen_why"] = time.time() + minutes * 60, "you are watching"
        hold_screen(0, "you are watching")
    else:
        S["screen_until"], S["screen_held"] = 0, True         # the next screen_tick turns it off
    return None


def allowance(minutes):
    """The owner's time window: minutes (0 ends it), or -1 = until he stops it. Spending money is never covered."""
    return time.time() + (10 * 365 * 86400 if minutes < 0 else 60 * max(0, min(7 * 24 * 60, minutes))) if minutes else 0


KEEPADB, TAILSCALE = "de.hohnepeople.keepadb", "com.tailscale.ipn"
BOOT_SETUP = [   # (what the owner approves, adb commands): the AI phone comes back by itself after every restart
    ("Let KeepADB switch Wireless debugging on after every restart (it gets the WRITE_SECURE_SETTINGS permission) and start it",
     [["shell", "pm", "grant", KEEPADB, "android.permission.WRITE_SECURE_SETTINGS"],
      ["shell", "pm", "grant", KEEPADB, "android.permission.POST_NOTIFICATIONS"],
      ["shell", "monkey", "-p", KEEPADB, "-c", "android.intent.category.LAUNCHER", "1"]]),
    ("Make Tailscale an always-on VPN, so it connects by itself after every restart (the internet keeps working when it is off)",
     [["shell", "settings", "put", "secure", "always_on_vpn_app", TAILSCALE],
      ["shell", "settings", "put", "secure", "always_on_vpn_lockdown", "0"]]),
    ("Exempt Tailscale and KeepADB from battery saving, so Android never stops them",
     [["shell", "dumpsys", "deviceidle", "whitelist", f"+{TAILSCALE}"],
      ["shell", "dumpsys", "deviceidle", "whitelist", f"+{KEEPADB}"]]),
]


# PHN-22: the AI phone as Hermes' speaker (docs/HOME-VOICE.md): Home Assistant becomes Android's assistant and may use the
# microphone. Both are Android settings, so the stack applies them only after the owner's one Allow on its own card.
HA_APP = "io.homeassistant.companion.android"
VOICE_SETUP = ("Make Home Assistant this phone's voice assistant: the default digital assistant instead of Google's, "
               "allowed to use the microphone, and never put to sleep by battery saving, so its wake word reaches Hermes "
               "also with the screen locked or off",
               [["shell", "cmd", "role", "add-role-holder", "--user", "0", "android.app.role.ASSISTANT", HA_APP],
                ["shell", "pm", "grant", HA_APP, "android.permission.RECORD_AUDIO"],
                ["shell", "dumpsys", "deviceidle", "whitelist", f"+{HA_APP}"],          # Samsung put it to sleep when locked
                ["shell", "cmd", "appops", "set", HA_APP, "RUN_ANY_IN_BACKGROUND", "allow"]])


def voice_status():
    """Is Home Assistant the phone's assistant, and may it hear? (the House page ticks its step from this)"""
    S["voice"] = {"assistant": HA_APP in adb("shell", "cmd", "role", "get-role-holders", "android.app.role.ASSISTANT"),
                  "mic": "RECORD_AUDIO: granted=true" in adb("shell", "dumpsys", "package", HA_APP),
                  "awake": f",{HA_APP}," in adb("shell", "dumpsys", "deviceidle", "whitelist")}
    return S["voice"]


async def voice_setup():
    if not await connect():
        log(tool="phone_setting", result=f"not changed: {S['error'] or 'the phone is not connected'}")
        return
    st = await asyncio.to_thread(voice_status)
    if all(st.values()):
        return
    what, cmds = VOICE_SETUP
    if (err := await guard("phone_setting", {"what": what}, "The owner asked to talk to Hermes on the AI phone", always="⚙ Phone setting: ")):
        log(tool="phone_setting", args={"what": what}, result=f"not changed: {err}")
        return
    out = [await asyncio.to_thread(adb, *c) for c in cmds]
    st = await asyncio.to_thread(voice_status)
    log(tool="phone_setting", args={"what": what}, result=("done" if all(st.values()) else f"not complete: {st}")
        + "".join(f"; {o.strip()}" for o in out if o.strip()))


def boot_status():
    """What makes the AI phone come back by itself after a restart (shown on the Phone page)."""
    pkg = adb("shell", "dumpsys", "package", KEEPADB)
    idle = adb("shell", "dumpsys", "deviceidle", "whitelist")
    S["boot"] = {"keepadb": "versionName" in pkg, "keepadb_allowed": "WRITE_SECURE_SETTINGS: granted=true" in pkg,
                 "tailscale_always_on": adb("shell", "settings", "get", "secure", "always_on_vpn_app").strip() == TAILSCALE,
                 "no_battery_limit": f",{TAILSCALE}," in idle and f",{KEEPADB}," in idle}
    return S["boot"]


_booting = set()


async def boot_setup():
    """The owner's "Start in AI mode": each setting change waits for his Allow (always its own approval). One run at a
    time: a second "Set it up" tap while a card is open would only ask the same thing twice."""
    if _booting:
        return
    _booting.add(1)
    try:
        await _boot_setup()
    finally:
        _booting.clear()


async def _boot_setup():
    if not await connect():                               # right after a restart it is not connected yet
        log(tool="phone_setting", result=f"not changed: {S['error'] or 'the phone is not connected'}")
        return
    st = await asyncio.to_thread(boot_status)
    done = [st["keepadb_allowed"], st["tailscale_always_on"], st["no_battery_limit"]]
    if not st["keepadb"]:
        log(tool="phone_setting", result="KeepADB is not installed on the phone")
        return
    for (what, cmds), ok in zip(BOOT_SETUP, done):
        if ok:
            continue
        if (err := await guard("phone_setting", {"what": what}, "so the AI phone always starts in AI mode", always="⚙ Phone setting: ")):
            log(tool="phone_setting", args={"what": what}, result=f"not changed: {err}")
            return
        out = [await asyncio.to_thread(adb, *c) for c in cmds]
        log(tool="phone_setting", args={"what": what}, result="done" + "".join(f"; {o}" for o in out if o.strip() and "Events injected" not in o))
        await asyncio.to_thread(boot_status)              # its ✓ shows on the Phone page at once, before the next card


def let_screen_sleep():
    """The screen sleeps like any phone's (it drained the battery faster than the charger filled it when it was kept on,
    2026-10-29): 30 s timeout, no stay-awake on the charger. Every action wakes it first (wake()), and a swipe-only lock
    is dismissed then, so nothing needs it on in between."""
    adb("shell", "svc", "power", "stayon", "false")
    adb("shell", "settings", "put", "system", "screen_off_timeout", "30000")


# ---------- connecting ----------
async def phone_online():
    """Is the phone there at all? An online phone refuses closed ports at once; an offline one (battery dead, off the
    tailnet) lets every connection attempt hang. Scanning an offline phone left ~11,000 hanging connections in rootless
    Docker's slirp4netns (2026-10-29), which then had no capacity left: every container lost the internet."""
    for port in (5555, 30000, 40000):
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection(HOST, port), 3)
            w.close()
            return True
        except ConnectionRefusedError:
            return True
        except Exception:
            pass
    return False


async def scan_ports():
    found = []

    async def probe(port, sem):
        async with sem:
            try:
                _, w = await asyncio.wait_for(asyncio.open_connection(HOST, port), 1.5)
                found.append(port)
                w.close()
            except Exception:
                pass
    sem = asyncio.Semaphore(100)                  # closed ports answer at once; this caps what can hang
    await asyncio.gather(*(probe(p, sem) for p in [5555, *range(30000, 50000)]))
    return sorted(found)


async def connect():
    """Wireless debugging picks a new port each time it is switched on: find it, then connect (keys from pairing)."""
    if stopped() or not HOST:
        return False
    devs = adb("devices")
    if S["serial"] and f"{S['serial']}\tdevice" in devs:
        return True
    if not await phone_online():
        S.update(connected=False, serial="", error="The phone does not answer (switched off, battery empty, or off Wi-Fi/Tailscale).")
        return False
    for port in await scan_ports():               # other ports answer too (the pairing dialog, phone services)
        try:
            out = await asyncio.to_thread(adb, "connect", f"{HOST}:{port}", timeout=10)
        except subprocess.TimeoutExpired:
            out = "timed out"
        if "connected to" in out and "failed" not in out and "unable" not in out:
            await asyncio.sleep(1)
            if f"{HOST}:{port}\tdevice" in adb("devices"):
                S.update(serial=f"{HOST}:{port}", connected=True, paired=True, error="")
                S["model"] = adb("shell", "getprop", "ro.product.model")
                S["android"] = adb("shell", "getprop", "ro.build.version.release")
                log(tool="connect", result=f"connected to {S['model']} (Android {S['android']}) on port {port}")
                let_screen_sleep()
                boot_status()
                voice_status()
                return True
        await asyncio.to_thread(adb, "disconnect", f"{HOST}:{port}")
    S.update(connected=False, serial="", error="No wireless debugging port answered. Is Wireless debugging on, and the phone paired?")
    return False


def pair(port, code):
    out = adb("pair", f"{HOST}:{int(port)}", re.sub(r"\D", "", str(code))[:6], timeout=30)
    ok = "Successfully paired" in out
    S.update(paired=ok or S["paired"], error="" if ok else f"Pairing failed: {out.strip()}")
    log(tool="pair", result="paired" if ok else out.strip())
    return ok


_skip = set()                                             # control files read once that this service may not read or delete


def take(f):
    """A request from the control folder, or None. One it cannot read is reported once and left, and one it may not delete
    (another user's, in the sticky folder) is taken once (FND-116: one unreadable request stopped every pass for a day)."""
    if f.name in _skip:
        return None
    try:
        req = json.loads(f.read_text())
    except (OSError, ValueError) as e:
        _skip.add(f.name)
        log(tool="phone_control", result=f"skipped {f.name}: {type(e).__name__}: {e}")
        return None
    try:
        f.unlink()
    except OSError:
        _skip.add(f.name)
    return req


async def control_loop():
    """Requests from the Phone page and the Stop switch; keeps state.json fresh and the screen on."""
    while True:
        try:
            if any(i.get("tool") == "phone_setting" for i in sweep_orphans()) and not stopped():
                asyncio.create_task(boot_setup())          # "Start in AI mode" was mid-way: ask that card again
            for f in sorted(CONTROL.glob("*.json")):
                req = take(f)
                if req is None:
                    continue
                if req.get("do") == "pair":
                    await asyncio.to_thread(pair, req.get("port", 0), req.get("code", ""))
                    await connect()
                elif req.get("do") == "connect":
                    await connect()
                elif req.get("do") == "boot_setup":
                    asyncio.create_task(boot_setup())          # waits for the owner's OKs: not in this loop
                elif req.get("do") == "voice_setup":
                    asyncio.create_task(voice_setup())         # waits for the owner's one Allow: not in this loop
                elif req.get("do") == "trust":
                    S["trust_until"] = allowance(int(req.get("minutes", 0)))
                elif req.get("do") == "end_task":
                    if S.get("task"):
                        log(tool="phone_task", result=f"ended by the owner after {S['task'].get('actions', 0)} actions")
                    S["task"] = None
                elif req.get("do") == "screen" and S["connected"]:
                    err = await asyncio.to_thread(owner_screen, req.get("minutes", 0))
                    log(tool="phone_screen", result=err or (f"on for {req.get('minutes')} min (the owner watches)" if req.get("minutes") else "off (the owner)"))
                elif req.get("do") == "shop_look":
                    asyncio.create_task(shop_look(req))       # it may wait for the owner's OK: not in this loop
                elif req.get("do") == "shop_open":
                    pa = active_purchase()
                    if pa and pa["id"] == req.get("purchase") and (await guard("phone_shop_open", {}, "", acting=False)) is None:
                        adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", pa["url"], pa["pkg"])
                        log(tool="phone_shop_open", args={"url": TC.cut(pa["url"], 300), "app": pa["pkg"]}, result=f"opened for purchase {pa['id']} (approved by the owner)")  # cap: untrusted
            for f in sorted(CLEANUP.glob("c-*.json")) if CLEANUP.exists() and not _cleaning else []:
                cid = f.stem                               # one step at a time: Approve all hands over many at once
                if CLEANUP_ID.match(cid) and not (CLEANUP / f"{cid}.result.json").exists():
                    _cleaning.add(cid)
                    asyncio.create_task(cleanup_do(cid))   # minutes of find/delete: not in this loop
                    break
            if stopped() and S["serial"]:
                adb("disconnect", S["serial"])
                S.update(connected=False, serial="", trust_until=0)
                log(tool="stop", result="stopped by the owner: disconnected")
            if S["serial"]:
                S["connected"] = f"{S['serial']}\tdevice" in await asyncio.to_thread(adb, "devices")
                if S["connected"]:
                    await asyncio.to_thread(foreground)
                    await asyncio.to_thread(screen_tick)
            if S["paired"] and not S["connected"] and not stopped() and time.time() - S.get("tried", 0) > S.get("retry_s", 60):
                S["tried"] = time.time()                     # Wi-Fi changed: wireless debugging has a new port
                ok = await connect()                         # failing again and again: try less often (up to 10 min)
                S["retry_s"] = 60 if ok else min(600, S.get("retry_s", 60) * 2)
        except Exception as e:
            S["error"] = str(e)
        save_state()
        await asyncio.sleep(3)


# ---------- approved cleanup steps (ops/phone_agents.py) ----------
_cleaning = set()


def delete_files(target, older_than_days=0):
    """Delete the files (older than N days) at a path deletable() allowed -> (found, deleted, bytes freed)."""
    q = target.replace("'", "'\\''")
    age = f" -mtime +{int(older_than_days)}" if older_than_days > 0 else ""
    found = _stat_lines(f"find '{q}' -type f{age}")
    if not found:
        return 0, 0, 0
    _sh(f"find '{q}' -type f{age} -delete" + ("" if age else f"; rm -rf -- '{q}'"), 1800)
    left = _stat_lines(f"find '{q}' -type f{age}")
    return len(found), len(found) - len(left), sum(n for n, _, _ in found) - sum(n for n, _, _ in left)


async def cleanup_do(cid):
    """One step the owner approved in Mission Control: exactly that, once, within its 30 minutes; refused like the tools
    (Stop, locked phone, block list, Android's own folders, system apps)."""
    res = CLEANUP / f"{cid}.result.json"
    try:
        a = json.loads((CLEANUP / f"{cid}.json").read_text())
    except (OSError, ValueError):
        return
    kind, args = a.get("kind"), a.get("args") or {}

    def done(ok, text, freed=0):
        res.write_text(json.dumps({"id": cid, "at": now(), "ok": ok, "text": text, "freed": max(0, int(freed))}, ensure_ascii=False))
        log(tool="phone_cleanup", args={"kind": kind, **args}, why=a.get("title", ""),
            decision=f"approved by the owner in Mission Control (step {cid})", result=text)
    try:
        if time.time() > a.get("expires", 0):
            return done(False, "The approval expired before the AI phone could start. Approve again.")
        if (err := await guard("phone_cleanup", {"kind": kind, **args}, a.get("title", ""), acting=False, target_pkg=args.get("package"))):
            return done(False, err)
        before = (await asyncio.to_thread(storage_report))["free"]
        deleted = 0
        if kind == "delete":
            target, err = deletable(args.get("path", ""))
            if not target:
                return done(False, err)
            n, k, size = await asyncio.to_thread(delete_files, target, int(args.get("older_than_days") or 0))
            deleted = size
            text = f"Deleted {k} of {n} files ({gb(size)}) at {target}" if n else f"Nothing left to delete at {target}"
        elif kind == "uninstall":
            pkg = str(args.get("package", ""))
            third = [x.split(":", 1)[1].strip() for x in (await asyncio.to_thread(adb, "shell", "pm list packages -3")).splitlines() if x.startswith("package:")]
            if pkg not in third:
                return done(False, f"{pkg} is not an app the owner installed (or is gone already)")
            if blocked(pkg):
                return done(False, f"Refused: {pkg} is a blocked app")
            text = f"Uninstall {pkg}: " + (await asyncio.to_thread(adb, "shell", "pm", "uninstall", pkg)).strip()
        elif kind == "trim_caches":
            await asyncio.to_thread(adb, "shell", "pm", "trim-caches", "4096G", timeout=300)
            text = "App caches emptied"
        else:
            return done(False, f"unknown step {kind}")
        try:
            after = (await asyncio.to_thread(storage_report))["free"]
        except Exception:
            after = 0
        if not after:                                   # the phone went away after the step (battery): count what was deleted
            return done(True, f"{text}; free space afterwards not readable", deleted)
        done(True, f"{text}; free space {gb(before)} → {gb(after)}", max(after - before, deleted))
    except Exception as e:
        done(False, f"{type(e).__name__}: {str(e)}")
    finally:
        _cleaning.discard(cid)


# ---------- the screen ----------
def screenshot(mark=None):
    """A small JPEG of the screen for the owner (approval card, log); mark = (x, y) of a planned tap."""
    from PIL import Image, ImageDraw
    png = adb("exec-out", "screencap", "-p", binary=True, timeout=20)
    if not png.startswith(b"\x89PNG"):
        return None
    im = Image.open(io.BytesIO(png)).convert("RGB")
    if mark:
        dr, r = ImageDraw.Draw(im), max(24, im.width // 25)
        dr.ellipse([mark[0] - r, mark[1] - r, mark[0] + r, mark[1] + r], outline=(255, 64, 64), width=max(6, r // 4))
    im.thumbnail((540, 1200))
    sid = uuid.uuid4().hex[:16]
    im.save(SHOTS / f"{sid}.jpg", quality=70)
    for old in sorted(SHOTS.glob("*.jpg"), key=lambda p: p.stat().st_mtime)[:-300]:   # keep the last 300  # cap: rotate (the newest 300 screenshots)
        old.unlink(missing_ok=True)
    return sid


def read_screen(limit=80):
    xml = adb("exec-out", "uiautomator", "dump", "/dev/tty", timeout=30)
    xml = xml[xml.find("<?xml"):xml.rfind(">") + 1] if "<?xml" in xml else ""
    out = []
    if not xml:
        return out
    for n in ET.fromstring(xml.split("UI hierchary dumped")[0].strip()).iter("node"):
        text, desc = (n.get("text") or "").strip(), (n.get("content-desc") or "").strip()
        click = n.get("clickable") == "true" or n.get("long-clickable") == "true"
        edit = "EditText" in (n.get("class") or "")
        secret = n.get("password") == "true" or (edit and SECRET_FIELD.search(f"{text} {desc} {n.get('resource-id', '')} {n.get('hint', '')}"))
        if not (text or desc or click or edit):
            continue
        b = re.findall(r"\d+", n.get("bounds") or "")
        if len(b) != 4:
            continue
        x1, y1, x2, y2 = map(int, b)
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        label = TC.cut(text or desc or n.get("hint") or n.get("resource-id", "").split("/")[-1] or n.get("class", "").split(".")[-1], 80)  # cap: prompt
        if secret:
            label = "(secret field: the owner types this himself)"   # never shown or typed by the model
        out.append({"label": label, "kind": "secret" if secret else "field" if edit else "button" if click else "text",
                    "x": (x1 + x2) // 2, "y": (y1 + y2) // 2, "box": (x1, y1, x2, y2), "focused": n.get("focused") == "true",
                    "money": spends_money(label) and not edit})
    return out[:limit]


# ---------- the guard every tool goes through ----------
WAITING = set()                                          # ids of the approvals a guard() call is waiting on right now


def sweep_orphans():
    """Approval cards nobody waits for any more: this service restarted (every deploy does) while a card was open, so
    an Allow reached nothing and the card stayed up in Mission Control and "Needs you" (2026-10-29). Drop them and their
    late answers; returns the dropped requests (the caller asks again where that makes sense)."""
    dropped = []
    for f in PENDING.glob("*.json"):
        if f.stem in WAITING:
            continue
        try:
            item = json.loads(f.read_text())
        except Exception:
            item = {}
        f.unlink(missing_ok=True)
        log(tool=item.get("tool", "request"), args=item.get("args") or {}, why=item.get("why", ""),
            decision="dropped: the AI phone service restarted while this waited (it asks again if still needed)")
        dropped.append(item)
    for f in DECISIONS.glob("*.json"):
        if f.stem not in WAITING:
            f.unlink(missing_ok=True)
    return dropped


OUTWARD = "↗ This can send text or a web address off the phone, so it asks you: "   # FND-02, DEC-23
# What must never leave the phone on an agent's own say (= images/research/server.py _LEAK): e-mail, IBAN, phone number,
# API key, IP address. In the owner's free mode only typing or an address with one of these still asks (PHN-19).
PRIVATE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}\b|\+?\d[\d /-]{8,}\d"
                     r"|\b(?:sk|ghp|xox[bp]|AKIA)[-_A-Za-z0-9]{12,}|\b(?:\d{1,3}\.){3}\d{1,3}\b")
TASK_MAX = 60                         # minutes one task approval lasts at most
HOMES = ("com.sec.android.app.launcher", "com.google.android.apps.nexuslauncher", "com.android.launcher3")   # the home screen


def active_task():
    t = S.get("task")
    return t if t and t["until"] > time.time() else None


def outward(target_pkg=None, text=None):
    """Typing, opening a web address or an app ask (DEC-23), unless the owner's permission covers them: the steps of a
    purchase he approved, the apps and texts of a task he approved (PHN-18), or his free mode when the text holds
    nothing private (PHN-19)."""
    pa = active_purchase()
    if pa and target_pkg and target_pkg == pa["pkg"]:
        return ""
    t = active_task()
    if t and ((text is None and target_pkg in t["apps"]) or (text is not None and text in t["texts"])):
        return ""
    if time.time() < S["trust_until"] and not (text and PRIVATE.search(text)):
        return ""
    return OUTWARD


def covered(tool, fg):
    """Why the owner's standing permission covers a tap, swipe or key here, or "" (then it asks)."""
    if time.time() < S["trust_until"]:
        return "the owner's free mode"
    t = active_task()
    if t and tool in ("phone_tap", "phone_swipe", "phone_key", "phone_type", "phone_open", "phone_url") and (fg in t["apps"] or fg in HOMES):
        return f"task “{TC.cut(t['task'], 60)}”"  # cap: preview
    return ""


async def guard(tool, args, why, acting=True, mark=None, target_pkg=None, money=False, always=""):
    """None if the action may run, else the reason it may not. money=True or always="⚠ text": always its own approval
    (the owner's time window never covers it)."""
    if stopped():
        return "The owner switched the AI phone off (Stop on the Phone page). Do not retry."
    if not await connect():
        return S["error"] or "The phone is not connected."
    if (err := await asyncio.to_thread(wake)):
        log(tool=tool, args=args, why=why, result="refused: phone locked")
        return err
    fg = await asyncio.to_thread(foreground)
    for pkg in (fg, target_pkg):
        if (b := blocked(pkg, hard=tool == "phone_task" and pkg in args.get("apps", []))):   # a task may name a task: app
            if pkg == fg:
                adb("shell", "input", "keyevent", "KEYCODE_HOME")
            log(tool=tool, args=args, why=why, result=f"refused: {pkg} is on the block list ({b})")
            return f"Refused: {pkg} is a blocked app (banking, payments, passwords or settings). The AI phone never uses it."
    if not acting:
        return None
    if not money and not always and (c := covered(tool, fg)):
        log(tool=tool, args=args, why=why, decision=f"allowed ({c})")
        if (t := active_task()) and c.startswith("task"):
            t["actions"] = t.get("actions", 0) + 1
        return None
    pa = active_purchase()
    if pa and not money and not always and fg == pa["pkg"] and tool in ("phone_tap", "phone_swipe", "phone_key"):
        log(tool=tool, args=args, why=why, decision=f"allowed (step of purchase {pa['id']}, approved by the owner)")
        return None
    aid = uuid.uuid4().hex[:16]
    WAITING.add(aid)
    shot = await asyncio.to_thread(screenshot, mark)
    item = {"id": aid, "at": now(), "tool": tool, "args": args, "why": why, "app": fg, "shot": shot, "money": money,
            "text": ("💳 This would spend money: " if money else always) + describe(tool, args), "always": bool(always)}
    (PENDING / f"{aid}.json").write_text(json.dumps(item, ensure_ascii=False))
    t0 = time.time()
    try:
        while time.time() - t0 < WAIT:
            if stopped():
                return "The owner switched the AI phone off."
            if not money and not always and (c := covered(tool, fg)):      # PHN-20: his permission came while it waited
                log(tool=tool, args=args, why=why, shot=shot, decision=f"allowed ({c}, given while it waited)")
                return await asyncio.to_thread(wake)
            d = DECISIONS / f"{aid}.json"
            if d.exists():
                dec = json.loads(d.read_text())
                d.unlink(missing_ok=True)
                if dec.get("allow"):
                    if dec.get("minutes") and not money and not always:   # such an OK never opens a time window
                        S["trust_until"] = allowance(int(dec["minutes"]))
                    log(tool=tool, args=args, why=why, shot=shot, decision="allowed" + (f" + {dec['minutes']} min" if dec.get("minutes") and not money else ""))
                    return await asyncio.to_thread(wake)     # the screen may have gone to sleep while it waited
                log(tool=tool, args=args, why=why, shot=shot, decision="declined")
                return "The owner declined this action. Ask what to do instead; do not repeat it."
            await asyncio.sleep(1)
        log(tool=tool, args=args, why=why, shot=shot, decision="no answer")
        return "The owner did not approve within 15 minutes, so nothing was done. Tell the owner what you wanted to do."
    finally:
        (PENDING / f"{aid}.json").unlink(missing_ok=True)
        WAITING.discard(aid)


def describe(tool, a):
    return {"phone_tap": lambda: f"Tap “{a.get('label') or ''}”".replace("“”", f"at {a.get('x')},{a.get('y')}"),
            "phone_task": lambda: f"{a.get('task')} · apps: {', '.join(a.get('apps') or [])} · types: "
                                  f"{'; '.join(a.get('texts') or []) or 'nothing'} · for {a.get('minutes')} min",
            "phone_type": lambda: f"Type “{a.get('text', '')}”" + (" and press Enter" if a.get("enter") else ""),
            "phone_swipe": lambda: f"Swipe {a.get('direction')}",
            "phone_shop_look": lambda: f"Search “{a.get('query', '')}” in {a.get('app', 'the shop app')} and read the results (read-only: no taps)",
            "phone_key": lambda: f"Press {a.get('key')}",
            "phone_open": lambda: f"Open the app {a.get('app')}",
            "phone_url": lambda: f"Open {a.get('url', '')} in Chrome",
            "phone_uninstall": lambda: f"Uninstall {a.get('package')} ({a.get('size', '?')}) and delete its data",
            "phone_setting": lambda: a.get("what", "Change a phone setting"),
            "phone_trim_caches": lambda: "Empty the caches of all apps (the system decides; logins and data stay)",
            "phone_delete": lambda: (f"Delete {a.get('what')}: {a.get('files')} files, {a.get('size')}"
                                     + (f" ({a.get('detail')})" if a.get("detail") else ""))}.get(tool, lambda: tool)()


async def after(tool, args, why):
    """After an action: settle, refuse if a blocked app came up, report what is on screen now."""
    await asyncio.sleep(1.2)
    fg = await asyncio.to_thread(foreground)
    if (b := blocked(fg)):
        adb("shell", "input", "keyevent", "KEYCODE_HOME")
        log(tool=tool, args=args, why=why, result=f"{fg} came up (blocked: {b}); sent to home screen")
        return f"Done, but a blocked app ({fg}) came up, so the phone went back to the home screen."
    log(tool=tool, args=args, why=why, result=f"done; now in {fg}")
    return f"Done. The phone now shows {fg or 'the home screen'}. Call phone_look to see the screen."


# ---------- storage and apps (cleanup reports; read-only: sizes, counts and dates, never file contents) ----------
def _sh(cmd, timeout=120):
    return adb("shell", cmd, timeout=timeout)


def _kb(line):
    """'1234\t/sdcard/X' -> (path, bytes)"""
    size, _, path = line.partition("\t")
    return path.strip(), int(size) * 1024 if size.strip().isdigit() else 0


def storage_report():
    """Where the space goes: totals, Android's own categories, and the biggest folders on shared storage."""
    ds = _sh("dumpsys diskstats 2>/dev/null")
    cat = {k: int(v) for k, v in re.findall(r"^(App Size|App Data Size|App Cache Size|Photos Size|Videos Size|Audio Size|Downloads Size|System Size|Other Size): (\d+)", ds, re.M)}
    m = re.search(r"Data-Free: (\d+)K / (\d+)K total", ds)
    total, free = (int(m[2]) * 1024, int(m[1]) * 1024) if m else (0, 0)
    top = [_kb(x) for x in _sh("du -sk /sdcard/* 2>/dev/null | sort -rn | head -15").splitlines() if x.strip()]
    media = [_kb(x) for x in _sh("du -sk /sdcard/Android/media/* /sdcard/Android/data/* 2>/dev/null | sort -rn | head -12").splitlines() if x.strip()]
    wa = [_kb(x) for x in _sh("du -sk /sdcard/Android/media/com.whatsapp/WhatsApp/Media/* 2>/dev/null | sort -rn | head -12").splitlines() if x.strip()]
    counts = {}
    for folder in ("DCIM/Camera", "Pictures/Screenshots", "Download", "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Video",
                   "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images"):
        n = _sh(f"ls -1 '/sdcard/{folder}' 2>/dev/null | wc -l").strip()
        counts[folder] = int(n) if n.isdigit() else 0
    return {"total": total, "free": free, "categories": cat, "folders": [{"path": p, "size": b} for p, b in top],
            "app_media": [{"path": p, "size": b} for p, b in media], "whatsapp": [{"path": p, "size": b} for p, b in wa],
            "file_counts": counts}


def apps_report():
    """Every app the owner installed: size, data, cache, install date, last use. Blocked apps are listed (marked) only."""
    ds = _sh("dumpsys diskstats 2>/dev/null")
    arr = {k: json.loads(v) for k, v in re.findall(r"^(Package Names|App Sizes|App Data Sizes|Cache Sizes): (\[.*\])$", ds, re.M)}
    names = arr.get("Package Names", [])
    size = {n: (arr.get("App Sizes", [0] * len(names))[i], arr.get("App Data Sizes", [0] * len(names))[i], arr.get("Cache Sizes", [0] * len(names))[i])
            for i, n in enumerate(names) if i < len(arr.get("App Sizes", []))}
    third = [x.split(":", 1)[1].strip() for x in _sh("pm list packages -3").splitlines() if x.startswith("package:")]
    used = {}
    for pkg, t in re.findall(r'package=(\S+) .*?lastTimeUsed="([\d\- :]+)"', _sh("dumpsys usagestats 2>/dev/null", timeout=180)):
        if not t.startswith("1970"):
            used[pkg] = max(used.get(pkg, ""), t)
    inst = dict(re.findall(r"^(\S+) +firstInstallTime=([\d\- :]+)", _sh(
        "for p in $(pm list packages -3 | cut -d: -f2); do echo \"$p $(dumpsys package $p 2>/dev/null | grep -m1 firstInstallTime)\"; done", timeout=300), re.M))
    out = []
    for pkg in third:
        a, d, c = size.get(pkg, (0, 0, 0))
        out.append({"package": pkg, "app": a, "data": d, "cache": c, "total": a + d, "installed": inst.get(pkg, "")[:10],
                    "last_used": used.get(pkg, "")[:10], "blocked": bool(blocked(pkg))})
    return sorted(out, key=lambda x: -x["total"])


def gb(n):
    return f"{n / 1e9:.1f} GB" if n >= 1e8 else f"{n / 1e6:.0f} MB"


# The S22 is no longer the owner's private phone: its old personal data may go. Files are listed by name, size and date
# (never opened or read); deleting needs the owner's OK for each deletion, never inside his time window.
FILE_AREAS = ("DCIM", "Pictures", "Download", "Documents", "Movies", "Music", "Recordings", "SdCardBackUp",
              "Android/media/com.whatsapp/WhatsApp/Media")


def _stat_lines(cmd):
    out = []
    # find -exec … {} + returned only its first batch (5k of 26k files): xargs passes them all
    for ln in _sh(cmd + " -print0 2>/dev/null | xargs -0 stat -c '%s|%Y|%n' 2>/dev/null", timeout=300).splitlines():
        size, _, rest = ln.partition("|")
        ts, _, path = rest.partition("|")
        if size.isdigit() and ts.isdigit():
            out.append((int(size), int(ts), path))
    return out


def files_report():
    """Biggest files, and per area how much is how old (by year), so old personal data can be cleared by age."""
    files = _stat_lines("find /sdcard/ -type f -size +20000k")          # /sdcard is a link: the slash makes find enter it
    biggest = [{"path": p, "size": n, "date": time.strftime("%Y-%m-%d", time.localtime(t))} for n, t, p in sorted(files, reverse=True)[:40]]  # cap: list (the 40 biggest; files_total counts all)
    areas = []
    for a in FILE_AREAS:
        entries = _stat_lines(f"find '/sdcard/{a}' -type f")
        if not entries:
            continue
        years = {}
        for n, t, _ in entries:
            y = time.strftime("%Y", time.localtime(t))
            c = years.setdefault(y, [0, 0]); c[0] += 1; c[1] += n
        areas.append({"area": a, "files": len(entries), "size": sum(n for n, _, _ in entries),
                      "oldest": time.strftime("%Y-%m-%d", time.localtime(min(t for _, t, _ in entries))),
                      "newest": time.strftime("%Y-%m-%d", time.localtime(max(t for _, t, _ in entries))),
                      "by_year": {y: {"files": c[0], "size": c[1]} for y, c in sorted(years.items())}})
    top = {}
    for a in ("SdCardBackUp", "Download", "Documents"):
        top[a] = [ln.strip() for ln in _sh(f"ls -1 '/sdcard/{a}' 2>/dev/null | head -40").splitlines() if ln.strip()]
    return {"biggest": biggest, "areas": sorted(areas, key=lambda x: -x["size"]), "contents": top}


def deletable(path):
    """A path on shared storage that may be offered for deletion, or the reason it may not."""
    path = (path or "").strip().replace("/storage/emulated/0", "/sdcard").rstrip("/")
    if path and not path.startswith("/"):
        path = "/sdcard/" + path
    if ".." in path or not path.startswith("/sdcard/") or path.rstrip("/") in ("/sdcard", "/sdcard/Android", "/sdcard/Android/data",
                                                                               "/sdcard/Android/media", "/sdcard/Android/obb"):
        return None, "Only files and folders on the phone's shared storage (/sdcard/…), never the whole storage or Android's own folders."
    pkg = next((seg for seg in path.split("/") if "." in seg and seg.count(".") >= 1 and seg[0].isalpha() and blocked(seg)), "")
    if pkg:
        return None, f"Refused: {path} belongs to a blocked app ({pkg})."
    return path, ""


# ---------- MCP tools ----------


# ---------- MCP tools ----------
mcp = MCPServer("phone")
WHY = "why: one sentence for the owner, who approves each action on their phone."


def look_text(els):
    lines = [f"{i}. [{e['kind']}] {e['label']}{'  💳' if e.get('money') else ''}  ({e['x']},{e['y']})" for i, e in enumerate(els, 1)]
    return (f"App in front: {S['foreground'] or 'home screen'} on {S['model']} (Android {S['android']}).\n"
            + ("\n".join(lines) or "(nothing readable)") + "\n💳 = spends money: always needs the owner's own OK.")


@mcp.tool(description="See the AI phone's screen: the app in front and a numbered list of what is on it (buttons, fields, text) "
                      "with positions. Call this first and after every action. picture=true also returns a screenshot (for "
                      "images, maps, product photos). Read-only, needs no approval.")
async def phone_look(picture: bool = False):
    global elements
    if (err := await guard("phone_look", {}, "", acting=False)):
        return err
    elements = await asyncio.to_thread(read_screen)
    log(tool="phone_look", result=f"{S['foreground']}: {len(elements)} elements" + (" + picture" if picture else ""))
    if picture and (sid := await asyncio.to_thread(screenshot)):
        return [look_text(elements), Image(path=SHOTS / f"{sid}.jpg")]
    return look_text(elements)


def find_label(els, text):
    t = text.strip().lower()
    exact = [e for e in els if e["label"].lower() == t]
    part = [e for e in els if t in e["label"].lower()]
    pick = (exact or part)
    return min(pick, key=lambda e: (e["kind"] == "text", len(e["label"]))) if pick else None


@mcp.tool(description="Tap something on the screen: by its label text (text='Search'), by its number from the last phone_look "
                      "(element=3), or by position x,y. Buttons that buy, pay, order or subscribe always need the owner's own OK. " + WHY)
async def phone_tap(why: str, text: str = "", element: int = 0, x: int = -1, y: int = -1) -> str:
    global elements
    if (err := await guard("phone_tap", {}, why, acting=False)):     # stop, lock, block list before reading anything
        return err
    now_els = await asyncio.to_thread(read_screen)        # what is really under the finger now, not at the last look
    if text:
        e = find_label(now_els, text)
        if not e:
            return f"Nothing labelled '{text}' on the screen now. Call phone_look."
        x, y = e["x"], e["y"]
    elif element:
        if not 1 <= element <= len(elements):
            return "No such element: call phone_look first."
        x, y = elements[element - 1]["x"], elements[element - 1]["y"]
    if x < 0 or y < 0:
        return "Give text, element or x and y."
    hit = element_at(now_els, x, y) or {}
    label = hit.get("label", "")
    money = spends_money(label) or any(e.get("money") and abs(e["x"] - x) < 40 and abs(e["y"] - y) < 40 for e in now_els)
    args = {"x": x, "y": y, "label": label}
    pa = active_purchase()
    if pa and S.get("foreground") == pa["pkg"]:
        if CHANGE.search(label):
            log(tool="phone_tap", args=args, why=why, result=f"refused: would change the address or payment ({label}) during purchase {pa['id']}")
            return "Refused: during an approved purchase the address, payment method and vouchers are never changed. Stop and call phone_done."
        if money and STEP.search(label) and not FINAL.search(label):
            if (err := await guard("phone_tap", {}, why, acting=False)):
                return err
            log(tool="phone_tap", args=args, why=why, decision=f"allowed (step toward checkout of purchase {pa['id']}, approved by the owner)")
            adb("shell", "input", "tap", str(x), str(y))
            return await after("phone_tap", args, why)
        if money and FINAL.search(label):
            return await final_tap(pa, x, y, args, why)
    if (err := await guard("phone_tap", args, why, mark=(x, y), money=money)):
        return err
    adb("shell", "input", "tap", str(x), str(y))
    return await after("phone_tap", args, why)


async def final_tap(pa, x, y, args, why):
    """The final buy button of an approved purchase: the owner's approval of the proposal stands in for the money
    guard's per-action OK for exactly this one tap, and only if the screen passes final_check."""
    if (err := await guard("phone_tap", {}, why, acting=False)):          # Stop, lock, block list still apply
        return err
    els = await asyncio.to_thread(read_screen, 400)
    ok, reason = final_check(els, pa)
    if ok is None:
        log(tool="phone_tap", args=args, why=why, result=f"refused: {reason}")
        return f"Refused: {reason}."
    shot = await asyncio.to_thread(screenshot, (x, y))
    if not ok:
        log(tool="phone_tap", args=args, why=why, shot=shot, result=f"refused: final-screen check failed for purchase {pa['id']}: {reason}")
        purchase_done(pa, status="stopped", reason=reason, shot=shot)
        return f"Stopped, nothing bought: {reason}. Call phone_done and tell the owner; he decides."
    log(tool="phone_tap", args=args, why=why, shot=shot,
        decision=f"allowed: purchase {pa['id']} approved by {pa.get('approved_by', 'the owner')} stands in for this money tap (final-screen check: {reason})")
    total = order_total(els)
    purchase_done(pa, status="tapped", total_eur=total, shot=shot, check=reason)   # used before the tap: never twice
    adb("shell", "input", "tap", str(x), str(y))
    await asyncio.sleep(7)
    after_els = await asyncio.to_thread(read_screen, 400)
    text = "\n".join(e["label"] for e in after_els)
    m = ORDER_NO.search(text)
    order = (m.group(1) or m.group(2)) if m else None
    done = await asyncio.to_thread(screenshot)
    purchase_done(pa, status="placed", order=order, total_eur=total, shot=done, check=reason)
    log(tool="phone_tap", args=args, why=why, shot=done, result=f"purchase {pa['id']} placed" + (f": order {order}" if order else " (order number not read)"))
    return f"Done: the order is placed{f', order number {order}' if order else ''}. Call phone_look once, then phone_done with the order number."


async def shop_look(req):
    """A read-only search in a shop's app for the shopping agent: open the search URL in the app, read the screen
    twice (scrolling once). It goes through the guard like any action (the owner's OK or his time window)."""
    out = RESEARCH / f"{req.get('id', 'x')}.json"
    try:
        RESEARCH.mkdir(exist_ok=True)
        pkg, url, q = str(req.get("pkg", "")), str(req.get("url", "")), str(req.get("query", ""))[:80]  # cap: api (a search typed on the phone; a marker would be searched for)
        if not re.fullmatch(r"[a-zA-Z0-9_.]+", pkg) or not url.startswith("https://") or not re.fullmatch(r"[a-f0-9]{16}", str(req.get("id", ""))):
            return
        args = {"query": q, "app": pkg}
        if (err := await guard("phone_shop_look", args, f"The shopping agent checks “{q}” in the shop app (read-only)", target_pkg=pkg)):
            out.write_text(json.dumps({"error": err}))
            return
        if time.time() > float(req.get("expires", 0)):
            log(tool="phone_shop_look", args=args, result="skipped: the shopping agent stopped waiting")
            return
        adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url, pkg)
        await asyncio.sleep(5)
        lines = [e["label"] for e in await asyncio.to_thread(read_screen, 200) if e["kind"] in ("text", "button")]
        adb("shell", "input", "swipe", "540", "1700", "540", "700", "300")
        await asyncio.sleep(2)
        lines += [x for x in (e["label"] for e in await asyncio.to_thread(read_screen, 200) if e["kind"] in ("text", "button")) if x not in lines]
        shot = await asyncio.to_thread(screenshot)
        out.write_text(json.dumps({"lines": TC.more(lines, 150, "more lines on this screen"), "shot": shot, "app": pkg}, ensure_ascii=False))  # cap: prompt
        log(tool="phone_shop_look", args=args, shot=shot, result=f"read {len(lines)} lines in {pkg}")
    except Exception as e:
        out.write_text(json.dumps({"error": f"{type(e).__name__}: {e}"}))


@mcp.tool(description="Type text into the focused field (tap the field first). enter=true presses Enter afterwards. Never for "
                      "passwords, card, bank or security codes: those fields are refused, the owner types them himself. " + WHY)
async def phone_type(text: str, why: str, enter: bool = False) -> str:
    if len(text) > 500:
        return f"Refused: {len(text)} characters to type; at most 500 at a time (type it in parts)."
    args = {"text": text, "enter": enter}
    if (err := await guard("phone_type", {}, why, acting=False)):
        return err
    focused = next((e for e in await asyncio.to_thread(read_screen) if e.get("focused")), None)
    if (pa := active_purchase()) and S.get("foreground") == pa["pkg"]:
        log(tool="phone_type", why=why, result=f"refused: no typing during purchase {pa['id']}")
        return "Refused: nothing is typed while completing an approved purchase. Stop and call phone_done."
    if (focused and focused["kind"] == "secret") or CARDLIKE.search(text):
        log(tool="phone_type", why=why, result="refused: secret field or card/bank number")
        return ("Refused: that is a password, card, bank or security-code field (or the text looks like a card/IBAN "
                "number). The owner types those himself; stop here and tell him what is left to do.")
    if (err := await guard("phone_type", args, why, always=outward(text=text))):
        return err
    for chunk in re.findall(r".{1,60}", text, re.S):            # adb input text: spaces as %s, shell-escaped
        adb("shell", "input", "text", "'" + chunk.replace("'", "'\\''").replace(" ", "%s") + "'")
    if enter:
        adb("shell", "input", "keyevent", "KEYCODE_ENTER")
    return await after("phone_type", args, why)


@mcp.tool(description="Scroll the screen: direction up, down, left or right (up = see what is further down). " + WHY)
async def phone_swipe(direction: str, why: str) -> str:
    vec = {"up": (540, 1700, 540, 700), "down": (540, 700, 540, 1700), "left": (900, 1200, 180, 1200), "right": (180, 1200, 900, 1200)}
    if direction not in vec:
        return "direction: up, down, left or right"
    args = {"direction": direction}
    if (err := await guard("phone_swipe", args, why)):
        return err
    adb("shell", "input", "swipe", *map(str, vec[direction]), "300")
    return await after("phone_swipe", args, why)


@mcp.tool(description="Open a web address in Chrome on the AI phone (faster than tapping through the address bar). " + WHY)
async def phone_url(url: str, why: str) -> str:
    if not re.match(r"^https?://[^\s]+$", url):
        return "Give a full http(s) address."
    if (b := blocked(url)):
        log(tool="phone_url", args={"url": url}, why=why, result=f"refused: blocked word ({b})")
        return f"Refused: that address matches the block list ({b}): banking, payments or passwords."
    if len(url) > 2000:
        return f"Refused: the address is {len(url)} characters; at most 2,000."
    args = {"url": url}
    if (err := await guard("phone_url", args, why, target_pkg="com.android.chrome", always=outward("com.android.chrome", url))):
        return err
    adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url, "com.android.chrome")
    return await after("phone_url", args, why)


@mcp.tool(description="Finish a phone task: a short summary for the owner (what you did, what you found, what he still has to do, "
                      "e.g. pay at checkout). It goes to his Telegram. No approval needed.")
async def phone_done(summary: str) -> str:
    t, S["task"] = active_task(), None                   # the task's permission ends with it
    if t:
        summary = f"{summary}\n\n(Task “{TC.cut(t['task'], 80)}”: {t.get('actions', 0)} actions under your one OK.)"  # cap: preview
    (DONE / f"{uuid.uuid4().hex[:16]}.json").write_text(json.dumps({"at": now(), "summary": summary[:3000]}, ensure_ascii=False))  # cap: id
    log(tool="phone_done", result=summary)
    return "Sent to the owner."


@mcp.tool(description="Ask the owner ONCE for a whole phone task, before its first action: what the task is, the apps it needs (package "
                      "names or words from phone_apps), the exact texts you will type (empty if none) and how many minutes (5 to 60). "
                      "After his one Allow, taps, swipes and keys in those apps, opening them and typing those exact texts run without "
                      "asking; anything else still asks. Money, passwords and blocked apps are never covered. End it with phone_done. " + WHY)
async def phone_task(task: str, apps: list[str], why: str, texts: list[str] = [], minutes: int = 30) -> str:
    known = await asyncio.to_thread(launchable)
    pkgs, missing = [], []
    for a in apps[:8]:
        p = a if a in known else next((k for k in known if a.lower() in k.lower()), "")
        (pkgs.append(p) if p and not blocked(p, hard=True) else missing.append(a))
    if missing or not pkgs:
        return f"Not a task the phone can approve: {', '.join(missing) or 'no app'} is not an app it may open (call phone_apps)."
    if any(len(x) > 200 or CARDLIKE.search(x) for x in texts):
        return "Refused: a text to type is too long, or looks like a card or bank number."
    args = {"task": task[:300], "apps": pkgs, "texts": [x for x in texts[:20] if x], "minutes": max(5, min(TASK_MAX, int(minutes)))}  # cap: id
    if (err := await guard("phone_task", args, why, always="" if time.time() < S["trust_until"] else "📋 One OK for a whole task: ")):
        return err
    S["task"] = {**args, "until": time.time() + args["minutes"] * 60, "at": now(), "actions": 0}
    save_state()
    return (f"Allowed for {args['minutes']} minutes: in {', '.join(pkgs)} you may tap, swipe, press keys, open them and type "
            f"{'only: ' + '; '.join(args['texts']) if args['texts'] else 'nothing'} without asking. Anything else still asks. "
            "Call phone_done when finished.")


@mcp.tool(description="Press a key: back, home, recents or enter. " + WHY)
async def phone_key(key: str, why: str) -> str:
    code = {"back": "KEYCODE_BACK", "home": "KEYCODE_HOME", "recents": "KEYCODE_APP_SWITCH", "enter": "KEYCODE_ENTER"}.get(key)
    if not code:
        return "key: back, home, recents or enter"
    args = {"key": key}
    if (err := await guard("phone_key", args, why, acting=key not in ("back", "home"))):   # going back/home is always safe
        return err
    adb("shell", "input", "keyevent", code)
    return await after("phone_key", args, why)


def launchable():
    out = adb("shell", "cmd", "package", "query-activities", "--brief", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", timeout=30)
    return sorted({ln.strip().split("/")[0] for ln in out.splitlines() if "/" in ln})


@mcp.tool(description="List the apps on the AI phone that it may open (blocked apps are left out). Read-only.")
async def phone_apps() -> str:
    if (err := await guard("phone_apps", {}, "", acting=False)):
        return err
    return "\n".join(p for p in await asyncio.to_thread(launchable) if not blocked(p))


@mcp.tool(description="Open an app by its package name (from phone_apps) or a word in it, e.g. 'chrome', 'maps'. " + WHY)
async def phone_open(app: str, why: str) -> str:
    apps = await asyncio.to_thread(launchable)
    pkg = app if app in apps else next((p for p in apps if app.lower() in p.lower()), "")
    if not pkg:
        return f"No app matches '{app}'. Call phone_apps."
    args = {"app": pkg}
    if (err := await guard("phone_open", args, why, target_pkg=pkg, always=outward(pkg))):
        return err
    adb("shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1")
    await asyncio.sleep(1.2)
    if (fg := await asyncio.to_thread(foreground)) != pkg and blocked(fg):
        # PHN-23: the app had opened a blocked screen (Android's settings) that still sits on top of it: open it fresh at
        # its start screen instead of walking into that screen again
        act = (adb("shell", "cmd", "package", "resolve-activity", "--brief", "-c", "android.intent.category.LAUNCHER", pkg).strip().splitlines() or [""])[-1]
        if act.startswith(pkg + "/"):
            adb("shell", "am", "start", "--activity-clear-task", "-n", act)
            log(tool="phone_open", args=args, why=why, result=f"{fg} sat on top of it: opened {pkg} fresh")
    return await after("phone_open", args, why)


@mcp.tool(description="Where the AI phone's storage goes: total and free, Android's categories (apps, app data, photos, videos, "
                      "audio, cache), the biggest folders on shared storage and inside app media (e.g. WhatsApp). Read-only: sizes and "
                      "counts, never file contents.")
async def phone_storage() -> str:
    if (err := await guard("phone_storage", {}, "", acting=False)):
        return err
    r = await asyncio.to_thread(storage_report)
    log(tool="phone_storage", result=f"{gb(r['free'])} free of {gb(r['total'])}")
    lines = [f"Storage: {gb(r['total'] - r['free'])} used of {gb(r['total'])}, {gb(r['free'])} free."]
    lines += ["Categories: " + ", ".join(f"{k.replace(' Size', '')} {gb(v)}" for k, v in r["categories"].items() if v)]
    lines += ["Biggest folders: " + ", ".join(f"{f['path'].replace('/sdcard/', '')} {gb(f['size'])}" for f in r["folders"][:10])]
    lines += ["Inside app media/data: " + ", ".join(f"{f['path'].split('/')[-1]} {gb(f['size'])}" for f in r["app_media"][:8])]
    if r["whatsapp"]:
        lines += ["WhatsApp media: " + ", ".join(f"{f['path'].split('/')[-1]} {gb(f['size'])}" for f in r["whatsapp"][:8])]
    lines += ["File counts: " + ", ".join(f"{k} {v}" for k, v in r["file_counts"].items())]
    return "\n".join(lines)


@mcp.tool(description="Every app the owner installed on the AI phone: size, data, cache, install date and last use, biggest first. Blocked "
                      "apps (banking etc.) are only listed, never opened or changed. Read-only.")
async def phone_apps_report() -> str:
    if (err := await guard("phone_apps_report", {}, "", acting=False)):
        return err
    apps = await asyncio.to_thread(apps_report)
    log(tool="phone_apps_report", result=f"{len(apps)} apps")
    return "\n".join(f"{a['package']}: {gb(a['total'])} (data {gb(a['data'])}, cache {gb(a['cache'])}), installed {a['installed'] or '?'}, "
                     f"last used {a['last_used'] or 'not in the last year'}{' · BLOCKED: never touched' if a['blocked'] else ''}" for a in apps)


@mcp.tool(description="Uninstall an app the owner installed (and delete its data). Always asks the owner for this one action, even inside his "
                      "time window. Never for blocked apps or system apps. " + WHY)
async def phone_uninstall(package: str, why: str) -> str:
    third = [x.split(":", 1)[1].strip() for x in (await asyncio.to_thread(adb, "shell", "pm list packages -3")).splitlines() if x.startswith("package:")]
    if package not in third:
        return f"{package} is not an app the owner installed (system apps are never removed). Call phone_apps_report."
    if blocked(package):
        return f"Refused: {package} is a blocked app. The owner removes it himself if he wants."
    a = next((x for x in await asyncio.to_thread(apps_report) if x["package"] == package), {})
    args = {"package": package, "size": gb(a.get("total", 0))}
    if (err := await guard("phone_uninstall", args, why, target_pkg=package, always="🗑 This removes an app: ")):
        return err
    out = await asyncio.to_thread(adb, "shell", "pm", "uninstall", package)
    log(tool="phone_uninstall", args=args, why=why, result=out)
    return f"Uninstall {package}: {out.strip()}"


@mcp.tool(description="Ask Android to empty the caches of all apps (logins and data stay; apps rebuild their cache). Always asks "
                      "The owner, even inside his time window. Per-app cache clearing is not possible without root, and clearing an "
                      "app's data is never offered. " + WHY)
async def phone_trim_caches(why: str) -> str:
    before = (await asyncio.to_thread(storage_report))["free"]
    if (err := await guard("phone_trim_caches", {}, why, always="🧹 ")):
        return err
    await asyncio.to_thread(adb, "shell", "pm", "trim-caches", "4096G", timeout=300)
    after = (await asyncio.to_thread(storage_report))["free"]
    log(tool="phone_trim_caches", why=why, result=f"free {gb(before)} -> {gb(after)}")
    return f"Caches trimmed: free space {gb(before)} -> {gb(after)}."


@mcp.tool(description="The AI phone's files, for cleaning up its old personal data (it is no longer the owner's private phone): the "
                      "40 biggest files with name, size and date, and per area (camera, pictures, downloads, documents, "
                      "WhatsApp media, old backups) how many files and how much space per year. Read-only: names, sizes and "
                      "dates, never contents.")
async def phone_files() -> str:
    if (err := await guard("phone_files", {}, "", acting=False)):
        return err
    r = await asyncio.to_thread(files_report)
    log(tool="phone_files", result=f"{len(r['biggest'])} big files, {len(r['areas'])} areas")
    lines = ["Biggest files: " + "; ".join(TC.more([f"{f['path'].replace('/sdcard/', '')} {gb(f['size'])} {f['date']}" for f in r["biggest"]], 25, "more"))]  # cap: prompt
    for a in r["areas"]:
        lines.append(f"{a['area']}: {a['files']} files, {gb(a['size'])}, {a['oldest']} to {a['newest']}; by year: "
                     + ", ".join(f"{y} {v['files']} files {gb(v['size'])}" for y, v in a["by_year"].items()))
    for k, v in r["contents"].items():
        if v:
            lines.append(f"In {k}: " + ", ".join(TC.more(v, 25, "more")))  # cap: prompt
    return "\n".join(lines)


@mcp.tool(description="Delete a file or folder on the AI phone's shared storage (e.g. '/sdcard/SdCardBackUp' or "
                      "'/sdcard/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images'); older_than_days > 0 deletes only "
                      "the files older than that inside a folder. The owner sees what and how much (files, size) and approves each "
                      "deletion himself: never covered by his time window. Never in blocked apps' folders. " + WHY)
async def phone_delete(path: str, why: str, older_than_days: int = 0) -> str:
    target, err = deletable(path)
    if not target:
        return err
    if (err := await guard("phone_delete", {"path": target}, why, acting=False)):
        return err
    q = target.replace("'", "'\\''")
    age = f" -mtime +{int(older_than_days)}" if older_than_days > 0 else ""
    found = await asyncio.to_thread(_stat_lines, f"find '{q}' -type f{age}")
    if not found:
        return f"Nothing to delete at {target}" + (f" older than {older_than_days} days." if age else ".")
    size = sum(n for n, _, _ in found)
    oldest, newest = (time.strftime("%Y-%m-%d", time.localtime(t)) for t in (min(t for _, t, _ in found), max(t for _, t, _ in found)))
    args = {"path": target, "what": target.replace("/sdcard/", "") + (f" (files older than {older_than_days} days)" if age else ""),
            "files": len(found), "size": gb(size), "detail": f"from {oldest} to {newest}", "older_than_days": older_than_days}
    if (err := await guard("phone_delete", args, why, always="🗑 ")):
        return err
    cmd = f"find '{q}' -type f{age} -delete" + ("" if age else f"; rm -rf -- '{q}'")
    await asyncio.to_thread(_sh, cmd, 600)
    left = await asyncio.to_thread(_stat_lines, f"find '{q}' -type f{age}")
    log(tool="phone_delete", args=args, why=why, result=f"deleted {len(found) - len(left)} files, {gb(size - sum(n for n, _, _ in left))}")
    return f"Deleted {len(found) - len(left)} of {len(found)} files ({gb(size - sum(n for n, _, _ in left))}) at {target}."


async def main():
    subprocess.run(["adb", "start-server"], capture_output=True)
    save_state()
    await asyncio.gather(
        uvicorn.Server(uvicorn.Config(mcp.streamable_http_app(transport_security=TransportSecuritySettings(
            allowed_hosts=["phone:8000"], allowed_origins=[])), host="0.0.0.0", port=8000, log_level="warning")).serve(),
        control_loop())


if __name__ == "__main__":
    asyncio.run(main())

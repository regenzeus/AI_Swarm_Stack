"""images/phone/phone.py: the AI phone's guards (Stop, block list, the owner's approval), with a fake phone."""
import asyncio
import importlib
import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "images" / "phone"))


@pytest.fixture
def P(tmp_path, monkeypatch):
    monkeypatch.setenv("PHONE_DIR", str(tmp_path))
    monkeypatch.setenv("PHONE_HOST", "100.64.0.10")
    import phone
    phone = importlib.reload(phone)                       # paths are read at import
    phone.WAIT = 3
    calls = []

    async def connected():
        return True
    monkeypatch.setattr(phone, "connect", connected)
    monkeypatch.setattr(phone, "foreground", lambda: phone.S.__setitem__("foreground", fg[0]) or fg[0])
    monkeypatch.setattr(phone, "screenshot", lambda mark=None: None)
    monkeypatch.setattr(phone, "wake", lambda: None)
    monkeypatch.setattr(phone, "adb", lambda *a, **k: calls.append(a) or "")
    fg = ["com.android.chrome"]
    phone.fg, phone.calls = fg, calls
    return phone


def answer(P, allow, minutes=0):
    """The owner taps in Mission Control: wait for the request, then write the decision."""
    def go():
        for _ in range(50):
            pend = list(P.PENDING.glob("*.json"))
            if pend:
                tmp = P.DECISIONS / f"{pend[0].stem}.tmp"              # atomic, as Mission Control writes it
                tmp.write_text(json.dumps({"allow": allow, "minutes": minutes}))
                tmp.rename(P.DECISIONS / pend[0].name)
                return
            time.sleep(0.05)
    threading.Thread(target=go, daemon=True).start()


def test_block_list_covers_money_passwords_and_settings(P):
    for pkg in ("de.comdirect.app", "com.paypal.android.p2pmobile", "de.traderepublic.app", "com.x8bit.bitwarden",
                "com.android.settings", "com.android.vending", "com.google.android.apps.authenticator2"):
        assert P.blocked(pkg), pkg
    for pkg in ("com.android.chrome", "com.google.android.apps.maps", "com.whatsapp", "com.something.app"):
        assert not P.blocked(pkg), pkg


def test_an_action_waits_for_the_owner(P):
    answer(P, True)
    out = asyncio.run(P.phone_tap(why="open the menu", x=10, y=20))
    assert out.startswith("Done") and ("shell", "input", "tap", "10", "20") in P.calls
    answer(P, False)
    assert "declined" in asyncio.run(P.phone_tap(why="again", x=10, y=20))
    assert "did not approve" in asyncio.run(P.phone_type(text="hello", why="no answer"))
    assert not list(P.PENDING.glob("*.json"))             # requests disappear once answered or timed out
    log = [json.loads(x) for x in (P.D / "log.jsonl").read_text().splitlines()]
    assert [e.get("decision") for e in log if e.get("decision")] == ["allowed", "declined", "no answer"]


def test_allow_for_a_few_minutes(P):
    answer(P, True, minutes=5)
    asyncio.run(P.phone_swipe(direction="up", why="scroll"))
    assert P.S["trust_until"] > time.time() + 200
    assert asyncio.run(P.phone_swipe(direction="up", why="scroll again")).startswith("Done")   # no second request


def test_blocked_app_and_stop_refuse_everything(P):
    P.fg[0] = "de.comdirect.app"
    assert "blocked app" in asyncio.run(P.phone_look())
    assert ("shell", "input", "keyevent", "KEYCODE_HOME") in P.calls        # sent away from the banking app
    P.fg[0] = "com.android.chrome"
    (P.D / "STOP").write_text("now")
    assert "switched the AI phone off" in asyncio.run(P.phone_key(key="back", why="x"))


def test_a_pin_locked_phone_is_never_unlocked(P, monkeypatch):
    monkeypatch.setattr(P, "wake", lambda: "The AI phone is locked with a PIN")
    assert "locked" in asyncio.run(P.phone_look())
    assert not any("input" in a and "text" in a for a in P.calls)


def screen(P, monkeypatch, *els):
    monkeypatch.setattr(P, "read_screen", lambda: [dict(e, box=(e["x"] - 50, e["y"] - 30, e["x"] + 50, e["y"] + 30),
                                                        money=P.spends_money(e["label"]) and e["kind"] != "field") for e in els])


def test_money_buttons_always_ask_even_in_a_time_window(P, monkeypatch):
    screen(P, monkeypatch, {"label": "Jetzt kaufen", "kind": "button", "x": 500, "y": 1800},
           {"label": "Add to basket", "kind": "button", "x": 500, "y": 1600})
    P.S["trust_until"] = time.time() + 600
    assert asyncio.run(P.phone_tap(why="add it", text="Add to basket")).startswith("Done")     # covered by the window
    answer(P, True, minutes=5)
    assert asyncio.run(P.phone_tap(why="buy it", text="Jetzt kaufen")).startswith("Done")      # but this waited for its own OK
    log = [json.loads(x) for x in (P.D / "log.jsonl").read_text().splitlines()]
    assert [e.get("decision") for e in log if e.get("decision")][-2:] == ["allowed (the owner's free mode)", "allowed"]
    assert P.S["trust_until"] < time.time() + 601                                              # its "5 min" opened nothing
    for label in ("Place your order", "Zahlungspflichtig bestellen", "Subscribe", "Pay now", "Zur Kasse"):
        assert P.spends_money(label), label
    for label in ("Search", "Weather", "Display settings", "Paypal-free"):
        assert not P.spends_money(label) or label == "Paypal-free", label


def test_secret_fields_and_card_numbers_are_never_typed(P, monkeypatch):
    screen(P, monkeypatch, {"label": "(secret field: the owner types this himself)", "kind": "secret", "x": 500, "y": 900, "focused": True})
    assert "Refused" in asyncio.run(P.phone_type(text="hunter2", why="log in"))
    screen(P, monkeypatch, {"label": "Search", "kind": "field", "x": 500, "y": 900, "focused": True})
    assert "Refused" in asyncio.run(P.phone_type(text="4111 1111 1111 1111", why="pay"))
    assert "Refused" in asyncio.run(P.phone_type(text="DE89 3704 0044 0532 0130 00", why="pay"))
    P.S["trust_until"] = time.time() + 600
    answer(P, True)                                                   # typing always asks, even in a time window (DEC-23)
    assert asyncio.run(P.phone_type(text="ddr4 32gb", why="search")).startswith("Done")


def test_in_free_mode_only_an_address_or_text_with_private_data_asks(P, monkeypatch):
    """FND-02, PHN-19: Hermes holds private data and typing or an address is a way out; in the owner's free mode a plain
    one runs, one carrying an e-mail address, phone number, IBAN or key still asks."""
    screen(P, monkeypatch, {"label": "Search", "kind": "field", "x": 500, "y": 900, "focused": True})
    assert P.outward() == P.OUTWARD                                     # no free mode: it asks
    P.S["trust_until"] = time.time() + 600
    assert asyncio.run(P.phone_url(url="https://example.com/?q=notes", why="look it up")).startswith("Done")
    answer(P, False)
    r = asyncio.run(P.phone_url(url="https://example.com/?to=owner@example.com", why="send it"))
    assert "declined" in r, r                                           # it asked, and the owner said no


def test_url_block_list_and_done_summary(P):
    assert "block list" in asyncio.run(P.phone_url(url="https://www.paypal.com/signin", why="x"))
    assert asyncio.run(P.phone_done(summary="Cart ready: 2x16 GB DDR4-3200, 89 EUR. Pay at checkout.")) == "Sent to the owner."
    assert json.loads(next(P.DONE.glob("*.json")).read_text())["summary"].startswith("Cart ready")


def test_allowance_any_length_or_until_stopped(P):
    now = time.time()
    assert P.allowance(0) == 0
    assert 3500 < P.allowance(60) - now < 3700
    assert P.allowance(-1) - now > 365 * 86400                       # until the owner stops it
    assert P.allowance(10 ** 9) - now <= 7 * 86400 + 5               # anything longer is capped at a week


# ---------- an approved purchase: the final-screen check (simulated Amazon checkout screens) ----------
def el(label, y, kind="text", x=540):
    return {"label": label, "kind": kind, "x": x, "y": y, "box": (0, y - 20, 1080, y + 20), "focused": False, "money": False}


REVIEW = [el("Bestellung überprüfen", 100), el("Liefern an: Alex Example, Musterweg 1, 12345 Musterstadt", 200),
          el("Corsair Vengeance LPX 16GB (2x8GB) DDR4 3200 MHz C16 CMK16GX4M2B3200C16", 400), el("Verkauf durch: Amazon EU S.a.r.l.", 450),
          el("Gesamtsumme:", 600, x=200), el("39,90 €", 600, x=900), el("Jetzt kaufen", 800, "button")]
PA = {"id": "p-0000abcd", "pkg": "com.amazon.mShop.android.shopping", "url": "https://www.amazon.de/dp/B0143UM4TC",
      "item_words": ["CMK16GX4M2B3200C16"], "variant_words": ["2x8GB"], "seller_words": ["Amazon"], "address_words": ["12345"],
      "max_total_eur": 42.1, "approved_by": "owner@test", "used": False}


def test_final_check_passes_only_the_approved_order(P):
    assert P.final_check(REVIEW, PA)[0] is True
    assert P.order_total(REVIEW) == 39.9
    dear = [e if e["label"] != "39,90 €" else el("59,90 €", 600, x=900) for e in REVIEW]
    assert P.final_check(dear, PA) == (False, "the total 59.90 € is above the approved 42.10 €")
    other = [e if "Corsair" not in e["label"] else el("Kingston FURY Beast 16GB (2x8GB) DDR4", 400) for e in REVIEW]
    assert "differs" in P.final_check(other, PA)[1]
    moved = [e if "Liefern" not in e["label"] else el("Liefern an: Packstation 99999", 200) for e in REVIEW]
    assert "address" in P.final_check(moved, PA)[1]
    for blocker in ("Bitte geben Sie den Bestätigungscode ein", "3-D Secure: Zahlung bestätigen", "Geben Sie die Zeichen ein (Captcha)", "Anmelden"):
        ok, why = P.final_check(REVIEW + [el(blocker, 700)], PA)
        assert ok is False, blocker
    product_page = [e for e in REVIEW if "Gesamt" not in e["label"] and "€" not in e["label"]]
    assert P.final_check(product_page, PA)[0] is None                         # not the review screen: refuse, don't stop


def purchase(P, monkeypatch, screen):
    P.PURCHASES.mkdir(exist_ok=True)
    (P.PURCHASES / f"{PA['id']}.json").write_text(json.dumps({**PA, "expires": time.time() + 600}))
    P.fg[0] = PA["pkg"]
    monkeypatch.setattr(P, "read_screen", lambda limit=80: screen)
    nap = asyncio.sleep
    monkeypatch.setattr(P.asyncio, "sleep", lambda s: nap(0))


def test_the_approved_final_tap_happens_once(P, monkeypatch):
    purchase(P, monkeypatch, REVIEW)
    out = asyncio.run(P.phone_tap(why="place the approved order", text="Jetzt kaufen"))
    assert out.startswith("Done: the order is placed") and P.calls.count(("shell", "input", "tap", "540", "800")) == 1
    res = json.loads((P.PURCHASES / f"{PA['id']}.result.json").read_text())
    assert res["status"] == "placed" and res["total_eur"] == 39.9
    log = (P.D / "log.jsonl").read_text()
    assert f"purchase {PA['id']} approved by owner@test stands in for this money tap" in log
    assert P.active_purchase() is None                                         # used: a second tap asks the owner again
    answer(P, False)
    assert "declined" in asyncio.run(P.phone_tap(why="again", text="Jetzt kaufen"))
    assert P.calls.count(("shell", "input", "tap", "540", "800")) == 1


def test_a_mismatch_stops_without_buying(P, monkeypatch):
    dear = [e if e["label"] != "39,90 €" else el("59,90 €", 600, x=900) for e in REVIEW]
    purchase(P, monkeypatch, dear)
    out = asyncio.run(P.phone_tap(why="place the approved order", text="Jetzt kaufen"))
    assert out.startswith("Stopped, nothing bought") and not any(c[:3] == ("shell", "input", "tap") for c in P.calls)
    assert json.loads((P.PURCHASES / f"{PA['id']}.result.json").read_text())["status"] == "stopped"


def test_during_a_purchase_no_typing_and_no_address_changes(P, monkeypatch):
    purchase(P, monkeypatch, REVIEW + [el("Ändern", 250, "button")])
    assert asyncio.run(P.phone_type(text="hello", why="x")).startswith("Refused")
    assert "never changed" in asyncio.run(P.phone_tap(why="x", text="Ändern"))
    out = asyncio.run(P.phone_swipe(direction="up", why="see the cart"))      # steps inside the shop app: no asking
    assert out.startswith("Done")
    assert not list(P.PENDING.glob("*.json"))


def test_an_offline_phone_is_not_port_scanned(tmp_path, monkeypatch):
    """A dead phone lets connections hang: scanning it flooded rootless Docker's slirp4netns (every container lost the
    internet, 2026-10-29). Only a phone that answers (even with 'refused') gets scanned; retries back off."""
    monkeypatch.setenv("PHONE_DIR", str(tmp_path))
    monkeypatch.setenv("PHONE_HOST", "100.64.0.10")
    import phone
    phone = importlib.reload(phone)
    monkeypatch.setattr(phone, "adb", lambda *a, **k: "")
    scanned = []

    async def scan():
        scanned.append(1)
        return []
    monkeypatch.setattr(phone, "scan_ports", scan)

    async def hang(host, port):
        raise asyncio.TimeoutError
    monkeypatch.setattr(phone.asyncio, "open_connection", hang)
    assert asyncio.run(phone.connect()) is False and not scanned and "does not answer" in phone.S["error"]

    async def refuse(host, port):
        raise ConnectionRefusedError
    monkeypatch.setattr(phone.asyncio, "open_connection", refuse)
    assert asyncio.run(phone.phone_online()) is True
    asyncio.run(phone.connect())
    assert scanned == [1]


def test_start_in_ai_mode_asks_for_each_setting(P, monkeypatch):
    state = {"pkg": "versionName=1.8.38\n WRITE_SECURE_SETTINGS: granted=false", "vpn": "null", "idle": ""}

    def adb(*a, **k):
        P.calls.append(a)
        cmd = " ".join(a)
        return state["pkg"] if "dumpsys package" in cmd else state["vpn"] if "settings get" in cmd else state["idle"] if cmd.endswith("whitelist") else ""
    monkeypatch.setattr(P, "adb", adb)
    asks = []

    async def guard(tool, args, why, **k):
        asks.append((tool, args["what"], k.get("always")))
        return None if len(asks) < 3 else "declined"
    monkeypatch.setattr(P, "guard", guard)

    async def offline():
        return False
    monkeypatch.setattr(P, "connect", offline)
    asyncio.run(P.boot_setup())
    assert not asks and "not installed" not in (P.D / "log.jsonl").read_text()     # offline: no wrong verdict
    monkeypatch.setattr(P, "connect", lambda: asyncio.sleep(0, True))
    asyncio.run(P.boot_setup())
    assert [a[0] for a in asks] == ["phone_setting"] * 3 and all(a[2] for a in asks)      # always its own OK
    ran = [c for c in P.calls if c[1] in ("pm", "settings") and c[2] in ("grant", "put")]
    assert ran == [("shell", "pm", "grant", P.KEEPADB, "android.permission.WRITE_SECURE_SETTINGS"),
                   ("shell", "pm", "grant", P.KEEPADB, "android.permission.POST_NOTIFICATIONS"),
                   ("shell", "settings", "put", "secure", "always_on_vpn_app", P.TAILSCALE),
                   ("shell", "settings", "put", "secure", "always_on_vpn_lockdown", "0")]
    assert not any("deviceidle" in c and "whitelist" in c and len(c) > 4 for c in P.calls)    # declined: not run


def test_cards_left_by_a_restart_are_dropped_and_start_in_ai_mode_asks_again(P, monkeypatch):
    (P.PENDING / "aaaaaaaaaaaaaaaa.json").write_text(json.dumps({"id": "aaaaaaaaaaaaaaaa", "tool": "phone_setting", "args": {"what": "x"}}))
    (P.DECISIONS / "aaaaaaaaaaaaaaaa.json").write_text('{"allow": true}')        # the owner's Allow reached nobody
    gone = P.sweep_orphans()
    assert [g["tool"] for g in gone] == ["phone_setting"]
    assert not list(P.PENDING.glob("*.json")) and not list(P.DECISIONS.glob("*.json"))
    assert "dropped" in (P.D / "log.jsonl").read_text()
    answer(P, True)                                         # a live card is never swept: its Allow still works
    res = {}

    async def run():
        t = asyncio.create_task(P.guard("phone_tap", {"label": "OK"}, "test"))
        for _ in range(20):
            await asyncio.sleep(0.02)
            P.sweep_orphans()
        res["r"] = await t
    asyncio.run(run())
    assert res["r"] is None and not P.WAITING


def test_the_screen_stays_on_while_working_or_waiting_and_goes_off_when_idle(P):
    """PHN-17: each action holds the screen on for SCREEN_HOLD; an action waiting for the owner's OK keeps it on; then
    Android's 30 s timeout is back and the screen goes off at once. The owner can watch for up to an hour, or turn it off."""
    awake = ["mWakefulness=Awake"]
    P.adb = lambda *a, **k: P.calls.append(a) or (awake[0] if "dumpsys power" in " ".join(a) else "")
    t0 = time.time()
    P.hold_screen(P.SCREEN_HOLD, "the agents are working", t0)
    assert P.S["screen_held"] and P.S["screen_why"] == "the agents are working"
    assert ("shell", "settings", "put", "system", "screen_off_timeout", str(P.SCREEN_WAIT_MAX * 1000 + 60000)) in P.calls
    n = len(P.calls)
    P.hold_screen(P.SCREEN_HOLD, "the agents are working", t0 + 5)
    assert len(P.calls) == n                                       # one setting while held, not one per action
    P.screen_tick(t0 + 60)
    assert P.S["screen_held"] and not any("KEYCODE_SLEEP" in c for c in P.calls)
    (P.PENDING / "x.json").write_text("{}")                       # an action waits for the owner
    P.screen_tick(t0 + P.SCREEN_HOLD + 30)
    assert P.S["screen_held"] and P.S["screen_why"] == "an action waits for your OK"
    (P.PENDING / "x.json").unlink()
    P.screen_tick(t0 + P.SCREEN_HOLD + 60)
    assert not P.S["screen_held"] and ("shell", "input", "keyevent", "KEYCODE_SLEEP") in P.calls
    assert ("shell", "settings", "put", "system", "screen_off_timeout", "30000") in P.calls
    assert P.owner_screen(500) is None and 59 * 60 < P.S["screen_until"] - time.time() <= 60 * 60      # at most an hour
    assert P.S["screen_why"] == "you are watching"
    P.owner_screen(0)
    P.screen_tick()
    assert not P.S["screen_held"]


HA = "io.homeassistant.companion.android"


def test_one_ok_covers_a_whole_task_and_money_still_asks(P):
    """PHN-18: one Allow for the task; then taps in its apps, opening them and typing its exact texts run without asking;
    another app or another text asks; money always asks; phone_done ends the task and says how much ran under the OK."""
    P.launchable = lambda: [HA, "com.android.chrome", "de.sparkasse.app"]
    P.fg[0] = HA
    answer(P, True)
    out = asyncio.run(P.phone_task(task="Set up Assist in Home Assistant", apps=["homeassistant"], why="voice speaker",
                                   texts=["aiphone"], minutes=500))
    assert out.startswith("Allowed for 60 minutes") and P.S["task"]["apps"] == [HA]
    assert asyncio.run(P.guard("phone_tap", {"label": "Assist"}, "settings")) is None
    assert asyncio.run(P.guard("phone_swipe", {"direction": "up"}, "scroll")) is None and P.S["task"]["actions"] == 2
    assert P.outward(HA) == "" and P.outward(text="aiphone") == "" and P.outward(text="something else") == P.OUTWARD
    assert P.covered("phone_tap", "com.android.chrome") == "" and P.covered("phone_tap", "com.sec.android.app.launcher")
    answer(P, False)
    assert "declined" in asyncio.run(P.guard("phone_tap", {"label": "Buy"}, "pay", money=True))   # it asked
    assert "is not an app it may open" in asyncio.run(P.phone_task(task="x", apps=["sparkasse"], why="y"))
    asyncio.run(P.phone_done(summary="Assist is set up."))
    done = json.loads(next(P.DONE.glob("*.json")).read_text())["summary"]
    assert P.S["task"] is None and "2 actions under your one OK" in done


def test_free_mode_types_freely_but_private_text_asks(P):
    """PHN-19"""
    assert P.outward(text="hello") == P.OUTWARD                      # no permission: it asks
    P.S["trust_until"] = time.time() + 600
    assert P.outward(text="weather in Heilbronn tomorrow") == "" and P.outward("com.android.chrome") == ""
    for private in ("write to owner@example.com", "call +49 171 1234567", "DE89 3704 0044 0532 0130 00", "key sk-abcdefghijklmnop12"):
        assert P.outward(text=private) == P.OUTWARD, private
    assert P.outward("com.android.chrome", "https://example.com/?to=owner@example.com") == P.OUTWARD


def test_a_waiting_request_goes_ahead_when_the_owner_opens_free_mode(P):
    """PHN-20: the request does not wait for an Allow the owner already gave as a window or a task."""
    async def go():
        waiting = asyncio.create_task(P.guard("phone_swipe", {"direction": "up"}, "scroll"))
        await asyncio.sleep(0.5)
        assert list(P.PENDING.glob("*.json"))                         # it asked
        P.S["trust_until"] = time.time() + 600
        return await asyncio.wait_for(waiting, 2)
    assert asyncio.run(go()) is None and not list(P.PENDING.glob("*.json"))
    log = [json.loads(x) for x in (P.D / "log.jsonl").read_text().splitlines()]
    assert log[-1]["decision"] == "allowed (the owner's free mode, given while it waited)"


def test_the_home_assistant_app_opens_only_inside_a_task_that_names_it(P):
    """VOI-07: free mode alone does not open it; a task the owner approved that names it does, for that task only."""
    P.launchable = lambda: [HA, "com.android.chrome"]
    P.S["trust_until"] = time.time() + 600
    assert P.blocked(HA) == "homeassistant" and P.blocked("de.sparkasse.app") == "sparkasse"
    out = asyncio.run(P.phone_task(task="Assist settings", apps=["homeassistant"], why="voice"))   # free mode: no card
    assert out.startswith("Allowed") and P.blocked(HA) is None and P.blocked("de.sparkasse.app") == "sparkasse"
    asyncio.run(P.phone_done(summary="done"))
    assert P.blocked(HA) == "homeassistant"


def test_free_mode_and_a_task_outlive_a_restart_but_not_stop(P):
    """PHN-21: a deploy restarts the phone service; the owner's permission stays, Stop ends it."""
    (P.D / "state.json").write_text(json.dumps({"trust_until": time.time() + 600,
                                                "task": {"task": "x", "apps": [HA], "texts": [], "until": time.time() + 600}}))
    again = importlib.reload(P)
    assert again.S["trust_until"] > time.time() and again.S["task"]["task"] == "x"
    (P.D / "state.json").write_text(json.dumps({"trust_until": time.time() - 5, "task": {"until": time.time() - 5}}))
    again = importlib.reload(P)
    assert again.S["trust_until"] == 0 and again.S["task"] is None              # what has run out stays out
    (P.D / "state.json").write_text(json.dumps({"trust_until": time.time() + 600}))
    (P.D / "STOP").write_text("now")
    assert importlib.reload(P).S["trust_until"] == 0


def test_home_assistant_becomes_the_phone_s_voice_assistant_after_one_allow(P):
    """PHN-22: two Android settings (the assistant role, the microphone), one card, applied only after the owner's Allow
    and never by free mode."""
    have = {"role": "com.google.android.googlequicksearchbox", "mic": "RECORD_AUDIO: granted=false", "idle": "system,com.tailscale.ipn,"}

    def adb(*a, **k):
        P.calls.append(a)
        if "add-role-holder" in a:
            have["role"] = P.HA_APP
        if "grant" in a:
            have["mic"] = "RECORD_AUDIO: granted=true"
        if f"+{P.HA_APP}" in a:
            have["idle"] += f"{P.HA_APP},"
        if "get-role-holders" in a:
            return have["role"]
        return have["idle"] if "deviceidle" in a else have["mic"] if "dumpsys" in a else ""
    P.adb = adb
    P.S["trust_until"] = time.time() + 600                     # free mode does not cover a setting
    answer(P, True)
    asyncio.run(P.voice_setup())
    assert ("shell", "cmd", "role", "add-role-holder", "--user", "0", "android.app.role.ASSISTANT", P.HA_APP) in P.calls
    assert ("shell", "pm", "grant", P.HA_APP, "android.permission.RECORD_AUDIO") in P.calls
    assert ("shell", "dumpsys", "deviceidle", "whitelist", f"+{P.HA_APP}") in P.calls       # also locked or dark
    assert P.S["voice"] == {"assistant": True, "mic": True, "awake": True}
    log = [json.loads(x) for x in (P.D / "log.jsonl").read_text().splitlines()]
    assert [e.get("decision") for e in log if e.get("tool") == "phone_setting" and e.get("decision")] == ["allowed"]   # it asked
    n = len(P.calls)
    asyncio.run(P.voice_setup())                                 # done: nothing asked or changed again
    assert not any("add-role-holder" in c for c in P.calls[n:])


def test_an_app_opens_fresh_when_a_blocked_screen_sits_on_top_of_it(P):
    """PHN-23: Home Assistant had opened Android's default-assistant screen; opening it again landed there and the guard
    sent the phone home, every time. Now it is opened fresh at its start screen."""
    P.launchable = lambda: [HA]
    P.S["task"] = {"task": "wake word", "apps": [HA], "texts": [], "until": time.time() + 600}   # the app opens only in a task
    P.fg[0] = "com.sec.android.app.launcher"

    def adb(*a, **k):
        P.calls.append(a)
        if "monkey" in a:
            P.fg[0] = "com.android.settings"                    # what sits on top of the app's task
        if "--activity-clear-task" in a:
            P.fg[0] = HA
        return f"priority=0\n{HA}/.launch.LaunchActivity" if "resolve-activity" in a else ""
    P.adb = adb
    out = asyncio.run(P.phone_open(app="homeassistant", why="wake word"))
    assert ("shell", "am", "start", "--activity-clear-task", "-n", f"{HA}/.launch.LaunchActivity") in P.calls
    assert P.fg[0] == HA and "blocked" not in out


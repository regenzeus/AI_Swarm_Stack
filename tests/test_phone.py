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
    assert [e.get("decision") for e in log if e.get("decision")][-2:] == ["allowed (owner's time window)", "allowed"]
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


def test_typing_urls_and_apps_always_ask_even_in_a_time_window(P, monkeypatch):
    """FND-02: Hermes holds private data; typing and opening addresses are a way out, so a time window never covers them."""
    screen(P, monkeypatch, {"label": "Search", "kind": "field", "x": 500, "y": 900, "focused": True})
    P.S["trust_until"] = time.time() + 600
    answer(P, False)
    r = asyncio.run(P.phone_url(url="https://example.com/?q=notes", why="look it up"))
    assert "declined" in r, r                                           # it asked, and the owner said no
    log = [json.loads(x) for x in (P.D / "log.jsonl").read_text().splitlines()]
    assert not any(e.get("tool") == "phone_url" and e.get("decision") == "allowed (owner's time window)" for e in log)
    assert P.outward() == P.OUTWARD


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

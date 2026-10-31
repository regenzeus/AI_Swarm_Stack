"""ops/shopping.py and images/browser/guard.py: shopping missions find offers, watch prices, and never buy."""
import asyncio
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REPORT = """## Result
### What fits
DDR4 kit.
### Offers
| # | Product | Shop | Price (EUR) | Why | Link |
|---|---|---|---|---|---|
| 1 | Corsair 2x8 | Alternate | 89,90 | same kit | https://example.com |

## Notes
seen 89,90 at Alternate

## Summary
Top pick: Corsair at Alternate for 89,90 €.

## Price
BEST_PRICE_EUR: {price}
"""


@pytest.fixture
def SH(runner, monkeypatch, tmp_path):
    import shopping
    M = runner
    shopping.M = M
    hw = tmp_path / "hardware.json"
    hw.write_text(json.dumps({"cpu": "i7-7700K", "board": "ASRock Z270 Pro4", "bios": "P1.00",
                              "memory": {"slots": 4, "max_gb": 64, "modules": [
                                  {"slot": "A1", "gb": 8, "type": "DDR4", "part": "CMK16GX4M2B3200C16", "rated_mhz": 2133,
                                   "configured_mhz": 2133, "volts": 1.2}] * 2}}), encoding="utf-8-sig")
    monkeypatch.setattr(shopping, "FACTS", hw)
    for name in ("HOME", "PHONE", "CONN"):                 # proposals, the phone's purchases, the Gmail grants
        (tmp_path / name).mkdir()
        monkeypatch.setattr(shopping, name, tmp_path / name)
    (tmp_path / "PHONE" / "control").mkdir()
    monkeypatch.setattr(shopping.PW, "watch", lambda url, title: "w-1")      # changedetection.io is not running here
    monkeypatch.setattr(shopping.PW, "forget", lambda uid: None)
    sent = {"events": [], "telegram": [], "delivered": []}
    monkeypatch.setattr(M, "event", lambda kind, slug="", text="", push=False, title="": sent["events"].append((kind, text)))
    monkeypatch.setattr(M.X, "telegram", lambda text, buttons=(), category="result": sent["telegram"].append(text) or sent.setdefault("buttons", []).append(buttons))
    monkeypatch.setattr(M.X, "deliver", lambda *a, **k: sent["delivered"].append(a[1]))
    monkeypatch.setattr(M.X, "compile_wiki", lambda *a, **k: None)
    monkeypatch.setattr(M, "vault_commit", lambda *a, **k: None)
    monkeypatch.setattr(M, "reindex", lambda: None)
    monkeypatch.setenv("VK_MISSION", "x")
    shopping.sent = sent
    return shopping


def mission(M, **kw):
    m = {"slug": "ram", "title": "RAM to 32 GB", "type": "shopping", "goal": "32 GB for this PC", "status": "active",
         "schedule": "manual", "deliver": ["telegram", "app"], **kw}
    M.save_mission(m)
    return m


def test_the_pc_facts_reach_the_prompt(SH):
    f = SH.pc_facts()
    assert "ASRock Z270 Pro4" in f and "16 GB installed in 2 of 4 slots" in f and "CMK16GX4M2B3200C16" in f


@pytest.mark.parametrize("text,price", [("89,90", 89.9), ("1.234,56", 1234.56), ("1,234.56", 1234.56), ("119.00", 119.0), ("none", None)])
def test_best_price_is_read_in_any_format(SH, text, price):
    assert SH.best_price(REPORT.format(price=text)) == price


def test_first_run_reports_and_remembers_the_price(SH, runner, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "hermes_z", lambda prompt, timeout=0: REPORT.format(price="89,90"))
    m = mission(runner)
    status, summary, rel = SH.run(m, tmp_path / "run.log")
    assert status == "ok" and SH.sent["delivered"] == ["RAM to 32 GB"]
    assert runner.load_missions()["ram"]["best_price_eur"] == 89.9


def test_price_watch_stays_quiet_until_the_price_drops(SH, runner, tmp_path, monkeypatch):
    m = mission(runner, watch_pct=5, best_price_eur=89.9)
    monkeypatch.setattr(runner, "hermes_z", lambda prompt, timeout=0: REPORT.format(price="88,00"))
    SH.run(m, tmp_path / "a.log")                                    # -2 %: no news
    assert not SH.sent["delivered"] and not SH.sent["telegram"]
    m = runner.load_missions()["ram"]
    monkeypatch.setattr(runner, "hermes_z", lambda prompt, timeout=0: REPORT.format(price="79,00"))
    SH.run(m, tmp_path / "b.log")                                    # -10 %: tell the owner
    assert any(k == "price_drop" for k, _ in SH.sent["events"]) and "88.00 € → 79.00 €" in SH.sent["telegram"][0]


def test_shopping_missions_can_be_created(runner):
    c = runner.db()
    r = runner.handle({"action": "create", "type": "shopping", "title": "Find 32 GB RAM", "description": "for this PC",
                       "run_now": False, "watch_pct": 5}, runner.load_missions(), c)
    m = runner.load_missions()[r["slug"]]
    assert m["type"] == "shopping" and m["watch_pct"] == 5 and "never buys" in r["detail"]


# ---------- the browser guard: it only looks ----------
@pytest.fixture
def G(monkeypatch):
    sys.path.insert(0, str(ROOT / "images" / "browser"))
    import guard
    guard = importlib.reload(guard)
    calls = []
    pages = {"url": "https://shop.example/search?q=ram"}
    snap = ('### Page\n- Page URL: {url}\n### Snapshot\n- generic [ref=e1]:\n  - searchbox "Suche" [ref=e5]\n'
            '  - button "In den Warenkorb" [ref=e7]\n  - link "Corsair 2x16GB" [ref=e9]\n  - textbox "E-Mail" [ref=e11]\n')

    async def fake(tool, args=None):
        calls.append((tool, args))
        if tool == "browser_navigate":
            pages["url"] = args["url"]
        if tool == "browser_navigate_back":
            pages["url"] = "https://shop.example/search?q=ram"
        return snap.format(url=pages["url"]) if tool == "browser_snapshot" else "ok"
    monkeypatch.setattr(guard, "call", fake)
    guard.calls, guard.pages = calls, pages
    return guard


def test_guard_refuses_login_cart_checkout_and_payment(G):
    run = asyncio.run
    assert "Product" not in run(G.browse_open("https://shop.example/search?q=ram")) and G.last["url"].startswith("https://shop")
    for u in ("https://shop.example/checkout", "https://www.amazon.de/gp/cart/view.html", "https://shop.example/login.php",
              "https://www.paypal.com/x", "file:///etc/passwd", "javascript:alert(1)"):
        assert run(G.browse_open(u)).startswith("Refused"), u
    assert run(G.browse_click("e7", "add to cart")).startswith("Refused")        # the buy button
    assert "Refused" not in run(G.browse_click("e9", "product link"))
    assert run(G.browse_search("e11", "ram")).startswith("Refused")              # not a search field
    assert run(G.browse_search("e5", "owner@example.com")).startswith("Refused")  # personal data
    assert "Refused" not in run(G.browse_search("e5", "DDR4 32GB 3200"))


def test_guard_goes_back_when_a_click_lands_on_checkout(G, monkeypatch):
    async def to_checkout(tool, args=None):
        G.calls.append((tool, args))
        if tool == "browser_click":
            G.pages["url"] = "https://shop.example/checkout/step1"
        if tool == "browser_navigate_back":
            G.pages["url"] = "https://shop.example/search?q=ram"
        return f"### Page\n- Page URL: {G.pages['url']}\n" if tool == "browser_snapshot" else "ok"
    asyncio.run(G.browse_open("https://shop.example/search?q=ram"))
    G.last["snapshot"] += '\n- link "Details" [ref=e3]'
    monkeypatch.setattr(G, "call", to_checkout)
    out = asyncio.run(G.browse_click("e3", "details"))
    assert out.startswith("Refused") and ("browser_navigate_back", None) in G.calls


def test_a_run_cut_off_by_a_runner_restart_starts_again_once(runner):
    c = runner.db()
    start = runner.now().isoformat(timespec="seconds")
    c.execute("insert into runs (slug, trigger, status, started) values ('ram', 'manual', 'running', ?)", (start,))
    c.execute("insert into runs (slug, trigger, status, started) values ('old', 'manual', 'running', '2026-10-20T10:00:00+01:00')")
    c.commit()
    runner.requeue_interrupted(c)
    rows = [tuple(r) for r in c.execute("select slug, trigger, status from runs order by id")]
    assert rows == [("ram", "manual", "failed"), ("old", "manual", "failed"), ("ram", "restart", "queued")]
    c.execute("update runs set status='running' where trigger='restart'"); c.commit()
    runner.requeue_interrupted(c)                                     # a restart run cut off again: not a third time
    assert not c.execute("select 1 from runs where status='queued'").fetchone()


# ---------- from wish to door: proposals, the owner's decision, limits ----------
OFFERS = """
## Offers JSON
```json
{"need": "a second 2x8 GB kit", "budget_eur": null, "deadline": null,
 "offers": [{"product": "Corsair Vengeance LPX 16GB (2x8GB) DDR4 3200 CMK16GX4M2B3200C16", "variant": "2x8 GB, black",
   "shop": "amazon.de", "seller": "Amazon", "rating": "4.8/5 (40,000)", "price_eur": 39.9, "shipping_eur": 0,
   "delivery": "Fri 31 Oct", "url": "https://www.amazon.de/dp/B0143UM4TC"},
  {"product": "Corsair Vengeance LPX 16GB", "variant": "2x8", "shop": "Mindfactory", "seller": "Mindfactory", "price_eur": "36,99",
   "shipping_eur": "6,99", "url": "https://www.mindfactory.de/product_info.php/x"}],
 "top": 0, "match": {"item": ["CMK16GX4M2B3200C16"], "variant": ["2x8GB"], "seller": ["Amazon"]},
 "price_history": "lowest 37 EUR in September", "trend": "rising since August",
 "verdict": {"action": "%s", "target_eur": %s, "until": %s, "reason": "DDR4 is getting dearer"},
 "why": "the same kit as the installed one", "why_now": "prices are rising"}
```
"""


def report(action="buy_now", target="null", until="null"):
    return REPORT.format(price="39,90") + OFFERS % (action, target, until)


def test_sales_ahead_know_black_friday(SH):
    import datetime as dt
    sales = dict((name, d) for d, name in SH.sales_ahead(dt.date(2026, 10, 28)))
    assert sales["Black Friday"] == dt.date(2026, 11, 27) and sales["Cyber Monday"] == dt.date(2026, 11, 30)


def test_a_run_ends_in_a_proposal_card(SH, runner, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "hermes_z", lambda prompt, timeout=0: report())
    m = mission(runner)
    assert SH.run(m, tmp_path / "run.log")[0] == "ok"
    [p] = SH.proposals("ram")
    assert (p["status"], p["shop"], p["seller"], p["total_eur"], p["delivery"]) == ("proposed", "amazon.de", "Amazon", 39.9, "Fri 31 Oct")
    assert p["offers"][1]["total_eur"] == 43.98 and p["watch"] == "w-1" and "default address" in p["address"]
    assert "Purchase proposal" in SH.sent["telegram"][-1] and "39.90 €" in SH.sent["telegram"][-1]
    labels = [b[0] for row in SH.sent["buttons"][-1] for b in row]
    assert labels[:3] == ["✅ Approve purchase", "⏸ Not now", "✏️ Change"]
    assert runner.load_missions()["ram"]["needs"] == ["gmail:read"]           # the proposal asks for the mail grant
    assert SH.state()["shopping"]["proposals"][0]["id"] == p["id"]


def test_wait_verdict_keeps_watching(SH, runner, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "hermes_z", lambda prompt, timeout=0: report("wait", "34.0", '"2026-11-27"'))
    SH.run(mission(runner), tmp_path / "run.log")
    [p] = SH.proposals("ram")
    assert p["status"] == "watching" and p["verdict"] == {"action": "wait", "target_eur": 34.0, "until": "2026-11-27", "reason": "DDR4 is getting dearer"}
    assert "Wait" in SH.sent["telegram"][-1]


def test_over_a_cap_only_a_buy_yourself_link(SH, runner, tmp_path, monkeypatch):
    (SH.HOME / "limits.json").write_text(json.dumps({"per_purchase_eur": 30}))
    monkeypatch.setattr(runner, "hermes_z", lambda prompt, timeout=0: report())
    SH.run(mission(runner), tmp_path / "run.log")
    [p] = SH.proposals("ram")
    assert p["status"] == "over_limit" and "per-purchase cap of 30" in p["over"]
    assert [b[0] for row in SH.sent["buttons"][-1] for b in row][0] == "🛒 Buy it yourself"


def proposed(SH, runner, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "hermes_z", lambda prompt, timeout=0: report())
    SH.run(mission(runner), tmp_path / "run.log")
    return SH.proposals("ram")[0]


def test_only_the_owner_approves_and_the_phone_gets_exactly_that(SH, runner, tmp_path, monkeypatch):
    p = proposed(SH, runner, tmp_path, monkeypatch)
    c = runner.db()
    for src in ("app", "chat", None):                                         # generic app requests, Hermes' tools
        with pytest.raises(ValueError, match="only the owner"):
            SH.handle({"action": "shop_decide", "id": p["id"], "decision": "approve", "source": src}, c)
    with pytest.raises(ValueError, match="address"):                          # no postcode to check: nothing can be bought
        SH.handle({"action": "shop_decide", "id": p["id"], "decision": "approve", "source": "owner"}, c)
    SH.handle({"action": "shop_limits", "address_words": ["12345"], "source": "owner"}, c)
    r = SH.handle({"action": "shop_decide", "id": p["id"], "decision": "approve", "source": "owner", "by": "owner@test"}, c)
    assert r == {"status": "approved", "ceiling_eur": 42.1}
    pa = json.loads((SH.PHONE / "purchases" / f"{p['id']}.json").read_text())
    assert (pa["item_words"], pa["variant_words"], pa["seller_words"], pa["address_words"], pa["max_total_eur"], pa["used"]) == \
           (["CMK16GX4M2B3200C16"], ["2x8GB"], ["Amazon"], ["12345"], 42.1, False)
    assert pa["pkg"] == "com.amazon.mShop.android.shopping" and pa["approved_by"] == "owner@test"
    run = c.execute("select trigger, event from runs where slug='ram' and status='queued'").fetchone()
    assert json.loads(run["event"])["shop"] == {"do": "buy", "id": p["id"]}
    with pytest.raises(ValueError, match="approved"):                         # once only
        SH.handle({"action": "shop_decide", "id": p["id"], "decision": "approve", "source": "owner"}, c)


def test_monthly_cap_counts_what_was_bought(SH, runner, tmp_path, monkeypatch):
    p = proposed(SH, runner, tmp_path, monkeypatch)
    SH.save({**p, "id": "p-00000001", "status": "bought", "total_eur": 280, "bought_at": runner.now().isoformat()})
    assert SH.spent_this_month() == 280
    assert "monthly cap of 300" in SH.over_limit(39.9, "amazon.de")


def test_not_now_keeps_watching_and_change_looks_again(SH, runner, tmp_path, monkeypatch):
    p = proposed(SH, runner, tmp_path, monkeypatch)
    c = runner.db()
    assert SH.handle({"action": "shop_decide", "id": p["id"], "decision": "not_now", "source": "owner"}, c)["status"] == "watching"
    assert SH.load(p["id"])["verdict"]["target_eur"] == 37.9
    r = SH.handle({"action": "shop_decide", "id": p["id"], "decision": "change", "note": "white, please", "source": "owner"}, c)
    assert r["rerun"] and json.loads(c.execute("select event from runs where slug='ram'").fetchone()[0])["summary"] == "white, please"


def test_buy_run_reports_the_order(SH, runner, tmp_path, monkeypatch):
    p = proposed(SH, runner, tmp_path, monkeypatch)
    c = runner.db()
    SH.handle({"action": "shop_limits", "address_words": ["12345"], "source": "owner"}, c)
    SH.handle({"action": "shop_decide", "id": p["id"], "decision": "approve", "source": "owner"}, c)
    monkeypatch.setattr(runner, "park", lambda what, ready, timeout=0, every=0: True)

    def phone_buys(prompt, timeout=0):                                        # the phone's final tap leaves its result
        (SH.PHONE / "purchases" / f"{p['id']}.result.json").write_text(json.dumps({"status": "placed", "order": "302-1234567-7654321", "total_eur": 39.9}))
        return "ORDER: 302-1234567-7654321 - placed"
    monkeypatch.setattr(SH, "hermes_main", phone_buys)
    st, summary, _ = SH.run(runner.load_missions()["ram"], tmp_path / "buy.log", {"trigger": "purchase approved", "shop": {"do": "buy", "id": p["id"]}})
    q = SH.load(p["id"])
    assert st == "ok" and q["status"] == "bought" and q["order"] == "302-1234567-7654321"
    assert not (SH.PHONE / "purchases" / f"{p['id']}.json").exists()           # the approval covered this one run
    assert "Ordered" in SH.sent["telegram"][-1]


def test_a_stopped_purchase_asks_the_owner(SH, runner, tmp_path, monkeypatch):
    p = proposed(SH, runner, tmp_path, monkeypatch)
    c = runner.db()
    SH.handle({"action": "shop_limits", "address_words": ["12345"], "source": "owner"}, c)
    SH.handle({"action": "shop_decide", "id": p["id"], "decision": "approve", "source": "owner"}, c)
    monkeypatch.setattr(runner, "park", lambda what, ready, timeout=0, every=0: True)

    def stopped(prompt, timeout=0):
        (SH.PHONE / "purchases" / f"{p['id']}.result.json").write_text(json.dumps({"status": "stopped", "reason": "the total 59.90 € is above the approved 42.10 €"}))
        return "ORDER: none - stopped"
    monkeypatch.setattr(SH, "hermes_main", stopped)
    st, summary, _ = SH.run(runner.load_missions()["ram"], tmp_path / "buy.log", {"trigger": "x", "shop": {"do": "buy", "id": p["id"]}})
    assert st == "failed" and SH.load(p["id"])["status"] == "needs_owner" and "above the approved" in SH.sent["telegram"][-1]


def test_limits_are_validated(SH, runner):
    c = runner.db()
    for bad in ({"per_purchase_eur": 0}, {"per_month_eur": 99999}, {"shops": ["not a shop"]}):
        with pytest.raises(ValueError):
            SH.handle({"action": "shop_limits", "source": "owner", **bad}, c)
    assert SH.handle({"action": "shop_limits", "source": "owner", "per_purchase_eur": 120, "shops": ["www.Amazon.de"]}, c)["limits"]["shops"] == ["amazon.de"]



def test_an_over_cap_pick_is_watched_and_proposed_again_under_the_cap(SH, runner, tmp_path, monkeypatch):
    (SH.HOME / "limits.json").write_text(json.dumps({"per_purchase_eur": 38}))
    monkeypatch.setattr(runner, "hermes_z", lambda prompt, timeout=0: report())
    SH.run(mission(runner), tmp_path / "run.log")
    assert SH.proposals("ram")[0]["status"] == "over_limit"
    monkeypatch.setattr(SH.PW, "reading", lambda uid: {"price": 37.5})
    c = runner.db()
    SH.tick(c)
    run = c.execute("select event from runs where slug='ram' and status='queued'").fetchone()
    assert json.loads(run["event"])["trigger"] == "price target reached"



def test_the_same_price_under_the_target_proposes_once(SH, runner, tmp_path, monkeypatch):
    """29 Oct: 68.61 EUR under a 69 EUR target re-proposed every run (10 Telegram messages): a reading is news once."""
    (SH.HOME / "limits.json").write_text(json.dumps({"per_purchase_eur": 38}))
    monkeypatch.setattr(runner, "hermes_z", lambda prompt, timeout=0: report())
    SH.run(mission(runner), tmp_path / "run.log")
    monkeypatch.setattr(SH.PW, "reading", lambda uid: {"price": 37.5})
    c = runner.db()
    count = lambda: c.execute("select count(*) from runs where slug='ram' and trigger='event'").fetchone()[0]
    SH.tick(c)
    assert count() == 1
    c.execute("update runs set status='ok' where slug='ram'")
    c.commit()
    SH._ticks.clear()                                                 # a runner restart forgets the in-memory timer
    SH.tick(c)
    assert count() == 1                                               # the proposal remembers when it was checked
    p = SH.proposals("ram")[0]
    p["watched_at"] = 0
    SH.save(p)
    SH._ticks.clear()
    SH.tick(c)
    assert count() == 1                                               # checked again, same price: not news
    monkeypatch.setattr(SH.PW, "reading", lambda uid: {"price": 36.0})
    p = SH.proposals("ram")[0]
    p["watched_at"] = 0
    SH.save(p)
    SH._ticks.clear()
    SH.tick(c)
    assert count() == 2                                               # a lower price is



def test_a_top_pick_from_another_shop_is_a_buy_yourself_link(SH, runner, tmp_path, monkeypatch):
    out = report().replace('"top": 0', '"top": 1')                         # the agent's pick is the Mindfactory offer
    monkeypatch.setattr(runner, "hermes_z", lambda prompt, timeout=0: out)
    SH.run(mission(runner), tmp_path / "run.log")
    [p] = SH.proposals("ram")
    assert (p["status"], p["shop"], p["total_eur"]) == ("over_limit", "mindfactory.de", 43.98)
    assert "not one of the shops you buy from directly" in p["over"] and p["buy_link"].startswith("https://www.mindfactory.de")

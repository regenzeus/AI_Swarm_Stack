"""Shopping agents (missions of type "shopping", run by ops/missions.py): from a wish to the door.

A run, step by step (each step is an event in the agent's runtime log):
  1. read    what fits: the PC's own facts (C:\\AI\\exports\\.host\\hardware.json, ops/windows/host-probe.ps1), the
             limits, the price history of an open proposal (ops/pricewatch.py: changedetection.io) and the sale calendar
  2. agent   the mission agent (Hermes profile "mission", vk-mission) researches the category and current offers through
             the research tool (the scout's browser) and writes the report plus a JSON block: offers in EUR incl.
             shipping with seller, rating and delivery date; the top pick; a verdict "buy now" or "wait until ≤ €X / date"
  3. phone   optional: the same item looked up in the shop's app on the AI phone (read-only; the phone asks the owner
             unless he lets it work without asking); the run parks meanwhile (missions.park), other missions run
  4. propose a proposal record (/srv/ai/missions/shopping/proposals/<id>.json, outside the vault: no agent can edit
             it), checked against the limits; a card in Mission Control (agent page + Home) and on Telegram with
             Approve purchase / Not now / Change. Over a cap: only a "buy it yourself" link. "Wait": it keeps watching
             (changedetection.io re-reads the offer page) and proposes again when the target or the date is reached.
After the owner's approval (only in Mission Control from his own device, never from the AI phone, never via an MCP tool):
  buy    a purchase approval for the AI phone (/srv/ai/phone/purchases/<id>.json) and a run of Hermes (main profile,
         phone tools) that puts exactly that item in the cart and goes to checkout. The phone (images/phone/phone.py)
         checks the final screen deterministically (item, variant, seller, total ≤ ceiling, address, no login/code/
         captcha/3-D Secure) and only then taps the final buy button, once; otherwise it stops and the owner is asked.
  track  order number from the confirmation screen, then the confirmation and shipping mails (Gmail read grant,
         requested in the proposal) until delivered.
The agents never type payment data or passwords and never change the address or payment method. Pattern: agents
propose, a human approves, then a narrow deterministic step acts (anthropics/commerce-agents, docs/SHOPPING.md).
"""
import datetime as dt
import html
import json
import re
import subprocess
import time
import urllib.parse
import uuid
from pathlib import Path

import pricewatch as PW
from textcap import STORE, cut, limit, tail                    # visible caps and input limits (AGENTS.md, truncation)
import textcap as TC
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md

M = None                                   # ops/missions.py (set in its main)
FACTS = Path("/srv/win-exports/.host/hardware.json")
HOME = Path("/srv/ai/missions/shopping")   # proposals + limits: the runner and Mission Control only
PHONE = Path("/srv/ai/phone")              # the AI phone's shared dir: control/, purchases/, research/
CONN = Path("/srv/ai/connections")
DEFAULT_LIMITS = {"per_purchase_eur": 150.0, "per_month_eur": 300.0, "shops": ["amazon.de"], "address_words": []}
SHOP_APPS = {"amazon.de": "com.amazon.mShop.android.shopping"}
ACTIONS = {"shop_decide", "shop_limits"}
LIVE = ("proposed", "watching", "approved", "buying", "needs_owner", "bought", "shipped")
SPENT = ("bought", "shipped", "delivered")
TRACK_EVERY = 3 * 3600
WATCH_EVERY = 6 * 3600

PROMPT = P.text("mission", "SHOPPING")

BUY_PROMPT = P.text("main", "BUY")

TRACK_PROMPT = P.text("mission", "TRACK")


# ---------- facts ----------
def pc_facts():
    """The PC's hardware, as lines for the prompt."""
    try:
        h = json.loads(FACTS.read_text(encoding="utf-8-sig"))
    except Exception:
        return "(not available: C:\\AI\\exports\\.host\\hardware.json is missing; ask the owner only what you need)"
    out = [f"- CPU: {h.get('cpu', '?')}", f"- Mainboard: {h.get('board', '?')} (BIOS {h.get('bios', '?')})"]
    mem = h.get("memory") or {}
    mods = mem.get("modules") or []
    out.append(f"- Memory: {sum(x.get('gb', 0) for x in mods):g} GB installed in {len(mods)} of {mem.get('slots', '?')} slots, "
               f"board maximum {mem.get('max_gb', '?')} GB")
    for x in mods:
        out.append(f"  - {x.get('slot', '?')}: {x.get('gb', '?')} GB {x.get('type', '')} {x.get('maker', '')} {x.get('part', '')}"
                   f" rated {x.get('rated_mhz', '?')} MT/s, running at {x.get('configured_mhz', '?')} MT/s, {x.get('volts', '?')} V")
    for g in h.get("gpu") or []:
        out.append(f"- Graphics: {g}")
    for d in h.get("disks") or []:
        out.append(f"- Disk: {d}")
    return "\n".join(out)


def sales_ahead(today):
    """The big German sale days in the next ~4 months (Black Friday = the day after the 4th Thursday of November)."""
    out = []
    for y in (today.year, today.year + 1):
        nov1 = dt.date(y, 11, 1)
        bf = nov1 + dt.timedelta(days=(3 - nov1.weekday()) % 7 + 21 + 1)
        for d, name in ((bf - dt.timedelta(days=7), "Black Week starts"), (bf, "Black Friday"), (bf + dt.timedelta(days=3), "Cyber Monday"),
                        (dt.date(y, 12, 26), "after-Christmas sales"), (dt.date(y + 1, 1, 2), "January sales")):
            if today <= d <= today + dt.timedelta(days=120):
                out.append((d, name))
    return sorted(set(out))


def best_price(out):
    m = re.search(r"BEST_PRICE_EUR:\s*([\d.,]+)", M.section(out, "Price") or out)
    return PW.eur(m.group(1)) or None if m else None


def offers_json(out):
    """The ## Offers JSON block of a report, or None."""
    sec = M.section(out, "Offers JSON") or ""
    m = re.search(r"\{.*\}", sec, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    offers = []
    for o in d.get("offers") or []:
        if not isinstance(o, dict) or not o.get("product"):
            continue
        price, ship = num(o.get("price_eur")), num(o.get("shipping_eur")) or 0.0
        total = num(o.get("total_eur")) or (round(price + ship, 2) if price else None)
        if not total:
            continue
        offers.append({"product": TC.cut(str(o["product"]), 200), "variant": TC.cut(str(o.get("variant") or ""), 160),  # cap: untrusted
                       "shop": shop_of(o.get("shop"), o.get("url")), "seller": TC.cut(str(o.get("seller") or ""), 80),  # cap: untrusted
                       "rating": TC.cut(str(o.get("rating") or ""), 60), "price_eur": price, "shipping_eur": ship, "total_eur": total,  # cap: untrusted
                       "delivery": TC.cut(str(o.get("delivery") or ""), 60), "url": str(o.get("url") or "")[:600]})  # cap: api (a URL; a marker would break it)
    if not offers:
        return None
    d["offers"] = offers
    top = d.get("top") if isinstance(d.get("top"), int) and 0 <= d["top"] < len(offers) else 0
    d["top"] = top
    v = d.get("verdict") if isinstance(d.get("verdict"), dict) else {}
    d["verdict"] = {"action": "wait" if str(v.get("action", "")).startswith("wait") else "buy_now",
                    "target_eur": num(v.get("target_eur")), "until": date_or_none(v.get("until")), "reason": cut(v.get("reason") or "", 2000)}  # cap: untrusted
    mt = d.get("match") if isinstance(d.get("match"), dict) else {}
    d["match"] = {k: [str(w)[:40] for w in (mt.get(k) or []) if str(w).strip()][:4] for k in ("item", "variant", "seller")}  # cap: parse (words matched on the phone's screen; a marker would never match)
    return d


def num(v):
    if isinstance(v, (int, float)):
        return round(float(v), 2) if v > 0 else None
    return PW.eur(str(v)) if v and re.search(r"\d", str(v)) else None


def date_or_none(v):
    try:
        return dt.date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        return None


def shop_of(shop, url):
    host = urllib.parse.urlparse(url or "").hostname or ""
    s = (host or str(shop or "")).lower().removeprefix("www.")
    return s[:60] or "?"  # cap: id


# ---------- limits and proposals ----------
def limits():
    try:
        d = json.loads((HOME / "limits.json").read_text())
    except (OSError, ValueError):
        d = {}
    return {**DEFAULT_LIMITS, **{k: v for k, v in d.items() if k in DEFAULT_LIMITS}}


def save_json(path, d):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    tmp.chmod(0o600)                          # proposals, limits, purchase approvals: this user only
    tmp.replace(path)


def to_phone(name, d):
    """A request in the AI phone's control folder, readable by the phone's service, which runs as another user (FND-116:
    written for this user only, like the proposals, it stopped the phone for a day)."""
    path = PHONE / "control" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False))
    tmp.chmod(0o644)
    tmp.replace(path)


def load(pid):
    try:
        return json.loads((HOME / "proposals" / f"{pid}.json").read_text()) if re.fullmatch(r"p-[a-f0-9]{8}", str(pid)) else None
    except (OSError, ValueError):
        return None


def save(p):
    p["updated"] = M.now().isoformat(timespec="seconds")
    save_json(HOME / "proposals" / f"{p['id']}.json", p)


def proposals(slug=None):
    out = []
    for f in sorted((HOME / "proposals").glob("p-*.json")) if (HOME / "proposals").exists() else []:
        try:
            p = json.loads(f.read_text())
        except ValueError:
            continue
        if slug is None or p.get("slug") == slug:
            out.append(p)
    return sorted(out, key=lambda p: p.get("created", ""), reverse=True)


def spent_this_month(now=None):
    month = (now or M.now()).strftime("%Y-%m")
    return round(sum(p.get("total_eur") or 0 for p in proposals() if p.get("status") in SPENT and (p.get("bought_at") or "")[:7] == month), 2)


def over_limit(total, shop, lim=None):
    lim = lim or limits()
    if shop not in lim["shops"]:
        return f"{shop} is not one of the shops you buy from directly ({', '.join(lim['shops'])})"
    if total > lim["per_purchase_eur"]:
        return f"{total:.2f} € is over your per-purchase cap of {lim['per_purchase_eur']:.0f} €"
    if spent_this_month() + total > lim["per_month_eur"]:
        return f"it would take this month over your monthly cap of {lim['per_month_eur']:.0f} € ({spent_this_month():.2f} € spent)"
    return ""


def note(p, text):
    """The proposal's own journal (shown on its card) and the activity feed."""
    p.setdefault("journal", []).append({"at": M.now().isoformat(timespec="minutes"), "text": text})
    p["journal"] = p["journal"][-40:]  # cap: rotate (the card's newest 40 notes; the activity feed and the vault keep every one)


def step(title, detail="", kind="stage", status=None):
    """One line in the agent's log: stage (a step), read (facts it read), propose (the proposal), wait (missions.park)."""
    M.RTM.stage(title, detail, kind=kind, status=status)


def state():
    """For state.json: open and recent proposals, the limits, this month's spending."""
    ps = [p for p in proposals() if p.get("status") in LIVE or p.get("updated", "") >= (M.now() - dt.timedelta(days=30)).isoformat()]
    return {"shopping": {"proposals": ps[:30], "more": max(0, len(ps) - 30), "limits": limits(), "spent_month": spent_this_month()}}  # cap: list


# ---------- a run ----------
def run(m, logf, ev=None):
    shop_ev = (ev or {}).get("shop") or {}
    if shop_ev.get("do") == "buy":
        return buy(m, logf, shop_ev.get("id"))
    if shop_ev.get("do") == "track":
        return track(m, logf, shop_ev.get("id"))
    return research(m, logf, ev)


def research(m, logf, ev=None):
    prev, pct = m.get("best_price_eur"), float(m.get("watch_pct") or 0)
    lim, today = limits(), M.now().date()
    facts = pc_facts()
    step("read the PC's hardware facts", facts, kind="read")
    open_p = next((p for p in proposals(m["slug"]) if p.get("status") in ("proposed", "watching", "over_limit")), None)
    hist = (open_p or {}).get("history") or []
    sales = sales_ahead(today)
    timing = "\n".join([f"- Sales ahead: " + ("; ".join(f"{name} {d:%a %d %b %Y}" for d, name in sales) or "none in the next 4 months"),
                        "- Price history of the current proposal: " + ("; ".join(f"{h['at'][:10]} {h['total_eur']:.2f} € ({h['source']})" for h in hist[-8:]) or "none yet")])
    step("read limits, price history and the sale calendar", timing + f"\n- Limits: {json.dumps(lim)}", kind="read")
    evtext = f"\nThis run was triggered by an event: {ev['trigger']}: {ev['summary']}\n" if ev else ""
    phone = ""
    if open_p and open_p.get("app_check"):
        phone = f"\nWhat the {open_p['shop']} app on the AI phone showed for your last top pick (read-only):\n{TC.cut(open_p['app_check']['text'], 1500)}\n"  # cap: prompt
    out = M.hermes_z(PROMPT.format(date=f"{M.now():%d %b %Y}", title=m["title"], goal=m.get("goal", ""), facts=facts,
                                   cap=lim["per_purchase_eur"], month=lim["per_month_eur"], spent=spent_this_month(),
                                   shops=", ".join(lim["shops"]), timing=timing, notes=M.read_notes(m),
                                   best=f"{prev:.2f} EUR" if prev else "(first run)", event=evtext, phone=phone))
    Path(logf).write_text(out)
    best = best_price(out)
    dropped = bool(best and prev and pct and best <= prev * (1 - pct / 100))
    quiet = is_quiet(m, prev, best, ev)                          # price watch: only news is worth a message
    status, summary, rel = M.file_task_result(m, out, "price check" if quiet else "run", deliver=not quiet)
    if status == "ok" and best:
        m.update(best_price_eur=best, best_price_at=M.now().isoformat(timespec="minutes"))
        M.save_mission(m)
    if status == "ok" and dropped:
        text = f"Price drop: {prev:.2f} € → {best:.2f} € ({(1 - best / prev) * 100:.0f} % less). {summary}"
        M.event("price_drop", m["slug"], text, push=True, title=m["title"])
        M.X.telegram(f"🛒 <b>{m['title']}</b>\n{text}", M.X.links(m["slug"], rel), category="alert")
    if status == "ok":
        d = offers_json(out)
        step("offers and verdict from the report", cut(json.dumps(d, ensure_ascii=False), STORE) if d else "no Offers JSON block: no proposal this run",  # cap: store
             kind="stage", status=None if d else "failure")
        if d:
            p = propose(m, d, rel, open_p)
            app_check(m, p)
    return status, summary, rel


def is_quiet(m, prev, best, ev=None):
    """A scheduled price check that found no drop of at least the watch's percentage: kept, not sent."""
    pct = float(m.get("watch_pct") or 0)
    return bool(pct and prev and not (best and best <= prev * (1 - pct / 100)) and not ev)


def recheck(c, m, ev):
    """Check the offers again: the shopping agent's next run, or, when a task holds the agent (TSK-21), the task's next
    occurrence under the Conductor. Buying and following an order stay the agent's own runs."""
    if m.get("task"):
        import conductor as CD
        CD.fire(c, m["task"], ev)
    else:
        M.enqueue(c, m["slug"], "event", event=ev)


def propose(m, d, rel, open_p=None):
    """Turn a report's offers + verdict into a proposal (or update the open one), check the limits, notify."""
    lim = limits()
    pick = d["offers"][d["top"]]          # the agent's own top pick (its match words describe this one); from another
    v = d["verdict"]                      # shop it is a buy-it-yourself link (over_limit checks the shop first)
    if v["action"] == "wait" and v["until"] and v["until"] <= M.now().date().isoformat():
        v["until"] = (M.now().date() + dt.timedelta(days=7)).isoformat()   # a date already past would re-check every 6 h
    if v["action"] == "wait" and not v["until"]:
        bf = next((day for day, name in sales_ahead(M.now().date()) if name == "Black Friday"), None)
        v["until"] = (bf or M.now().date() + dt.timedelta(days=14)).isoformat()
    if v["action"] == "wait" and not v["target_eur"]:
        v["target_eur"] = round(pick["total_eur"] * 0.92, 2)
    same = open_p and open_p.get("url") == pick["url"]
    p = open_p if same else {"id": f"p-{uuid.uuid4().hex[:8]}", "slug": m["slug"], "mission": m["title"],
                             "created": M.now().isoformat(timespec="seconds"), "history": [], "journal": []}
    if open_p and not same:
        open_p["status"] = "superseded"
        note(open_p, f"Replaced by a new pick: {pick['product']}")
        save(open_p)
        if open_p.get("watch"):
            PW.forget(open_p["watch"])
    p.update(item=pick["product"], variant=pick["variant"], shop=pick["shop"], seller=pick["seller"], rating=pick["rating"],
             price_eur=pick["price_eur"], shipping_eur=pick["shipping_eur"], total_eur=pick["total_eur"], delivery=pick["delivery"],
             url=pick["url"], address=f"your {pick['shop']} account's default address (never changed)", why=cut(d.get("why") or "", 2000),  # cap: untrusted
             why_now=cut(d.get("why_now") or v["reason"], 2000), verdict=v, need=TC.cut(str(d.get("need") or ""), 300),  # cap: untrusted
             trend=TC.cut(str(d.get("trend") or ""), 200), price_history=TC.cut(str(d.get("price_history") or ""), 200), report=rel,  # cap: untrusted
             offers=d["offers"][:6], match=d["match"], budget_eur=num(d.get("budget_eur")), deadline=date_or_none(d.get("deadline")))
    p["history"] = (p.get("history") or []) + [{"at": M.now().isoformat(timespec="minutes"), "total_eur": pick["total_eur"], "source": "agent"}]
    p["history"] = p["history"][-60:]  # cap: rotate (the newest 60 prices, for the trend line)
    over = over_limit(pick["total_eur"], pick["shop"], lim)
    if not over and p.get("budget_eur") and pick["total_eur"] > p["budget_eur"]:
        over = f"{pick['total_eur']:.2f} € is over your budget of {p['budget_eur']:.0f} €"
    p["over"] = over or None
    p["buy_link"] = pick["url"]
    was = p.get("status")
    p["status"] = "over_limit" if over else "watching" if v["action"] == "wait" else "proposed"
    if not p.get("watch") and pick["url"].startswith("http"):
        p["watch"] = PW.watch(pick["url"], f"{m['title']}: {pick['product']}")
    if p["status"] == "proposed":
        note(p, f"Proposed: {pick['total_eur']:.2f} € at {pick['shop']} ({pick['seller']})")
    elif p["status"] == "watching":
        note(p, f"Waiting: buy at ≤ {v['target_eur']:.2f} € or on {v['until']} ({v['reason']})")
    else:
        note(p, f"Over the limits: {over}. Buy-it-yourself link only.")
    needs = set(m.get("needs") or [])
    if "gmail:read" not in needs:                     # to follow the order's mails after a purchase (granted by the owner)
        needs.add("gmail:read")
        m["needs"] = sorted(needs)
        _save_needs(m)
    save(p)
    step(f"proposal {p['id']}: {p['status']}", json.dumps({k: p.get(k) for k in ("item", "variant", "shop", "seller", "total_eur", "delivery", "verdict", "over")}, ensure_ascii=False),
         kind="propose")
    if p["status"] != was or p["status"] == "proposed":
        tell(m, p)
    return p


def _save_needs(m):
    """needs is kept in MISSION.md's front matter (save_mission leaves it out): add it there."""
    path = M.MISSIONS / m["slug"] / "MISSION.md"
    meta, body = M.split_front(path.read_text())
    meta["needs"] = m["needs"]
    M.write_front(path, meta, body)


def card_text(p):
    lines = [f"<b>{html.escape(p['item'])}</b>", html.escape(p.get("variant") or ""),
             f"{html.escape(p['shop'])} · seller {html.escape(p.get('seller') or '?')}" + (f" · ★ {html.escape(p['rating'])}" if p.get("rating") else ""),
             f"<b>{p['total_eur']:.2f} €</b> incl. shipping ({(p.get('price_eur') or 0):.2f} + {(p.get('shipping_eur') or 0):.2f})"
             + (f" · delivery {html.escape(p['delivery'])}" if p.get("delivery") else ""),
             f"To: {html.escape(p['address'])}"]
    if p.get("why"):
        lines.append(f"<i>Why this one:</i> {html.escape(p['why'])}")
    if p.get("why_now"):
        lines.append(f"<i>{'Why now' if p['status'] == 'proposed' else 'Why wait'}:</i> {html.escape(p['why_now'])}")
    return "\n".join(x for x in lines if x)


def tell(m, p):
    app = M.X.APP
    go = f"{app}/#/mission/{urllib.parse.quote(m['slug'])}?shop={p['id']}&do="
    if p["status"] == "proposed":
        head = "🛒 <b>Purchase proposal</b>: buy now?"
        buttons = [[("✅ Approve purchase", go + "approve"), ("⏸ Not now", go + "not_now")], [("✏️ Change", go + "change"), ("🔍 Details", go)]]
        M.event("shop_proposal", m["slug"], f"Purchase proposal: {p['item']} for {p['total_eur']:.2f} € at {p['shop']}: approve or not", push=True, title=m["title"])
    elif p["status"] == "watching":
        v = p["verdict"]
        head = f"⏳ <b>Wait</b>: buy at ≤ {v['target_eur']:.2f} € or on {v['until']}. {html.escape(v['reason'])}"
        buttons = [[("🔍 Details", go), ("✏️ Change", go + "change")]]
        M.event("shop_wait", m["slug"], f"Waiting to buy {p['item']}: at ≤ {v['target_eur']:.2f} € or on {v['until']}", title=m["title"])
    elif p["status"] == "over_limit":
        head = f"🛒 <b>Over your limits</b>: {html.escape(p['over'])}. Buy it yourself if you want it."
        buttons = [[("🛒 Buy it yourself", p["buy_link"])] if p.get("buy_link", "").startswith("http") else [], [("🔍 Details", go)]]
        M.event("shop_over", m["slug"], f"{p['item']}: {p['over']}: buy-it-yourself link only", push=True, title=m["title"])
    else:
        return
    M.X.telegram(f"{head}\n{card_text(p)}", [b for b in buttons if b], category="approval")
    step("told the owner (Telegram + Mission Control)", p["status"], kind="stage")


def app_check(m, p):
    """Look the pick up in the shop's app on the AI phone (read-only search, no taps), as evidence on the card. The run
    parks while the phone asks the owner, so other missions run meanwhile."""
    pkg = SHOP_APPS.get(p.get("shop") or "")
    try:
        st = json.loads((PHONE / "state.json").read_text())
    except (OSError, ValueError):
        st = {}
    why = ("no app for this shop on the AI phone" if not pkg else f"the proposal is {p['status']}" if p["status"] not in ("proposed", "watching")
           else "the AI phone is stopped" if (PHONE / "STOP").exists() else "the AI phone is not connected" if not st.get("connected") else "")
    if why:
        step("AI phone app check skipped", why, kind="stage")
        return
    words = " ".join((p.get("match") or {}).get("item") or [p["item"]])[:80]  # cap: id
    rid = uuid.uuid4().hex[:16]
    (PHONE / "research").mkdir(exist_ok=True)
    to_phone(rid, {"do": "shop_look", "id": rid, "pkg": pkg, "query": words, "expires": time.time() + 600,
                    "url": f"https://www.{p['shop']}/s?k={urllib.parse.quote_plus(words)}"})
    res = PHONE / "research" / f"{rid}.json"
    if not M.park(f"the AI phone ({p['shop']} app search: {words})", res.exists, timeout=660, every=5):
        step("AI phone app check: no answer", "the owner did not allow it in time, or the phone was busy", kind="stage")
        return
    r = json.loads(res.read_text())
    res.unlink(missing_ok=True)
    if r.get("error"):
        step("AI phone app check refused", r["error"], kind="stage", status="failure")
        return
    lines = r.get("lines") or []
    price = next((PW.eur(a or b) for ln in lines for a, b in PW.PRICE.findall(ln)), None)
    p["app_check"] = {"at": M.now().isoformat(timespec="minutes"), "price_eur": price, "shot": r.get("shot"),
                      "text": "\n".join(TC.more(lines, 60, "more lines")), "found": all(w.lower() in " ".join(lines).lower() for w in (p.get("match") or {}).get("item") or [])}  # cap: untrusted
    note(p, f"Checked in the {p['shop']} app: " + (f"first price shown {price:.2f} €" if price else "no price read"))
    save(p)
    step("AI phone app check", cut(p["app_check"]["text"], STORE), kind="read")  # cap: store


# ---------- the owner's decisions (Mission Control only) ----------
def handle(req, c):
    if req.get("source") != "owner":
        raise ValueError("only the owner decides this, in Mission Control on his own device")
    if req["action"] == "shop_limits":
        return set_limits(req)
    p = load(req.get("id"))
    if not p:
        raise ValueError("no such proposal")
    m = M.load_missions().get(p["slug"])
    d, by = req.get("decision"), req.get("by") or "owner"
    if d == "approve":
        return approve(p, m, by, c)
    if d == "not_now":
        if p["status"] not in ("proposed", "watching", "over_limit", "needs_owner"):
            raise ValueError(f"the proposal is {p['status']}")
        until = (M.now().date() + dt.timedelta(days=14)).isoformat()
        p.update(status="watching", verdict={**(p.get("verdict") or {}), "action": "wait", "target_eur": round(p["total_eur"] * 0.95, 2),
                                             "until": until, "reason": "The owner said not now"})
        note(p, f"Not now ({by}): watching for ≤ {p['verdict']['target_eur']:.2f} € until {until}")
        save(p)
        M.event("shop_wait", p["slug"], f"Not now: watching {p['item']} for a lower price", title=p.get("mission", ""))
        return {"status": p["status"]}
    if d == "change":
        txt = limit(str(req.get("note") or "").strip(), 2000, "the note")
        if not txt:
            raise ValueError("say what to change")
        p["status"] = "superseded"
        note(p, f"Change requested ({by}): {txt}")
        save(p)
        if p.get("watch"):
            PW.forget(p["watch"])
        M.enqueue(c, p["slug"], "event", event={"trigger": "The owner asked for a change", "summary": txt})
        return {"status": "superseded", "rerun": True}
    raise ValueError("decision: approve, not_now or change")


def approve(p, m, by, c):
    lim = limits()
    if p["status"] != "proposed":
        raise ValueError(f"the proposal is {p['status']}, not waiting for approval")
    if not m or m.get("status") != "active":
        raise ValueError("the shopping agent is not active")
    if (over := over_limit(p["total_eur"], p["shop"], lim)):
        p.update(status="over_limit", over=over)
        save(p)
        raise ValueError(f"over the limits: {over}")
    if not lim["address_words"]:
        raise ValueError("set the delivery-address check first (shopping agent → Settings → Limits: your postcode)")
    if not (p.get("match") or {}).get("item"):
        raise ValueError("the proposal has no words to check the item on the final screen: ask for a change")
    if p["shop"] not in SHOP_APPS:
        raise ValueError(f"no shop app for {p['shop']} on the AI phone: buy it yourself")
    ceiling = round(min(p["total_eur"] * 1.03 + 1, lim["per_purchase_eur"]), 2)
    pa = {"id": p["id"], "shop": p["shop"], "pkg": SHOP_APPS[p["shop"]], "url": p["url"], "item": p["item"],
          "item_words": p["match"]["item"], "variant_words": p["match"].get("variant") or [], "seller_words": p["match"].get("seller") or [],
          "address_words": lim["address_words"], "max_total_eur": ceiling, "approved_by": by,
          "approved_at": M.now().isoformat(timespec="seconds"), "expires": time.time() + 45 * 60, "used": False}
    save_json(PHONE / "purchases" / f"{p['id']}.json", pa)
    p.update(status="approved", approved_by=by, approved_at=pa["approved_at"], ceiling_eur=ceiling)
    note(p, f"Approved by {by}: ceiling {ceiling:.2f} € incl. shipping; the AI phone buys it now")
    save(p)
    M.enqueue(c, p["slug"], "event", event={"trigger": "purchase approved", "summary": f"{p['item']} for ≤ {ceiling:.2f} €", "shop": {"do": "buy", "id": p["id"]}})
    M.event("shop_approved", p["slug"], f"Purchase approved: {p['item']} for ≤ {ceiling:.2f} €", title=p.get("mission", ""))
    return {"status": "approved", "ceiling_eur": ceiling}


def set_limits(req):
    d = limits()
    for k in ("per_purchase_eur", "per_month_eur"):
        if k in req:
            v = float(req[k])
            if not 0 < v <= 5000:
                raise ValueError(f"{k}: between 1 and 5000 €")
            d[k] = round(v, 2)
    if "shops" in req:
        shops = [str(s).strip().lower().removeprefix("www.") for s in req["shops"] if str(s).strip()]
        if not all(re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", s) for s in shops):
            raise ValueError("shops: domains like amazon.de")
        d["shops"] = shops[:10]
    if "address_words" in req:
        words = [limit(str(w).strip(), 100, "an address word") for w in req["address_words"] if str(w).strip()]
        d["address_words"] = words[:4]
    save_json(HOME / "limits.json", d)
    M.event("shop_limits", "", f"Shopping limits: {d['per_purchase_eur']:.0f} € per purchase, {d['per_month_eur']:.0f} € per month, "
                               f"shops {', '.join(d['shops'])}", title="Shopping")
    return {"limits": d}


# ---------- buying (after the owner's approval) ----------
def hermes_main(prompt, timeout=1200):
    """Hermes' main profile (vk-main: it has the AI phone's tools), tied to this run's runtime record."""
    P.record(prompt)                                  # MEM-11: the run records the prompt's version
    t0 = time.time()
    step("Hermes (main profile, phone tools) starts", prompt)
    try:
        p = subprocess.run(["docker", "exec", "-u", "hermes", *M.RTM.env_args(), M.HERMES, "timeout", str(timeout), "hermes", "-z", prompt],
                           capture_output=True, text=True, timeout=timeout + 60)
        step(f"Hermes (main profile) finished after {time.time() - t0:.0f} s", tail(p.stdout, STORE), status="failure" if p.returncode else None)  # cap: store
        return p.stdout
    except subprocess.TimeoutExpired:
        step("Hermes (main profile) timed out", f"after {timeout} s", kind="error", status="failure")
        return ""


def buy(m, logf, pid):
    p = load(pid)
    pa_file, res_file = PHONE / "purchases" / f"{pid}.json", PHONE / "purchases" / f"{pid}.result.json"
    if not p or p.get("status") != "approved" or not pa_file.exists():
        return "failed", "No approved proposal to buy (it was answered, expired or changed).", ""
    pa = json.loads(pa_file.read_text())
    if time.time() > pa["expires"]:
        p["status"] = "needs_owner"
        note(p, "The approval expired before the phone got to it: approve again")
        save(p)
        pa_file.unlink(missing_ok=True)
        return "failed", "The purchase approval expired.", ""
    p["status"] = "buying"
    note(p, "Buying on the AI phone")
    save(p)
    step(f"purchase {pid}: approved by {pa['approved_by']}, ceiling {pa['max_total_eur']:.2f} €", json.dumps(pa, ensure_ascii=False), kind="read")
    to_phone(uuid.uuid4().hex[:16], {"do": "shop_open", "purchase": pid})
    M.park("the AI phone to open the product in the shop app", lambda: not any((PHONE / "control").glob("*.json")), timeout=60, every=2)
    out = hermes_main(BUY_PROMPT.format(item=p["item"], variant=p.get("variant") or "-", shop=p["shop"], seller=p.get("seller") or "?",
                                        ceiling=pa["max_total_eur"]))
    Path(logf).write_text(out)
    r = {}
    if res_file.exists():
        r = json.loads(res_file.read_text())
        res_file.unlink(missing_ok=True)
    pa_file.unlink(missing_ok=True)                        # the approval covers this one run only
    shot = f"{M.X.APP}/#/phone"
    if r.get("status") in ("placed", "tapped"):          # tapped: the final tap happened, the confirmation was not read
        order = r.get("order") or (re.search(r"ORDER:\s*([0-9-]{8,})", out) or [None, None])[1]
        p.update(status="bought", bought_at=M.now().isoformat(timespec="seconds"), order=order, order_shot=r.get("shot"),
                 paid_eur=r.get("total_eur"), track_next=time.time() + 1800)
        note(p, f"Ordered: order {order or '(number not read)'}, total {r.get('total_eur') or '?'} €. Following the mails until delivered.")
        save(p)
        if p.get("watch"):
            PW.forget(p["watch"])
        text = f"✅ <b>Ordered</b>: {html.escape(p['item'])}\n{(r.get('total_eur') or p['total_eur']):.2f} € at {html.escape(p['shop'])}" \
               f"{', order ' + html.escape(order) if order else ''}\nI follow the confirmation and shipping mails until it arrives."
        M.X.telegram(text, [[("🔍 Order", f"{M.X.APP}/#/mission/{urllib.parse.quote(m['slug'])}?shop={pid}")]], category="alert")
        M.event("shop_bought", m["slug"], f"Ordered {p['item']} ({order or 'order number not read'})", push=True, title=m["title"])
        return "ok", f"Ordered {p['item']} for {(r.get('total_eur') or p['total_eur']):.2f} € (order {order or '?'}).", ""
    reason = r.get("reason") or "the agent stopped before the final screen: " + ((out.strip().splitlines() or ["no answer"])[-1])
    p.update(status="needs_owner", stopped_reason=reason, stopped_shot=r.get("shot"))
    note(p, f"Stopped before buying: {reason}")
    save(p)
    M.X.telegram(f"✋ <b>Stopped before buying</b> {html.escape(p['item'])}\n{html.escape(reason)}\nNothing was bought. Finish it yourself "
                 "in the app, or approve again after a change.", [[("📱 Phone page (screenshot)", shot), ("🛒 Buy it yourself", p["url"])]], category="alert")
    M.event("shop_stopped", m["slug"], f"Stopped before buying {p['item']}: {reason}", push=True, title=m["title"])
    return "failed", f"Stopped before buying: {reason}", ""


# ---------- tracking (Gmail, read grant) and price watching ----------
def granted(scope="gmail:read"):
    conn, sc = scope.split(":")
    try:
        g = json.loads((CONN / "grants.json").read_text()).get(conn, {}).get(sc)
        return bool(g and g.get("until", 0) > time.time())
    except (OSError, ValueError):
        return False


def track(m, logf, pid):
    p = load(pid)
    if not p or p.get("status") not in ("bought", "shipped"):
        return "failed", "Nothing to follow.", ""
    out = M.hermes_z(TRACK_PROMPT.format(item=p["item"], shop=p["shop"], date=(p.get("bought_at") or "")[:10], order=p.get("order") or "(unknown)"))
    Path(logf).write_text(out)
    mt = re.search(r"\{.*\}", out, re.S)
    try:
        d = json.loads(mt.group(0)) if mt else {}
    except ValueError:
        d = {}
    p["track_next"] = time.time() + TRACK_EVERY
    st = d.get("status")
    if st in ("shipped", "out_for_delivery", "delivered", "problem") or d.get("confirmed"):
        old = p.get("shipping") or {}
        p["shipping"] = {k: d.get(k) for k in ("confirmed", "status", "carrier", "tracking", "eta", "evidence")}
        if st != old.get("status"):
            note(p, f"Mail: {st or 'confirmed'}" + (f", {d.get('carrier')} {d.get('tracking') or ''}" if d.get("carrier") else "")
                 + (f", expected {d.get('eta')}" if d.get("eta") else "") + f" ({d.get('evidence') or ''})")
            M.X.telegram(f"📦 <b>{html.escape(p['item'])}</b>: {html.escape(st or 'order confirmed')}"
                         + (f"\n{html.escape(str(d.get('carrier')))} {html.escape(str(d.get('tracking') or ''))}" if d.get("carrier") else "")
                         + (f"\nexpected {html.escape(str(d.get('eta')))}" if d.get("eta") else ""), [], category="alert")
        if st == "shipped":
            p["status"] = "shipped"
        if st == "delivered":
            p.update(status="delivered", delivered_at=M.now().isoformat(timespec="seconds"))
            M.event("shop_delivered", m["slug"], f"Delivered: {p['item']}", push=True, title=m["title"])
    save(p)
    return "ok", f"{p['item']}: {p.get('shipping', {}).get('status') or 'no mail about it yet'}", ""


_ticks = {}


def tick(c):
    """Called every minute by the runner's watcher: price readings for waiting proposals (propose again when the target
    or the date is reached) and tracking runs for bought orders (with the Gmail read grant)."""
    t = time.time()
    missions = None
    for p in proposals():
        key = p["id"]
        if p.get("status") in ("watching", "over_limit") and t - max(_ticks.get(key, 0), p.get("watched_at") or 0) > WATCH_EVERY:
            _ticks[key] = t                                   # also on the proposal: a runner restart must not re-check at once
            p["watched_at"] = t
            save(p)
            missions = missions or M.load_missions()
            m = missions.get(p["slug"])
            if not m or m.get("status") != "active":
                continue
            r = PW.reading(p["watch"]) if p.get("watch") else None
            if r and r.get("price"):
                total = round(r["price"] + (p.get("shipping_eur") or 0), 2)
                p["history"] = (p.get("history") or [])[-59:] + [{"at": M.now().isoformat(timespec="minutes"), "total_eur": total, "source": "pricewatch"}]  # cap: list
                save(p)
                v = p.get("verdict") or {}
                caps = [x for x in (v.get("target_eur"), limits()["per_purchase_eur"] if p["status"] == "over_limit" else None) if x]
                if caps and total > min(caps):
                    p.pop("alerted_total", None)                  # above the target again: the next drop is news
                    save(p)
                if caps and total <= min(caps) and (p.get("alerted_total") is None or total < p["alerted_total"] - 0.005):
                    p["alerted_total"] = total                    # told once: the same price does not propose again (SN-18)
                    note(p, f"Target reached: {total:.2f} € (≤ {min(caps):.2f} €): proposing again")
                    recheck(c, m, {"trigger": "price target reached", "summary": f"{p['item']} now {total:.2f} € at {p['shop']}"})
                    save(p)
                    continue
            until = (p.get("verdict") or {}).get("until")
            if until and M.now().date().isoformat() >= until:
                note(p, f"Waited until {until}: checking the offers again")
                save(p)
                recheck(c, m, {"trigger": "waited until the planned date", "summary": f"re-check {p['item']}"})
        elif p.get("status") in ("bought", "shipped") and t >= (p.get("track_next") or 0) and granted():
            if (M.now() - dt.datetime.fromisoformat(p.get("bought_at") or M.now().isoformat())).days > 30:
                p["status"] = "delivered"
                note(p, "Stopped following after 30 days")
                save(p)
                continue
            p["track_next"] = t + TRACK_EVERY
            save(p)
            M.enqueue(c, p["slug"], "event", event={"trigger": "follow the order", "summary": f"mails about {p['item']}", "shop": {"do": "track", "id": p["id"]}})

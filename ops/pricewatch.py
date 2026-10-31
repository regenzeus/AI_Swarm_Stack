"""The price watch for shopping agents: a small client for changedetection.io (images/pricewatch, Apache-2.0).

changedetection.io runs sealed (its own network, an egress firewall against private/LAN/Tailscale ranges, no
notifications configured: no Telegram, no apprise) and re-reads the offer pages of open proposals with a plain HTTP
fetcher (no browser). The runner (ops/shopping.py) reads prices through its API on 127.0.0.1:8095 and reports
itself. Shops that block plain fetches (Amazon, idealo, geizhals) simply give no reading: the agent's own re-check in
its next run covers those. Every call here may fail; callers treat None / [] as "not readable".
"""
import json
import re
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8095/api/v1"
DATA = Path("/srv/ai/pricewatch")
TAG = "shopping"
EXAMPLES = ("news.ycombinator.com", "changedetection.io/CHANGELOG")     # the demo watches a fresh datastore starts with
PRICE = re.compile(r"(?:€\s*(\d{1,5}(?:[.,]\d{3})*(?:[.,]\d{2})?)|(\d{1,5}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*(?:€|EUR))")


def key():
    for name in ("changedetection.json", "url-watches.json"):
        try:
            return json.loads((DATA / name).read_text())["settings"]["application"]["api_access_token"]
        except (OSError, ValueError, KeyError):
            continue
    return ""


def _call(method, path, body=None, timeout=15):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"x-api-key": key(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode(errors="replace")
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def up():
    try:
        return "version" in _call("GET", "/systeminfo", timeout=5)
    except Exception:
        return False


def eur(text):
    """'1.234,56' / '89,90' / '89.90' -> float."""
    v = text.strip().rstrip(".,")
    if "," in v and "." in v:
        v = v.replace(".", "").replace(",", ".") if v.rfind(",") > v.rfind(".") else v.replace(",", "")
    elif "," in v:
        v = v.replace(".", "").replace(",", ".") if re.search(r",\d{2}$", v) else v.replace(",", "")
    try:
        return round(float(v), 2)
    except ValueError:
        return None


def tidy():
    """Remove the demo watches of a fresh datastore (they would fetch news sites for nothing)."""
    try:
        for uid, w in (_call("GET", "/watch") or {}).items():
            if any(x in (w.get("url") or "") for x in EXAMPLES):
                _call("DELETE", f"/watch/{uid}")
    except Exception:
        pass


def watch(url, title):
    """Start watching an offer page; returns its uuid or None. restock_diff reads price and stock from the page's
    structured data (schema.org Product/Offer), which most shops embed."""
    try:
        tidy()
        r = _call("POST", "/watch", {"url": url, "title": title[:120], "processor": "restock_diff", "tag": TAG,  # cap: api
                                     "time_between_check": {"hours": 6}})
        return r.get("uuid") if isinstance(r, dict) else None
    except Exception:
        return None


def forget(uid):
    try:
        _call("DELETE", f"/watch/{uid}")
    except Exception:
        pass


def reading(uid):
    """What it last read: {"price": float|None, "in_stock": bool|None, "checked": epoch, "error": str|None}, or None."""
    try:
        w = _call("GET", f"/watch/{uid}")
    except Exception:
        return None
    if not isinstance(w, dict):
        return None
    out = {"price": None, "in_stock": None, "checked": w.get("last_checked") or 0, "error": w.get("last_error") or None}
    rs = w.get("restock") or {}
    if isinstance(rs, dict):
        p = rs.get("price")
        out["price"] = round(float(p), 2) if isinstance(p, (int, float)) or (isinstance(p, str) and p.replace(".", "", 1).isdigit()) else None
        out["in_stock"] = rs.get("in_stock")
    if out["price"] is None and w.get("history_n"):
        try:
            snap = _call("GET", f"/watch/{uid}/history/latest")
            out["price"] = snapshot_price(snap if isinstance(snap, str) else json.dumps(snap))
        except Exception:
            pass
    return out


def snapshot_price(text):
    """The price in a restock snapshot ("Price: 89.9" / "In stock ... 89,90 €")."""
    m = re.search(r"price\W{0,3}\s*([\d.,]+)", text or "", re.I)
    if m and (v := eur(m.group(1))):
        return v
    vals = [eur(a or b) for a, b in PRICE.findall(text or "")]
    vals = [v for v in vals if v]
    return vals[0] if vals else None

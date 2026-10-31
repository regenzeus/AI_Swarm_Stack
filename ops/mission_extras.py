"""Mission Control extras, used by ops/missions.py (which sets M to itself):
  event triggers   new SEC filings, big price moves, news on a query -> an event run of the mission
  deep research    plan -> one agent run per step (vault + web research) -> synthesis, steps shown live
  mission wikis    after every result: the model updates the mission's LLM wiki (entities, concepts, projects, events)
  delivery         Telegram with buttons into the app, designed e-mail (needs GMAIL_* + MAIL_TO in the secrets)
All web access happens in the desk container (SSRF-guarded "webonly" network); this module only talks to LiteLLM,
Telegram's API and Gmail's SMTP.
"""
import datetime as dt, hashlib, html, json, os, re, smtplib, subprocess, time, urllib.parse, urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from textcap import cut, tail                    # visible caps and input limits (AGENTS.md, truncation)
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md

M = None                      # the missions module
APP = os.environ.get("MC_URL", "https://pc.example.ts.net:8447")
FORMS = ["8-K", "6-K", "10-Q", "10-K", "20-F", "40-F", "S-1", "S-3", "F-10", "424B5", "SC 13D", "SC 13G", "4", "DEF 14A", "425"]
DEFAULT_FORMS = ["8-K", "6-K", "10-Q", "10-K", "20-F", "40-F", "S-3", "424B5", "SC 13D", "425"]
WATCH_EVERY = 600             # seconds between event checks


# ---------- delivery ----------
def telegram(text, buttons=()):
    """HTML message with URL buttons into Mission Control (callback buttons would need Hermes' bot loop)."""
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), (os.environ.get("TELEGRAM_ALLOWED_USERS") or "").split(",")[0]
    if tok and chat:
        body = {"chat_id": chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}  # cap: api
        if buttons:
            body["reply_markup"] = {"inline_keyboard": [[{"text": t, "url": u} for t, u in row] for row in buttons]}
        try:
            req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            if json.load(urllib.request.urlopen(req, timeout=30)).get("ok"):
                return True
        except Exception as e:
            M.log(f"telegram failed ({type(e).__name__}), falling back to plain text")
    M.notify(re.sub(r"<[^>]+>", "", html.unescape(text)))
    return False


def links(slug, path=None):
    row = []
    if path:
        row.append(("📄 Open report", f"{APP}/#/read?path={urllib.parse.quote(path)}&m={slug}"))
    row.append(("🎯 Mission", f"{APP}/#/mission/{slug}"))
    return [row, [("💬 Ask about it", f"{APP}/#/chat?mission={slug}"), ("▶ Run again", f"{APP}/#/mission/{slug}?do=run")]]


def email_ready():
    return all(os.environ.get(k) for k in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "MAIL_TO"))


def email(subject, markdown_text, kicker, url):
    if not email_ready():
        return False
    p = subprocess.run(["docker", "run", "--rm", "-i", "--network", "none", "aistack/desk:1", "--email"],
                       input=json.dumps({"markdown": markdown_text, "kicker": kicker, "url": url}), capture_output=True,
                       text=True, timeout=120)
    if p.returncode:
        M.log("email render failed:", tail(p.stderr, 4000))  # cap: store
        return False
    d = json.loads(p.stdout)
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, f"AI Stack <{os.environ['GMAIL_ADDRESS']}>", os.environ["MAIL_TO"]
    msg.attach(MIMEText(d["text"], "plain", "utf-8"))
    msg.attach(MIMEText(d["html"], "html", "utf-8"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
            s.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
            s.send_message(msg)
        return True
    except Exception as e:
        M.log(f"email failed: {type(e).__name__}: {str(e)}")
        M.event("error", "", f"E-mail could not be sent ({type(e).__name__})", push=True)
        return False


def briefing_empty(text):
    """A briefing the desk chose no news for (its front matter's stats say chosen: 0): prices alone are no delivery."""
    st = re.search(r"^stats: (\{.*\})$", text, re.M)
    try:
        return bool(st) and json.loads(st.group(1)).get("chosen", 1) == 0
    except ValueError:
        return False


def quiet_file():
    return M.HOME / "quiet-runs.json"           # per mission, the dates of runs that found nothing new (FND-60)


def deliver(m, title, short, path, kicker, markdown_text=None, empty=False):
    """Telegram and e-mail for a finished run. An empty run (a briefing with no news chosen) stays in the app: its date
    is kept and named in the kicker of the next full delivery instead (MIS-15, FND-60)."""
    d = m.get("deliver") or []
    f = quiet_file()
    try:
        quiet = json.loads(f.read_text())
    except (OSError, ValueError):
        quiet = {}
    days = quiet.pop(m["slug"], [])
    if empty:
        if "telegram" in d or "email" in d:
            M.log(f"{m['slug']}: nothing new, kept in the app (not sent by Telegram or e-mail)")
        quiet[m["slug"]] = days + [f"{M.now():%d %b}"]
        f.write_text(json.dumps(quiet))
        return False
    if days:
        kicker += f" · nothing new on {', '.join(days)}"
        f.write_text(json.dumps(quiet))
    if "telegram" in d:
        telegram(f"<b>{html.escape(title)}</b>\n<i>{html.escape(kicker)}</i>\n\n{html.escape(short)}", links(m["slug"], path))
    if "email" in d and markdown_text:
        email(f"{m['title']}: {title}", markdown_text, kicker, f"{APP}/#/read?path={urllib.parse.quote(path)}&m={m['slug']}")
    return True


# ---------- triggers ----------
def clean_triggers(raw):
    """Validate triggers from the app or chat; raises ValueError with a readable reason."""
    out = []
    for t in (raw or [])[:10]:
        k = t.get("type")
        if k == "sec_filing":
            tick = [x.strip().upper() for x in t.get("tickers", []) if re.fullmatch(r"[A-Za-z.\-]{1,10}", str(x).strip())][:10]
            forms = [f for f in t.get("forms") or DEFAULT_FORMS if f in FORMS]
            if not tick:
                raise ValueError("SEC filing trigger needs at least one US ticker")
            out.append({"type": k, "tickers": tick, "forms": forms})
        elif k == "price_move":
            sym = str(t.get("symbol", "")).strip()
            pct = float(t.get("pct", 5))
            if not re.fullmatch(r"[A-Za-z0-9.\-=^]{1,15}", sym) or not 1 <= pct <= 50:
                raise ValueError("price trigger needs a Yahoo symbol and a move of 1-50 %")
            out.append({"type": k, "symbol": sym.upper(), "pct": pct})
        elif k == "news":
            q = str(t.get("query", "")).strip()[:120]  # cap: api
            if len(q) < 3:
                raise ValueError("news trigger needs a search query")
            out.append({"type": k, "query": q})
        else:
            raise ValueError(f"unknown trigger type '{k}'")
    return out


def trigger_text(t):
    if t["type"] == "sec_filing":
        return f"New SEC filing by {', '.join(t['tickers'])}"
    if t["type"] == "price_move":
        return f"{t['symbol']} moves ±{t['pct']:g} % in a day"
    return f"News about “{t['query']}”"


_last_watch = {"t": 0}


def check_events(missions, c):
    """Every WATCH_EVERY seconds: fetch filings/prices/news for all active triggers, fire new events as runs.
    The first look at a trigger only records what exists (no flood of old items)."""
    if time.time() - _last_watch["t"] < WATCH_EVERY:
        return
    _last_watch["t"] = time.time()
    act = [(m, t) for m in missions.values() if m.get("status") == "active" for t in m.get("triggers") or []]
    if not act:
        return
    spec = {"sec": sorted({x for _, t in act if t["type"] == "sec_filing" for x in t["tickers"]}),
            "prices": sorted({t["symbol"] for _, t in act if t["type"] == "price_move"}),
            "news": sorted({t["query"] for _, t in act if t["type"] == "news"})}
    p = subprocess.run(["docker", "run", "--rm", "-i", "--network", "aistack_webonly", "-e", "SEC_CONTACT", "aistack/desk:1", "--watch"],
                       input=json.dumps(spec), capture_output=True, text=True, timeout=600)
    if p.returncode:
        M.log("watch failed:", tail(p.stderr, 4000))  # cap: store
        return
    seen_now = json.loads(p.stdout)
    today = dt.date.today().isoformat()
    for m, t in act:
        tid = hashlib.sha1(json.dumps(t, sort_keys=True).encode()).hexdigest()[:10]
        first = not c.execute("select 1 from seen_events where key=?", (f"{m['slug']}|init|{tid}",)).fetchone()
        fire = []
        if t["type"] == "sec_filing":
            for tick in t["tickers"]:
                for f in seen_now["sec"].get(tick, []):
                    k = f"{m['slug']}|sec|{f['id']}"
                    if f["form"] in t["forms"] and not seen(c, k):
                        mark(c, k)
                        fire.append(f)
            ev = fire and {"kind": "sec_filing", "summary": "; ".join(f["title"][:120] for f in fire[:3]), "items": fire[:4]}  # cap: preview
        elif t["type"] == "price_move":
            q = seen_now["prices"].get(t["symbol"])
            ev = None
            if q and q.get("prev") and abs(q["pct"]) >= t["pct"] and q["date"] >= (dt.date.today() - dt.timedelta(days=3)).isoformat():
                k = f"{m['slug']}|price|{t['symbol']}|{q['date']}|{'up' if q['pct'] > 0 else 'down'}"
                if not seen(c, k):
                    mark(c, k)
                    ev = {"kind": "price_move", "items": [],
                          "summary": f"{t['symbol']} {'up' if q['pct'] > 0 else 'down'} {abs(q['pct']):.1f} % to {q['last']:.2f} {q['currency']} "
                                     f"(previous close {q['prev']:.2f}, {q['date']})"}
        else:
            for n in seen_now["news"].get(t["query"], []):
                k = f"{m['slug']}|news|{n['id']}"
                if not seen(c, k):
                    mark(c, k)
                    fire.append(n)
            ev = fire and {"kind": "news", "summary": f"{len(fire)} new article(s) about “{t['query']}”: " + "; ".join(n["title"][:100] for n in fire[:3]),  # cap: preview
                           "items": fire[:4]}
        if first:
            mark(c, f"{m['slug']}|init|{tid}")
            continue                         # baseline only
        if ev and ev.get("summary"):
            ev["trigger"] = trigger_text(t)
            M.enqueue(c, m["slug"], "event", event=ev)
            M.event("triggered", m["slug"], f"{ev['trigger']}: {ev['summary']}", push=True, title=m["title"])
    c.commit()


def seen(c, k):
    return c.execute("select 1 from seen_events where key=?", (k,)).fetchone() is not None


def mark(c, k):
    c.execute("insert or ignore into seen_events values (?, ?)", (k, M.now().isoformat(timespec="seconds")))


def run_alert(m, ev, logf):
    """Event on a briefing mission: a short alert written by the desk from the event's sources."""
    topic = m.get("topic", m["slug"])
    p = subprocess.run(["docker", "run", "--rm", "-i", "--network", "aistack_webonly", "-e", "VK_DESK", "-e", "SEC_CONTACT",
                        "-v", f"/srv/vault/topics/{topic}:/topic:ro", "-v", f"{M.OPS.parent / 'prompts'}:/prompts:ro", "aistack/desk:1", "--alert"],
                       input=json.dumps({"event": ev}), capture_output=True, text=True, timeout=900)
    open(logf, "w").write(p.stderr)
    if p.returncode or not p.stdout.strip():
        return "failed", (p.stderr.strip().splitlines() or ["alert failed"])[-1], ""
    a = json.loads(p.stdout)
    if a.get("prompt"):                          # MEM-11: the alert's prompt version in the run record, its call a replay case
        M.RTM.stage("Prompt", a["prompt"])
    if a.get("case"):
        P.add_case(**a["case"])
    a.pop("prompt", None), a.pop("case", None)
    t = M.now()
    rel = f"topics/{topic}/alerts/{t:%Y}/{t:%m}/{t:%Y-%m-%d-%H%M}-{ev['kind']}.md"
    M.write_front(M.VAULT / rel, {"topic": topic, "date": t.isoformat(timespec="minutes"), "type": "alert",
                                  "trigger": ev.get("trigger", ev["kind"])}, a["markdown"])
    M.vault_commit([f"topics/{topic}/alerts"], f"desk: {topic} alert {t:%F %H:%M}")
    M.reindex()
    deliver(m, a.get("title") or ev["summary"][:80], a.get("short", ""), rel, f"Alert · {ev.get('trigger', '')}", a["markdown"])  # cap: id
    return "ok", a.get("short") or a.get("title", "Alert"), rel


# ---------- deep research ----------
PLAN = P.text("mission", "DEEP_PLAN")

STEP = P.text("mission", "DEEP_STEP")

SYNTH = P.text("mission", "DEEP_SYNTH")


def run_deep(m, logf, rid, c, ev=None):
    goal, notes = m.get("goal", ""), M.read_notes(m)
    evtext = f"Triggered by an event: {ev['trigger']}: {ev['summary']}" if ev else ""
    plan = M.ask_json(PLAN.format(title=m["title"], goal=goal, notes=notes[:3000], event=evtext), os.environ["VK_MISSION"])  # cap: prompt
    steps = [{"title": s.get("title", "")[:60], "question": s.get("question", "")[:500], "status": "pending"}  # cap: untrusted
             for s in plan.get("steps", [])[:5] if s.get("question")]
    if not steps:
        return "failed", "planning failed", ""
    save = lambda: (c.execute("update runs set steps=? where id=?", (json.dumps(steps), rid)), c.commit())
    save()
    found = []
    with open(logf, "w") as f:
        for s in steps:
            s["status"] = "running"
            save()
            f.write(f"## {s['title']}\n{s['question']}\n")
            f.flush()
            out = M.hermes_z(STEP.format(date=f"{M.now():%d %b %Y}", title=m["title"], goal=goal, step_title=s["title"],
                                         question=s["question"], earlier="\n\n".join(found)[-6000:] or "(none yet)"), timeout=900)  # cap: prompt
            f.write(out + "\n\n")
            f.flush()
            s["status"] = "done" if out.strip() else "failed"
            s["finding"] = cut(out.strip(), 4000)  # cap: store
            found.append(f"### {s['title']}\n{out.strip()[:2500]}")  # cap: prompt
            save()
    if not any(s["status"] == "done" for s in steps):
        return "failed", "no step produced a finding", ""
    final = M.ask_text(SYNTH.format(date=f"{M.now():%d %b %Y}", title=m["title"], goal=goal, notes=notes[:3000], event=evtext,  # cap: prompt
                                    findings="\n\n".join(found)), os.environ["VK_MISSION"])
    return M.file_task_result(m, final, kind="deep research")


# ---------- mission wikis ----------
WIKI = P.text("mission", "WIKI")


KIND = {"entities": "entity", "concepts": "concept", "projects": "project", "events": "event"}


def wiki_root(m):
    return f"topics/{m.get('topic', m['slug'])}/wiki" if m["type"] == "briefing" else f"missions/{m['slug']}/wiki"


def wiki_pages(root):
    out = []
    for p in sorted((M.VAULT / root).rglob("*.md")):
        if p.name == "index.md":
            continue
        meta, body = M.split_front(p.read_text(errors="replace"))
        if meta.get("merged_into"):              # the Librarian merged it into another page: a stub, not a page
            continue
        out.append({"path": str(p.relative_to(M.VAULT / root))[:-3], "title": meta.get("title") or p.stem,
                    "summary": meta.get("summary", ""), "aliases": meta.get("aliases") or [], "type": meta.get("type", ""),
                    "body": body, "meta": meta})
    return out


def compile_wiki(m, source_rel, text, key):
    if m.get("wiki_off"):                        # the owner deleted this mission's wiki (ops/wikis.py)
        return 0
    root = wiki_root(m)
    pages = wiki_pages(root)
    low = text.lower()
    touched = [p for p in pages if any(n and n.lower() in low for n in [p["title"], *p["aliases"]])][:6]
    index = "\n".join(f"- [[{p['path']}]] {p['title']}: {p['summary']}" for p in pages) or "(empty: this is the first result)"
    src = source_rel[:-3] if source_rel.endswith(".md") else source_rel
    try:                                         # MEM-03: the one writer folds in what other agents gave the wiki
        import swarm_client as SW
        helps = SW.wiki_helps(root, m["title"])
    except Exception:
        SW, helps = None, []
    contrib = "\n".join(f"- from {h['helper']}: {h['text']} (why its owner would not see it, it says: {h['unseen']})" for h in helps) or "(none)"
    r = M.ask_json(WIKI.format(title=m["title"], source=src, index=index[:6000], contributions=contrib,  # cap: prompt
                               pages="\n\n".join(f"=== {p['path']}\n{p['body'][:3000]}" for p in touched) or "(none)",  # cap: prompt
                               text=re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)[:14000]), key, timeout=400)  # cap: prompt
    today = dt.date.today().isoformat()
    by_path = {p["path"]: p for p in pages}
    n = 0
    for pg in r.get("pages", [])[:8]:
        path = str(pg.get("path", "")).strip().lower().removesuffix(".md")
        if not re.fullmatch(r"(entities|concepts|projects|events)/[a-z0-9][a-z0-9-]{0,60}", path) or not pg.get("body"):
            continue
        old = by_path.get(path, {}).get("meta", {})
        body = keep_superseded(by_path.get(path, {}).get("body", ""), str(pg["body"]))    # MEM-12: a superseded fact stays
        meta = {"title": str(pg.get("title") or path.split("/")[1])[:100], "type": KIND[path.split("/")[0]],  # cap: untrusted
                "summary": str(pg.get("summary", "")), "aliases": [str(a)[:60] for a in pg.get("aliases") or []][:8],  # cap: untrusted
                "sources": sorted(set((old.get("sources") or []) + [src]))[-30:], "created": old.get("created", today),
                "last_validated": today, "trust": "contested" if "[!contradiction]" in body else "news"}
        M.write_front(M.VAULT / root / f"{path}.md", meta, body)
        M.RTM.touched(f"{root}/{path}.md", changed=True, note="wiki page compiled from the result")   # MEM-10: the access map sees it
        n += 1
    if helps and SW:
        try:
            SW.wiki_folded(root, helps, src)
        except Exception:
            pass
    write_index(root, m["title"])
    return n


def write_index(root, title):
    """A wiki's index.md: its pages by folder (the compile writes it, and the Librarian after a merge)."""
    pages = wiki_pages(root)
    groups = {}
    for p in pages:
        groups.setdefault(p["path"].split("/")[0], []).append(p)
    idx = [f"# {title}: wiki", "", f"_{len(pages)} pages, compiled from the mission's results. Updated {dt.date.today().isoformat()}._", ""]
    for g in ("entities", "projects", "concepts", "events"):
        if groups.get(g):
            idx += [f"## {g.title()}", ""] + [f"- [[{p['path']}|{p['title']}]] — {p['summary']}" for p in groups[g]] + [""]
    M.write_front(M.VAULT / root / "index.md", {"title": f"{title}: wiki", "type": "index"}, "\n".join(idx))


def section(body, name):
    """The non-empty lines of one '## name' section of a page body."""
    m = re.search(rf"^## {re.escape(name)}\s*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    return [ln for ln in m.group(1).splitlines() if ln.strip()] if m else []


def keep_superseded(old, new):
    """MEM-12: what a page once moved under Superseded is never lost: lines the new body dropped come back."""
    lost = [ln for ln in dict.fromkeys(section(old, "Superseded")) if ln not in new]
    if not lost:
        return new
    if re.search(r"^## Superseded\s*$", new, re.M):
        return re.sub(r"^(## Superseded\s*\n)", lambda x: x.group(1) + "\n".join(lost) + "\n", new, count=1, flags=re.M)
    return new.rstrip() + "\n\n## Superseded\n" + "\n".join(lost) + "\n"

"""Topic Desk, phase 1: the nightly briefing for one focus topic.
  desk.py --topic /topic --state /state --out /out [--date YYYY-MM-DD] [--dry]     desk.py --check < sources.json
/topic holds TOPIC.md (the brief) and reports/ (earlier briefings, read-only). /state keeps seen.sqlite (what was
already reported). /out receives <date>.md (the report) and <date>.telegram.txt (the short version).
Steps: collect (feeds, Google News, GDELT) -> keep new items of the brief's window (window_hours: 36 h for a daily
briefing, a week for a weekly one) -> group duplicates into events ->
triage against the key questions (gpt-sub-fast) -> read the chosen articles (trafilatura, private addresses refused)
-> prices (Yahoo chart data; deterministic, never written by the model) -> write the report (gpt-sub, in the brief's
language, citing only numbered sources) -> check citations.
Runs on the "webonly" network: internet and LiteLLM only. Env: LITELLM_URL, VK_DESK.
"""
import argparse, base64, datetime as dt, hashlib, html, ipaddress, json, os, re, socket, sqlite3, sys, time, urllib.parse, urllib.request
import textcap as TC                              # visible caps (AGENTS.md, truncation)
from pathlib import Path

import feedparser
import trafilatura
import yaml

UA = "Mozilla/5.0 (X11; Linux x86_64) ai-stack-desk/1.0 (personal research)"
NOW = dt.datetime.now(dt.timezone.utc)
WINDOW_H = 36                                    # the brief's window_hours: what counts as recent (set by main)


def gnews_url(q, hours=36):
    """A Google News search in the query's own language (Chinese, German, else English), over the window unless the
    query names its own (when:7d)."""
    lang = (("zh-CN", "CN", "CN:zh-Hans") if re.search(r"[一-鿿]", q) else
            ("de", "DE", "DE:de") if re.search(r"[äöüß]|\bUran\b", q) else ("en-US", "US", "US:en"))
    if "when:" not in q:
        q += f" when:{max(1, hours // 24)}d"
    return f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl={lang[0]}&gl={lang[1]}&ceid={lang[2]}"


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------- prompts: prompts/desk.md of the repository, mounted read-only (MEM-13) ----------
PROMPTS = Path(os.environ.get("PROMPTS_DIR", "/prompts"))
SECTION = re.compile(r"^<!-- prompt: ([A-Z][A-Z0-9_]*)\b([^\n]*)-->\n(.*?)\n<!-- end -->$", re.M | re.S)   # = ops/prompts.py SECTION
CASE_FILE = None                                 # /out/prompt-cases.jsonl in a briefing run: each call's fills and answer, for replays
CASES = []                                       # this run's cases (an alert hands its case to the runner)


def prompt(name, **fills):
    """(text, ref, fills) of one prompt of prompts/desk.md; ref = desk/NAME@sha, the version the run log names."""
    t = {m.group(1): m.group(3) for m in SECTION.finditer((PROMPTS / "desk.md").read_text())}[name]
    return (t.format(**fills) if fills else t), f"desk/{name}@{hashlib.sha256(t.encode()).hexdigest()[:12]}", fills


# ---------- safety: never fetch internal addresses (feeds are untrusted and could point anywhere) ----------
def public_url(url):
    try:
        p = urllib.parse.urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        for info in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def get(url, timeout=25, headers=None):
    if not public_url(url):
        raise ValueError(f"refused non-public url {url}")
    host = urllib.parse.urlparse(url).hostname or ""
    # SEC EDGAR requires a contact in the User-Agent (its fair-access policy); only sent to sec.gov.
    ua = os.environ.get("SEC_CONTACT", UA) if host == "sec.gov" or host.endswith(".sec.gov") else UA
    req = urllib.request.Request(url, headers={"User-Agent": ua, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def doc_text(raw):
    """Main text of a page; filings and other non-article HTML fall back to the plain text of the whole page."""
    page = raw.decode("utf-8", "replace")
    text = trafilatura.extract(page, include_comments=False) or ""
    if len(text) < 300:
        page = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page)
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page))).strip()
    return text


# ---------- the brief ----------
def brief(topic_dir):
    text = (Path(topic_dir) / "TOPIC.md").read_text()
    _, front, notes = text.split("---", 2)
    b = yaml.safe_load(front)
    b["notes"] = notes.strip()
    return b


# ---------- collect ----------
def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def when(entry):
    for k in ("published_parsed", "updated_parsed"):
        if entry.get(k):
            return dt.datetime(*entry[k][:6], tzinfo=dt.timezone.utc)
    return None


def from_feed(url, kind):
    items = []
    try:
        f = feedparser.parse(get(url))
    except Exception as e:
        log(f"feed failed: {url}: {e}")
        return items
    for e in f.entries:
        title = clean(e.get("title"))
        source = clean((e.get("source") or {}).get("title")) if kind == "gnews" else clean(f.feed.get("title"))
        if kind == "gnews" and " - " in title:
            title, source = title.rsplit(" - ", 1)
        items.append({"title": title, "url": e.get("link", ""), "source": source or urllib.parse.urlparse(url).hostname,
                      "published": when(e), "summary": TC.cut(clean(e.get("summary")), 600), "via": kind})  # cap: prompt
    return items


def from_gdelt(query):
    url = ("https://api.gdeltproject.org/api/v2/doc/doc?mode=artlist&format=json&timespan=24h&maxrecords=50&query="
           + urllib.parse.quote(query))
    try:
        data = json.loads(get(url))
    except Exception as e:
        log(f"gdelt skipped ({query}): {str(e)}")
        return []
    out = []
    for a in data.get("articles", []):
        try:
            p = dt.datetime.strptime(a.get("seendate", ""), "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            p = None
        out.append({"title": clean(a.get("title")), "url": a.get("url", ""), "source": a.get("domain", ""),
                    "published": p, "summary": "", "via": "gdelt"})
    return out


BOILER = re.compile(r"\b(EX-99|Exhibit 99|NEWS RELEASE|PRESS RELEASE|All amounts in|designated news release|"
                    r"prospectus|FORM 6-K|FORM 8-K|SECURITIES AND EXCHANGE COMMISSION|Commission File Number)", re.I)


def release_text(text):
    """Skip the standard opening of a filed press release (exhibit header, currency note, prospectus clause)."""
    sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text))
    while sentences and BOILER.search(sentences[0]):
        sentences.pop(0)
    return " ".join(sentences)


FORMS = {"8-K", "6-K", "10-Q", "10-K", "40-F", "20-F", "S-3", "F-10", "SC 13D", "SC 13G", "4", "DEF 14A"}


def from_sec(tickers):
    """New SEC EDGAR filings of watchlist companies (primary sources: results, guidance, financings, insiders)."""
    if not tickers or not os.environ.get("SEC_CONTACT"):
        return []
    try:
        index = {v["ticker"]: v for v in json.loads(get("https://www.sec.gov/files/company_tickers.json")).values()}
    except Exception as e:
        log(f"sec index failed: {str(e)}")
        return []
    out = []
    for t in tickers:
        c = index.get(t)
        if not c:
            log(f"sec: no filer for {t}")
            continue
        try:
            sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{c['cik_str']:010d}.json"))
        except Exception as e:
            log(f"sec failed {t}: {str(e)}")
            continue
        r = sub["filings"]["recent"]
        for i in range(min(len(r["form"]), 40)):
            if r["form"][i] not in FORMS:
                continue
            try:
                p = dt.datetime.strptime(r["acceptanceDateTime"][i][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
            except (ValueError, KeyError):
                p = None
            acc = r["accessionNumber"][i].replace("-", "")
            desc = r.get("primaryDocDescription", [""] * 99)[i] or r["form"][i]
            url = f"https://www.sec.gov/Archives/edgar/data/{c['cik_str']}/{acc}/{r['primaryDocument'][i]}"
            summary = f"SEC filing, form {r['form'][i]}"
            if p and (NOW - p).total_seconds() < WINDOW_H * 3600:  # recent: read it, so triage sees what it is about
                try:
                    text = ""
                    if r["form"][i] in ("6-K", "8-K"):       # the cover page is boilerplate; the news is in exhibit 99.x
                        base = url.rsplit("/", 1)[0]
                        files = json.loads(get(base + "/index.json"))["directory"]["item"]
                        ex = [f["name"] for f in files if re.search(r"ex-?99", f["name"], re.I) and f["name"].endswith((".htm", ".html", ".txt"))]
                        if ex:
                            url = f"{base}/{sorted(ex)[0]}"
                            time.sleep(0.3)
                            text = doc_text(get(url))
                    if len(text) < 300:
                        text = doc_text(get(url))
                    summary = TC.cut(release_text(text), 800) or summary  # cap: prompt
                    desc = summary[:110] if desc == r["form"][i] else desc  # cap: id
                    time.sleep(0.3)
                except Exception as e:
                    log(f"sec doc failed {url}: {e}")
            out.append({"title": f"{c['title'].title()} files {r['form'][i]}: {desc}", "url": url,
                        "source": "SEC EDGAR", "published": p, "summary": summary, "via": "sec"})
        time.sleep(0.3)                                      # SEC fair access: well below 10 requests/second
    return out


# ---------- job openings: the federal job board (Bundesagentur für Arbeit), for a job-hunt brief (MIS-21) ----------
JOBS_API = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
JOBS_KEY = {"X-API-Key": "jobboerse-jobsuche"}         # the board's public key, the one its own website sends
JOB_PAGE = "https://www.arbeitsagentur.de/jobsuche/jobdetail/"


def from_jobs(searches):
    """Openings for each {what, where, radius_km} of the brief. They carry no publication time on purpose: an opening is
    news until it has been reported once (seen.sqlite), however long ago it was posted."""
    out = []
    for s in searches[:10]:                              # cap: list (the brief's searches)
        if not isinstance(s, dict) or not s.get("what"):
            continue
        q = {"was": s["what"], "angebotsart": 1, "veroeffentlichtseit": 30, "size": 50}
        if s.get("where"):
            q |= {"wo": s["where"], "umkreis": int(s.get("radius_km") or 50)}
        try:
            d = json.loads(get(f"{JOBS_API}/pc/v6/jobs?{urllib.parse.urlencode(q)}", headers=JOBS_KEY))
        except Exception as e:
            log(f"jobs {s['what']} failed: {e}")
            continue
        for j in d.get("ergebnisliste") or []:
            a = ((j.get("stellenlokationen") or [{}])[0] or {}).get("adresse") or {}
            where = " ".join(x for x in (a.get("plz"), a.get("ort")) if x)
            title = " ".join((j.get("stellenangebotsTitel") or "").split())
            out.append({"title": f"{title} · {j.get('firma', '')} · {where}", "url": JOB_PAGE + j.get("referenznummer", ""),
                        "source": "Bundesagentur für Arbeit", "published": None, "via": "jobs", "refnr": j.get("referenznummer", ""),
                        "summary": f"{j.get('hauptberuf', '')}; {'full' if j.get('arbeitszeitVollzeit') else 'part'} time; "
                                   f"{(j.get('vertragsdauer') or '').lower()}; {j.get('entfernung', '?')} km away; posted "
                                   f"{(j.get('veroeffentlichungszeitraum') or {}).get('von', '?')}"})
        time.sleep(1)
    return out


def job_text(refnr):
    """The employer's full ad of one opening."""
    d = json.loads(get(f"{JOBS_API}/pc/v4/jobdetails/{base64.b64encode(refnr.encode()).decode()}", headers=JOBS_KEY))
    return d.get("stellenangebotsBeschreibung") or ""


def collect(b):
    src = b.get("sources", {})
    items = from_sec(src.get("filings", [])) + from_jobs(src.get("jobs", []))
    for u in src.get("feeds", []):
        items += from_feed(u, "feed")
    for q in src.get("search", []):
        items += from_feed(gnews_url(q, WINDOW_H), "gnews")
        time.sleep(1)
    for q in src.get("gdelt", []):
        time.sleep(6)                                        # GDELT allows one request per 5 seconds
        items += from_gdelt(q)
    return items


# ---------- new items, grouped into events ----------
def key(it):
    return hashlib.sha1((it["url"] or it["title"]).encode()).hexdigest()


def words(t):
    return {w for w in re.findall(r"[a-z0-9äöüß]+", t.lower()) if len(w) > 2}


def events(items, db):
    seen = {r[0] for r in db.execute("select id from seen")}
    fresh, keys = [], set()
    for it in items:
        k = key(it)
        recent = it["published"] is None or (NOW - it["published"]).total_seconds() < WINDOW_H * 3600
        if k in seen or k in keys or not recent or not it["title"]:
            continue
        keys.add(k)
        it["id"] = k
        fresh.append(it)
    groups = []
    for it in sorted(fresh, key=lambda x: x["via"] != "feed"):   # direct feeds first: real article links
        w = words(it["title"])
        for g in groups if it["via"] != "jobs" else ():         # two openings are two events however alike their titles
            if g["items"][0]["via"] != "jobs" and len(w & g["words"]) / max(len(w | g["words"]), 1) >= 0.5:
                g["items"].append(it)
                break
        else:
            groups.append({"words": w, "items": [it]})
    return fresh, groups


# ---------- model calls via LiteLLM ----------
def ask(prompt, model, max_tokens=None, ref="", fills=None):
    if ref:
        log(f"prompt {ref}")                     # MEM-11: the run's log names the version it sent
    body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    if max_tokens:
        body["max_tokens"] = max_tokens
    req = urllib.request.Request(os.environ.get("LITELLM_URL", "http://litellm:4000") + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {os.environ['VK_DESK']}", "Content-Type": "application/json"})
    err = None
    for attempt in range(4):
        try:
            text = TC.answer(json.load(urllib.request.urlopen(req, timeout=300)), model)
            out = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
            if ref and fills is not None:
                case = {"at": time.time(), "ref": ref, "model": model, "fills": {k: TC.cut(str(v), 20000) for k, v in fills.items()},  # cap: store
                        "out": TC.cut(text, 20000)}  # cap: store
                CASES.append(case)
                if CASE_FILE:
                    with open(CASE_FILE, "a") as f:
                        f.write(json.dumps(case, ensure_ascii=False) + "\n")
            return out
        except Exception as e:
            err = e
            time.sleep(30 * (attempt + 1))
    raise RuntimeError(f"model call failed: {err}")


def triage(b, groups, keep=16):
    qs = "\n".join(f"Q{i + 1}. {q}" for i, q in enumerate(b["key_questions"]))
    picked = []
    for start in range(0, len(groups), 60):
        chunk = groups[start:start + 60]
        lines = "\n".join(
            f"[{start + i}] {g['items'][0]['title']} ({', '.join(sorted({x['source'] for x in g['items']})[:3])}"
            f"{', +' + str(len(g['items']) - 3) if len(g['items']) > 3 else ''}) {TC.cut(g['items'][0]['summary'], 200)}"  # cap: prompt
            for i, g in enumerate(chunk))
        text, ref, fills = prompt("TRIAGE", topic=b["topic"], mission=b["mission"], questions=qs, prefer=", ".join(b["sources"].get("prefer", [])),
                                  avoid=", ".join(b["sources"].get("avoid", [])), items=lines)
        r = ask(text, "gpt-sub-fast", ref=ref, fills=fills)
        for p in r.get("picks", []):
            if isinstance(p.get("n"), int) and 0 <= p["n"] < len(groups):
                picked.append((p.get("score", 1), p["n"], p))
    picked.sort(key=lambda x: (-x[0], x[1]))
    return [(groups[n], p) for _, n, p in picked[:keep]]


def article_url(url):
    """Google News links point to a Google page, not the article: decode them (also gives real links in the report)."""
    if "news.google.com" not in url:
        return url
    try:
        from googlenewsdecoder import new_decoderv1
        r = new_decoderv1(url, interval=1)
        return r["decoded_url"] if r.get("status") else url
    except Exception as e:
        log(f"google news link not decoded: {str(e)}")
        return url


def read(group):
    for it in group["items"][:4]:
        it["url"] = article_url(it["url"])
    for it in group["items"]:
        if "news.google.com" in it["url"]:
            continue
        try:
            text = job_text(it["refnr"]) if it.get("via") == "jobs" else doc_text(get(it["url"]))   # a job page is a script app
            if len(text) > 300:
                return TC.cut(text, 3500)  # cap: prompt
        except Exception as e:
            log(f"read failed {it['url']}: {e}")
    return TC.cut(" ".join(x["summary"] for x in group["items"]), 1500)  # cap: prompt


# ---------- prices: from data, never from the model ----------
def prices(b):
    rows = []
    for w in b.get("watchlist", []):
        sym = w.get("symbol")
        if not sym:
            continue
        try:
            d = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=1mo&interval=1d"))
            res = d["chart"]["result"][0]
            closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
            if len(closes) < 2:
                continue
            last, prev, first = closes[-1], closes[-2], closes[0]
            rows.append({"name": w["name"], "symbol": sym, "currency": res["meta"].get("currency", ""),
                         "last": last, "day": (last / prev - 1) * 100, "month": (last / first - 1) * 100,
                         "proxy": w.get("proxy", "")})
        except Exception as e:
            log(f"price failed {sym}: {str(e)}")
        time.sleep(0.5)
    return rows


def price_table(rows):
    if not rows:
        return "_No price data available._"
    lines = ["| Series | Last | Day | 30 days |\n|---|---:|---:|---:|"]
    for r in rows:
        label = r["name"] + (" (spot proxy)" if r["proxy"] == "spot" else "")
        lines.append(f"| {label} · {r['symbol']} | {r['last']:,.2f} {r['currency']} | {r['day']:+.1f} % | {r['month']:+.1f} % |")
    note = "No free official spot price: the rows marked spot proxy stand in for it. " if any(r["proxy"] == "spot" for r in rows) else ""
    return "\n".join(lines) + f"\n\n_{note}Closing prices, source Yahoo Finance._"


# ---------- write ----------
def previous(topic_dir, date):
    reps = sorted((Path(topic_dir) / "reports").rglob("*.md"))
    reps = [p for p in reps if p.stem < date]
    if not reps:
        return ""
    t = reps[-1].read_text()
    return TC.cut(t, 2500)  # cap: prompt



def write(b, chosen, rows, prev, date):
    sources, blocks = [], []
    for i, (g, p) in enumerate(chosen, 1):
        nums = []
        for it in g["items"][:4]:
            sources.append(it)
            nums.append(len(sources))
        blocks.append(f"EVENT {i} (sources {', '.join(f'[{n}]' for n in nums)}; key questions {p.get('questions', [])}; "
                      f"published {g['items'][0]['published'] or 'unknown'}):\nTITLE: {g['items'][0]['title']}\n"
                      f"TEXT: {g['text']}")
    sections = [s for s in b["report"]["sections"] if s not in ("Prices", "Headline", "In 60 seconds")]
    text, ref, fills = prompt("BRIEFING", topic=b["topic"], mission=b["mission"], questions=json.dumps(b["key_questions"], ensure_ascii=False),
                              notes=b["notes"], previous=prev or "(none, this is the first briefing)", events="\n\n".join(blocks),
                              language="English",                          # every briefing is English (DEC-02, FND-21)
                              style="" if WINDOW_H <= 36 else f"This briefing covers the last {round(WINDOW_H / 24)} days, not one day; "
                                    "the previous briefing is the last one, not yesterday's. ",
                              source_titles=json.dumps({n: it["title"] for n, it in enumerate(sources, 1)}, ensure_ascii=False),
                              sections=", ".join(json.dumps(s, ensure_ascii=False) + ": markdown" for s in sections),
                              titles="")
    r = ask(text, "gpt-sub", ref=ref, fills=fills)
    valid = set(range(1, len(sources) + 1))
    fix = lambda s: re.sub(r"\[(\d+)\]", lambda m: m.group(0) if int(m.group(1)) in valid else "", s or "")
    r["headline"] = re.sub(r"\s*\[\d+\]", "", r.get("headline") or b["topic"]).strip()
    md = [f"# {r['headline']}", "", f"**In 60 seconds:** {fix(r.get('sixty_seconds', ''))}", "",
          "## Prices", "", price_table(rows), ""]
    for s in sections:
        body = fix(r.get("sections", {}).get(s, "")).strip()
        if body:
            md += [f"## {s}", "", body, ""]
    md += ["## Sources", ""]
    md += [f"{n}. [{it['title']}]({it['url']}) · {it['source']}"
           + (f" · {it['published']:%d.%m. %H:%M} UTC" if it["published"] else "") for n, it in enumerate(sources, 1)]
    return "\n".join(md) + "\n", r.get("telegram", ""), r.get("headline", "")


# ---------- Mission Control: event watching, alerts, e-mail ----------
def watch(spec):
    """--watch: current filings, prices and news for event triggers (no model calls, no seen-state: the runner diffs).
    stdin {"sec": [tickers], "prices": [symbols], "news": [queries], "feeds": [urls], "github": ["owner/repo"]}
    -> stdout {"sec": {t: [filing]}, "prices": {...}, "news": {...}, "feeds": {...}, "github": {...}}"""
    out = {"sec": {}, "prices": {}, "news": {}}
    if spec.get("sec") and os.environ.get("SEC_CONTACT"):
        try:
            index = {v["ticker"]: v for v in json.loads(get("https://www.sec.gov/files/company_tickers.json")).values()}
        except Exception as e:
            log(f"watch: sec index failed ({str(e)})")
            index = {}
        for t in TC.first(spec["sec"], 20, "SEC tickers of the topic"):  # cap: list (a briefing's fetch budget; the log names the rest)
            c = index.get(t)
            if not c:
                continue
            try:
                r = json.loads(get(f"https://data.sec.gov/submissions/CIK{c['cik_str']:010d}.json"))["filings"]["recent"]
            except Exception as e:
                log(f"watch: sec {t} failed ({str(e)})")
                continue
            fl = []
            for i in range(min(len(r["form"]), 15)):
                acc = r["accessionNumber"][i]
                fl.append({"id": acc, "form": r["form"][i], "filed": r["acceptanceDateTime"][i][:19],
                           "title": f"{c['title'].title()} filed {r['form'][i]}: {r.get('primaryDocDescription', [''] * 99)[i] or r['form'][i]}",
                           "url": f"https://www.sec.gov/Archives/edgar/data/{c['cik_str']}/{acc.replace('-', '')}/{r['primaryDocument'][i]}"})
            out["sec"][t] = fl
            time.sleep(0.3)
    for sym in TC.first(spec.get("prices", []), 30, "price symbols of the topic"):  # cap: list (the log names the rest)
        try:
            res = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=5d&interval=1d"))["chart"]["result"][0]
            bars = [(t, c) for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]) if c is not None]
            last = res["meta"].get("regularMarketPrice") or bars[-1][1]
            day = dt.datetime.fromtimestamp(res["meta"].get("regularMarketTime") or bars[-1][0], dt.timezone.utc).date()
            before = [c for t, c in bars if dt.datetime.fromtimestamp(t, dt.timezone.utc).date() < day]   # previous close
            prev = before[-1] if before else None
            out["prices"][sym] = {"last": last, "prev": prev, "pct": (last / prev - 1) * 100 if prev else 0,
                                  "currency": res["meta"].get("currency", ""), "date": day.isoformat()}
        except Exception as e:
            log(f"watch: price {sym} failed ({str(e)})")
        time.sleep(0.3)
    for q in TC.first(spec.get("news", []), 20, "news searches of the topic"):  # cap: list (the log names the rest)
        u = gnews_url(q, 24)
        out["news"][q] = [{"id": key(it), "title": it["title"], "url": it["url"], "source": it["source"],
                           "published": it["published"].isoformat() if it["published"] else None} for it in from_feed(u, "gnews")[:15]]
        time.sleep(1)
    out["feeds"], out["github"] = {}, {}               # the event bus (ops/events.py, TSK-10): feeds and GitHub activity
    for u in TC.first(spec.get("feeds", []), 20, "feeds of the topic"):  # cap: list (the log names the rest)
        out["feeds"][u] = [{"id": key(it), "title": it["title"], "url": it["url"], "source": it["source"],
                            "published": it["published"].isoformat() if it["published"] else None} for it in from_feed(u, "feed")[:20]]  # cap: list (a feed's 20 newest items; the feed has the rest)
    for r in spec.get("github", [])[:10]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", r):
            continue
        try:                                            # public activity, no token: 60 calls an hour are plenty for a few repos
            evs = json.loads(get(f"https://api.github.com/repos/{r}/events?per_page=30"))
        except Exception as e:
            log(f"watch: github {r} failed ({str(e)})")
            continue
        out["github"][r] = [{"id": e["id"], "url": f"https://github.com/{r}", "published": e.get("created_at"),
                             "title": f"{e['type'].removesuffix('Event')} by {e.get('actor', {}).get('login', '?')}"
                                      + (f": {e['payload'].get('action')}" if isinstance(e.get("payload"), dict) and e["payload"].get("action") else "")}
                            for e in evs if isinstance(e, dict) and e.get("id")]
    print(json.dumps(out))


def filing_text(url, form):
    text = ""
    if form in ("6-K", "8-K"):                                # the news is in exhibit 99.x, not the cover page
        base = url.rsplit("/", 1)[0]
        files = json.loads(get(base + "/index.json"))["directory"]["item"]
        ex = [f["name"] for f in files if re.search(r"ex-?99", f["name"], re.I) and f["name"].endswith((".htm", ".html", ".txt"))]
        if ex:
            url = f"{base}/{sorted(ex)[0]}"
            text = doc_text(get(url))
    if len(text) < 300:
        text = doc_text(get(url))
    return release_text(text), url


def alert(spec):
    """--alert: a short English alert for one event of a briefing mission. stdin {"event": {...}} with /topic mounted;
    stdout {"title", "markdown", "short"}."""
    b = brief("/topic")
    ev = spec["event"]
    texts = []
    for it in ev.get("items", [])[:4]:
        body = ""
        try:
            if it.get("form"):
                body, it["url"] = filing_text(it["url"], it["form"])
            elif it.get("url"):
                body = doc_text(get(article_url(it["url"])))
        except Exception as e:
            log(f"alert: could not read {it.get('url', '')} ({e})")
        texts.append(f"ITEM: {it.get('title', '')}\nURL: {it.get('url', '')}\nTEXT: {TC.cut(body, 3500) or '(not readable)'}")  # cap: prompt
    text, ref, fills = prompt("ALERT", topic=b["topic"], mission=b["mission"], questions=json.dumps(b["key_questions"], ensure_ascii=False),
                              kind=ev["kind"], summary=ev["summary"], items="\n\n".join(texts))
    r = ask(text, "gpt-sub", ref=ref, fills=fills)
    srcs = "\n".join(f"{i}. [{it.get('title', '')}]({it.get('url', '')})" for i, it in enumerate(ev.get("items", [])[:4], 1))
    r["markdown"] = f"# {r.get('title') or ev['summary']}\n\n{r.get('markdown', '')}\n\n## Sources\n\n{srcs}\n"
    r["prompt"], r["case"] = ref, (CASES[-1] if CASES else None)      # the runner records the version and keeps the case
    print(json.dumps(r, ensure_ascii=False))


# FND-79: fluid width and a viewport, so phone mail apps don't treat it as a desktop page and blow its text up
MAIL = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting"><meta name="color-scheme" content="light dark"><title>{headline}</title></head>
<body style="margin:0;padding:0;background:#eef1f6;-webkit-text-size-adjust:100%;text-size-adjust:100%">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef1f6;padding:16px 0"><tr><td align="center" style="padding:0 8px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;font-family:-apple-system,Segoe UI,Inter,Helvetica,Arial,sans-serif;color:#0f1626">
<tr><td style="background-color:#0f766e;padding:18px 20px;color:#ffffff">
<div style="font-size:12px;line-height:1.4;letter-spacing:.06em;text-transform:uppercase;opacity:.85">{kicker}</div>
<div style="font-size:18px;font-weight:700;line-height:1.35;margin-top:6px">{headline}</div></td></tr>
<tr><td style="padding:4px 20px 20px;font-size:15px;line-height:1.6;word-break:break-word" class="body">{body}</td></tr>
<tr><td style="padding:14px 20px;background:#f6f7fb;font-size:12px;line-height:1.5;color:#5a6478">{footer}</td></tr>
</table></td></tr></table></body></html>"""


def email(spec):
    """--email: a designed HTML e-mail of a report (no model call). stdin {"markdown", "kicker", "url"} -> stdout {"html", "text"}."""
    import markdown as mdlib
    text = re.sub(r"^---\n.*?\n---\n", "", spec["markdown"], flags=re.S).lstrip()   # FND-79: a blank line hid the headline
    m = re.match(r"#\s+(.+)\n", text)
    headline = m.group(1) if m else spec.get("kicker", "")
    body = mdlib.markdown(text[m.end():] if m else text, extensions=["tables", "sane_lists"])
    styles = {"h1": "font-size:18px;line-height:1.35;margin:16px 0 8px", "h3": "font-size:15px;line-height:1.4;margin:18px 0 6px",
              "h2": "font-size:13px;line-height:1.4;letter-spacing:.06em;text-transform:uppercase;color:#0f766e;margin:24px 0 8px",
              "table": "width:100%;border-collapse:collapse;font-size:12px;margin:8px 0",
              "th": "text-align:left;padding:5px 4px;border-bottom:2px solid #e3e7ef;color:#5a6478;font-weight:600",
              "td": "padding:5px 4px;border-bottom:1px solid #eef1f6", "a": "color:#0f766e;word-break:break-all",
              "li": "margin:5px 0", "p": "margin:10px 0", "em": "color:#5a6478"}
    for tag, st in styles.items():
        body = re.sub(rf"<{tag}(?=[ >])", f'<{tag} style="{st}"', body)
    footer = (f'<a href="{html.escape(spec["url"])}" style="color:#0f766e;font-weight:600">Open in Mission Control</a> · '
              if spec.get("url") else "") + "Sent by your AI stack. Facts and sources only, no investment advice."
    out = MAIL.format(kicker=html.escape(spec.get("kicker", "")), headline=html.escape(headline), body=body, footer=footer)
    print(json.dumps({"html": out, "text": text}))


def fetch(spec):
    """--fetch: the readable text of one public page, for adding it to the vault. stdin {"url"} -> {"title", "text"}"""
    raw = get(spec["url"])
    meta = trafilatura.extract_metadata(raw.decode("utf-8", "replace"))
    print(json.dumps({"title": (meta.title if meta else "") or "", "text": TC.cut(doc_text(raw), 200000)}))  # cap: untrusted


def check(spec):
    """--check: keep only the sources of a drafted brief that work (Mission Control, new briefings).
    stdin {"symbols": [...], "feeds": [...], "filings": [...]} -> stdout the same keys, failing entries removed."""
    ok = {"symbols": [], "feeds": [], "filings": []}
    for sym in spec.get("symbols", [])[:15]:
        try:
            d = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=5d&interval=1d"))
            if [c for c in d["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c is not None]:
                ok["symbols"].append(sym)
        except Exception as e:
            log(f"check: symbol {sym} dropped ({str(e)})")
        time.sleep(0.3)
    for url in spec.get("feeds", [])[:8]:
        try:
            if feedparser.parse(get(url)).entries:
                ok["feeds"].append(url)
            else:
                log(f"check: feed {url} dropped (no entries)")
        except Exception as e:
            log(f"check: feed {url} dropped ({str(e)})")
    if spec.get("filings") and os.environ.get("SEC_CONTACT"):
        try:
            known = {v["ticker"] for v in json.loads(get("https://www.sec.gov/files/company_tickers.json")).values()}
            ok["filings"] = [t for t in spec["filings"][:10] if t in known]
        except Exception as e:
            log(f"check: sec index failed ({str(e)})")
    print(json.dumps(ok))


def main():
    for mode, fn in (("--check", check), ("--fetch", fetch), ("--watch", watch), ("--alert", alert), ("--email", email)):
        if mode in sys.argv:
            return fn(json.load(sys.stdin))
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic"); ap.add_argument("--state"); ap.add_argument("--out")
    ap.add_argument("--date", default=dt.date.today().isoformat()); ap.add_argument("--dry", action="store_true")
    ap.add_argument("--collect", action="store_true")   # TSK-22: the briefing's first step: collect, choose, read; no writing
    ap.add_argument("--write", action="store_true")     # its writing step: the collected events and the scouts' findings
    a = ap.parse_args()
    global CASE_FILE
    if a.out and not a.dry:
        CASE_FILE = Path(a.out) / "prompt-cases.jsonl"
        CASE_FILE.write_text("")                 # this run's cases only; ops/desk.sh keeps them after the run
    b = brief(a.topic)
    global WINDOW_H
    WINDOW_H = int(b.get("window_hours") or 36)
    out = Path(a.out or ".")
    if a.write:
        saved = json.loads((out / f"{a.date}.collected.json").read_text())
        fp = out / "findings.json"
        chosen = thaw(saved["chosen"]) + research_events(json.loads(fp.read_text()) if fp.exists() else [])
        file_report(b, a, out, chosen, saved["prices"], saved["stats"])
        return
    db = sqlite3.connect(Path(a.state) / "seen.sqlite")
    db.execute("create table if not exists seen (id text primary key, first_seen text, title text)")
    items = collect(b)
    fresh, groups = events(items, db)
    log(f"{len(items)} items collected, {len(fresh)} new in {WINDOW_H} h, {len(groups)} events")
    if a.dry:
        for g in groups[:40]:  # cap: list (a dry run's log; the next line counts the rest)
            log(f"  {len(g['items'])}x {g['items'][0]['source'][:20]:20} {g['items'][0]['title']}")  # cap: id (a source's name in a 20-wide log column)
        if len(groups) > 40:
            log(f"  … and {len(groups) - 40} more events")
        return
    chosen = triage(b, groups) if groups else []
    log(f"triage kept {len(chosen)}")
    for g, _ in chosen:
        g["text"] = read(g)
    rows = prices(b)
    stats = {"items": len(items), "new": len(fresh), "events": len(groups), "chosen": len(chosen)}
    if a.collect:
        (out / f"{a.date}.collected.json").write_text(json.dumps({"chosen": freeze(chosen), "prices": rows, "stats": stats}, ensure_ascii=False))
        log(f"collected: {json.dumps(stats)}")
    else:
        file_report(b, a, out, chosen, rows, stats)
    db.executemany("insert or ignore into seen values (?,?,?)", [(it["id"], NOW.isoformat(), it["title"]) for it in fresh])
    db.commit()


def file_report(b, a, out, chosen, rows, stats):
    report, telegram, headline = write(b, chosen, rows, previous(a.topic, a.date), a.date)
    stats = {**stats, "chosen": len(chosen), "sources": report.count("](http")}
    front = (f"---\ntopic: {b['slug']}\ndate: {a.date}\ntype: daily-briefing\nheadline: {json.dumps(headline, ensure_ascii=False)}\n"
             f"stats: {json.dumps(stats)}\n---\n\n")
    (out / f"{a.date}.md").write_text(front + report)
    (out / f"{a.date}.telegram.txt").write_text(telegram)
    log(f"report written: {stats}")


def freeze(chosen):
    """The chosen events as JSON (their times as ISO text), for the writing step."""
    return [[{**g, "words": sorted(g.get("words") or []), "items": [{**it, "published": it["published"].isoformat() if it["published"] else None}
                                                                   for it in g["items"]]}, p] for g, p in chosen]


def thaw(saved):
    return [({**g, "items": [{**it, "published": dt.datetime.fromisoformat(it["published"]) if it["published"] else None} for it in g["items"]]}, p)
            for g, p in saved]


def research_events(findings):
    """Each scout's finding as one more event for the writer; the links it names are its sources (TSK-22)."""
    out = []
    for f in findings:
        urls = list(dict.fromkeys(re.findall(r"https?://[^\s)\]>\"']+", f.get("text") or "")))[:4]   # cap: list (write() cites four per event)
        items = [{"title": f"{urllib.parse.urlparse(u).hostname or u} (research: {f['question'][:80]})", "url": u.rstrip(".,;"),  # cap: id
                  "source": "scout research", "published": None, "summary": ""} for u in urls] or \
                [{"title": f"Research: {f['question'][:80]}", "url": "", "source": "scout research", "published": None, "summary": ""}]  # cap: id
        out.append(({"items": items, "text": TC.cut((f.get("text") or ""), 6000)}, {"questions": []}))   # cap: prompt
    return out


if __name__ == "__main__":
    main()

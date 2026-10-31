"""The event bus (TSK-10 to TSK-12; phase 3 of docs/SWARM-ROADMAP.md): one event log, the owner's rules that start
tasks from events, and breaking-news detection.

Sources (each one says when it last looked, what it found, or why it is off, on Tasks → Triggers):
  from the web, through the desk container on the isolated web-only network (images/desk --watch), and only for what
  a rule asks about: news on a query, breaking stories on a subject, RSS/Atom feeds, GitHub activity, prices, SEC filings
  local: Forgejo activity (the NAS) and new mail (only under the owner's Gmail read grant, every 5 minutes), both only
  while a rule asks for them; changes in the House (Home
  Assistant), new files in C:\\AI\\exports, schedules, finished tasks, and the missions' own event triggers
  (Forgejo and GitHub are read, not called back: nothing may reach the PC from outside, CST-04.)

A source's first look at something only records what is there (a baseline), so a new rule never fires on old items.

A rule: a source, its parameter (a query, a feed, a repository, a symbol, a schedule ...), words the event must hold,
a cooldown, the task to start (a sentence; {title}, {detail}, {url} and {source} are filled from the event), and an
optional check a model answers ("is this the event the rule means?"). Each firing is recorded with its event and the
task it started; the task goes through the intake like any other (ops/tasks.py).

Breaking news (TSK-12): news on a watched subject is grouped into stories by their titles; when three or more different
publishers report the same new story within 30 minutes, one breaking event is raised for it, and later reports attach
to it. The owner rates each one (right / not news), the gate's measure.
"""
import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path

WEB_EVERY = 600                                  # seconds between web looks (one desk container run for every rule's subjects)
LOCAL_EVERY = 60                                 # seconds between local looks
MAIL_EVERY = 300                                 # seconds between looks at the inbox (a Gmail search each time)
ASKED = ("forgejo", "mail")                      # looked at only while a rule asks for them, like the web (the owner's inbox above all)
SOURCES = {"news": "news on a search", "breaking": "a breaking story on a subject", "feed": "a new item in an RSS/Atom feed",
           "github": "activity on a GitHub repository", "price": "a price move of a symbol", "filing": "a new SEC filing of a ticker",
           "forgejo": "activity on a Forgejo repository", "mail": "new mail (Gmail, under its read grant)",
           "house": "a change in the House", "file": "a new file in C:\\AI\\exports", "schedule": "a time",
           "task": "a task that finished", "mission": "a mission's own event trigger"}
WEB = ("news", "breaking", "feed", "github", "price", "filing")
EXPORTS = Path("/srv/win-exports")
STORY_SOURCES, STORY_MINUTES, STORY_FRESH_H = 3, 30, 3    # TSK-12: 3 publishers within 30 min; a story older than 3 h is not breaking
HOUSE_DOMAINS = ("light", "switch", "cover", "lock", "binary_sensor", "climate", "media_player", "alarm_control_panel")
STOP = set("the a an and or of in on at to for with from by is are was were be has have had it its this that as new says after "
           "over into than more will can about not but up out who what how why when news live update latest report".split())
M = None                                         # ops/missions.py, set by its main()
_last = {"web": 0.0, "local": 0.0, "mail": 0.0}
_status = {}                                     # source -> {at, found, error, off}


def table(c):
    c.executescript("""
      create table if not exists bus (id integer primary key, source text, kind text, key text unique, ts text, title text,
        detail text, url text, param text, data text, baseline integer default 0, story integer, rating integer);
      create table if not exists rules (id integer primary key, name text, source text, param text, words text,
        cooldown_min integer, task text, check_text text, enabled integer default 1, created text, last_fired text);
      create table if not exists firings (id integer primary key, rule integer, event integer, ts text, decision text,
        task integer, why text);
      create table if not exists stories (id integer primary key, subject text, title text, tokens text, items text,
        first_ts text, raised integer default 0, event integer);
      create table if not exists bus_meta (k text primary key, v text);
      create index if not exists bus_source on bus (source, id);""")


def now():
    return dt.datetime.now().astimezone()


def iso(t=None):
    return (t or now()).isoformat(timespec="seconds")


def when(s):
    """An event's time as an aware datetime (a feed's naive time is UTC)."""
    d = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def meta(c, k, v=None):
    if v is None:
        r = c.execute("select v from bus_meta where k=?", (k,)).fetchone()
        return json.loads(r["v"]) if r else None
    c.execute("insert or replace into bus_meta values (?, ?)", (k, json.dumps(v)))
    c.commit()


def status(source, found=0, error=None, off=None):
    _status[source] = {"at": iso(), "found": found, "error": error, "off": off}


# ---------- the log (TSK-10) ----------
def record(c, source, kind, key, title, detail="", url="", param="", data=None, ts=None, baseline=False):
    """One event; the same (source, key) is recorded once. -> its id, or None when it was already there."""
    try:
        cur = c.execute("insert into bus (source, kind, key, ts, title, detail, url, param, data, baseline) values (?,?,?,?,?,?,?,?,?,?)",
                        (source, kind, f"{source}|{key}", ts or iso(), str(title)[:500], str(detail)[:4000], url or "", param or "",  # cap: store
                         json.dumps(data or {}), 1 if baseline else 0))
    except sqlite3.IntegrityError:               # seen before (by its unique key)
        return None
    c.commit()
    return cur.lastrowid


def fresh(base, eid):
    """Counts as new: recorded (always, also on a first look) and not part of the baseline."""
    return bool(eid) and not base


def first_look(c, what):
    """True the first time a source looks at something (a query, a feed, a repository): only a baseline then."""
    k = f"seen:{what}"
    if meta(c, k):
        return False
    meta(c, k, iso())
    return True


# ---------- rules (TSK-11) ----------
def rules(c, source=None):
    q, a = "select * from rules where enabled=1", ()
    if source:
        q, a = q + " and source=?", (source,)
    return [dict(r) for r in c.execute(q, a).fetchall()]


def save_rule(c, req):
    src = str(req.get("when", ""))                     # not "source": every app request carries source=app (server.py)
    if src not in SOURCES:
        raise ValueError(f"the source must be one of: {', '.join(SOURCES)}")
    name, task = re.sub(r"\s+", " ", str(req.get("name", ""))).strip(), re.sub(r"\s+", " ", str(req.get("task", ""))).strip()
    if not 3 <= len(name) <= 80:
        raise ValueError("give the rule a name of 3 to 80 characters")
    if len(task) < 8:
        raise ValueError("say what the stack should do when it fires (a sentence)")
    param = str(req.get("param") or "").strip()
    if src in ("news", "breaking") and len(param) < 3:
        raise ValueError("say what to search the news for")
    if src == "feed" and not re.match(r"https?://", param):
        raise ValueError("give the feed's address (https://...)")
    if src == "github" and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", param):
        raise ValueError("give the repository as owner/name")
    if src == "price" and not re.fullmatch(r"[A-Za-z0-9.\-=^]{1,15}:\d{1,2}(\.\d)?", param):
        raise ValueError("give the price rule as SYMBOL:percent, e.g. CCJ:8")
    if src == "filing" and not re.fullmatch(r"[A-Za-z.]{1,8}", param):
        raise ValueError("give the US ticker")
    if src == "schedule" and not M.valid_schedule(param):
        raise ValueError("a schedule is daily HH:MM, weekdays HH:MM, weekly mon,thu HH:MM or every Nh")
    cooldown = min(max(int(req.get("cooldown_min") or 60), 0), 7 * 1440)
    row = (name, src, param, str(req.get("words") or "").strip(), cooldown, task, str(req.get("check") or "").strip())
    if req.get("id"):
        c.execute("update rules set name=?, source=?, param=?, words=?, cooldown_min=?, task=?, check_text=? where id=?", (*row, int(req["id"])))
        rid = int(req["id"])
    else:
        rid = c.execute("insert into rules (name, source, param, words, cooldown_min, task, check_text, enabled, created) values (?,?,?,?,?,?,?,1,?)",
                        (*row, iso())).lastrowid
    c.commit()
    return rid


def matches(rule, ev):
    if rule["source"] != ev["source"] or ev.get("baseline"):
        return False
    if ev["source"] == "schedule":                     # a schedule event belongs to the one rule that set it
        return ev.get("param") == f"rule {rule['id']}"
    if rule["param"] and rule["param"].lower() != (ev.get("param") or "").lower():
        if not (ev["source"] in ("forgejo", "house", "file", "task", "mission", "mail") and rule["param"].lower() in
                f"{ev.get('param', '')} {ev['title']}".lower()):
            return False
    text = f"{ev['title']} {ev.get('detail', '')}".lower()
    return all(w.lower() in text for w in re.findall(r"[^,\s]+", rule["words"] or ""))


def fill(text, ev):
    return (text.replace("{title}", ev["title"]).replace("{detail}", (ev.get("detail") or "")[:1500])  # cap: prompt
            .replace("{url}", ev.get("url") or "").replace("{source}", ev["source"]))


def check(rule, ev, ask=None):
    """The rule's model check: does the event mean what the rule describes? -> (bool, why)."""
    import prompts as P
    p = P.text("intake", "RULE_CHECK").format(rule=rule["check_text"], title=ev["title"], detail=(ev.get("detail") or "")[:3000],  # cap: prompt
                                              source=SOURCES[ev["source"]], url=ev.get("url") or "")
    r = (ask or (lambda q: M.ask_json(q, os.environ["VK_INTAKE"], "gpt-sub-fast")))(p)
    return bool(r.get("match")), str(r.get("why", ""))[:300]  # cap: store (one sentence on the firing)


def fire(c, ev, ask=None, create=None):
    """The rules an event matches: within the cooldown it is recorded and nothing starts; else the check (if any), then
    the task. -> [firing decisions]."""
    import tasks as TK
    out = []
    for r in rules(c, ev["source"]):
        if not matches(r, ev):
            continue
        last = r["last_fired"]
        if last and (now() - dt.datetime.fromisoformat(last)).total_seconds() < r["cooldown_min"] * 60:
            decision, why, tid = "cooldown", f"fired at {last[11:16]}, cooldown {r['cooldown_min']} min", None
        else:
            try:
                ok, why = check(r, ev, ask) if r["check_text"] else (True, "")
                decision = "fired" if ok else "rejected by its check"
            except Exception as e:                    # the check could not be asked (a usage limit): said on the firing
                ok, why, decision = False, f"{type(e).__name__}: {e}", "check failed"
            tid = None
            if ok:
                res = (create or TK.create)({"text": fill(r["task"], ev), "autonomy": "auto", "source": f"rule:{r['id']}"}, c)
                tid = res["task"]
                c.execute("update rules set last_fired=? where id=?", (iso(), r["id"]))
                M.event("triggered", "", f"Rule “{r['name']}” fired on {ev['title'][:120]}: task #{tid}", push=True, title="Triggers")  # cap: preview
        c.execute("insert into firings (rule, event, ts, decision, task, why) values (?,?,?,?,?,?)", (r["id"], ev["id"], iso(), decision, tid, why))
        c.commit()
        out.append({"rule": r["id"], "decision": decision, "task": tid, "why": why})
    return out


def emit(c, source, kind, key, title, ask=None, create=None, **kw):
    """Record an event and run the rules on it. -> (event id or None, firings)."""
    eid = record(c, source, kind, key, title, **kw)
    if not eid:
        return None, []
    ev = dict(c.execute("select * from bus where id=?", (eid,)).fetchone())
    return eid, fire(c, ev, ask, create)


# ---------- breaking news (TSK-12) ----------
def tokens(title):
    title = re.sub(r"\s[-–|]\s[^-–|]{2,40}$", "", title)        # Google News appends " - Publisher"
    return {w for w in re.findall(r"[a-z0-9äöüß]+", title.lower()) if len(w) > 2 and w not in STOP}


def same_story(a, b):
    return len(a & b) >= 3 or (a and b and len(a & b) / len(a | b) >= 0.4)


def breaking(c, subject, items, now_t=None, ask=None, create=None, baseline=False):
    """News items on a watched subject -> stories; a story that three publishers report within 30 minutes, and that
    is new, raises one breaking event; later reports attach to it. On the first look (baseline) stories are only
    built. -> the events raised."""
    now_t = now_t or now()
    raised = []
    for it in items:
        if not it.get("published") or not it.get("source"):
            continue
        it = {**it, "published": when(it["published"]).astimezone(dt.timezone.utc).isoformat(timespec="seconds")}
        tk = tokens(it["title"])
        st = None
        for s in c.execute("select * from stories where subject=?", (subject,)).fetchall():
            if (now_t - when(s["first_ts"])).total_seconds() < 86400 and same_story(tk, set(json.loads(s["tokens"]))):
                st = dict(s)
                break
        if st is None:
            sid = c.execute("insert into stories (subject, title, tokens, items, first_ts) values (?,?,?,?,?)",
                            (subject, it["title"], json.dumps(sorted(tk)), "[]", it["published"])).lastrowid
            st = dict(c.execute("select * from stories where id=?", (sid,)).fetchone())
        its = json.loads(st["items"])
        if any(x["id"] == it["id"] for x in its):
            continue
        its.append({k: it.get(k) for k in ("id", "title", "url", "source", "published")})
        first = min(x["published"] for x in its)
        c.execute("update stories set items=?, first_ts=? where id=?", (json.dumps(its), first, st["id"]))
        c.commit()
        if st["raised"] or baseline:
            if st["event"]:                                     # later reports attach to the event
                c.execute("update bus set detail=? where id=?", (story_text(its), st["event"]))
                c.commit()
            continue
        pubs = {}
        for x in sorted(its, key=lambda x: x["published"]):
            pubs.setdefault(x["source"], x["published"])
        times = sorted(when(x) for x in pubs.values())
        fresh = bool(times) and (now_t - times[0]).total_seconds() < STORY_FRESH_H * 3600
        within = any((times[i + STORY_SOURCES - 1] - times[i]).total_seconds() <= STORY_MINUTES * 60 for i in range(len(times) - STORY_SOURCES + 1))
        if len(pubs) >= STORY_SOURCES and within and fresh:
            eid, _ = emit(c, "breaking", "story", f"{subject}|{st['id']}", st["title"], ask=ask, create=create, detail=story_text(its),
                          url=its[0]["url"], param=subject, data={"story": st["id"], "publishers": sorted(pubs)})
            c.execute("update stories set raised=1, event=? where id=?", (eid, st["id"]))
            c.execute("update bus set story=? where id=?", (st["id"], eid))
            c.commit()
            raised.append(eid)
    return raised


def story_text(its):
    return "\n".join(f"- {x['source']}, {x['published'][11:16]}: {x['title']} ({x['url']})" for x in sorted(its, key=lambda x: x["published"]))


# ---------- the sources ----------
def watch(spec):
    """The desk container's --watch on the web-only network: no model, nothing kept there; the bus diffs."""
    p = subprocess.run(["docker", "run", "--rm", "-i", "--network", "aistack_webonly", "-e", "SEC_CONTACT", "aistack/desk:1", "--watch"],
                       input=json.dumps(spec), capture_output=True, text=True, timeout=600)
    if p.returncode:
        raise RuntimeError((p.stderr or "").strip()[-400:] or f"exit {p.returncode}")  # cap: preview
    return json.loads(p.stdout)


def web(c, look=None, ask=None, create=None):
    """One look at the web for every rule's subject (news, breaking, feeds, GitHub, prices, filings)."""
    rs = [r for r in rules(c) if r["source"] in WEB]
    spec = {"news": sorted({r["param"] for r in rs if r["source"] in ("news", "breaking")}), "feeds": sorted({r["param"] for r in rs if r["source"] == "feed"}),
            "github": sorted({r["param"] for r in rs if r["source"] == "github"}), "prices": sorted({r["param"].split(":")[0].upper() for r in rs if r["source"] == "price"}),
            "sec": sorted({r["param"].upper() for r in rs if r["source"] == "filing"})}
    if not any(spec.values()):
        for s in WEB:
            status(s, off="no rule asks for it")
        return
    try:
        got = (look or watch)(spec)
    except Exception as e:                       # the web look failed: every web source says so; the next look tries again
        for s in WEB:
            status(s, error=f"{type(e).__name__}: {e}")
        return
    n = {s: 0 for s in WEB}
    for q, items in (got.get("news") or {}).items():
        base = first_look(c, f"news:{q}")
        for it in items:
            n["news"] += fresh(base, emit(c, "news", "article", f"{q}|{it['id']}", it["title"], ask, create, url=it["url"], param=q, ts=it.get("published"),
                                   detail=it.get("source") or "", data={"source": it.get("source")}, baseline=base)[0])
        if any(r["source"] == "breaking" and r["param"] == q for r in rs):
            n["breaking"] += len(breaking(c, q, items, ask=ask, create=create, baseline=base))
    for u, items in (got.get("feeds") or {}).items():
        base = first_look(c, f"feed:{u}")
        for it in items:
            n["feed"] += fresh(base, emit(c, "feed", "item", f"{u}|{it['id']}", it["title"], ask, create, url=it["url"], param=u, ts=it.get("published"),
                                   detail=it.get("source") or "", baseline=base)[0])
    for repo, items in (got.get("github") or {}).items():
        base = first_look(c, f"github:{repo}")
        for it in items:
            n["github"] += fresh(base, emit(c, "github", "activity", f"{repo}|{it['id']}", f"{repo}: {it['title']}", ask, create, url=it["url"],
                                     param=repo, ts=it.get("published"), baseline=base)[0])
    for r in (x for x in rs if x["source"] == "price"):
        sym, pct = r["param"].split(":")
        q = (got.get("prices") or {}).get(sym.upper())
        if q and q.get("prev") and abs(q["pct"]) >= float(pct):
            d = "up" if q["pct"] > 0 else "down"
            n["price"] += bool(emit(c, "price", "move", f"{sym.upper()}|{q['date']}|{d}|{pct}", f"{sym.upper()} {d} {abs(q['pct']):.1f} % to {q['last']:.2f} {q.get('currency', '')}",
                                    ask, create, param=r["param"], detail=f"previous close {q['prev']:.2f} ({q['date']})")[0])
    for tick, fl in (got.get("sec") or {}).items():
        base = first_look(c, f"filing:{tick}")
        for f in fl:
            n["filing"] += fresh(base, emit(c, "filing", f["form"], f"{tick}|{f['id']}", f["title"], ask, create, url=f["url"], param=tick, ts=f.get("filed"),
                                     baseline=base)[0])
    for s in WEB:
        status(s, found=n[s], off=None if any(r["source"] == s for r in rs) else "no rule asks for it")


def forgejo(c, get=None, ask=None, create=None):
    """New commits, issues and pull requests on the owner's Forgejo repositories (read from the NAS)."""
    import builds as B
    tok = os.environ.get("FORGEJO_TOKEN")
    if not tok:
        return status("forgejo", off="Forgejo is not connected (Code tab)")

    def fetch(path):
        import urllib.request
        r = urllib.request.Request(B.FORGEJO + path, headers={"Authorization": f"token {tok}"})
        with urllib.request.urlopen(r, timeout=15) as resp:
            return json.load(resp)
    get = get or fetch
    n = 0
    try:
        for repo in B.repos():
            full = re.sub(r"^forgejo:|\.git$", "", B.origin(repo))
            base = first_look(c, f"forgejo:{full}")
            for cm in get(f"/repos/{full}/commits?limit=10") or []:
                n += fresh(base, emit(c, "forgejo", "commit", f"{full}|{cm['sha']}", f"{repo}: {cm['commit']['message'].splitlines()[0]}", ask, create,
                               url=cm.get("html_url", ""), param=repo, ts=cm["commit"]["author"]["date"], baseline=base)[0])
            for it in get(f"/repos/{full}/issues?state=all&limit=10&sort=updated&type=all") or []:
                kind = "pull request" if it.get("pull_request") else "issue"
                n += fresh(base, emit(c, "forgejo", kind, f"{full}|{it['number']}|{it['state']}", f"{repo}: {kind} #{it['number']} {it['state']}: {it['title']}",
                               ask, create, url=it.get("html_url", ""), param=repo, ts=it.get("updated_at"), baseline=base)[0])
    except Exception as e:                       # the NAS asleep or a refused token: said on the source; the next look tries again
        return status("forgejo", error=f"{type(e).__name__}: {e}")
    status("forgejo", found=n)


def mail(c, search=None, ask=None, create=None):
    """New mail in the inbox, read through the gateway only while the owner grants Gmail read (the inbox digest's way)."""
    import inbox as IN
    if not IN.granted("read"):
        return status("mail", off="Gmail 'read' is not granted (Stack → Connections)")
    try:
        rows = IN.rows_of((search or IN.mcp)("mail-mail_search", {"query": "newer_than:1d", "folder": "inbox", "limit": 25}))
    except Exception as e:                       # the gateway or Gmail: said on the source
        return status("mail", error=f"{type(e).__name__}: {e}")
    base, n = first_look(c, "mail:inbox"), 0
    for r in rows:
        n += fresh(base, emit(c, "mail", "message", r["id"], f"{r.get('subject') or '(no subject)'}", ask, create, param=r.get("from") or "",
                       detail=f"from {r.get('from', '?')}", baseline=base)[0])
    status("mail", found=n)


def house(c, things=None, ask=None, create=None):
    """A thing in the House that changed state (lights, plugs, shutters, locks, sensors ...)."""
    import house as H
    try:
        th = things if things is not None else (H.state().get("house") or {}).get("things") or []
    except Exception as e:                       # Home Assistant away: said on the source
        return status("house", error=f"{type(e).__name__}: {e}")
    if not th:
        return status("house", off="Home Assistant is not connected or not reachable")
    last, cur = meta(c, "house:states") or {}, {t["entity_id"]: t["state"] for t in th if t["domain"] in HOUSE_DOMAINS}
    n = 0
    names = {t["entity_id"]: t for t in th}
    for e, s in cur.items():
        if e in last and last[e] != s and s not in ("unavailable", "unknown"):
            t = names[e]
            n += bool(emit(c, "house", t["domain"], f"{e}|{s}|{int(time.time() // 60)}", f"{t['name']}: {last[e]} → {s}", ask, create,
                           param=f"{t['name']} {e} {t.get('area') or ''}")[0])
    meta(c, "house:states", cur)
    status("house", found=n)


def files(c, folder=None, ask=None, create=None):
    """A new file in C:\\AI\\exports (WSL: /srv/win-exports), top level, not hidden."""
    d = folder or EXPORTS
    if not d.exists():
        return status("file", off=f"{d} is not there")
    seen, n = meta(c, "files:seen") or {}, 0
    cur = {p.name: int(p.stat().st_mtime) for p in d.iterdir() if p.is_file() and not p.name.startswith(".")}
    base = not seen and first_look(c, "files")
    for name, mt in cur.items():
        if seen.get(name) != mt:
            n += fresh(base, emit(c, "file", "new", f"{name}|{mt}", name, ask, create, param=name, detail=f"{d / name}", baseline=base)[0])
    meta(c, "files:seen", cur)
    status("file", found=n)


DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def due(sched, last, t):
    """Is a schedule due at t, given when it last fired? (daily, weekdays, weekly <days>, every Nh)"""
    m = re.match(r"^(?:(daily|weekdays) (\d\d):(\d\d)|weekly ((?:\w{3},?)+) (\d\d):(\d\d)|every (\d{1,2})h)$", sched)
    if not m:
        return False
    if m.group(7):
        return not last or (t - dt.datetime.fromisoformat(last)).total_seconds() >= int(m.group(7)) * 3600
    hh, mm = (m.group(2), m.group(3)) if m.group(1) else (m.group(5), m.group(6))
    days = DAYS if m.group(1) == "daily" else DAYS[:5] if m.group(1) == "weekdays" else m.group(4).split(",")
    slot = t.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    return DAYS[t.weekday()] in days and t >= slot and (not last or dt.datetime.fromisoformat(last) < slot)


def schedules(c, t=None, ask=None, create=None):
    t, n = t or now(), 0
    for r in rules(c, "schedule"):
        if due(r["param"], r["last_fired"], t):
            n += bool(emit(c, "schedule", "time", f"{r['id']}|{t:%Y-%m-%dT%H:%M}", f"{r['name']}: {r['param']}", ask, create, param=f"rule {r['id']}")[0])
    status("schedule", found=n, off=None if rules(c, "schedule") else "no rule asks for it")


def task_done(c, t, state):
    """From ops/tasks.py: a task finished (done or failed). The bus's tables may not exist yet (its thread starts later)."""
    table(c)
    status("task", found=1)
    emit(c, "task", state, f"{t['id']}|{state}", f"Task #{t['id']} {state}: {t['title']}", param=f"#{t['id']} {t['title']}",
         detail=t.get("goal") or "")


def mission_event(c, slug, ev):
    """From ops/mission_extras.py check_events: a mission's own trigger fired (it runs its mission as before)."""
    table(c)
    status("mission", found=1)
    emit(c, "mission", ev.get("kind", "event"), f"{slug}|{ev.get('summary', '')[:200]}", f"{slug}: {ev.get('trigger', '')}: {ev.get('summary', '')}"[:500],  # cap: id
         param=slug, detail=ev.get("summary", ""))


def tick(c):
    """The worker's pass: local sources every minute, the web every 10 minutes (one container run)."""
    table(c)
    t = time.time()
    if t - _last["local"] >= LOCAL_EVERY:
        _last["local"] = t
        asked = {r["source"] for r in rules(c)}
        for s in ASKED:
            if s not in asked:
                status(s, off="no rule asks for it")
        mail_due = "mail" in asked and t - _last["mail"] >= MAIL_EVERY
        if mail_due:
            _last["mail"] = t
        for f in [schedules, house, files] + ([forgejo] if "forgejo" in asked else []) + ([mail] if mail_due else []):
            try:
                f(c)
            except Exception as e:                # one source's bug never stops the others; it is logged and shown
                status(f.__name__.rstrip("s") if f.__name__ != "schedules" else "schedule", error=f"{type(e).__name__}: {e}")
                M.log(f"events {f.__name__}: {type(e).__name__}: {e}")
    if t - _last["web"] >= WEB_EVERY:
        _last["web"] = t
        web(c)


def worker():
    c = M.db()
    table(c)
    while not M.stop.is_set():
        try:
            tick(c)
        except Exception as e:                    # the next pass tries again; it is logged
            M.log(f"events: {type(e).__name__}: {e}")
        M.stop.wait(15)


ACTIONS = {"rule_save", "rule_toggle", "rule_delete", "event_rate"}


def handle(req, c):
    table(c)
    a = req["action"]
    if a == "rule_save":
        return {"rule": save_rule(c, req)}
    if a == "rule_toggle":
        c.execute("update rules set enabled=? where id=?", (1 if req.get("on") else 0, int(req.get("id") or 0)))
    elif a == "rule_delete":                        # the rule only; its firings and the events stay in the log
        c.execute("delete from rules where id=?", (int(req.get("id") or 0),))
    elif a == "event_rate":
        if req.get("rating") not in (1, -1, 0):
            raise ValueError("rate it right (1), not news (-1) or clear it (0)")
        c.execute("update bus set rating=? where id=? and source='breaking'", (req["rating"] or None, int(req.get("id") or 0)))
    c.commit()
    return {}


def state(c):
    """Tasks → Triggers: the rules with their last firings, the newest events, the breaking stories, each source's state."""
    table(c)
    rs = [dict(r) | {"firings": [dict(f) for f in c.execute("select * from firings where rule=? order by id desc limit 5", (r["id"],)).fetchall()]}  # cap: list
          for r in c.execute("select * from rules order by id desc").fetchall()]
    evs = [dict(r) for r in c.execute("select id, source, kind, ts, title, url, param, baseline, story, rating from bus where baseline=0 order by id desc limit 60").fetchall()]  # cap: list (the newest; the log keeps all)
    br = [dict(r) for r in c.execute("select id, ts, title, detail, url, param, rating from bus where source='breaking' order by id desc limit 20").fetchall()]  # cap: list
    rated = c.execute("select sum(rating=1), sum(rating=-1), count(*) from bus where source='breaking'").fetchone()
    return {"bus": {"sources": {s: {"what": SOURCES[s], **_status.get(s, {"off": "not looked at yet"})} for s in SOURCES}, "rules": rs, "events": evs,
                    "breaking": br, "ratings": {"right": rated[0] or 0, "not_news": rated[1] or 0, "raised": rated[2] or 0}}}

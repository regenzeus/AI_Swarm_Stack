#!/usr/bin/env python3
"""Journey checks (TSK-32): the owner's journeys followed end to end, because unit tests check parts and the owner uses
journeys (six faults the tests missed: the e-mail headline, the weekly window, Chinese search, the Makefile, a card that
was no link, a page wider than the phone). On demand (`make journeys`) and nightly (the Journey checks crew job,
crew-journeys.timer); each failure is an alert on the health board (ops/crew.py journey_issues).

  python3 ops/journeys.py [all|make|task|email|routes|tools|selftest]      exit 1 when a journey fails

- make: every make target dry-run (make -n), and each script its recipe names exists.
- task: a task given in a sentence and followed to its result, on replayed answers: the newest finished planned task's
  intake answer, step results and judgement (read only from the live database) go through the real intake check, the
  Conductor, the result file, the done message, the judge and the Tasks board, in a sandbox. Nothing live is written
  and no model is called.
- email: the newest briefing rendered as its e-mail (the desk image, no network) and opened at phone width: the
  headline once, in the header, unmangled; nothing wider than the phone.
- routes: every route of the app at 375 px, on the live data and on an emptied state, in the scout's browser image
  (ops/journeys.mjs): no sideways scrolling, script error or empty screen; a card opens its page; an empty state offers
  its action; dates and numbers the app's way. A write is answered in the browser and never sent.
- tools: every menu link of the Stack tab's tools (web/static/tools.json, APP-30) opens from the PC: the NAS, the
  Router and Home Assistant on the home network, the rest through tailscale serve; a link is broken when it does not
  answer, or answers 404 or a server error (a sign-in page is fine). Hosts outside the house are not called.
- selftest: a page, an e-mail and a Makefile with each fault these checks are for are caught (a check that cannot
  fail proves nothing).
"""
import contextlib
import html
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ops"))
OUT = Path("/srv/ai/missions/crew/journeys.json")     # the health board reads it (ops/crew.py journey_issues)
LIVE_DB = Path("/srv/ai/missions/missions.sqlite")
VAULT = Path("/srv/vault")
BROWSER, DESK = "aistack/browser:1", "aistack/desk:1"
APP, NET = "http://mission-control:8090", "aistack_mcui"   # the app as Tailscale serve reaches it; the browser allows no other host
PHONE = 375
# the routes a sweep starts from; it follows every link it finds (two screens of each kind)
SEEDS = ["#/", "#/tasks", "#/missions", "#/new", "#/chat", "#/system", "#/wiki", "#/build", "#/guide", "#/share", "#/phone",
         "#/house", "#/telemetry", *[f"#/swarm?tab={t}" for t in ("activity", "agents", "improve")], "#/swarm/agent/scout",
         "#/crew/doctor?tab=team", "#/crew/memory", "#/swarm?tab=activity&agents=mission,scout&h=168", "#/swarm?tab=chat&ctx=calls:mission+scout"]
MAKE_VARS = {"REPO": "example", "NAME": "example", "TEXT": "example", "MISSION": "example", "TOPIC": "example", "FILE": "example"}
PATHS = re.compile(r"(?<![\w./-])((?:ops|images|eval|nas|compose|config|scripts)/[\w./-]+\.(?:py|sh|mjs|js|yaml|yml|json))\b")


def tail(s, n=400):
    s = (s or "").strip()
    return s if len(s) <= n else "…" + s[-n:]  # cap: preview (the run log keeps all of it)


# ---------- make: every target dry-run ----------
def targets(makefile):
    """Every rule of the Makefile (not a variable, not a special target), in its order."""
    return list(dict.fromkeys(re.findall(r"^([a-z][a-z0-9_-]*):(?!=)", makefile.read_text(), re.M)))


def dry_run(target, root=ROOT, run=subprocess.run):
    """None when `make -n target` works and every script it names exists, else what is wrong."""
    p = run(["make", "-n", "-C", str(root), target, *[f"{k}={v}" for k, v in MAKE_VARS.items()]], capture_output=True, text=True, timeout=60)
    if p.returncode:
        return f"make {target} does not run: {tail(p.stderr or p.stdout, 300)}"  # cap: preview (make's last words say why)
    missing = sorted({x for x in PATHS.findall(p.stdout) if not (root / x).exists()})
    return f"make {target} names {', '.join(missing)}, which {'does' if len(missing) == 1 else 'do'} not exist" if missing else None


def check_make(root=ROOT, run=subprocess.run):
    ts = targets(root / "Makefile")
    return {"checked": len(ts), "failures": [f for f in (dry_run(t, root, run) for t in ts) if f]}


# ---------- task: a sentence followed to its result, on replayed answers ----------
SAMPLE = {"task": None, "text": "Find the newest stable Python release and the three changes that matter most for small services",
          "answer": {"title": "Newest Python release", "goal": "Name the newest stable Python release and three changes that matter",
                     "kind": "research", "done": ["names the release and its date", "lists three relevant changes"], "questions": [],
                     "rhythm": {"type": "once"}, "effort": "light", "deadline": None,
                     "plan": [{"step": "Find the newest stable release and its date", "agent": "scout", "why": "reads the web", "after": []},
                              {"step": "List the three changes that matter most", "agent": "mission", "why": "works through it", "after": [1]}]},
          "outputs": {1: "Python 3.15.2, released 25 October 2026 (https://www.python.org/downloads/release/python-3152/).",
                      2: "1. TLS checks are stricter. 2. tarfile refuses unsafe paths. 3. http.cookies parses strictly."},
          "judgement": {"verdict": "met", "points": [{"point": "names the release and its date", "met": True, "why": "3.15.2, 25 October"},
                                                     {"point": "lists three relevant changes", "met": True, "why": "three are listed"}]}}


def recorded_task(db=LIVE_DB):
    """The newest finished planned task that ran once, as its replay (read only): the owner's sentence, the intake's
    answer, each step's result and the judge's verdict. Not a trial's, nor one in a repository: the sandbox has no
    repositories (a coding task's intake would ask for one). None when there is none yet."""
    if not Path(db).exists():
        return None
    import conductor as CD
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        for t in c.execute("select * from tasks where door='plan' and status='done' order by id desc limit 20"):  # cap: parse (the newest replayable task is among them)
            spec, rhythm = json.loads(t["spec"] or "{}"), json.loads(t["rhythm"] or "{}")
            if rhythm.get("type") != "once" or not spec.get("plan") or not (spec.get("judgement") or {}).get("points"):
                continue
            if str(t["source"] or "").startswith("trial:") or spec.get("repo"):
                continue                                  # 2 Nov: the Mustache trial's task was replayed and its intake asked for a repository
            outs = {r["idx"]: r["output"] for r in c.execute("select idx, output from task_steps where task=? and occ=1 and status='done'", (t["id"],))}
            if len(outs) != len(spec["plan"]) or any(CD.BLOCKED.match(o or "") for o in outs.values()):
                continue                                  # a step that said it could not work fails its task now (TSK-35)
            return {"task": t["id"], "text": t["text"], "outputs": outs, "judgement": spec["judgement"],
                    "answer": {"title": t["title"], "goal": t["goal"], "kind": t["kind"], "done": json.loads(t["done"] or "[]"), "questions": [],
                               "plan": spec["plan"], "rhythm": rhythm, "effort": t["effort"], "deadline": t["deadline"]}}
    finally:
        c.close()
    return None


@contextlib.contextmanager
def patched(*items):
    """Module attributes set for the journey and put back after it (the sandbox's doors to the live system)."""
    old = [(o, a, getattr(o, a)) for o, a, _ in items]
    try:
        for o, a, v in items:
            setattr(o, a, v)
        yield
    finally:
        for o, a, v in old:
            setattr(o, a, v)


def check_task(rec=None):
    """Give the task, then follow it: planned, each step run with what it waits for, the result filed, the owner told,
    judged, and on the Tasks board as done with its verdict."""
    import conductor as CD
    import events as EV
    import missions as MM
    import notify as N
    import provenance as PV
    import runtime as RTM
    import staffing as ST
    import tasks as TK
    rec = rec or recorded_task() or SAMPLE
    outputs = {int(k): v for k, v in rec["outputs"].items()}
    fails, sent, prompts, ran = [], [], {}, []
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)

        def conn():
            x = sqlite3.connect(d / "m.sqlite", timeout=5)
            x.row_factory = sqlite3.Row
            return x
        ns = types.SimpleNamespace(db=conn, event=lambda *a, **k: None, log=lambda *a, **k: None, paused=MM.paused, VAULT=d, PUBLIC=d / "public",
                                   HOME=d, vault_commit=lambda paths, msg: None, stop=threading.Event(), next_due=MM.next_due, now=MM.now,
                                   valid_schedule=MM.valid_schedule, X=types.SimpleNamespace(APP="https://app", clean_triggers=lambda t: t or []),
                                   notify_task=lambda tid, title, what: sent.append((f"Task #{tid} {what}", {})))

        def replay(c, t, s, prompt, card):
            prompts[s["idx"]] = prompt
            ran.append(s["idx"])
            return outputs[s["idx"]]
        judge = lambda p: json.dumps({"points": [{"met": x["met"], "why": x["why"]} for x in rec["judgement"]["points"]]})
        with patched((CD, "M", ns), (TK, "M", ns), (PV, "M", ns), (EV, "M", ns), (ST, "M", ns), (CD, "RESULTS", d / "tasks"),
                     (CD, "headroom", lambda s: None), (CD, "ADAPTERS", {h: replay for h in CD.ADAPTERS}), (CD, "routed", lambda c, t, s, agents: s),
                     (N, "send", lambda text, category, **k: sent.append((text, k)) or {}), (RTM, "start", lambda *a, **k: None),
                     (RTM, "end", lambda *a, **k: None), (RTM, "set_ref", lambda *a, **k: None), (RTM, "stage", lambda *a, **k: None),
                     (ST, "end_keys", lambda tid, call=None: []), (ST, "cost_of", lambda run, *a, **k: None), (TK, "B_repos", lambda: [])):
            c = conn()
            TK.table(c)
            CD.table(c)
            ST.table(c)
            tid = TK.create({"text": rec["text"]}, c)["task"]
            TK.intake(c, tid, ask=lambda p: rec["answer"])
            t = TK.row(c, tid)
            plan = t["spec"].get("plan") or []
            if t["status"] != "running" or t["door"] != "plan" or len(CD.steps(c, tid)) != len(rec["answer"]["plan"]):
                fails.append(f"the intake did not start the task's plan: it is {t['status']} at {t['door']} ({t.get('error') or 'no error'})")
                return {"checked": 1, "failures": fails, "replay": rec["task"]}
            for _ in range(3 * len(plan) + 3):
                CD.tick(c, start_thread=lambda f: f())
                if TK.row(c, tid)["status"] in ("done", "failed"):
                    break
            t = TK.row(c, tid)
            if t["status"] != "done":
                fails.append(f"the task ended {t['status']}, not done: {t.get('error') or 'no error'}")
            if sorted(ran) != list(range(1, len(plan) + 1)):
                fails.append(f"the steps that ran were {ran}, not each of the {len(plan)} once")
            for i, s in enumerate(plan, 1):
                for a in s.get("after") or []:
                    if outputs[a][:200] not in prompts.get(i, ""):  # cap: parse (its start is enough to know the result is there)
                        fails.append(f"step {i} did not get the result of step {a}, which it waits for")
            f = d / (t["spec"].get("result") or "-")
            leaves = [i for i in range(1, len(plan) + 1) if not any(i in (s.get("after") or []) for s in plan)]
            if not f.is_file():
                fails.append("no result file was written for the task")
            elif not all(outputs[i].strip() in f.read_text() for i in leaves):
                fails.append("the result file does not hold the last steps' answers")
            told = [k for text, k in sent if f"Task #{tid} is done" in text]
            if not told or f"#/task/{tid}" not in json.dumps(told[0].get("buttons")):
                fails.append("the owner was not told the task is done, with a link to it")
            ST.judge_runs(c, ask=judge)
            o = (CD.occurrences(c, tid) or [{}])[0]
            if o.get("verdict") != rec["judgement"]["verdict"]:
                fails.append(f"the run was judged {o.get('verdict')!r}, the recorded verdict is {rec['judgement']['verdict']!r}")
            card = next((x for x in TK.state(c)["tasks"] if x["id"] == tid), None)
            if not card or card["status"] != "done" or card["verdict"] != rec["judgement"]["verdict"] or card["result"] != t["spec"].get("result"):
                fails.append(f"the Tasks board does not show it done with its result and verdict: {card and {k: card[k] for k in ('status', 'verdict', 'result')}}")
            c.close()
    return {"checked": 1, "failures": fails, "replay": rec["task"], "steps": len(plan)}


# ---------- email: the newest briefing at phone width ----------
def newest_report(vault=VAULT):
    files = sorted(vault.glob("topics/*/reports/*/*/*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def headline_of(text):
    """The headline the owner should see: the front matter's, else the report's first heading."""
    fm = re.match(r"---\n(.*?)\n---\n", text, re.S)
    m = fm and re.search(r'^headline: "?(.*?)"?$', fm.group(1), re.M)
    if m and m.group(1).strip():
        return m.group(1).strip().replace('\\"', '"')
    h = re.search(r"^#\s+(.+)$", text[fm.end() if fm else 0:], re.M)
    return h.group(1).strip() if h else ""


def judge_email(page, headline, kicker):
    """What is mangled in a rendered e-mail (its HTML): the headline once in its own element, no Markdown marks or
    twice-escaped text, the kicker once, a phone viewport."""
    fails, esc = [], html.escape(headline)
    viewport = 'name="viewport"' in page
    page = re.sub(r"^.*?<body[^>]*>", "", page, flags=re.S)     # what the mail app shows (the <title> is the tab's)
    n = page.count(f">{esc}<")
    if not headline:
        fails.append("the report has no headline")
    elif n != 1:
        fails.append(f"the headline “{headline}” is in the e-mail {n} times, not once in its header")
    visible = re.sub(r"<[^>]+>", "\n", page)
    if re.search(r"^\s*#{1,6}\s", visible, re.M):
        fails.append("a Markdown heading mark (#) shows in the e-mail")
    if "**" in visible:
        fails.append("Markdown bold marks (**) show in the e-mail")
    if re.search(r"&amp;(?:amp|lt|gt|quot|#\d+);", page):
        fails.append("text escaped twice (like &amp;amp;) shows in the e-mail")
    if kicker and page.count(html.escape(kicker)) != 1:
        fails.append(f"the line “{kicker}” shows {page.count(html.escape(kicker))} times in the e-mail, not once")
    if not viewport:
        fails.append("the e-mail has no phone viewport, so phone mail apps scale it")
    return fails


def judge_email_layout(m):
    out = []
    if (m.get("overflow") or 0) > 1:
        out.append(f"the e-mail scrolls sideways at {PHONE} px by {m['overflow']} px")
    if not m.get("headline"):
        out.append("the headline is not one element of the e-mail at phone width")
    elif (m.get("headline_top") or 0) > 812:
        out.append("the headline is below the first screen of a phone")
    elif (m.get("headline_px") or 0) < (m.get("body_px") or 0):
        out.append(f"the headline ({m['headline_px']} px) is smaller than the text ({m['body_px']} px)")
    return out


def render_email(markdown_text, kicker, run=subprocess.run):
    p = run(["docker", "run", "--rm", "-i", "--network", "none", DESK, "--email"], input=json.dumps({"markdown": markdown_text, "kicker": kicker,
            "url": "https://app/#/read"}), capture_output=True, text=True, timeout=120)
    if p.returncode:
        raise RuntimeError(f"the desk did not render it: {tail(p.stderr)}")  # cap: preview (its error's end)
    return json.loads(p.stdout)["html"]


# ---------- routes: every screen at 375 px, in a browser ----------
def judge_routes(report):
    """The browser's report -> each fault, said where the owner meets it."""
    out = []
    for mode, label in (("live", ""), ("empty", " (with no data)")):
        part = report.get(mode) or {}
        for e in part.get("errors") or []:
            if not e.get("route"):
                out.append(f"the app reported an error{label}: {e['msg']}")
        for r in part.get("results") or []:
            at = f"{r['route']}{label}"
            if (r.get("overflow") or 0) > 1:
                out.append(f"{at} scrolls sideways at {PHONE} px by {r['overflow']} px ({'; '.join(r.get('wide') or [])}"
                           + (f"; from {(r.get('chain') or [''])[-1]}" if r.get("chain") else "") + ")")
            out += [f"{at}: a script error: {m}" for m in dict.fromkeys(r.get("errors") or [])]
            if not r.get("main") and not r.get("graphic"):
                out.append(f"{at} shows nothing")
            if r.get("skeleton"):
                out.append(f"{at} is still loading after 7 s")
            out += [f"{at}: the card “{x}” does not open its page on a tap" for x in r.get("cards") or []]
            out += [f"{at}: an empty state that offers no action: “{x}”" for x in r.get("empties") or []]
            out += [f"{at} shows “{x}”, not the app's date and number format" for x in dict.fromkeys(r.get("formats") or [])]
            if mode == "empty" and not r.get("actions"):
                out.append(f"{at} offers no action")
    return out


def browser(cfg, web=None, extra=(), run=subprocess.run):
    """journeys.mjs in the browser image with cfg (and files to mount), on the app's network; its JSON report."""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "config.json").write_text(json.dumps({"base": APP, **cfg, **({"web": "/web"} if web else {})}))
        for name, text in extra:
            (Path(d) / name).write_text(text)
        Path(d).chmod(0o755)
        for f in Path(d).iterdir():
            f.chmod(0o644)
        cmd = ["docker", "run", "--rm", "--network", NET, "-m", "1g", "--user", "10008", "-e", "HOME=/tmp",
               "-v", f"{ROOT / 'ops/journeys.mjs'}:/j/journeys.mjs:ro", "-v", f"{d}:/jd:ro",
               *(["-v", f"{web}:/web:ro"] if web else []), "--entrypoint", "node", BROWSER, "/j/journeys.mjs", "/jd/config.json"]
        p = run(cmd, capture_output=True, text=True, timeout=1500)
    if p.returncode:
        raise RuntimeError(f"the browser did not run: {tail(p.stderr)}")  # cap: preview (its error's end)
    return json.loads(p.stdout)


def seeds(db=LIVE_DB):
    """SEEDS and the newest planned tasks' cards and maps."""
    out = list(SEEDS)
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        for (tid,) in c.execute("select id from tasks where door='plan' order by id desc limit 2"):  # cap: parse (two tasks' pages are enough to try)
            out += [f"#/task/{tid}", f"#/taskmap?t={tid}"]
        c.close()
    except sqlite3.Error:
        pass
    return out


def check_routes(run=subprocess.run):
    rep = browser({"routes": seeds(), "max": 90}, web=ROOT / "images/mission-control/web", run=run)
    return {"checked": len((rep.get("live") or {}).get("results") or []) + len((rep.get("empty") or {}).get("results") or []),
            "failures": judge_routes(rep), "writes_not_sent": sorted(set((rep.get("live") or {}).get("writes") or []))}


def check_email(run=subprocess.run):
    f = newest_report()
    if not f:
        return {"checked": 0, "failures": [], "note": "no briefing yet"}
    text = f.read_text()
    headline, kicker = headline_of(text), f"Briefing · {f.stem}"
    page = render_email(text, kicker, run)
    fails = judge_email(page, headline, kicker)
    rep = browser({"email": "/jd/email.html", "headline": headline}, extra=[("email.html", page)], run=run)
    return {"checked": 1, "failures": [f"{x} ({f.relative_to(VAULT)})" for x in fails + judge_email_layout(rep.get("email") or {})]}


# ---------- tools: every link of the Stack tab's tools opens (APP-30) ----------
TOOLS = ROOT / "images/mission-control/web/static/tools.json"
TAILNET = "https://pc.example.ts.net"            # = app.js HOSTURL off the tailnet


def tool_links(tools=None):
    """-> [(tool, menu, url)] of every menu at home or on the tailnet (tailscale.com and the like are not called)."""
    tools = tools or json.loads(TOOLS.read_text())
    out = []
    for t in tools["tools"]:
        base = TAILNET + t["host"][7:] if t["host"].startswith("tailnet") else t["host"]
        if not t["host"].startswith("tailnet") and not re.match(r"https?://(192\.168\.|10\.|fritz\.box)", base):
            continue
        out += [(t["name"], m["name"], base + m["path"]) for m in t["menus"]]
    return out


def open_link(url, timeout=8):
    """-> the HTTP status, or the error; a sign-in redirect counts as open. The NAS's certificate is its own."""
    import ssl
    import urllib.error
    import urllib.request

    class Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    try:
        with urllib.request.build_opener(Stay, urllib.request.HTTPSHandler(context=ctx)).open(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError as e:
        return f"{type(e).__name__}: {getattr(e, 'reason', e)}"


def check_tools(tools=None, opener=open_link):
    links = tool_links(tools)
    fails = []
    for tool, menu, url in links:
        s = opener(url)
        if not isinstance(s, int):                   # one slow answer while the PC is busy is not a broken tool: it must fail twice
            s = opener(url)
        if not isinstance(s, int) or s == 404 or s >= 500:
            fails.append(f"{tool} → {menu} does not open ({s}): {url}")
    return {"checked": len(links), "failures": fails}


# ---------- selftest: each fault is caught ----------
BAD_EMAIL = ('<html><head></head><body><div>Daily · 1 Nov</div><div>Daily · 1 Nov</div><h1># China Weekly</h1>'
             '<p>**In 60 seconds:** BYD &amp;amp; VW</p></body></html>')


def selftest(run=subprocess.run):
    fails = []
    if len(judge_email(BAD_EMAIL, "China Weekly", "Daily · 1 Nov")) < 5:
        fails.append("the e-mail check passed a mangled headline")
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "Makefile").write_text("good:\n\techo ok\nbroken:\n\tpython3 ops/gone.py\nworse:\n\t$(error a broken rule)\n")
        got = check_make(Path(d), run)["failures"]
        if len(got) != 2:
            fails.append(f"the make check found {len(got)} of 2 broken targets: {got}")
    try:
        w = browser({"wide": True}, run=run).get("wide") or {}
        missed = [k for k, ok in (("a page wider than the phone", (w.get("overflow") or 0) > 1), ("a card that is no link", w.get("cards")),
                                  ("an empty state with no action", w.get("empties")), ("an ISO time and a German price", len(w.get("formats") or []) >= 2)) if not ok]
        fails += [f"the browser check missed {x}" for x in missed]
    except Exception as e:
        fails.append(f"the browser check could not run: {e}")
    return {"checked": 3, "failures": fails}


JOURNEYS = {"selftest": selftest, "make": check_make, "task": check_task, "email": check_email, "routes": check_routes, "tools": check_tools}


def run_all(names=None, out=OUT):
    """Each journey (a crash is that journey's failure), the report written for the health board; the report."""
    res = []
    for name in names or JOURNEYS:
        t0 = time.time()
        try:
            r = JOURNEYS[name]()
        except Exception as e:
            r = {"checked": 0, "failures": [f"the {name} journey could not run: {type(e).__name__}: {e}"]}
        res.append({"name": name, "seconds": round(time.time() - t0, 1), **r})
        print(f"{'FAIL' if r['failures'] else 'ok  '}  {name}: {r.get('checked', 0)} checked" + "".join(f"\n      {x}" for x in r["failures"]), flush=True)
    rep = {"at": time.time(), "journeys": res, "failures": sum(len(r["failures"]) for r in res)}
    if names is None or set(names) == set(JOURNEYS):
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp")
            tmp.write_text(json.dumps(rep, ensure_ascii=False, indent=1))
            tmp.replace(out)
        except OSError as e:
            print(f"   the report was not written for the health board: {e}")
    return rep


def summary(rep):
    bad = [r for r in rep["journeys"] if r["failures"]]
    if not bad:
        return f"all {len(rep['journeys'])} journeys pass ({sum(r.get('checked', 0) for r in rep['journeys'])} checks)"
    return f"{len(bad)} of {len(rep['journeys'])} journeys fail: " + "; ".join(f"{r['name']}: {r['failures'][0]}" for r in bad)


if __name__ == "__main__":
    arg = sys.argv[1:] or ["all"]
    if arg[0] not in ("all", *JOURNEYS):
        sys.exit(__doc__)
    sys.exit(1 if run_all(None if arg[0] == "all" else arg)["failures"] else 0)

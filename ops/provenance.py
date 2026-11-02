"""What every step of a task's run used and made (TSK-23), and the run's swarm map (TSK-24; docs/SWARM-DESIGN.md).

Artifacts are anything used or made: a web page, a search, a job ad, a vault note, a memory, a feed item the Topic
Desk chose, a step's finding, the report, a wiki page, a delivery. Each link is one of W3C PROV's relations:

  used       a step read it (the agents' tool calls in the runtime record: fetch, web search, the browser, the job
             board, the vault, memory; the desk's chosen items)
  generated  a step made it (its finding, the report, a written file, a wiki page, a delivery)
  derived    an artifact came from another (the report from the findings it waits for, a finding from the pages it
             names, a delivery from the report)
  cited      the report's or the answer's text links to it, so the map tells what was read but never used

They are recorded where the work happens: when a step ends (record_step, from its runtime record and its own output)
and again when the run ends (record_run: late tool events, the result and its citations). Each change writes the
run's map, public/maps/<task>.<occ>.json, which the app draws as a flow and a timeline (live while it runs).
"""
import datetime as dt
import hashlib
import json
import re
import sqlite3
import urllib.parse
from pathlib import Path

RUNTIME_DB = Path("/srv/ai/missions/app/runtime.db")
DESK = Path("/srv/ai/desk")                       # the Topic Desk's per-topic folders (ops/desk.sh)
M = None                                          # ops/missions.py, set by its main()
URL = re.compile(r"https?://[^\s)\]>\"'<`]+")
READ = ("page", "job", "note", "item", "memory")  # what counts as read (a search is a look, not a read)
TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ref_)")


def table(c):
    c.executescript("""
      create table if not exists artifacts (id text primary key, kind text, title text, uri text, site text, first text, last text);
      create table if not exists prov (task integer, occ integer, step integer, run text, rel text, artifact text,
        src text default '', at real, primary key (task, occ, step, rel, artifact, src));
      create index if not exists prov_run on prov (task, occ);""")


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def norm(url):
    """One address for one page: no fragment, no tracking parameters, no trailing slash, the host in lower case."""
    try:
        u = urllib.parse.urlsplit(url.strip().rstrip(".,;:!?)]}'\""))
    except ValueError:
        return url
    q = urllib.parse.urlencode([(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True) if not TRACKING.match(k)])
    return urllib.parse.urlunsplit((u.scheme.lower(), u.netloc.lower().removeprefix("www."), u.path.rstrip("/") or "/", q, ""))


def site(uri):
    return urllib.parse.urlsplit(uri).netloc if uri.startswith("http") else uri.split(":", 1)[0]


def urls(text):
    return {norm(u) for u in URL.findall(text or "")}


def art(c, kind, uri, title=""):
    """The artifact's id (a hash of its kind and address); made on first use, its last use moved on."""
    aid = hashlib.sha1(f"{kind}:{uri}".encode()).hexdigest()[:16]
    t = now()
    c.execute("insert into artifacts (id, kind, title, uri, site, first, last) values (?,?,?,?,?,?,?) "
              "on conflict (id) do update set last=excluded.last, title=coalesce(nullif(artifacts.title, ''), excluded.title)",
              (aid, kind, str(title)[:300], uri, site(uri), t, t))  # cap: id (the artifact keeps its address whole)
    return aid


def link(c, task, occ, step, run, rel, aid, src="", at=None):
    c.execute("insert or ignore into prov (task, occ, step, run, rel, artifact, src, at) values (?,?,?,?,?,?,?,?)",
              (task, occ, step, run, rel, aid, src, at))


# ---------- the runtime record: a step's agent runs and their tool calls ----------
def tree(run, db=None):
    """The run and every run inside it (its agents, their helpers): [{run, ref, agent, started, ended, state}]."""
    try:
        c = sqlite3.connect(f"file:{db or RUNTIME_DB}?mode=ro", uri=True)
        rows = c.execute("""with recursive t(run) as (select ? union select r.run from runs r join t on r.ref = t.run)
                            select r.run, r.ref, r.agent, r.started, r.ended, r.end_state from runs r where r.run in (select run from t)""",
                         (run,)).fetchall()
        c.close()
    except sqlite3.Error:
        return []
    return [dict(zip(("run", "ref", "agent", "started", "ended", "state"), r)) for r in rows]


def calls(runs, db=None):
    """The tool calls of these runs, oldest first: [(run, ts, tool, args)]."""
    if not runs:
        return []
    try:
        c = sqlite3.connect(f"file:{db or RUNTIME_DB}?mode=ro", uri=True)
        rows = c.execute(f"select run, ts, title, detail from events where kind='call' and run in ({','.join('?' * len(runs))}) order by id",
                         list(runs)).fetchall()
        c.close()
    except sqlite3.Error:
        return []
    out = []
    for run, ts, tool, detail in rows:
        try:
            args = json.loads(detail or "{}")
        except ValueError:                        # a cut argument list: what can be read of it
            args = {k: v for k, v in re.findall(r'"(url|query|question|what|where|refnr|file|path)":\s*"([^"]*)', detail or "")}
        out.append((run, ts, tool, args if isinstance(args, dict) else {}))
    return out


def from_call(tool, a):
    """A tool call -> (rel, kind, uri, title), or None for calls that touch nothing outside the agent."""
    t = tool.lower()
    if "research_research" in t:                      # the vault's research tool hands a question to the scout
        q = str(a.get("question") or "")
        return ("used", "search", f"research:{q}", f"Research asked: {q}") if q else None
    if "jobs_search" in t:
        q = " ".join(str(a.get(k) or "") for k in ("what", "where")).strip()
        return "used", "search", f"jobs:{q}", f"Job board: {q}"
    if "job_details" in t:
        return "used", "job", f"job:{a.get('refnr', '')}", f"Job ad {a.get('refnr', '')}"
    if t.endswith("web_search") or t == "search" or t.endswith("search_web"):
        q = str(a.get("query") or a.get("q") or "")
        return ("used", "search", f"search:{q}", f"Web search: {q}") if q else None
    if any(k in t for k in ("fetch", "web_extract", "browse_open", "browser_navigate")):
        u = a.get("url") or (a.get("urls") or [None])[0]
        return ("used", "page", norm(str(u)), str(u)) if u else None
    if any(k in t for k in ("qmd_get", "qmd_multi_get")) or t in ("read_file", "read"):
        p = str(a.get("file") or a.get("path") or a.get("files") or "")
        return ("used", "note", f"vault:{p}", p) if p else None
    if any(k in t for k in ("qmd_query", "qmd_search", "wiki_search", "search_files", "grep")):
        q = str(a.get("query") or a.get("question") or a.get("pattern") or "")
        return ("used", "search", f"vault-search:{q}", f"Vault search: {q}") if q else None
    if "memory_recall" in t:
        q = str(a.get("query") or "")
        return "used", "memory", f"memory:{q}", f"Memory: {q}"
    if t in ("write_file", "patch"):
        p = str(a.get("path") or "")
        return ("generated", "file", f"vault:{p}", p) if p else None
    return None


# ---------- recording ----------
def run_of(task, occ):
    return f"task:{task}" if (occ or 1) <= 1 else f"task:{task}.{occ}"


def record_step(c, t, s, db=None):
    """A step's used and generated artifacts: its agents' tool calls, the desk's chosen items, its finding and what
    that finding names, the report and the deliveries. Safe to call again: links are kept once."""
    table(c)
    task, occ, idx = t["id"], s.get("occ") or 1, s["idx"]
    run = f"{run_of(task, occ)}:step:{idx}"
    seen = {}                                         # normalised address -> artifact id, for what the output names
    for r, ts, tool, a in calls([x["run"] for x in tree(run, db)], db):
        m = from_call(tool, a)
        if m:
            rel, kind, uri, title = m
            aid = art(c, kind, uri, title)
            link(c, task, occ, idx, r, rel, aid, at=ts)
            if kind == "page":
                seen[uri] = aid
    h, out = s.get("harness"), s.get("output") or ""
    resume = s.get("resume") if isinstance(s.get("resume"), dict) else json.loads(s.get("resume") or "{}")
    if h == "desk-collect" and t["spec"].get("topic") and resume.get("date"):
        f = DESK / t["spec"]["topic"] / "out" / f"{resume['date']}.collected.json"
        try:
            chosen = json.loads(f.read_text()).get("chosen") or []
        except (OSError, ValueError):
            chosen = []
        for g, _ in chosen:
            for it in (g.get("items") or [])[:6]:     # cap: list (a story's first reports; the desk keeps all of them)
                if it.get("url"):
                    aid = art(c, "item", norm(it["url"]), f"{it.get('title', '')} · {it.get('source', '')}")
                    link(c, task, occ, idx, run, "used", aid)
                    seen[norm(it["url"])] = aid
    made = None
    if h in ("desk-write", "desk-alert") and resume.get("report"):
        made = art(c, "report", f"vault:{resume['report']}", "The briefing" if h == "desk-write" else "The alert")
    elif h == "shop":
        p = re.search(r"\((missions/\S+?\.md)\)", out)
        made = art(c, "report", f"vault:{p.group(1)}", "The price check") if p else None
    elif h == "deliver":
        ways = [w for w, word in (("telegram", "Telegram"), ("email", "e-mail")) if word in out.split("(")[0]] + ["app"]
        rep = c.execute("select artifact from prov where task=? and occ=? and rel='generated' and artifact in "
                        "(select id from artifacts where kind='report')", (task, occ)).fetchone()
        for w in ways if not out.startswith("Nothing new") else ["app"]:
            d = art(c, "delivery", f"delivery:{task}.{occ}:{w}", {"telegram": "Telegram", "email": "E-mail", "app": "The app"}[w])
            link(c, task, occ, idx, run, "generated", d)
            if rep:
                link(c, task, occ, idx, run, "derived", d, rep[0])
        wiki = re.search(r"Topic wiki pages updated: ([^\n]+?)\.(?:\n|$)", out.split("\n\n")[0])     # conductor.run_deliver
        for p in (wiki.group(1).split(", ") if wiki and t["spec"].get("topic") else []):
            w = art(c, "wiki", f"vault:topics/{t['spec']['topic']}/wiki/{p}.md", p)
            link(c, task, occ, idx, run, "generated", w)
            if rep:
                link(c, task, occ, idx, run, "derived", w, rep[0])
    elif h == "wiki":
        root = (t["spec"].get("wiki") or {}).get("root", "")
        for p in re.findall(r"(?:entities|concepts|projects|events|howto|answers|comparisons|sources)/[a-z0-9-]+", out.split("(findings:")[0]):
            link(c, task, occ, idx, run, "generated", art(c, "wiki", f"vault:{root}/{p}.md", p))
    if h not in ("deliver", "wiki"):
        made = made or art(c, "finding", f"finding:{task}.{occ}.{idx}", s.get("title") or f"Step {idx}")
        link(c, task, occ, idx, run, "generated", made)
        for a in [x["id"] for x in finding_of(c, task, occ, s.get("after") or [])]:
            link(c, task, occ, idx, run, "derived", made, a)          # from the findings of the steps it waited for
        for u in urls(out):                                           # from the pages its answer names
            aid = seen.get(u) or (c.execute("select id from artifacts where uri=? and kind in ('page','item')", (u,)).fetchone() or [None])[0]
            if aid:
                link(c, task, occ, idx, run, "derived", made, aid)
    c.commit()


def finding_of(c, task, occ, idxs):
    if not idxs:
        return []
    return [dict(r) for r in c.execute(f"select distinct a.id, a.kind from prov p join artifacts a on a.id = p.artifact where p.task=? and p.occ=? "
                                       f"and p.rel='generated' and p.step in ({','.join('?' * len(idxs))}) and a.kind in ('finding','report')",
                                       (task, occ, *idxs)).fetchall()]


def record_run(c, t, occ, steps, db=None):
    """At the run's end: every step again (tool events that came late), the answer, and the citations: each source
    whose address the report's or the answer's text links is marked cited."""
    table(c)
    for s in steps:
        if s["status"] in ("done", "failed", "running", "waiting"):
            record_step(c, t, s, db)
    task = t["id"]
    o = c.execute("select result from task_occ where task=? and occ=?", (task, occ)).fetchone()
    texts = []
    if o and (o["result"] or "").startswith("tasks/"):
        res = art(c, "result", f"vault:{o['result']}", "The answer")
        link(c, task, occ, 0, run_of(task, occ), "generated", res)
        leaves = [s["idx"] for s in steps if not any(s["idx"] in x["after"] for x in steps)]
        for f in finding_of(c, task, occ, leaves):
            link(c, task, occ, 0, run_of(task, occ), "derived", res, f["id"])
        texts.append(_read(o["result"]))
    for (uri,) in c.execute("select a.uri from prov p join artifacts a on a.id = p.artifact where p.task=? and p.occ=? and a.kind='report'", (task, occ)):
        texts.append(_read(uri.removeprefix("vault:")))
    cited = set().union(*(urls(x) for x in texts)) if texts else set()
    for aid, uri in c.execute("select distinct a.id, a.uri from prov p join artifacts a on a.id = p.artifact where p.task=? and p.occ=? "
                              "and p.rel='used' and a.kind in ('page','item')", (task, occ)).fetchall():
        if uri in cited:
            link(c, task, occ, 0, run_of(task, occ), "cited", aid)
    c.commit()


def _read(rel):
    try:
        return (M.VAULT / rel).read_text(errors="replace")
    except (OSError, AttributeError):
        return ""


# ---------- the map (TSK-24) ----------
def map_of(c, task, occ, db=None):
    """The run's swarm: its steps and agent runs (lanes), artifacts and links, and the numbers on top."""
    table(c)
    t = c.execute("select id, title, kind from tasks where id=?", (task,)).fetchone()
    o = c.execute("select occ, trigger, started, ended, status, verdict from task_occ where task=? and occ=?", (task, occ)).fetchone()
    steps = [dict(r) for r in c.execute("select idx, title, item, agent, harness, status, started, ended, after, waiting_for from task_steps "
                                        "where task=? and coalesce(occ, 1)=? order by idx", (task, occ))]
    for s in steps:
        s["after"] = json.loads(s["after"] or "[]")
    lanes = []
    import prices as PR
    import staffing as ST
    table_ = PR.load()
    for s in steps:
        run = f"{run_of(task, occ)}:step:{s['idx']}"
        for r in tree(run, db):
            u = ST.usage_of(r["run"], db, tree=False)                  # TSK-27: each run's own tokens and their list price
            lanes.append({**r, "step": s["idx"], "own": r["run"] == run, "tokens": sum(v["in"] + v["out"] for v in u.values()),
                          "cost": PR.total(u, table_)[0] if u else None, "models": sorted(m for m in u if m)})
    links = [dict(r) for r in c.execute("select step, run, rel, artifact, src, at from prov where task=? and occ=?", (task, occ))]
    ids = {x["artifact"] for x in links} | {x["src"] for x in links if x["src"]}
    arts = [dict(r) for r in c.execute(f"select id, kind, title, uri, site from artifacts where id in ({','.join('?' * len(ids))})", list(ids))] if ids else []
    read = {x["artifact"] for x in links if x["rel"] == "used"} & {a["id"] for a in arts if a["kind"] in READ}
    cited = {x["artifact"] for x in links if x["rel"] == "cited"}
    spans = sorted((s["started"], s["ended"] or now()) for s in steps if s["started"])
    most = max((sum(1 for a, b in spans if a <= x < b) for x, _ in spans), default=0)
    try:
        u = ST.usage_of(run_of(task, occ), db)
        tokens, cost = sum(v["in"] + v["out"] for v in u.values()), (PR.total(u, table_)[0] if u else None)
    except Exception:                                 # the numbers are a view; a missing record shows none
        tokens = cost = None
    wall, first = None, (o["started"] if o and o["started"] else min((s["started"] for s in steps if s["started"]), default=None))
    if first:                                         # a run before run records: from its steps
        last = o["ended"] if o and o["ended"] else max((s["ended"] for s in steps if s["ended"]), default=None) if not o else None
        end = dt.datetime.fromisoformat(last) if last else dt.datetime.now().astimezone()
        wall = round((end - dt.datetime.fromisoformat(first)).total_seconds())
    return {"task": task, "occ": occ, "title": t["title"] if t else "", "kind": t["kind"] if t else "",
            "run": dict(o) if o else None, "steps": steps, "lanes": lanes, "artifacts": arts, "links": links,
            "numbers": {"read": len(read), "cited": len(read & cited), "agents": len({x["agent"] for x in lanes}), "parallel": most,
                        "wall_s": wall, "tokens": tokens, "cost": cost, "steps": len(steps)},
            "written": now()}


def write_map(c, task, occ, db=None):
    """public/maps/<task>.<occ>.json for the app (written whenever the run changes); never raises into the run."""
    try:
        d = M.PUBLIC / "maps"
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f"{task}.{occ}.json.tmp"
        tmp.write_text(json.dumps(map_of(c, task, occ, db), ensure_ascii=False))
        tmp.replace(d / f"{task}.{occ}.json")
    except Exception as e:
        M.log(f"provenance: the map of task {task} run {occ} not written: {type(e).__name__}: {e}")


def backfill():
    """python3 ops/provenance.py backfill: record and draw every finished run of the Conductor's tasks (the runs before
    this module, or after a change to it); the work itself is not touched."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import missions as MM
    import conductor as CD
    import tasks as TK
    globals()["M"] = MM
    c = MM.db()
    TK.table(c)
    CD.table(c)
    n = 0
    for r in c.execute("select distinct task, coalesce(occ, 1) occ from task_steps order by task, occ").fetchall():   # runs before run records too
        try:
            t = TK.row(c, r["task"])
        except ValueError:
            continue
        record_run(c, t, r["occ"], CD.steps(c, r["task"], r["occ"]))
        write_map(c, r["task"], r["occ"])
        n += 1
    print(f"{n} runs recorded and drawn")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["backfill"]:
        backfill()
    else:
        sys.exit(__doc__)

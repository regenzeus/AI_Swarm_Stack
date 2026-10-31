"""Phase 0, proof 3b: a prototype of the Swarm service at its target size (2,000 artifacts, 100,000 events, 20,000
messages), on the stack's own web stack (Starlette + uvicorn, SQLite WAL + FTS5), measured for memory and latency."""
import json, math, random, re, sqlite3, statistics, threading, time, urllib.request
from collections import Counter

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

DB = "/tmp/swarm.db"
random.seed(7)
WORDS = ("partial read detector fetch pagination notice tool error robots backup rsync phone home wiki summary "
         "front matter usage limit stalled crew job board entry ddgs import scout venv health doctor build review "
         "test flaky journal memory curator inbox digest mail grant price watch shopping offer house light plug").split()
KINDS = ["idea", "finding", "report", "wiki", "purchase", "build", "agent_change"]
STATES = ["draft", "open", "ready", "active", "checking", "done", "blocked", "snoozed", "declined", "merged", "gone"]
AGENTS = ["doctor", "maintainability", "tests", "self-review", "scout", "curator", "builder", "main", "mission", "checker", "coach", "inbox"]


def words(n):
    return " ".join(random.choice(WORDS) for _ in range(n))


def build():
    c = sqlite3.connect(DB)
    c.executescript("""
    pragma journal_mode=wal;
    create table artifacts(id integer primary key, kind text, key text, title text, body text, state text, version int,
      owner text, score real, label text, updated real, unique(kind, key));
    create virtual table artifacts_fts using fts5(title, body, content='artifacts', content_rowid='id');
    create table events(seq integer primary key, artifact_id int, actor text, kind text, payload text, ts real, idem text unique);
    create index events_art on events(artifact_id, seq);
    create table messages(seq integer primary key, mid text unique, sender text, recipients text, context text, act text,
      parts text, ts real, label text);
    create table receipts(mid text, agent text, read real, primary key(mid, agent));
    create index msg_ctx on messages(context, seq);
    """)
    for i in range(1, 2001):
        k = random.choice(KINDS)
        c.execute("insert into artifacts values(?,?,?,?,?,?,?,?,?,?,?)", (i, k, f"{k}:{i}", words(8), words(120), random.choice(STATES),
                  random.randint(1, 6), random.choice(AGENTS), random.random(), random.choice(["public", "internal", "private"]), time.time()))
    c.execute("insert into artifacts_fts(artifacts_fts) values('rebuild')")
    for s in range(100000):
        c.execute("insert into events(artifact_id, actor, kind, payload, ts, idem) values(?,?,?,?,?,?)",
                  (random.randint(1, 2000), random.choice(AGENTS), random.choice(["upsert", "transition", "evidence", "link"]),
                   json.dumps({"reason": words(12), "evidence": words(30)}), time.time(), f"i{s}"))
    for s in range(20000):
        to = random.sample(AGENTS, random.randint(1, 3))
        c.execute("insert into messages(mid, sender, recipients, context, act, parts, ts, label) values(?,?,?,?,?,?,?,?)",
                  (f"m{s}", random.choice(AGENTS), json.dumps(to), f"artifact:{random.randint(1, 2000)}", random.choice(["inform", "request", "ack"]),
                   json.dumps([{"text": words(40)}]), time.time(), "internal"))
        for a in to:
            if random.random() < 0.9:
                c.execute("insert into receipts values(?,?,?)", (f"m{s}", a, time.time()))
    c.commit()
    c.close()


build()
local = threading.local()


def db():
    if not hasattr(local, "c"):
        local.c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, check_same_thread=False)
        local.c.row_factory = sqlite3.Row
    return local.c


STOP = set()
tfidf = {}


def index_kind(kind):
    rows = db().execute("select id, title, body from artifacts where kind=? and state not in ('done','declined','merged','gone')", (kind,)).fetchall()
    toks = {r["id"]: re.findall(r"[a-z0-9]+", (r["title"] + " " + r["body"]).lower()) for r in rows}
    df = Counter(w for t in toks.values() for w in set(t))
    n = len(toks)
    vec = {}
    for i, t in toks.items():
        v = {w: (1 + math.log(c)) * math.log((n + 1) / df[w]) for w, c in Counter(t).items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        vec[i] = {w: x / norm for w, x in v.items()}
    tfidf[kind] = (vec, df, n)


async def find(req):
    q = req.query_params.get("q", "")
    kind = req.query_params.get("kind")
    rows = db().execute("select a.id, a.kind, a.key, a.title, a.state, a.score from artifacts_fts f join artifacts a on a.id=f.rowid "
                        "where artifacts_fts match ? " + ("and a.kind=? " if kind else "") + "order by bm25(artifacts_fts) limit 20",
                        (q, kind) if kind else (q,)).fetchall()
    sim = []
    if kind:
        vec, df, n = tfidf[kind]
        v = {w: (1 + math.log(c)) * math.log((n + 1) / df.get(w, 1)) for w, c in Counter(re.findall(r"[a-z0-9]+", q.lower())).items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        sim = sorted(((sum(x / norm * d.get(w, 0) for w, x in v.items()), i) for i, d in vec.items()), reverse=True)[:3]
    return JSONResponse({"hits": [dict(r) for r in rows], "similar": sim})


async def get(req):
    i = int(req.path_params["id"])
    a = dict(db().execute("select * from artifacts where id=?", (i,)).fetchone())
    a["events"] = [dict(r) for r in db().execute("select * from events where artifact_id=? order by seq desc limit 50", (i,))]
    a["thread"] = [dict(r) for r in db().execute("select * from messages where context=? order by seq desc limit 50", (f"artifact:{i}",))]
    return JSONResponse(a)


async def inbox(req):
    agent = req.path_params["agent"]
    rows = db().execute("select m.* from messages m where m.recipients like ? and not exists (select 1 from receipts r where r.mid=m.mid "
                        "and r.agent=?) order by m.seq desc limit 50", (f'%"{agent}"%', agent)).fetchall()
    return JSONResponse({"unread": [dict(r) for r in rows]})


for k in KINDS:
    index_kind(k)
app = Starlette(routes=[Route("/find", find), Route("/get/{id}", get), Route("/inbox/{agent}", inbox)])
threading.Thread(target=lambda: uvicorn.run(app, host="127.0.0.1", port=8099, log_level="warning"), daemon=True).start()
time.sleep(2)


def hit(path):
    t = time.perf_counter()
    with urllib.request.urlopen("http://127.0.0.1:8099" + path, timeout=10) as r:
        r.read()
    return (time.perf_counter() - t) * 1000


res = {}
for name, mk in (("ledger_find", lambda: f"/find?q={'+'.join(random.sample(WORDS, 2))}&kind={random.choice(KINDS)}"),
                 ("ledger_get", lambda: f"/get/{random.randint(1, 2000)}"),
                 ("board_inbox", lambda: f"/inbox/{random.choice(AGENTS)}")):
    xs = sorted(hit(mk()) for _ in range(300))
    res[name] = {"p50_ms": round(statistics.median(xs), 1), "p95_ms": round(xs[int(len(xs) * 0.95)], 1)}
status = dict(l.split(":", 1) for l in open("/proc/self/status") if ":" in l)
import os
res["db_mb"] = round(sum(os.path.getsize(DB + s) for s in ("", "-wal") if os.path.exists(DB + s)) / 1e6, 1)
res["rss_mb"] = round(int(status["VmRSS"].split()[0]) / 1024)
res["peak_rss_mb"] = round(int(status["VmHWM"].split()[0]) / 1024)
print(json.dumps(res))

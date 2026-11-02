"""Every memory system of the stack in one inventory (MEM-01, MEM-07): what each holds, its kind (CoALA: episodic,
semantic, procedural, shared work, and the search over them), who writes and reads it, its size and growth, its limit,
who curates it and when that last ran, and what is wrong with it. The runner refreshes it once an hour in a background
thread (state.json never waits for it) and keeps one snapshot a day, from which the growth over 7 days is read:
public/memory.json and public/memory-history.json."""
import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

VAULT = Path(os.environ.get("MEMORY_VAULT", "/srv/vault"))
PUBLIC = Path(os.environ.get("MISSIONS_PUBLIC", "/srv/ai/missions/public"))
RUNTIME_DB = Path(os.environ.get("RUNTIME_DB_HOST", "/srv/ai/missions/app/runtime.db"))
MISSIONS_DB = Path(os.environ.get("MISSIONS_DB", "/srv/ai/missions/missions.sqlite"))
CHATS = Path(os.environ.get("MISSIONS_CHATS", "/srv/ai/missions/app/chats"))
CODE = Path(os.environ.get("CODE_DIR", "/home/owner/code"))
EVERY = 3600                  # an inventory is a dozen docker and file calls: once an hour is enough to see a trend
HISTORY_DAYS = 120            # snapshots kept (one a day) for growth  # cap: store
ORPHAN_SHARE = 0.10           # qmd: embedding chunks of files that are gone, above this share the index needs a cleanup
ALARM_DAYS = 8                # over its limit this long, its weekly curator had its chance: an alert on the health board

# kind: what the memory is for (CoALA): working = what one task's steps hand on, episodic = what happened, semantic =
# what is true, procedural = how to act, shared = the team's shared work, index = the search over the others. limit: [number, unit] the store should stay under.
STORES = [
    {"id": "vault-notes", "name": "Vault notes", "kind": "semantic", "holds": "your sources and clippings, never rewritten",
     "writes": "you, imports", "reads": "search (qmd), the curator", "curator": None, "limit": [2000, "notes"],
     "tidy": "nothing to tidy: your sources are never rewritten"},
    {"id": "vault-wiki", "name": "Vault wiki", "kind": "semantic", "holds": "knowledge compiled from your notes, the top layer",
     "writes": "the curator; the Librarian writes its hub pages", "reads": "search (qmd): your assistant, missions, the curator",
     "curator": "wiki-curator", "limit": [500, "pages"]},
    {"id": "agent-wikis", "name": "Agent wikis", "kind": "semantic", "holds": "one wiki per mission or topic, from its results",
     "writes": "its one writer (the runner, after each result), folding in other agents' helps; the Librarian merges and marks",
     "reads": "missions at a run's start (their own first, then the vault and related wikis), search (qmd)", "curator": "memory",
     "limit": [200, "pages per wiki"]},
    {"id": "journals", "name": "Agent journals", "kind": "episodic", "holds": "each agent's working state and own runs (its Memory tab)",
     "writes": "the runner, after each run", "reads": "that agent at a run's start", "curator": "memory", "limit": [20000, "bytes per journal"]},
    {"id": "mission-notes", "name": "Old mission notes", "kind": "episodic", "holds": "NOTES.md files not yet moved into their journals",
     "writes": "nobody since MEM-05", "reads": "until its mission's next run", "curator": None, "limit": [0, "files"],
     "tidy": "moved into the mission's journal at its next run"},
    {"id": "hindsight", "name": "Long-term memory (Hindsight)", "kind": "semantic", "holds": "facts about you (no copies of journal entries)",
     "writes": "your chats (through the gatekeeper)", "reads": "your assistant, a run's start (recall)", "curator": "memory",
     "limit": [5000, "facts"]},
    {"id": "ledger", "name": "The Ledger", "kind": "shared", "holds": "ideas, findings, evidence, your decisions and reasons",
     "writes": "agents, the runner, you", "reads": "every swarm agent (its start pack)", "curator": "checker", "limit": [200, "MB"]},
    {"id": "skills", "name": "Skills", "kind": "procedural", "holds": "how Hermes does things",
     "writes": "the skill keeper", "reads": "Hermes' agents", "curator": "curator", "limit": [60, "skills"]},
    {"id": "run-records", "name": "Run records", "kind": "episodic", "holds": "every run's steps, reads and writes (raw)",
     "writes": "every agent's runs", "reads": "you (run logs), the doctor, replay tests", "curator": None, "limit": [500, "MB"],
     "tidy": "the run record drops a run's full events after 90 days; its summary stays"},
    {"id": "qmd", "name": "Search index (qmd)", "kind": "index", "holds": "the search over the vault, wikis, journals and specs",
     "writes": "qmd, from the vault", "reads": "every agent with vault search, a run's start", "curator": "memory", "limit": [ORPHAN_SHARE, "orphaned share"]},
    # MEM-19: the four the first inventory did not have (FND-108)
    {"id": "task-handoffs", "name": "Task hand-offs", "kind": "working", "holds": "each task step's result, which the steps after it build on (MEM-15)",
     "writes": "every task step", "reads": "the steps after it, the Orchestrator's checkpoint, the judge, the task page", "curator": None,
     "limit": [200, "MB"], "tidy": "kept with its task, whose page shows them; a long one is also a file in the vault (tasks/)"},
    {"id": "hermes-memory", "name": "Hermes' own memory", "kind": "semantic", "holds": "Hermes' notes and your profile (USER.md, MEMORY.md), in every prompt",
     "writes": "Hermes, each write approved by the memory gatekeeper or by you", "reads": "Hermes, every turn", "curator": "memory-review",
     "limit": [4400, "characters"]},
    {"id": "code-graphs", "name": "Code graphs", "kind": "index", "holds": "each repository's graph of files, symbols and calls (graphify)",
     "writes": "graphify-sync, at each new commit", "reads": "the builder's context packs, the code map", "curator": None,
     "limit": [1000, "MB"], "tidy": "rebuilt from the code at each commit: one graph per repository"},
    {"id": "chats", "name": "Chats", "kind": "episodic", "holds": "your chats with Hermes in the app", "writes": "you and Hermes",
     "reads": "you; long-term memory keeps what is worth keeping from them", "curator": None, "limit": [2000, "chats"],
     "tidy": "you delete a chat; what matters lives on in long-term memory"},
]
WIKI_CURATOR_AGENT = "curator"      # the Hermes curator profile in the run record: who curates the vault wiki

_cache = {"t": 0.0, "data": None, "busy": False}
_lock = threading.Lock()


def sh(*cmd, timeout=60):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip().splitlines()[-1] if (p.stderr or p.stdout).strip() else f"exit {p.returncode}")
    return p.stdout


def md_files(d):
    return [p for p in d.rglob("*.md") if p.is_file()] if d.exists() else []


def wiki_dirs():
    out = [VAULT / "wiki"] if (VAULT / "wiki").is_dir() else []
    return out + sorted(p for base in ("missions", "topics") for p in (VAULT / base).glob("*/wiki") if p.is_dir())


def measure(sid, now):
    """One store's numbers: {count, unit, bytes, parts, problems}."""
    week = now - 7 * 86400
    if sid == "vault-notes":
        f = md_files(VAULT / "raw")
        return {"count": len(f), "unit": "notes", "bytes": sum(p.stat().st_size for p in f)}
    if sid in ("vault-wiki", "agent-wikis"):
        dirs = [d for d in wiki_dirs() if (d == VAULT / "wiki") == (sid == "vault-wiki")]
        parts = []
        for d in dirs:
            f = md_files(d)
            parts.append({"root": str(d.relative_to(VAULT)), "pages": len(f), "bytes": sum(p.stat().st_size for p in f),
                          "changed_7d": sum(p.stat().st_mtime > week for p in f), "last": max((p.stat().st_mtime for p in f), default=None)})
        out = {"count": sum(p["pages"] for p in parts), "unit": "pages", "bytes": sum(p["bytes"] for p in parts), "parts": parts}
        if sid == "agent-wikis":
            out["count_label"] = f"{len(parts)} wikis"
            out["largest"] = max((p["pages"] for p in parts), default=0)
        return out
    if sid == "journals":
        f = sorted((VAULT / "agents").glob("*/MEMORY.md")) if (VAULT / "agents").exists() else []
        sizes = {p.parent.name: p.stat().st_size for p in f}
        entries = sum(p.read_text(errors="replace").count("\n### ") for p in f)
        return {"count": len(f), "unit": "journals", "bytes": sum(sizes.values()), "entries": entries,
                "largest": max(sizes.values(), default=0), "largest_of": max(sizes, key=sizes.get) if sizes else ""}
    if sid == "mission-notes":
        f = sorted((VAULT / "missions").glob("*/NOTES.md")) + sorted((VAULT / "topics").glob("*/NOTES.md"))
        return {"count": len(f), "unit": "notes files", "bytes": sum(p.stat().st_size for p in f),
                "largest": max((p.read_text(errors="replace").count("\n") for p in f), default=0)}
    if sid == "hindsight":
        q = "select t || '=' || n from (select coalesce(fact_type, '?') t, count(*) n from memory_units group by 1) x order by 1"
        rows = sh("docker", "exec", "aistack-hindsight-db-1", "psql", "-U", "hindsight", "-d", "hindsight", "-Atc", q).split()
        kinds = dict(r.split("=", 1) for r in rows if "=" in r)
        size = int(sh("docker", "exec", "aistack-hindsight-db-1", "psql", "-U", "hindsight", "-d", "hindsight", "-Atc",
                      "select pg_database_size(current_database())").strip() or 0)
        return {"count": sum(int(v) for v in kinds.values()), "unit": "facts", "bytes": size, "by_kind": {k: int(v) for k, v in kinds.items()}}
    if sid == "ledger":
        size = sum(int(x) for x in sh("docker", "exec", "aistack-swarm-1", "sh", "-c",
                                      "stat -c %s /data/swarm.db /data/swarm.db-wal 2>/dev/null || true").split())
        import swarm_client as SW
        r = SW.call("stats", {}, "system")
        st = r.get("result") or {} if r.get("ok") else {}
        return {"count": st.get("artifacts") or 0, "unit": "artifacts", "bytes": size, "events": st.get("events") or 0}
    if sid == "skills":
        out = sh("docker", "exec", "aistack-hermes-1", "sh", "-c", "ls /opt/data/skills | wc -l; du -sb /opt/data/skills | cut -f1").split()
        return {"count": int(out[0]), "unit": "skills", "bytes": int(out[1])}
    if sid == "run-records":
        c = sqlite3.connect(f"file:{RUNTIME_DB}?mode=ro", uri=True)
        n = c.execute("select count(*) from runs").fetchone()[0]
        return {"count": n, "unit": "runs", "bytes": RUNTIME_DB.stat().st_size, "runs_7d": c.execute("select count(*) from runs where started>?", (week,)).fetchone()[0]}
    if sid == "qmd":
        s = sh("docker", "exec", "aistack-qmd-1", "qmd", "status")
        num = lambda pat: int(m.group(1)) if (m := re.search(pat, s)) else 0
        size = re.search(r"Size:\s+([\d.]+)\s*(KB|MB|GB)", s)
        b = int(float(size.group(1)) * {"KB": 1e3, "MB": 1e6, "GB": 1e9}[size.group(2)]) if size else 0
        share = re.search(r"Orphaned:\s+\d+ embedding chunks \((\d+)%\)", s)        # qmd's own share: orphaned of embedded
        return {"count": num(r"Total:\s+(\d+) files"), "unit": "files", "bytes": b, "vectors": num(r"Vectors:\s+(\d+)"),
                "orphaned": num(r"Orphaned:\s+(\d+)"), "orphaned_share": int(share.group(1)) / 100 if share else 0.0}
    if sid == "task-handoffs":
        c = sqlite3.connect(f"file:{MISSIONS_DB}?mode=ro", uri=True)
        n, b = c.execute("select count(*), coalesce(sum(length(output)), 0) from task_steps where output is not null").fetchone()
        return {"count": n, "unit": "step results", "bytes": b}
    if sid == "hermes-memory":
        out = sh("docker", "exec", "aistack-hermes-1", "sh", "-c", "cat /opt/data/memories/*.md 2>/dev/null | wc -c")
        n = int(out.strip() or 0)
        return {"count": n, "unit": "characters", "bytes": n}
    if sid == "code-graphs":
        dirs = [d for d in CODE.glob("*/graphify-out") if d.is_dir()]
        parts = [{"root": d.parent.name, "bytes": sum(p.stat().st_size for p in d.rglob("*") if p.is_file())} for d in dirs]
        return {"count": len(parts), "unit": "graphs", "bytes": sum(p["bytes"] for p in parts), "parts": parts}
    if sid == "chats":
        f = [p for p in CHATS.rglob("*.json") if p.is_file()] if CHATS.exists() else []
        return {"count": len(f), "unit": "chats", "bytes": sum(p.stat().st_size for p in f)}
    raise ValueError(sid)


def curated(store, crew, curator_last):
    """When the store's curator last ran (None: it has no curator)."""
    who = store.get("curator")
    if who == "wiki-curator":
        return curator_last
    item = next((c for c in crew or [] if c.get("id") == who), None)
    return item.get("last") if item else None


def problems(store, m):
    """What is wrong, in plain words (each names the planned fix where there is one)."""
    out, lim = [], store["limit"]
    sid = store["id"]
    if "error" in m:
        return [f"could not be measured: {m['error']}"]
    if sid == "qmd":
        share = m.get("orphaned_share") or 0.0
        if share > lim[0]:
            out.append(f"{m['orphaned']} embedding chunks ({share:.0%}) belong to files that are gone: the Memory Keeper cleans them tonight")
    elif sid == "agent-wikis":
        big = [p["root"] for p in m.get("parts") or [] if p["pages"] > lim[0]]
        out += [f"{r} is over {lim[0]} pages" for r in big]
    elif sid == "journals":
        if (m.get("largest") or 0) > lim[0]:
            out.append(f"the journal of {m['largest_of']} is {m['largest'] / 1000:.0f} KB, over {lim[0] // 1000} KB")
    elif sid == "mission-notes" and m["count"]:
        out.append(f"{m['count']} NOTES.md file{'s' if m['count'] > 1 else ''} not yet moved into a journal (at that mission's next run)")
    elif sid == "hindsight":
        if m["count"] > lim[0]:
            out.append(f"{m['count']} facts, over {lim[0]}")
    elif sid in ("ledger", "run-records"):
        if m["bytes"] > lim[0] * 1e6:
            out.append(f"{m['bytes'] / 1e6:.0f} MB, over {lim[0]} MB")
    elif sid in ("vault-wiki", "vault-notes", "skills") and m["count"] > lim[0]:
        out.append(f"{m['count']} {m['unit']}, over {lim[0]}")
    if store.get("curator") is None and not store.get("tidy"):
        out.append("nobody curates it")
    return out


def over(store, m):
    """True while the store is over its limit (the old mission notes move at each mission's next run: never an alarm)."""
    lim, sid = store["limit"][0], store["id"]
    if "error" in m or sid == "mission-notes":
        return False
    if sid == "qmd":
        return (m.get("orphaned_share") or 0.0) > lim
    if sid in ("agent-wikis", "journals"):
        return (m.get("largest") or 0) > lim
    if store["limit"][1] == "MB":
        return (m.get("bytes") or 0) > lim * 1e6
    return (m.get("count") or 0) > lim


def alarms(inv, now=None):
    """[(store, text)]: the stores over their limit for ALARM_DAYS or more (crew.health raises them on their curator)."""
    now = now or time.time()
    return [(s, f"{s['name']} has been over its limit since {dt.date.fromtimestamp(s['over_since']).isoformat()}: "
                + ((s.get("problems") or ["over its limit"])[0]))
            for s in (inv or {}).get("stores", []) if s.get("over_since") and now - s["over_since"] >= ALARM_DAYS * 86400]


def last():
    """The last inventory (the cache, else public/memory.json)."""
    with _lock:
        if _cache["data"] is not None:
            return _cache["data"]
    try:
        return json.loads((PUBLIC / "memory.json").read_text())
    except (FileNotFoundError, ValueError):
        return None


def collect(crew=None, now=None):
    """The whole inventory now, with the growth over 7 days from the daily snapshots."""
    now = now or time.time()
    try:
        c = sqlite3.connect(f"file:{RUNTIME_DB}?mode=ro", uri=True)
        curator_last = c.execute("select max(started) from runs where agent like ?", (f"%{WIKI_CURATOR_AGENT}%",)).fetchone()[0]
    except sqlite3.Error:
        curator_last = None
    hist = history()
    week_ago = (dt.date.fromtimestamp(now) - dt.timedelta(days=7)).isoformat()
    base = next((h for h in hist if h["date"] >= week_ago), None)
    before = {s["id"]: s for s in (last() or {}).get("stores", [])}
    out = []
    for s in STORES:
        try:
            m = measure(s["id"], now)
        except Exception as e:
            m = {"error": f"{type(e).__name__}: {e}"}
        prev = (base or {}).get("stores", {}).get(s["id"]) if base else None
        since = (before.get(s["id"]) or {}).get("over_since") or now if over(s, m) else None
        out.append({**s, **m, "growth_7d": None if not prev or "count" not in m else {"count": m["count"] - prev.get("count", 0),
                                                                                          "bytes": m.get("bytes", 0) - prev.get("bytes", 0), "since": base["date"]},
                    "curated": curated(s, crew, curator_last), "problems": problems(s, m), "over_since": since})
    lib = {}
    try:
        lib = json.loads((PUBLIC / "librarian.json").read_text())
        lib.pop("read", None)                              # which page text it read and which pairs it kept apart: its own bookkeeping
        lib.pop("apart", None)
    except (FileNotFoundError, ValueError):
        pass
    return {"at": now, "stores": out, "librarian": lib or None}


def history():
    try:
        return json.loads((PUBLIC / "memory-history.json").read_text())
    except (FileNotFoundError, ValueError):
        return []


def remember(inv):
    """One snapshot a day (the first refresh of the day), the last HISTORY_DAYS kept."""
    day = dt.date.fromtimestamp(inv["at"]).isoformat()
    hist = [h for h in history() if h["date"] != day]
    hist.append({"date": day, "stores": {s["id"]: {"count": s.get("count", 0), "bytes": s.get("bytes", 0)} for s in inv["stores"] if "error" not in s}})
    (PUBLIC / "memory-history.json").write_text(json.dumps(hist[-HISTORY_DAYS:]))   # cap: rotate (one snapshot a day for HISTORY_DAYS)


def refresh(crew=None):
    try:
        inv = collect(crew)
        (PUBLIC / "memory.json").write_text(json.dumps(inv, default=str))
        if not any(h["date"] == dt.date.fromtimestamp(inv["at"]).isoformat() for h in history()):
            remember(inv)
        with _lock:
            _cache.update(t=time.time(), data=inv)
    finally:
        with _lock:
            _cache["busy"] = False


def state(crew=None):
    """For state.json: the last inventory, refreshed in the background once it is older than EVERY."""
    with _lock:
        if _cache["data"] is None:
            try:
                _cache["data"] = json.loads((PUBLIC / "memory.json").read_text())
                _cache["t"] = _cache["data"].get("at", 0)
            except (FileNotFoundError, ValueError):
                pass
        stale = time.time() - _cache["t"] > EVERY and not _cache["busy"]
        if stale:
            _cache["busy"] = True
    if stale:
        threading.Thread(target=refresh, args=(crew,), daemon=True).start()
    return {"memory": _cache["data"]}

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

import deployment as DEPLOY                        # this deployment's hosts and paths (deployments/<name>/deployment.env)

VAULT = Path(os.environ.get("MEMORY_VAULT", "/srv/vault"))
PUBLIC = Path(os.environ.get("MISSIONS_PUBLIC", "/srv/ai/missions/public"))
RUNTIME_DB = Path(os.environ.get("RUNTIME_DB_HOST", "/srv/ai/missions/app/runtime.db"))
MISSIONS_DB = Path(os.environ.get("MISSIONS_DB", "/srv/ai/missions/missions.sqlite"))
CHATS = Path(os.environ.get("MISSIONS_CHATS", "/srv/ai/missions/app/chats"))
CODE = Path(DEPLOY.CODE_DIR)
PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
EVERY = 3600                  # an inventory is a dozen docker and file calls: once an hour is enough to see a trend
HISTORY_DAYS = 120            # snapshots kept (one a day) for growth  # cap: store
ORPHAN_SHARE = 0.10           # qmd: embedding chunks of files that are gone, above this share the index needs a cleanup
ALARM_DAYS = 8                # over its limit this long, its weekly curator had its chance: an alert on the health board

# kind: what the memory is for (CoALA): working = what one task's steps hand on, episodic = what happened, semantic =
# what is true, procedural = how to act, shared = the team's shared work, index = the search over the others. limit: [number, unit] the store should stay under.
# group: the question the owner asks of it (the app's headings). origin: where its content comes from, said plainly: the app never calls
# anything "true", because a wiki compiled from filed mail is what was found, not what is so.
GROUPS = [["you", "What it knows about you"], ["world", "What it has found out"], ["happened", "What happened"],
          ["how", "How to do things"], ["work", "Work in progress"], ["find", "How it finds things"]]
STORES = [
    {"id": "vault-notes", "group": "world", "name": "Filed sources", "kind": "semantic", "origin": "as it came, not checked",
     "holds": "Mail, articles and documents kept for reading: what the inbox job files by itself, imports, and anything you add. Never rewritten.",
     "writes": "the inbox job, imports, you", "reads": "the curator, and search", "curator": None, "limit": [2000, "items"],
     "tidy": "Nothing to tidy: sources stay as they came."},
    {"id": "vault-wiki", "group": "world", "name": "Vault wiki", "kind": "semantic", "origin": "compiled by AI",
     "holds": "Pages the curator compiles from those sources: people, companies, topics. Each names its source.",
     "writes": "the curator; the Memory Keeper adds the pages that join the wikis", "reads": "your assistant, missions and the curator, through search",
     "curator": "wiki-curator", "limit": [500, "pages"]},
    {"id": "agent-wikis", "group": "world", "name": "Task and topic wikis", "kind": "semantic", "origin": "compiled by AI",
     "holds": "One wiki per mission or topic, built from its research results, each fact with its source. What a briefing draws on.",
     "writes": "the mission's own writer, after each result", "reads": "that mission at the start of each run, then the related wikis and search", "curator": "memory",
     "limit": [200, "pages per wiki"]},
    {"id": "repo-wikis", "group": "world", "name": "Repository wikis", "kind": "semantic", "origin": "compiled by AI, cites commits",
     "holds": "One wiki per repository: how it is built and tested, and what past changes taught. Each fact cites its commit.",
     "writes": "the Scribe, when a repository is onboarded and after each change", "reads": "the agents changing that repository", "curator": None,
     "limit": [200, "pages per wiki"], "tidy": "The Scribe checks a page against today's code; a page it cannot confirm is marked."},
    {"id": "journals", "group": "happened", "name": "Agent journals", "kind": "episodic", "origin": "written by each agent",
     "holds": "Each agent's own notebook: what it is in the middle of, lessons it keeps, its last runs.",
     "writes": "the runner, after each run", "reads": "that agent, at the start of each run", "curator": "memory", "limit": [20000, "bytes per journal"]},
    {"id": "mission-notes", "group": "happened", "name": "Old mission notes", "kind": "episodic", "origin": "being retired",
     "holds": "Notes from before journals existed. Each file moves into its mission's journal at that mission's next run.",
     "writes": "nobody any more", "reads": "that mission, until then", "curator": None, "limit": [0, "files"],
     "tidy": "Moved into the mission's journal at its next run."},
    {"id": "hindsight", "group": "you", "name": "Long-term memory", "kind": "semantic", "origin": "extracted by AI, no source shown",
     "holds": "Facts a model extracted from chats and, earlier, from agents' journals: about you, and much about other things (docs/MEMORY-TAB.md). You can search and forget them.",
     "writes": "your chats, through the gatekeeper; earlier also agents' journals", "reads": "your assistant, and every agent at the start of a run", "curator": "memory",
     "limit": [5000, "facts"]},
    {"id": "ledger", "group": "work", "name": "The Ledger", "kind": "shared", "origin": "the team's shared board",
     "holds": "Ideas, findings, evidence and your decisions with their reasons: what the agents are working on together.",
     "writes": "agents, the runner, you", "reads": "every swarm agent, at the start of a run", "curator": "checker", "limit": [200, "MB"]},
    {"id": "skills", "group": "how", "name": "Skills", "kind": "procedural", "origin": "written instructions", "href": "#/skills",
     "holds": "Instructions your assistant looks up for a particular job. Most came with Hermes; some it wrote itself.",
     "writes": "Hermes, the skill keeper", "reads": "your assistant, when a job calls for one", "curator": "curator", "limit": [100, "skills"]},
    {"id": "prompts", "group": "how", "name": "Agent instructions", "kind": "procedural", "origin": "versioned files",
     "holds": "Each agent's standing prompts. A changed prompt must first pass a replay of real cases.",
     "writes": "you, and agent changes you approve", "reads": "each agent, in every run", "curator": None, "limit": [200, "prompts"],
     "tidy": "Changed only through a landing, with a replay."},
    {"id": "run-records", "group": "happened", "name": "Run records", "kind": "episodic", "origin": "exact record",
     "holds": "Every step of every run, as it happened: what was read, called and written.",
     "writes": "every agent's runs", "reads": "you (run logs), the Health doctor, replay tests", "curator": None, "limit": [500, "MB"],
     "tidy": "A run's full events go after 90 days; its summary stays."},
    {"id": "qmd", "group": "find", "name": "Search index", "kind": "index", "origin": "holds no knowledge of its own",
     "holds": "What makes the wikis, sources, journals and specs searchable, by words and by meaning.",
     "writes": "the search service, from the vault", "reads": "every agent with vault search, and each run's opening", "curator": "memory", "limit": [ORPHAN_SHARE, "orphaned share"]},
    {"id": "task-handoffs", "group": "happened", "name": "Task hand-offs", "kind": "working", "origin": "exact record",
     "holds": "Each task step's result, which the steps after it build on.",
     "writes": "every task step", "reads": "the steps after it, the judge, the task page", "curator": None,
     "limit": [200, "MB"], "tidy": "Kept with its task, whose page shows them."},
    {"id": "hermes-memory", "group": "you", "name": "Your profile", "kind": "semantic", "origin": "from your chats",
     "holds": "A few lines your assistant sees in every prompt: how you like answers, your setup.",
     "writes": "your assistant, each write approved by the gatekeeper or by you", "reads": "your assistant, every turn", "curator": "memory-review",
     "limit": [4400, "characters"]},
    {"id": "code-graphs", "group": "find", "name": "Code graphs", "kind": "index", "origin": "built from the code",
     "holds": "Each repository's map of files, symbols and calls.",
     "writes": "rebuilt at each new commit", "reads": "the builder, your assistant, the code map", "curator": None,
     "limit": [1000, "MB"], "tidy": "Rebuilt from the code at each commit."},
    {"id": "chats", "group": "happened", "name": "Chats", "kind": "episodic", "origin": "exact record",
     "holds": "Your chats with your assistant in the app.", "writes": "you and your assistant",
     "reads": "you; long-term memory keeps what is worth keeping from them", "curator": None, "limit": [2000, "chats"],
     "tidy": "You delete a chat; what matters lives on in long-term memory."},
]
# what the run record can count: a store's use over USE_DAYS, by the tools that reach it
USE_DAYS = 14
USE = {"hindsight": ("Read", r"memory_recall|hindsight"), "qmd": ("Searched", r"qmd_|wiki_search|memory(public)?[_-]search"),
       "ledger": ("Read", r"swarm_context|ledger_(find|get)"), "skills": ("Opened", r"skill_view"), "code-graphs": ("Queried", r"graphify_"),
       "journals": ("Written", r"journal_write|agent_note|memory(public)?[_-]note")}
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
    return out + sorted(p for base in ("missions", "topics", "repos") for p in (VAULT / base).glob("*/wiki") if p.is_dir())


def measure(sid, now):
    """One store's numbers: {count, unit, bytes, parts, problems}."""
    week = now - 7 * 86400
    if sid == "vault-notes":
        f = md_files(VAULT / "raw")
        return {"count": len(f), "unit": "items", "bytes": sum(p.stat().st_size for p in f), "from_mail": sum("-mail-" in p.name for p in f)}
    if sid in ("vault-wiki", "agent-wikis"):
        dirs = [d for d in wiki_dirs() if (d == VAULT / "wiki") == (sid == "vault-wiki") and d.parent.parent != VAULT / "repos"]   # repository wikis are their own store
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
    if sid == "repo-wikis":
        parts = []
        for d in sorted((VAULT / "repos").glob("*/wiki")) if (VAULT / "repos").exists() else []:
            f = md_files(d)
            parts.append({"root": d.parent.name, "pages": len(f), "bytes": sum(p.stat().st_size for p in f)})
        return {"count": sum(p["pages"] for p in parts), "unit": "pages", "bytes": sum(p["bytes"] for p in parts), "parts": parts,
                "count_label": f"{len(parts)} wikis", "largest": max((p["pages"] for p in parts), default=0)}
    if sid == "prompts":
        f = sorted(PROMPTS.glob("**/*.md")) if PROMPTS.exists() else []
        return {"count": len(f), "unit": "prompts", "bytes": sum(p.stat().st_size for p in f)}
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
        q = "select t || '=' || n from (select coalesce(fact_type, '?') t, count(*) n from memory_units where bank_id = 'owner' group by 1) x order by 1"   # the owner's bank only: a trial has its own
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
        # each SKILL.md, not the folders: "ls" counted 13 categories while 63 skills were there (7 Nov 2026)
        out = sh("docker", "exec", "aistack-hermes-1", "sh", "-c", "find /opt/data/skills -name SKILL.md -not -path '*/.archive/*' | wc -l; du -sb /opt/data/skills | cut -f1").split()
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
    elif sid in ("agent-wikis", "repo-wikis"):
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
    elif sid in ("vault-wiki", "vault-notes", "skills", "prompts") and m["count"] > lim[0]:
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
    if sid in ("agent-wikis", "repo-wikis", "journals"):
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


def uses(now):
    """{store id: {verb, n}}: what the run record saw of each store over USE_DAYS; what it cannot count stays out."""
    try:
        c = sqlite3.connect(f"file:{RUNTIME_DB}?mode=ro", uri=True)
        rows = c.execute("select title, count(*) from events where ts>? and kind in ('call', 'read', 'tool') group by title", (now - USE_DAYS * 86400,)).fetchall()
    except sqlite3.Error:
        return {}
    return {sid: {"verb": verb, "n": sum(n for t, n in rows if re.search(pat, t or "")), "days": USE_DAYS} for sid, (verb, pat) in USE.items()}


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
    used = uses(now)
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
                    "curated": curated(s, crew, curator_last), "problems": problems(s, m), "over_since": since, "used": used.get(s["id"])})
    lib = {}
    try:
        lib = json.loads((PUBLIC / "librarian.json").read_text())
        lib.pop("read", None)                              # which page text it read and which pairs it kept apart: its own bookkeeping
        lib.pop("apart", None)
    except (FileNotFoundError, ValueError):
        pass
    return {"at": now, "groups": GROUPS, "stores": out, "librarian": lib or None}


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


def skill_catalog(now=None):
    """Every skill with its instructions, for the app's Skills page (public/skills.json): whether it came with Hermes, is archived, and how
    often it was opened over 30 days."""
    import yaml
    now = now or time.time()
    code = ("import json,pathlib\nb=pathlib.Path('/opt/data/skills');o=[]\n"
            "for f in sorted(b.rglob('SKILL.md')):\n"
            " d=f.parent;o.append({'path':str(d.relative_to(b)),'text':f.read_text(errors='replace'),'files':sorted(str(x.relative_to(d)) for x in d.rglob('*') if x.is_file() and x!=f)})\n"
            "m=b/'.bundled_manifest'\nprint(json.dumps({'skills':o,'bundled':[l.split(':')[0] for l in m.read_text().split()] if m.exists() else []}))")
    raw = json.loads(sh("docker", "exec", "aistack-hermes-1", "python3", "-c", code, timeout=120))
    opened = {}
    try:
        c = sqlite3.connect(f"file:{RUNTIME_DB}?mode=ro", uri=True)
        for (detail,) in c.execute("select detail from events where ts>? and kind='call' and title like '%skill_view%'", (now - 30 * 86400,)):
            m = re.search(r'"name":\s*"([^"]+)"', detail or "")
            if m:
                opened[m.group(1)] = opened.get(m.group(1), 0) + 1
    except sqlite3.Error:
        pass
    out = []
    for x in raw["skills"]:
        meta, body = {}, x["text"]
        if body.startswith("---"):
            head, _, rest = body[3:].partition("\n---")
            try:
                meta = yaml.safe_load(head) or {}
            except yaml.YAMLError:
                meta = {}
            body = rest.lstrip("\n") if rest else body
        path = x["path"]
        name = str(meta.get("name") or path.rsplit("/", 1)[-1])
        archived = path.startswith(".archive")
        parts = path.split("/")
        out.append({"path": path, "name": name, "category": "Archived" if archived else (parts[0] if len(parts) > 1 else "other"), "description": str(meta.get("description") or ""),
                    "version": str(meta.get("version") or ""), "author": str(meta.get("author") or ""), "platforms": meta.get("platforms") or [],
                    "archived": archived, "bundled": name in raw["bundled"] or path.rsplit("/", 1)[-1] in raw["bundled"],
                    "opened_30d": opened.get(name, 0), "files": x["files"], "body": body})
    return {"at": now, "skills": out}


def refresh(crew=None):
    try:
        inv = collect(crew)
        try:                                               # MEM-44, MEM-47: given and used per run kind, the trials' gate, for Stack -> Health
            import memstack as MS
            inv["stack"] = {k: v for k, v in MS.write_status().items() if k != "writes"}
        except Exception as e:
            inv["stack"] = {"error": f"{type(e).__name__}: {e}"}
        (PUBLIC / "memory.json").write_text(json.dumps(inv, default=str))
        try:
            (PUBLIC / "skills.json").write_text(json.dumps(skill_catalog(inv["at"])))
        except Exception as e:                             # the page says when its list could not be read; the inventory goes on
            (PUBLIC / "skills.json").write_text(json.dumps({"at": inv["at"], "skills": [], "error": f"{type(e).__name__}: {e}"}))
        if not any(h["date"] == dt.date.fromtimestamp(inv["at"]).isoformat() for h in history()):
            remember(inv)
        with _lock:
            _cache.update(t=time.time(), data=inv)
        try:                                               # MEM-22: the catalogue of collections, from the same stores
            import memstack as MS
            MS.write_catalogue()
        except Exception as e:
            print(f"memory: the catalogue could not be written: {type(e).__name__}: {e}", flush=True)
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

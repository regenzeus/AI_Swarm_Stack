"""A mission's files: the things the owner asked it to make (docs/DELIVERABLES.md, MIS-23 to MIS-26).

A run report says what a run did; a file is what the owner asked for (a document, a spec, a table). Files live outside
the vault's git, in /srv/ai/missions/files/<slug>/, so deleting one really frees its space (a file deleted from git
stays in its history). Each mission folder holds:
  <name>                         the current version
  .versions/<name>/<stamp>-<sha8> earlier versions (the newest KEEP_VERSIONS are kept)
  files.json                     the manifest: per file its size, words, checkboxes, run, versions, deliveries, pin;
                                 per run what it was asked for, what it saved and what is missing
A deleted file goes to .trash/ for TRASH_DAYS and can be restored; the daily cleanup also thins old versions and
moves the files of long-archived missions to the trash, unless pinned. The app shows it all on the Files page.
Writes come only through the runner (the app's requests, the mission agent's file_save tool): SEC-12.
"""
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import time
from pathlib import Path

M = None                                             # ops/missions.py, set by its main()
ROOT = Path(os.environ.get("FILES_DIR", "/srv/ai/missions/files"))
LEDGER = Path(os.environ.get("SWARM_DB", "/srv/ai/swarm/swarm.db"))
TYPES = {".md": "text/markdown", ".csv": "text/csv", ".json": "application/json", ".txt": "text/plain"}
# limit: refuses, one file a mission makes, with its size: split it (MIS-23)
MAX_BYTES = 2_000_000                                # one file; the e-mail's attachments together stay under ATTACH_MAX
# limit: refuses, a mail's attachments together: Gmail takes 25 MB, encoding adds a third
ATTACH_MAX = 20_000_000                              # Gmail takes 25 MB in all, the encoding adds a third
KEEP_VERSIONS = 5                                    # earlier versions kept per file
ARCHIVED_DAYS = 180                                  # an archived mission's files, untouched this long, go to the trash
TRASH_DAYS = 30                                      # the trash is emptied after this
QUOTA = int(os.environ.get("FILES_QUOTA", 2_000_000_000))   # the Files page's bar; past WARN_AT a notice
WARN_AT = 0.8
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
ACTIONS = {"file_save", "file_delete", "file_restore", "file_pin", "files_cleanup", "files_asked"}
_lock = threading.Lock()


class Refused(ValueError):
    """A request the store does not take, with a reason the agent or the owner can act on."""


def clean_name(name):
    """A file name as asked for: letters, digits, . _ -, one of the TYPES; anything else is refused with the reason."""
    n = str(name or "").strip().replace(" ", "-")
    ext = Path(n).suffix.lower()
    if ext not in TYPES:
        raise Refused(f"'{name}': the stack makes {', '.join(TYPES)} files only (no Word, PDF, images or archives); "
                      "offer Markdown instead")
    if not NAME.fullmatch(n) or n in (".", "..") or n.startswith(".") or n == "files.json":
        raise Refused(f"'{name}': a file name has letters, digits, '.', '_' or '-', at most 96 characters")
    return n


def asked_of(raw):
    """[{name, what}] from what the owner asked (a list of names or of {name, what}); bad names refused."""
    out, seen = [], set()
    for x in raw or []:
        name, what = (x.get("name"), x.get("what", "")) if isinstance(x, dict) else (x, "")
        n = clean_name(name)
        if n not in seen:
            seen.add(n)
            out.append({"name": n, "what": M.limit(str(what or ""), 500, "what the file is") if M else str(what or "")})
    # limit: refuses, files asked of one mission, with the limit (MIS-23)
    if len(out) > 20:
        raise Refused(f"{len(out)} files asked for; at most 20 per mission")
    return out


def folder(slug):
    if not SLUG.fullmatch(slug or ""):
        raise Refused(f"no mission '{slug}'")
    return ROOT / slug


def manifest(slug):
    try:
        return json.loads((folder(slug) / "files.json").read_text())
    except (OSError, ValueError):
        return {"files": {}, "runs": {}}


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _save_manifest(slug, man):
    _write(folder(slug) / "files.json", json.dumps(man, ensure_ascii=False, indent=1).encode())


def brief(m, plan=False):
    """What the mission's agent is told about the files asked of it (prompts/mission.md FILES, FILES_PLAN); "" if none."""
    asked = m.get("files_asked") or []
    if not asked:
        return ""
    lines = "\n".join(f"- {a['name']}" + (f": {a['what']}" if a.get("what") else "") for a in asked)
    if plan:
        return "\n" + M.P.text("mission", "FILES_PLAN").format(files=", ".join(a["name"] for a in asked))
    return "\n" + M.P.text("mission", "FILES").format(files=lines, slug=m["slug"])


def stats_of(text):
    """What a card shows about a text file: its words and, for a checkbox spec, its checkboxes."""
    return {"words": len(text.split()), "checkboxes": len(re.findall(r"^\s*[-*] \[[ xX]\]", text, re.M)),
            "sections": len(re.findall(r"^#{1,3} ", text, re.M))}


def ledger_body(aid):
    """A Ledger report's body, read-only (the mission agent drafts long documents there)."""
    c = sqlite3.connect(f"file:{LEDGER}?mode=ro", uri=True, timeout=10)
    try:
        r = c.execute("select body, kind from artifacts where id=?", (int(aid),)).fetchone()
    finally:
        c.close()
    if not r:
        raise Refused(f"no Ledger artifact #{aid}")
    return r[0] or ""


def running_run(slug):
    """(run id, started epoch) of this mission's run in progress, or (None, None): a file saved now belongs to it."""
    if M is None:
        return None, None
    with M.lock:
        cands = [dict(M.running)] + [dict(p) for p in M.parked.values()]
    for r in cands:
        if r.get("slug") == slug and r.get("id"):
            try:
                return r["id"], dt.datetime.fromisoformat(r["started"]).timestamp()
            except (KeyError, ValueError, TypeError):
                return r["id"], None
    return None, None


def save(slug, name, text=None, from_ledger=None, final=True, source="agent", now=None):
    """Write a file (a new version when it changed); -> its manifest entry."""
    n, now = clean_name(name), now or time.time()
    if text is None and from_ledger is None:
        raise Refused("give the file's text, or from_ledger=<Ledger report id>")
    body = ledger_body(from_ledger) if from_ledger is not None else str(text)
    data = body.encode("utf-8")
    # limit: refuses, as MAX_BYTES
    if len(data) > MAX_BYTES:
        raise Refused(f"'{n}' is {len(data):,} bytes; a file can have at most {MAX_BYTES:,}: split it")
    if not data.strip():
        raise Refused(f"'{n}' is empty")
    d, sha = folder(slug), hashlib.sha256(data).hexdigest()
    rid, _ = running_run(slug)
    with _lock:
        man = manifest(slug)
        e = man["files"].get(n) or {"name": n, "versions": [], "deliveries": [], "pinned": False, "created": now}
        cur = d / n
        if cur.exists() and e.get("sha") and e["sha"] != sha:     # the old version is kept before it is replaced
            stamp = dt.datetime.fromtimestamp(e.get("updated") or now).strftime("%Y%m%d-%H%M%S")
            old = d / ".versions" / n / f"{stamp}-{e['sha'][:8]}"
            _write(old, cur.read_bytes())
            e["versions"] = ([{"file": old.name, "sha": e["sha"], "size": e.get("size", 0), "ts": e.get("updated"), "run": e.get("run")}]
                             + e["versions"])
        if e.get("sha") != sha:
            _write(cur, data)
        e.update(sha=sha, size=len(data), updated=now, run=rid, final=bool(final), source=source,
                 from_ledger=int(from_ledger) if from_ledger is not None else None, type=TYPES[Path(n).suffix.lower()],
                 **stats_of(body))
        man["files"][n] = e
        if rid:
            r = man["runs"].setdefault(str(rid), {"saved": []})
            if n not in r["saved"]:
                r["saved"].append(n)
        _save_manifest(slug, man)
    return e


def check_run(m, rid=None, since=None):
    """At a run's delivery: the files asked for that this run saved, and those still missing. Recorded per run.
    -> {asked, saved, missing, attach: [(name, bytes, type)]}."""
    slug = m["slug"]
    asked = [a["name"] for a in m.get("files_asked") or []]
    if rid is None:
        rid, since = running_run(slug)
    with _lock:
        man = manifest(slug)
        files = man["files"]
        mine = [n for n, e in files.items() if (rid and e.get("run") == rid) or (since and (e.get("updated") or 0) >= since)]
        missing = [n for n in asked if n not in files]               # asked and never made, by this run or an earlier one
        if rid:
            man["runs"][str(rid)] = {"asked": asked, "saved": sorted(mine), "missing": missing, "ts": time.time()}
            _save_manifest(slug, man)
    attach, total = [], 0
    for n in sorted(mine):
        p = folder(slug) / n
        if p.exists() and total + p.stat().st_size <= ATTACH_MAX:
            attach.append((n, p.read_bytes(), files[n].get("type") or "text/plain"))
            total += p.stat().st_size
    return {"asked": asked, "saved": sorted(mine), "missing": missing, "attach": attach}


def record_delivery(slug, names, channel, ok, why=""):
    """Each file's own delivery record (the card's "E-mailed as attachment ✓")."""
    if not names:
        return
    with _lock:
        man = manifest(slug)
        for n in names:
            if n in man["files"]:
                man["files"][n]["deliveries"] = ([{"channel": channel, "ok": bool(ok), "ts": time.time(), "why": why}]
                                                 + man["files"][n].get("deliveries", []))[:20]  # cap: list (the 20 newest deliveries)
        _save_manifest(slug, man)


def _trash_dir():
    return ROOT / ".trash"


def delete(slug, name, why="deleted by the owner"):
    """To the trash (with its versions), restorable for TRASH_DAYS."""
    n = clean_name(name)
    with _lock:
        man = manifest(slug)
        e = man["files"].pop(n, None)
        if not e:
            raise Refused(f"no file '{n}' in this mission")
        tid = f"{int(time.time())}-{slug}-{n}"
        t = _trash_dir() / tid
        t.mkdir(parents=True, exist_ok=True)
        for src in (folder(slug) / n, folder(slug) / ".versions" / n):
            if src.exists():
                shutil.move(str(src), str(t / src.name if src.is_file() else t / ".versions"))
        (t / "entry.json").write_text(json.dumps({"slug": slug, "entry": e, "deleted": time.time(), "why": why}))
        _save_manifest(slug, man)
    return {"trash": tid}


def restore(tid):
    t = _trash_dir() / str(tid)
    if not re.fullmatch(r"\d+-[a-z0-9-]+-[A-Za-z0-9._-]+", str(tid)) or not (t / "entry.json").exists():
        raise Refused("not in the trash (emptied after 30 days)")
    info = json.loads((t / "entry.json").read_text())
    slug, e = info["slug"], info["entry"]
    with _lock:
        man = manifest(slug)
        if e["name"] in man["files"]:
            raise Refused(f"'{e['name']}' exists again in this mission; delete or rename that one first")
        d = folder(slug)
        d.mkdir(parents=True, exist_ok=True)
        if (t / e["name"]).exists():
            shutil.move(str(t / e["name"]), str(d / e["name"]))
        if (t / ".versions").exists():
            (d / ".versions").mkdir(exist_ok=True)
            shutil.move(str(t / ".versions"), str(d / ".versions" / e["name"]))
        man["files"][e["name"]] = e
        _save_manifest(slug, man)
        shutil.rmtree(t)
    return {"restored": e["name"], "slug": slug}


def pin(slug, name, on=True):
    with _lock:
        man = manifest(slug)
        n = clean_name(name)
        if n not in man["files"]:
            raise Refused(f"no file '{n}' in this mission")
        man["files"][n]["pinned"] = bool(on)
        _save_manifest(slug, man)
    return {"pinned": bool(on)}


def size_of(p):
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def trash_list(now=None):
    now, out = now or time.time(), []
    for t in sorted(_trash_dir().glob("*/entry.json")) if _trash_dir().exists() else []:
        try:
            info = json.loads(t.read_text())
        except (OSError, ValueError):
            continue
        out.append({"id": t.parent.name, "slug": info["slug"], "name": info["entry"]["name"], "deleted": info["deleted"],
                    "why": info.get("why", ""), "size": size_of(t.parent), "purge_at": info["deleted"] + TRASH_DAYS * 86400})
    return sorted(out, key=lambda x: -x["deleted"])


def cleanup(missions, dry=False, now=None):
    """The retention pass (daily, and on the owner's "Clean up now"): -> {"steps": [{what, slug, name, size}], "freed"}.
    1. versions beyond the newest KEEP_VERSIONS of a file are removed;
    2. an archived mission's unpinned files untouched for ARCHIVED_DAYS go to the trash;
    3. the trash is emptied of what was deleted more than TRASH_DAYS ago.
    dry=True only says what it would do (the app shows it before the owner confirms)."""
    now, steps = now or time.time(), []
    for d in sorted(ROOT.iterdir()) if ROOT.exists() else []:
        if d.name.startswith(".") or not d.is_dir():
            continue
        slug, man = d.name, manifest(d.name)
        for n, e in list(man["files"].items()):
            for v in e.get("versions", [])[KEEP_VERSIONS:]:
                steps.append({"what": "old version removed", "slug": slug, "name": n, "file": v["file"], "size": v.get("size", 0)})
            m = missions.get(slug)
            gone = m is None or m.get("status") == "archived"
            if gone and not e.get("pinned") and now - (e.get("updated") or now) > ARCHIVED_DAYS * 86400:
                steps.append({"what": f"to the trash (mission {'archived' if m else 'removed'}, untouched {ARCHIVED_DAYS} days)",
                              "slug": slug, "name": n, "size": size_of(d / n) + size_of(d / ".versions" / n)})
    for t in trash_list(now):
        if t["purge_at"] <= now:
            steps.append({"what": f"trash emptied (deleted over {TRASH_DAYS} days ago)", "slug": t["slug"], "name": t["name"],
                          "trash": t["id"], "size": t["size"]})
    if not dry:
        for s in steps:
            try:
                if s["what"] == "old version removed":
                    with _lock:
                        man = manifest(s["slug"])
                        e = man["files"].get(s["name"])
                        (folder(s["slug"]) / ".versions" / s["name"] / s["file"]).unlink(missing_ok=True)
                        if e:
                            e["versions"] = [v for v in e["versions"] if v["file"] != s["file"]]
                            _save_manifest(s["slug"], man)
                elif s["what"].startswith("to the trash"):
                    delete(s["slug"], s["name"], why=s["what"])
                else:
                    shutil.rmtree(_trash_dir() / s["trash"], ignore_errors=True)
            except (OSError, Refused) as e:
                s["error"] = f"{type(e).__name__}: {e}"
    return {"steps": steps, "freed": sum(s["size"] for s in steps if "error" not in s and not s["what"].startswith("to the trash")),
            "dry": dry}


def usage():
    per = {d.name: size_of(d) for d in ROOT.iterdir() if d.is_dir() and not d.name.startswith(".")} if ROOT.exists() else {}
    used, trash = sum(per.values()), size_of(_trash_dir())
    return {"used": used, "trash": trash, "quota": QUOTA, "pct": round(100 * (used + trash) / QUOTA, 1) if QUOTA else 0,
            "by_mission": per}


def state():
    """The Files page and each mission's Results: every mission's manifest, the trash, the storage use, the policy."""
    out = {}
    for d in sorted(ROOT.iterdir()) if ROOT.exists() else []:
        if d.is_dir() and not d.name.startswith("."):
            man = manifest(d.name)
            out[d.name] = {"files": sorted(man["files"].values(), key=lambda e: -(e.get("updated") or 0)),
                           "runs": dict(sorted(man["runs"].items(), key=lambda x: -int(x[0]))[:20])}  # cap: list (the 20 newest runs' checks)
    return {"files": {"missions": out, "trash": trash_list(), "usage": usage(), "last_cleanup": _last.get("result"),
                      "policy": {"keep_versions": KEEP_VERSIONS, "archived_days": ARCHIVED_DAYS, "trash_days": TRASH_DAYS,
                                 "max_bytes": MAX_BYTES, "types": sorted(TYPES)}}}


_last = {}


def handle(req):
    a = req.get("action")
    if a == "file_save":
        e = save(req.get("slug"), req.get("name"), req.get("text"), req.get("from_ledger"), req.get("final", True),
                 req.get("source", "agent"))
        return {"name": e["name"], "size": e["size"], "words": e["words"], "version": len(e["versions"]) + 1}
    if a == "file_delete":
        return delete(req.get("slug"), req.get("name"))
    if a == "file_restore":
        return restore(req.get("id"))
    if a == "file_pin":
        return pin(req.get("slug"), req.get("name"), req.get("on", True))
    if a == "files_cleanup":
        r = cleanup(M.load_missions(), dry=bool(req.get("dry")))
        if not r["dry"]:
            _last["result"] = {"ts": time.time(), "steps": len(r["steps"]), "freed": r["freed"], "by": "owner"}
        return r
    if a == "files_asked":                   # the files a mission must deliver (its page's Settings, or Hermes)
        ms = M.load_missions()
        m = ms.get(req.get("slug"))
        if not m:
            raise Refused(f"no mission '{req.get('slug')}'")
        m["files_asked"] = asked_of(req.get("files"))
        M.save_mission(m)
        M.vault_commit([f"missions/{m['slug']}"], f"mission: {m['slug']} files asked for")
        return {"files_asked": m["files_asked"]}
    raise Refused(f"unknown action '{a}'")


def worker():
    """Daily retention, and a notice when the files use most of their space."""
    while not M.stop.is_set():
        try:
            r = cleanup(M.load_missions())
            _last["result"] = {"ts": time.time(), "steps": len(r["steps"]), "freed": r["freed"], "by": "daily"}
            if r["steps"]:
                M.log(f"files: cleanup {len(r['steps'])} steps, {r['freed']:,} bytes freed")
            u = usage()
            if u["pct"] >= WARN_AT * 100:
                M.N.send(f"Mission files use {u['pct']} % of their {QUOTA / 1e9:.1f} GB. Open Files to clean up.", "system", by="stack",
                         key="files-quota", every=86400)
        except Exception as e:                       # logged; tried again tomorrow
            M.log(f"files: {type(e).__name__}: {e}")
        M.stop.wait(86400)


def start():
    threading.Thread(target=worker, daemon=True, name="files").start()

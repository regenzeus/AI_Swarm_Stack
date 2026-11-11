"""Records, links and measures (REC-01 to REC-08, docs/AI-STACK.md §6): a read cache of a deployment's tracker of
record, typed by the deployment's pack, with typed links both ways, the queries a review asks and the measures the pack
declares. The stack names no record type, link type or measure: the pack does (records.yaml), and the tests use the toy
pack's and a stand-in Jira.

A tracker in trackers.yaml names the pack whose records it holds (`records: <pack>`); such a tracker is often read-only
(`write: off`, trackers.py) and starts no run when it names no workflow. The pack's records.yaml:

    fields:     {<name>: <the tracker's field id>}   the fields the cache keeps (summary is the title; nothing else is kept)
    types:      {<id>: {name, match: {issue_type, label}, template, fields: [required], needs: [{type, link}], links: [required]}}
    links:      {<id>: {name, inverse, said: [phrases], said_back: [phrases]}}
    gates:      [{type, to, role}]                 status changes only the role's holder approves
    measures:   [{id, name, share|count|duration: {...}, about}]

An item is the first type whose match it meets (issue type and label, in the file's order). A link is what the item's
page says ("is tested by DEMO-5"): a phrase in `said` is a link from the item, one in `said_back` a link to it, so each
link is kept once whichever of its two items was read, and asked from either end. A type's work products (`needs`) are
records of a type linked by a link type; its `fields` and `links` must be there too. A measure is computed from the cache
on every pass, never typed: a share (of: <filter>, where: <filter>), a count, or a duration (from, to: created, updated,
resolved or {status: <name>}; stat: median, mean or max), each optionally per field values (by), and each number keeps
the records behind it. A filter is type, status, label, field: {name: value}, has: [fields], link: <id> or {type, to,
direction}, complete: true|false, not: <filter> and any: [<filter>], all of its keys together.

One way: the cache reads (trackers' changes, record) and never writes to the tracker. Its store is SQLite under
/srv/ai/state/records (WAL; AISTACK_RECORDS); the app's Measures view reads the view the poller writes beside the
runner's state (public/records.json; AISTACK_RECORDS_VIEW). A new pack commit whose records.yaml differs reads its
tracker again from the start.

The gated transition hook (REC-08, ops/domain/AGENTS.md): a transition write of the stack to a status the pack gates
(trackers.write) asks check_transition(). The Ask system registers its gate once with set_gate(fn): fn(need) gets
{id, gate: True, tracker, key, type, to, role, question} and answers {state: approved|waiting|refused, person, role, chip,
ask, at, why}. Only state approved with chip true (an explicit tap, never words, a default, a rule or a digest) by a
person who holds the role (domain/roles.py) lets the write through; with no gate registered every gated transition is
refused with the reason.

    sync(cfg)                      one pass over the trackers that name records -> {tracker: {read, problem}}
    missing_work_products(tracker) records whose type needs a linked record it lacks
    missing_link(tracker, link)    records missing a link of that type (of the types that need it, else all typed)
    links_of(tracker, key)         its links both ways
    measures(tracker)              each measure with the records behind its numbers
    view(cfg) / refresh(cfg)       what the app shows / a pass and the view written
    gate_of, check_transition, set_gate   the gated transition hook

    python3 ops/domain/records.py sync|view|measures [tracker]|missing [tracker] [link]
"""
import contextlib
import datetime as dt
import hashlib
import json
import os
import sqlite3
import statistics
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import statefile as SF  # noqa: E402
import textcap as TC  # noqa: E402

TITLE_CHARS = 300                          # cap: store, a record's title in the cache; the whole is in the tracker
FIELD_CHARS = 2000                         # cap: store, one field's value in the cache; the whole is in the tracker
TEMPLATE_CHARS = 20000                     # cap: store, a type's template as the app shows it; the whole is in the pack
DB_WAIT_S = 30                             # limit: waits, a pass waits 30 s for another writer of the cache, then fails with the reason; the next pass reads again
KINDS = ("share", "count", "duration")
FILTERS = {"type", "status", "label", "field", "has", "link", "complete", "not", "any"}
POINTS = ("created", "updated", "resolved")
STATS = ("median", "mean", "max")
SCHEMA = """
create table if not exists records (tracker text, key text, type text, issue_type text, title text, status text,
  labels text, fields text, created text, updated text, resolved text, history text, synced text, primary key (tracker, key));
create table if not exists links (tracker text, src text, link text, dst text, seen_from text,
  primary key (tracker, src, link, dst, seen_from));
create table if not exists cursors (tracker text primary key, cursor text, sig text, synced text);
create table if not exists gates (tracker text, key text, to_status text, role text, person text, ask text, at text);
"""


def path():
    return Path(os.environ.get("AISTACK_RECORDS") or "/srv/ai/state/records/records.db")


def view_path():
    return Path(os.environ.get("AISTACK_RECORDS_VIEW") or "/srv/ai/missions/public/records.json")


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


@contextlib.contextmanager
def _db(p=None):
    p = Path(p or path())
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=DB_WAIT_S)                 # limit: waits, DB_WAIT_S above
    try:
        c.execute("pragma journal_mode=wal")
        c.executescript(SCHEMA)
        yield c
        c.commit()
    finally:
        c.close()


# ---------- the pack's declaration ----------
def _list(v):
    return [str(x) for x in (v if isinstance(v, list) else [v] if v not in (None, "") else [])]


def declared(where):
    """A pack's records.yaml (the pack's folder or the file) -> its declaration with its problems; None without one."""
    p = Path(where)
    f = p / "records.yaml" if p.is_dir() else p
    if not f.is_file():
        return None
    try:
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        return {"types": {}, "links": {}, "fields": {}, "gates": [], "measures": [], "problems": [f"records.yaml: {type(e).__name__}: {e}"]}
    return _checked(d if isinstance(d, dict) else {}, f.parent)


def _checked(d, folder):
    problems = []
    fields = {str(k): str(v or k) for k, v in (d.get("fields") or {}).items()}
    fields.setdefault("summary", "summary")
    links = {}
    for lid, v in (d.get("links") or {}).items():
        v = v or {}
        links[str(lid)] = {"id": str(lid), "name": str(v.get("name") or lid), "inverse": str(v.get("inverse") or f"{v.get('name') or lid} (back)"),
                           "said": [x.lower() for x in _list(v.get("said"))], "said_back": [x.lower() for x in _list(v.get("said_back"))]}
        if not links[str(lid)]["said"] and not links[str(lid)]["said_back"]:
            problems.append(f"links.{lid}: it names no phrase (said, said_back) a tracker shows it by")
    types = {}
    for tid, v in (d.get("types") or {}).items():
        v = v or {}
        m = v.get("match") or {}
        t = {"id": str(tid), "name": str(v.get("name") or tid), "match": {"issue_type": [x.lower() for x in _list(m.get("issue_type"))],
                                                                          "label": [x.lower() for x in _list(m.get("label"))]},
             "fields": _list(v.get("fields")), "links": _list(v.get("links")), "template": "",
             "needs": [{"type": str(n.get("type") or ""), "link": str(n.get("link") or ""), "direction": str(n.get("direction") or "any")}
                       for n in v.get("needs") or [] if isinstance(n, dict)]}
        if not t["match"]["issue_type"] and not t["match"]["label"]:
            problems.append(f"types.{tid}: its match names no issue type or label")
        if v.get("template"):
            tf = (folder / str(v["template"])).resolve()
            if not tf.is_relative_to(folder.resolve()) or not tf.is_file():
                problems.append(f"types.{tid}: its template {v['template']} is not a file of the pack")
            else:
                t["template"] = TC.cut(tf.read_text(encoding="utf-8"), TEMPLATE_CHARS, "the whole template is in the pack")   # cap: store, TEMPLATE_CHARS above
        types[str(tid)] = t
    for t in types.values():
        problems += [f"types.{t['id']}: field {f} is not in fields" for f in t["fields"] if f not in fields]
        problems += [f"types.{t['id']}: link {x} is not in links" for x in t["links"] if x not in links]
        for n in t["needs"]:
            if n["type"] not in types or n["link"] not in links or n["direction"] not in ("out", "in", "any"):
                problems.append(f"types.{t['id']}: a need is a type and a link of this file (direction out, in or any), not {n}")
    gates = [{"type": str(g.get("type") or ""), "to": str(g.get("to") or ""), "role": str(g.get("role") or "owner")}
             for g in d.get("gates") or [] if isinstance(g, dict)]
    problems += [f"gates: {g['type'] or '?'} to {g['to'] or '?'}: a gate names a type of this file and a status" for g in gates
                 if g["type"] not in types or not g["to"]]
    decl = {"types": types, "links": links, "fields": fields, "gates": gates, "measures": [], "problems": problems}
    seen = set()
    for m in d.get("measures") or []:
        m = m if isinstance(m, dict) else {}
        kind = next((k for k in KINDS if k in m), "")
        mid = str(m.get("id") or "")
        if not mid or mid in seen or not kind or not isinstance(m.get(kind), dict):
            problems.append(f"measures: {mid or '?'}: a measure has an id of its own and one of {', '.join(KINDS)}")
            continue
        seen.add(mid)
        spec = m[kind]
        bad = _filter_problems(spec.get("of") or {}, decl) + (_filter_problems(spec.get("where") or {}, decl) if kind == "share" else [])
        bad += [f"by {b} is not a field, status or type" for b in _list(spec.get("by")) if b not in fields and b not in ("status", "type")]
        if kind == "duration":
            bad += [f"{k} is created, updated, resolved or {{status: <name>}}" for k in ("from", "to") if not _point_ok(spec.get(k))]
            bad += [f"stat is {', '.join(STATS)}"] if spec.get("stat", "median") not in STATS else []
        problems += [f"measures.{mid}: {b}" for b in bad]
        decl["measures"].append({"id": mid, "name": str(m.get("name") or mid), "kind": kind, "spec": spec, "about": str(m.get("about") or "")})
    return decl


def _point_ok(p):
    return p in POINTS or isinstance(p, dict) and set(p) == {"status"} and bool(_list(p["status"]))


def _filter_problems(f, decl):
    if not isinstance(f, dict):
        return [f"a filter is a mapping, not {f!r}"]
    bad = [f"{k} is not a filter ({', '.join(sorted(FILTERS))})" for k in f if k not in FILTERS]
    bad += [f"type {x} is not in types" for x in _list(f.get("type")) if x not in decl["types"]]
    bad += [f"field {x} is not in fields" for x in list((f.get("field") or {}).keys()) + _list(f.get("has")) if x not in decl["fields"]]
    if "link" in f:
        lk = f["link"] if isinstance(f["link"], dict) else {"type": f["link"]}
        bad += [f"link {lk.get('type')} is not in links"] if lk.get("type") not in decl["links"] else []
        bad += [f"link to {lk['to']} is not in types"] if lk.get("to") and lk["to"] not in decl["types"] else []
    for k in ("not",):
        if k in f:
            bad += _filter_problems(f[k], decl)
    for x in f.get("any") or []:
        bad += _filter_problems(x, decl)
    return bad


def signature(decl):
    return hashlib.sha1(json.dumps(decl, sort_keys=True).encode()).hexdigest()[:16]   # cap: id, the declaration's hash names it


def decl_of(t, packs=None):
    """The declaration of the pack a tracker names (records: <pack>) -> (declaration, "") or (None, why)."""
    name = str(t.get("records") or "")
    if packs is None:
        from domain import packs as PK
        packs = PK.load()["packs"]
    p = next((p for p in packs if p["name"] == name), None)
    if not p:
        return None, f"{t.get('name')}: its records come from the pack {name}, which does not run in this deployment"
    d = p.get("records") if "records" in p else declared(p["dir"])
    if not d:
        return None, f"{t.get('name')}: the pack {name} declares no records (records.yaml)"
    if d["problems"]:
        return None, f"{t.get('name')}: the pack {name}'s records.yaml: {d['problems'][0]}"
    return d, ""


# ---------- reading: one way ----------
def classify(decl, raw):
    """The record type an item is: the first type of the declaration whose match it meets, or ""."""
    it, labels = str(raw.get("issue_type") or "").lower(), {str(x).lower() for x in raw.get("labels") or []}
    for t in decl["types"].values():
        m = t["match"]
        if (m["issue_type"] or m["label"]) and (not m["issue_type"] or it in m["issue_type"]) and (not m["label"] or labels & set(m["label"])):
            return t["id"]
    return ""


def value(v):
    """A field's value as text: a select's value or name, a list joined, empty as ""."""
    if v is None:
        return ""
    if isinstance(v, dict):
        return str(v.get("value") or v.get("name") or v.get("displayName") or v.get("key") or "")
    if isinstance(v, list):
        return ", ".join(x for x in (value(i) for i in v) if x)
    return str(v).strip()


def edges(decl, key, links):
    """An item's links as its page shows them -> (from, link type, to) of the declared link types."""
    out = set()
    for x in links or []:
        said, other = str(x.get("as") or "").lower(), str(x.get("key") or "")
        for lk in decl["links"].values():
            if said in lk["said"]:
                out.add((key, lk["id"], other))
            elif said in lk["said_back"]:
                out.add((other, lk["id"], key))
    return sorted(out)


def sync(cfg=None, ad=None, packs=None, db=None):
    """One pass, one way: each tracker that names its pack's records reads the items changed since its own cursor
    (apart from the poller's) and keeps each as a record: its type, status, title, the declared fields, its status
    history and its links. Nothing is written to the tracker. -> {tracker: {read, problem}}."""
    from domain import trackers as TR
    cfg = cfg or TR.config()
    out = {}
    for t in cfg["trackers"]:
        if not t.get("records") or TR.refused(t):
            continue
        name = t["name"]
        decl, why = decl_of(t, packs)
        if why:
            out[name] = {"read": 0, "problem": why}
            continue
        a = (ad or {}).get(name) or TR.adapter(t)
        sig = signature(decl)
        with _db(db) as c:
            row = c.execute("select cursor, sig from cursors where tracker=?", (name,)).fetchone()
        cursor = json.loads(row[0]) if row and row[1] == sig else ""
        try:
            items, cursor = a.changes(cursor)
            got = [a.record(i["key"]) for i in items]
        except Exception as e:                             # the tracker away or refusing: the cursor stays, the next pass reads again
            out[name] = {"read": 0, "problem": f"{name}: {type(e).__name__}: {e}"}
            continue
        with _db(db) as c:
            if not row or row[1] != sig:                    # a new declaration reads the tracker again from its start
                c.execute("delete from records where tracker=?", (name,))
                c.execute("delete from links where tracker=?", (name,))
            for raw in got:
                _keep(c, name, decl, raw)
            c.execute("insert or replace into cursors values (?,?,?,?)", (name, json.dumps(cursor), sig, _now()))
        out[name] = {"read": len(got), "problem": ""}
    return out


def _keep(c, tracker, decl, raw):
    key = str(raw["key"])
    f = raw.get("fields") or {}
    fields = {n: TC.cut(value(raw.get("title") if src == "summary" and "summary" not in f else f.get(src)), FIELD_CHARS, "the whole is in the tracker")   # cap: store, FIELD_CHARS above
              for n, src in decl["fields"].items()}
    hist = sorted(({"to": str(h.get("to") or ""), "at": str(h.get("at") or "")} for h in raw.get("history") or []), key=lambda h: h["at"])
    c.execute("insert or replace into records values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (tracker, key, classify(decl, raw), str(raw.get("issue_type") or ""), TC.cut(str(raw.get("title") or ""), TITLE_CHARS),   # cap: store, TITLE_CHARS above
               str(raw.get("status") or ""), json.dumps(list(raw.get("labels") or [])), json.dumps(fields), str(raw.get("created") or ""),
               str(raw.get("updated") or ""), str(raw.get("resolved") or ""), json.dumps(hist), _now()))
    c.execute("delete from links where tracker=? and seen_from=?", (tracker, key))
    c.executemany("insert or replace into links values (?,?,?,?,?)", [(tracker, s, lk, d, key) for s, lk, d in edges(decl, key, raw.get("links"))])


# ---------- the cache, asked ----------
def _t(s):
    from domain import trackers as TR
    try:
        d = TR._when(s)
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


class Cache:
    """One tracker's records and links as the last pass kept them, asked with its pack's declaration."""

    def __init__(self, tracker, decl, db=None):
        self.tracker, self.decl = tracker, decl
        with _db(db) as c:
            cols = ("key", "type", "issue_type", "title", "status", "labels", "fields", "created", "updated", "resolved", "history")
            self.recs = {r[0]: dict(zip(cols, r)) for r in c.execute(f"select {', '.join(cols)} from records where tracker=? order by key", (tracker,))}
            self.edges = sorted({tuple(r) for r in c.execute("select src, link, dst from links where tracker=?", (tracker,))})
            row = c.execute("select synced from cursors where tracker=?", (tracker,)).fetchone()
            self.gates = [dict(zip(("key", "to", "role", "person", "ask", "at"), r))
                          for r in c.execute("select key, to_status, role, person, ask, at from gates where tracker=? order by at", (tracker,))]
        self.synced = row[0] if row else ""
        for r in self.recs.values():
            r["labels"], r["fields"], r["history"] = json.loads(r["labels"]), json.loads(r["fields"]), json.loads(r["history"])

    def typed(self):
        return [k for k, r in self.recs.items() if r["type"]]

    def type_of(self, key):
        return (self.recs.get(key) or {}).get("type", "")

    def linked(self, key, link, to_type=None, direction="any"):
        """The keys linked to key by that link type: out (key -> other), in (other -> key) or any."""
        got = [d for s, lk, d in self.edges if lk == link and s == key and direction in ("out", "any")]
        got += [s for s, lk, d in self.edges if lk == link and d == key and direction in ("in", "any")]
        return sorted({k for k in got if not to_type or self.type_of(k) == to_type})

    def both_ways(self, key):
        names = self.decl["links"]
        out = [{"link": lk, "name": names[lk]["name"], "key": d, "known": d in self.recs} for s, lk, d in self.edges if s == key and lk in names]
        back = [{"link": lk, "name": names[lk]["inverse"], "key": s, "known": s in self.recs} for s, lk, d in self.edges if d == key and lk in names]
        return {"out": out, "in": back}

    def missing_fields(self, key):
        r = self.recs[key]
        t = self.decl["types"].get(r["type"]) or {}
        return [f for f in t.get("fields") or [] if not str(r["fields"].get(f) or "").strip()]

    def missing_needs(self, key):
        t = self.decl["types"].get(self.type_of(key)) or {}
        return [n for n in t.get("needs") or [] if not self.linked(key, n["link"], n["type"], n["direction"])]

    def missing_links(self, key):
        t = self.decl["types"].get(self.type_of(key)) or {}
        return [x for x in t.get("links") or [] if not self.linked(key, x)]

    def complete(self, key):
        return not (self.missing_fields(key) or self.missing_needs(key) or self.missing_links(key))

    def match(self, key, f):
        r = self.recs[key]
        low = lambda v: {x.lower() for x in _list(v)}                         # noqa: E731
        if "type" in f and r["type"] not in _list(f["type"]):
            return False
        if "status" in f and r["status"].lower() not in low(f["status"]):
            return False
        if "label" in f and not ({x.lower() for x in r["labels"]} & low(f["label"])):
            return False
        if any(str(r["fields"].get(k) or "").lower() not in low(v) for k, v in (f.get("field") or {}).items()):
            return False
        if any(not str(r["fields"].get(k) or "").strip() for k in _list(f.get("has"))):
            return False
        if "link" in f:
            lk = f["link"] if isinstance(f["link"], dict) else {"type": f["link"]}
            if not self.linked(key, lk["type"], lk.get("to"), lk.get("direction") or "any"):
                return False
        if "complete" in f and self.complete(key) != bool(f["complete"]):
            return False
        if "not" in f and self.match(key, f["not"]):
            return False
        return not f.get("any") or any(self.match(key, x) for x in f["any"])

    def point(self, key, p):
        """When a record reached a point: created, updated, resolved, or its first entry into a status."""
        r = self.recs[key]
        if p in POINTS:
            return _t(r[p]) if r[p] else None
        want = {x.lower() for x in _list(p["status"])}
        hit = next((h["at"] for h in r["history"] if h["to"].lower() in want), "")
        if not hit and not r["history"] and r["status"].lower() in want:   # made in that status: no change led there
            hit = r["created"]
        return _t(hit) if hit else None


def _row(c, key):
    r = c.recs[key]
    t = c.decl["types"].get(r["type"]) or {}
    return {"key": key, "title": r["title"], "type": r["type"], "type_name": t.get("name", ""), "status": r["status"]}


def cache(tracker, cfg=None, packs=None, db=None):
    from domain import trackers as TR
    t = TR.find(tracker, cfg)
    if not t or not t.get("records"):
        raise ValueError(f"no tracker {tracker!r} with records in this deployment's trackers.yaml")
    decl, why = decl_of(t, packs)
    if why:
        raise ValueError(why)
    return Cache(tracker, decl, db)


def missing_work_products(tracker, cfg=None, packs=None, db=None, c=None):
    """The records whose type needs a work product (a record of a type, linked by a link type) they lack."""
    c = c or cache(tracker, cfg, packs, db)
    L, T = c.decl["links"], c.decl["types"]
    return [{**_row(c, k), "missing": [{**n, "type_name": T[n["type"]]["name"], "link_name": L[n["link"]]["name"]} for n in c.missing_needs(k)]}
            for k in c.typed() if c.missing_needs(k)]


def missing_fields(tracker, cfg=None, packs=None, db=None, c=None):
    c = c or cache(tracker, cfg, packs, db)
    return [{**_row(c, k), "missing": c.missing_fields(k)} for k in c.typed() if c.missing_fields(k)]


def missing_link(tracker, link, types=None, cfg=None, packs=None, db=None, c=None):
    """The records missing a link of that type, in either direction: of the types given, else of the types whose
    declaration needs it, else of every type."""
    c = c or cache(tracker, cfg, packs, db)
    if link not in c.decl["links"]:
        raise ValueError(f"{link} is not a link type of this pack ({', '.join(c.decl['links'])})")
    scope = _list(types) or [t["id"] for t in c.decl["types"].values() if link in t["links"]] or list(c.decl["types"])
    return [_row(c, k) for k in c.typed() if c.type_of(k) in scope and not c.linked(k, link)]


def links_of(tracker, key, cfg=None, packs=None, db=None):
    return cache(tracker, cfg, packs, db).both_ways(key)


# ---------- measures: computed, never typed ----------
def _cell(c, m, keys):
    s = m["spec"]
    if m["kind"] == "count":
        return {"value": len(keys), "n": len(keys), "counted": keys}
    if m["kind"] == "share":
        num = [k for k in keys if c.match(k, s.get("where") or {})]
        return {"value": round(len(num) / len(keys), 4) if keys else None, "n": len(num), "of": len(keys), "counted": num,
                "not_counted": [k for k in keys if k not in num]}
    rows, still = [], []
    for k in keys:
        a, b = c.point(k, s["from"]), c.point(k, s["to"])
        if a and b:
            rows.append({"key": k, "hours": round((b - a).total_seconds() / 3600, 2)})
        else:
            still.append(k)
    hs = [r["hours"] for r in rows]
    stat = {"median": statistics.median, "mean": statistics.fmean, "max": max}[s.get("stat", "median")]
    return {"value": round(stat(hs), 2) if hs else None, "n": len(rows), "unit": "hours", "stat": s.get("stat", "median"), "rows": rows, "open": still}


def _by(c, keys, by):
    groups = {}
    for k in keys:
        r = c.recs[k]
        label = " · ".join((r[b] if b in ("status", "type") else str(r["fields"].get(b) or "")) or "(none)" for b in by)
        groups.setdefault(label, []).append(k)
    return sorted(groups.items())


def _words(f, c):
    """A filter in plain words, for a measure's About."""
    T, L = c.decl["types"], c.decl["links"]
    w = []
    if "type" in f:
        w.append(" or ".join(T[x]["name"] for x in _list(f["type"])))
    if "status" in f:
        w.append("in status " + " or ".join(_list(f["status"])))
    if "label" in f:
        w.append("labelled " + " or ".join(_list(f["label"])))
    w += [f"with {k} {' or '.join(_list(v))}" for k, v in (f.get("field") or {}).items()]
    w += [f"with {k} filled in" for k in _list(f.get("has"))]
    if "link" in f:
        lk = f["link"] if isinstance(f["link"], dict) else {"type": f["link"]}
        w.append(f"linked as {L[lk['type']]['name']}" + (f" to a {T[lk['to']]['name']}" if lk.get("to") else ""))
    if "complete" in f:
        w.append("with every required field, work product and link" if f["complete"] else "missing a required field, work product or link")
    if "not" in f:
        w.append(f"not {_words(f['not'], c)}")
    if f.get("any"):
        w.append("either " + " or ".join(_words(x, c) for x in f["any"]))
    return ", ".join(w) or "every record"


def _about(m, c):
    if m["about"]:
        return m["about"]
    s = m["spec"]
    by = f", per {' and '.join(_list(s.get('by')))}" if s.get("by") else ""
    if m["kind"] == "count":
        return f"How many records are {_words(s.get('of') or {}, c)}{by}."
    if m["kind"] == "share":
        return f"Of the records {_words(s.get('of') or {}, c)}, the share {_words(s.get('where') or {}, c)}{by}."
    pt = lambda p: p if p in POINTS else f"first in {' or '.join(_list(p['status']))}"   # noqa: E731
    return f"The {s.get('stat', 'median')} hours from {pt(s['from'])} to {pt(s['to'])}, of the records {_words(s.get('of') or {}, c)}{by}."


def measures(tracker, cfg=None, packs=None, db=None, c=None):
    """Each measure of the pack over the cache: its value, the records behind it, per group when it has a by."""
    c = c or cache(tracker, cfg, packs, db)
    out = []
    for m in c.decl["measures"]:
        keys = [k for k in c.typed() if c.match(k, m["spec"].get("of") or {})]
        by = _list(m["spec"].get("by"))
        out.append({"id": m["id"], "name": m["name"], "kind": m["kind"], "about": _about(m, c), **_cell(c, m, keys),
                    "groups": [{"group": g, **_cell(c, m, ks)} for g, ks in _by(c, keys, by)] if by else []})
    return out


# ---------- the gated transition hook (U's gate asks; REC-08) ----------
_GATE = None


def set_gate(fn):
    """The Ask system's gate: fn(need) -> {state, person, role, chip, ask, at, why}. None takes it away."""
    global _GATE
    _GATE = fn


def gate_of(tracker, key, to, cfg=None, packs=None, db=None):
    """The gate a transition of the stack meets, or None: the pack gates the status for the record's type (a record the
    cache does not hold yet meets every gate on that status). A pack that cannot be read gates every status for the owner."""
    from domain import trackers as TR
    t = TR.find(tracker, cfg)
    if not t or not t.get("records"):
        return None
    need = {"id": f"gate:{tracker}/{key}/{to}", "gate": True, "tracker": tracker, "key": key, "to": str(to),
            "question": f"May {key} move to {to}?"}
    decl, why = decl_of(t, packs)
    if why:
        return {**need, "type": "", "role": "owner", "why": why}
    hits = [g for g in decl["gates"] if g["to"].lower() == str(to).lower()]
    if not hits:
        return None
    with _db(db) as c:
        row = c.execute("select type from records where tracker=? and key=?", (tracker, str(key))).fetchone()
    hits = [g for g in hits if row is None or g["type"] == row[0]]
    return {**need, "type": hits[0]["type"], "role": hits[0]["role"]} if hits else None


def check_transition(tracker, key, to, cfg=None, packs=None, db=None, roles=None):
    """{ok: True} when the stack may write this transition, else {ok: False, gate: need, why}. Only the registered
    gate's approval by a chip of a person holding the role lets a gated one through; it is kept in the cache's gates."""
    need = gate_of(tracker, key, to, cfg, packs, db)
    if not need:
        return {"ok": True}
    role = need["role"]
    if _GATE is None:
        return {"ok": False, "gate": need, "why": f"moving {key} to {to} needs the approval of the role {role}, and no gate is set up to ask for it"}
    a = _GATE(need) or {}
    if a.get("state") != "approved":
        return {"ok": False, "gate": need, "why": f"moving {key} to {to} waits for the approval of the role {role}" + (f": {a['why']}" if a.get("why") else "")}
    if a.get("chip") is not True or a.get("interpreted_as") or a.get("by_default") or a.get("rule"):
        return {"ok": False, "gate": need, "why": "only a tap on the approving choice by the role's holder approves a gate; words, a default or a rule never do"}
    from domain import roles as R
    person = str(a.get("person") or "")
    if not R.may(role, person, roles):
        return {"ok": False, "gate": need, "why": f"{person or 'nobody'} does not hold the role {role}: only {', '.join(R.people(role, roles))} may approve"}
    with _db(db) as c:
        c.execute("insert into gates values (?,?,?,?,?,?,?)", (tracker, str(key), str(to), role, person, str(a.get("ask") or ""), str(a.get("at") or _now())))
    return {"ok": True, "approved": {"person": person, "role": role, "ask": a.get("ask")}}


# ---------- the app's view ----------
def _tracker_view(t, c):
    T, L = c.decl["types"], c.decl["links"]
    iso = lambda s: (_t(s).isoformat() if s and _t(s) else "")             # noqa: E731  a time the app's browser reads (Jira's +0100 is not ISO)
    recs = {}
    for k, r in c.recs.items():
        recs[k] = {**_row(c, k), "created": iso(r["created"]), "updated": iso(r["updated"]), "resolved": iso(r["resolved"]),
                   "history": [{"to": h["to"], "at": iso(h["at"])} for h in r["history"]],
                   "fields": [{"name": f, "value": r["fields"].get(f, ""), "required": f in (T.get(r["type"]) or {}).get("fields", [])}
                              for f in c.decl["fields"] if f != "summary"],
                   "missing": {"fields": c.missing_fields(k) if r["type"] else [],
                               "needs": [{**n, "type_name": T[n["type"]]["name"], "link_name": L[n["link"]]["name"]} for n in c.missing_needs(k)] if r["type"] else [],
                               "links": c.missing_links(k) if r["type"] else []},
                   "gates": [g for g in c.gates if g["key"] == k], **c.both_ways(k)}
    url = str(t.get("url") or "").rstrip("/")
    return {"name": t["name"], "pack": t["records"], "kind": t["kind"], "read_only": t.get("write", True) in (False, "off"),
            "browse": f"{url}/browse/" if t["kind"] == "jira" and url else "", "synced": c.synced,
            "types": [{**{k: x[k] for k in ("id", "name", "fields", "links", "template")}, "n": sum(1 for r in c.recs.values() if r["type"] == x["id"]),
                       "needs": [{**n, "type_name": T[n["type"]]["name"], "link_name": L[n["link"]]["name"]} for n in x["needs"]]} for x in T.values()],
            "links": [{"id": x["id"], "name": x["name"], "inverse": x["inverse"],
                       "needed_by": [y["id"] for y in T.values() if x["id"] in y["links"]]} for x in L.values()],
            "gates": c.decl["gates"], "records": recs, "untyped": len(c.recs) - len(c.typed()),
            "measures": measures(t["name"], c=c), "missing_work_products": missing_work_products(t["name"], c=c),
            "missing_fields": missing_fields(t["name"], c=c),
            "missing_links": {lk: [x["key"] for x in missing_link(t["name"], lk, c=c)] for lk in L}}


def view(cfg=None, packs=None, db=None):
    """What the Measures view shows, per tracker that names records: its types, links, gates, records, the two
    queries and the measures with the records behind each; a tracker whose pack cannot be read says why."""
    from domain import trackers as TR
    cfg = cfg or TR.config()
    out = []
    for t in cfg["trackers"]:
        if not t.get("records"):
            continue
        why = TR.refused(t)
        decl, why = (None, why) if why else decl_of(t, packs)
        if why:
            out.append({"name": t["name"], "pack": t["records"], "problem": why})
            continue
        out.append(_tracker_view(t, Cache(t["name"], decl, db)))
    try:
        import deployment as D
        dep = D.chosen().name
    except Exception:                                    # the view says no deployment's name rather than none at all
        dep = ""
    return {"made": _now(), "deployment": dep, "trackers": out}


def refresh(cfg=None, ad=None, packs=None, db=None, out=None):
    """One pass of the cache and the app's view written (the tracker poller's, ops/runreg.py). -> the problems."""
    from domain import trackers as TR
    cfg = cfg or TR.config()
    if not any(t.get("records") for t in cfg["trackers"]):
        return []
    if packs is None:
        from domain import packs as PK
        packs = PK.load()["packs"]
    got = sync(cfg, ad, packs, db)
    SF.save(Path(out or view_path()), view(cfg, packs, db))
    return [r["problem"] for r in got.values() if r["problem"]]


def main(argv):
    args = argv[1:]
    if args[:1] == ["sync"]:
        print("\n".join(refresh()) or "the records are read")
        return 0
    if args[:1] == ["view"]:
        print(json.dumps(view(), indent=1, ensure_ascii=False))
        return 0
    from domain import trackers as TR
    names = [t["name"] for t in TR.config()["trackers"] if t.get("records")]
    tr = args[1] if len(args) > 1 else (names[0] if names else "")
    if args[:1] == ["measures"] and tr:
        for m in measures(tr):
            print(f"{m['name']}: {m['value']}" + (f" ({m['n']} of {m['of']})" if m["kind"] == "share" else ""))
        return 0
    if args[:1] == ["missing"] and tr:
        rows = missing_link(tr, args[2]) if len(args) > 2 else missing_work_products(tr)
        print("\n".join(f"{r['key']} {r['type_name']}: {r['title']}" + "".join(f"; no {m['type_name']} ({m['link_name']})" for m in r.get("missing") or [])
                        for r in rows) or "none")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

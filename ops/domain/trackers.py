"""Trackers and the forge (GEN-25, GEN-26, docs/AI-STACK.md §8): read by polling with a cursor, written only through
gates, every kind of write in shadow until the owner lets it go live.

The deployment lists its trackers in trackers.yaml beside its deployment.env:
    shadow_needed: 5                 # approved shadow items a kind of write needs before the owner may let it go live
    poll_minutes: 5                  # how often the poller asks the trackers (the crew job tracker-poll, ops/runreg.py)
    trackers:
      - {name: bugs, kind: jira, url: https://jira.example, query: 'project = DEMO', workflow: demo/bug}
      - {name: inbox, kind: forgejo, repo: '${FORGEJO_OWNER}/inbox', workflow: home/inbox, restart: on_comment}
      - {name: test, kind: standin, path: /tmp/standin.json, workflow: demo/bug}
Tokens are secrets (sops), never in the file: JIRA_TOKEN, FORGEJO_TOKEN. "workflow" is the workflow an item starts
(through n8n's webhook item/<workflow>): a pack's <pack>/<name>, or the stack's own home/<name> (n8n/workflows/
item-home-<name>.json; no pack may be named home, ops/domain/packs.py core_names). "restart" says whether a new comment
on an item whose run has ended starts a new run (on_comment) or not (never, the default). A value may name a value of
the deployment.env beside the file as ${NAME} (home's repository is ${FORGEJO_OWNER}/inbox). "me" is the tracker
account the stack writes with when it has one of its own (default ai-stack); leave it out where the stack writes with
the owner's account (home's Forgejo token), or the owner's replies would count as the stack's. An entry that cannot be
used is refused with its reason (refused(): an unknown kind or restart, a Jira query with its own ORDER BY, a ${NAME}
the deployment does not set) and not asked.

Reading. poll() asks each tracker for the items changed since its cursor and hands each change on as one event for
the run named after its item (<workflow>:<tracker>/<key>), with the comments from someone other than the stack that it
has not handed on before. A comment is the stack's own (own()) when its author is the tracker's "me" or when it ends
with the stack's write mark, which every write of the stack ends with; so where the stack and the owner write with the
same account, the owner's replies still wake the run and the stack's own comments do not. The cursor and the comments
seen are kept on disk, so a restart hands nothing on twice. Which run an event starts or wakes is the run register's
business (ops/runreg.py), never this module's. item_text() is the item as an agent step that names it reads it: its
title, its text and every comment in order, each marked as the stack's own or by its author (WFL-25).

Writing. A write is one call with a write id, so a retry is harmless. The kinds: comment, summary (the stack's one
summary comment, edited, never duplicated), attach, link, transition, label. Each kind starts in shadow: the write goes
to the shadow log and the owner's queue, never outward. Once the owner approved shadow_needed of a kind's items, the
queue asks whether that kind may go live; a live kind writes outward.

    adapter(cfg)               a tracker's adapter: StandIn, Forgejo, Jira
    own(comment, me)           whether a comment is the stack's own write
    poll(cfg, hand=None)       one pass over every tracker -> the events it hands on (to hand() before a cursor moves)
    item_text(tracker, key)    the item's title, text and comments, as an agent step reads them
    problems(cfg)              the tracker entries refused at load, each with its reason
    write(d)                   one write, in shadow or live
    decisions(make)            the queue's items: shadow writes to approve, kinds ready to go live
    handle(req)                the app's actions: tracker_shadow_approve, tracker_shadow_reject, tracker_live
"""
import datetime as dt
import os
import re
import sys
import urllib.parse
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import statefile as SF  # noqa: E402
import textcap as TC  # noqa: E402

KINDS = ("comment", "summary", "attach", "link", "transition", "label")
SUMMARY_MARK = "<!-- ai-stack:summary -->"     # the stack's one summary comment carries this, so it is edited, not added
WRITE_MARK = "<!-- ai-stack:write {id} -->"    # every write carries its id, so a retry finds it written
SHADOW_NEEDED = 5                              # limit: waits, approved shadow items a kind of write needs before it may go live (the deployment may set more)
BODY_CHARS = 20000                             # cap: store, one write's text (a tracker refuses far less than this)
POLL_MINUTES = 5                               # limit: paces, the trackers are asked every 5 minutes unless the deployment's poll_minutes says otherwise
RESTART = ("never", "on_comment")              # a new comment on an item whose run has ended starts a new run only with on_comment
ORDER_BY = re.compile(r"\border\s+by\b", re.I)
JIRA_PAGE = 50                                 # issues per request; the pass pages on until Jira has given every one
JIRA_PAGES = 1000                              # limit: stops, a pass that asked for 1,000 pages (50,000 changed items) stops there; the cursor keeps what was handed on and the next pass goes on
FORGEJO_PAGE = 50                              # issues per request; the pass pages on until Forgejo has given every one
FORGEJO_PAGES = 1000                           # limit: stops, a pass that asked for 1,000 pages (50,000 changed issues) stops there; the cursor keeps what was handed on and the next pass goes on
WRITTEN = re.compile(r"<!-- ai-stack:write \S+ -->")   # WRITE_MARK as it ends every write of the stack
ITEM_HEAD = 6000                               # cap: prompt, an item's title and text as an agent step reads them
ITEM_TALK = 10000                              # cap: prompt, its comments as an agent step reads them, the newest kept
VAR = re.compile(r"\$\{(\w+)\}")


def _deployment():
    import deployment as D
    return D.chosen()


def _values(folder):
    """The values a trackers.yaml may name as ${NAME}: those of the deployment.env beside it, else this deployment's."""
    import deployment as D
    env = folder / "deployment.env"
    return D.load(env) if env.is_file() else D.VALUES


def config(path=None, values=None):
    p = Path(path or os.environ.get("AISTACK_TRACKERS") or _deployment() / "trackers.yaml")
    try:
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except OSError:
        d = {}
    trackers = list(d.get("trackers") or [])
    if any(isinstance(v, str) and VAR.search(v) for t in trackers if isinstance(t, dict) for v in t.values()):
        vals = values if values is not None else _values(p.parent)
        trackers = [{k: VAR.sub(lambda m: vals.get(m.group(1), m.group(0)), v) if isinstance(v, str) else v for k, v in t.items()}
                    if isinstance(t, dict) else t for t in trackers]
    return {"shadow_needed": int(d.get("shadow_needed") or SHADOW_NEEDED), "trackers": trackers,
            "poll_minutes": float(d.get("poll_minutes") or POLL_MINUTES)}


def refused(t):
    """Why a tracker's entry cannot be used, or "": it is read at load and refused with the reason, never half used."""
    unset = sorted({m for v in t.values() if isinstance(v, str) for m in VAR.findall(v)})
    if unset:
        return f"{t.get('name')}: it names ${{{unset[0]}}}, which the deployment.env does not set"
    if t.get("kind") not in ADAPTERS:
        return f"{t.get('name')}: kind is one of {', '.join(ADAPTERS)}, not {t.get('kind')!r}"
    if t.get("restart", "never") not in RESTART:
        return f"{t.get('name')}: restart is never or on_comment, not {t.get('restart')!r}"
    if t.get("kind") == "jira" and ORDER_BY.search(str(t.get("query") or "")):
        return (f"{t.get('name')}: its query has its own ORDER BY; the stack orders by updated itself to keep its cursor, "
                "so leave the order out of the query")
    return ""


def problems(cfg=None):
    return [w for w in (refused(t) for t in (cfg or config())["trackers"]) if w]


def state_dir():
    return Path(os.environ.get("AISTACK_TRACKER_STATE") or "/srv/ai/state/trackers")


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _read(p, default):
    return SF.load(p, default)


def _write_json(p, d):
    SF.save(p, d, indent=1)                          # whole or not at all: a cursor, the seen comments, the shadow writes


# ---------- the stack's own comments ----------
def own(c, me):
    """A comment is the stack's own when its author is the tracker's account for the stack (me), or when its last line
    is the stack's write mark: every write of the stack ends with it, so where the stack writes with the owner's own
    account (home's Forgejo) the owner's replies still count as someone else's. A reply that quotes the stack's comment
    ends with the owner's words or with the quoted mark ("> <!-- ... -->"), so it is the owner's."""
    if str(c.get("author") or "") == str(me):
        return True
    lines = str(c.get("body") or "").strip().splitlines()
    return bool(lines) and bool(WRITTEN.fullmatch(lines[-1].strip()))


def unmarked(body):
    """A comment's text without the stack's marks (they are for the stack, not for the reader)."""
    return "\n".join(x for x in str(body or "").splitlines() if not (WRITTEN.fullmatch(x.strip()) or x.strip() == SUMMARY_MARK)).strip()


# ---------- adapters ----------
class StandIn:
    """A tracker in one JSON file: what the tests and the preview poll and write. Same answers as a real one."""
    me = "ai-stack"

    def __init__(self, cfg):
        self.path = Path(cfg["path"])

    def _db(self):
        return _read(self.path, {"items": {}})

    def changes(self, cursor):
        items = [{"key": k, **v} for k, v in self._db()["items"].items() if v.get("updated", "") > (cursor or "")]
        items.sort(key=lambda i: i["updated"])
        return items, (items[-1]["updated"] if items else cursor)

    def comments(self, key):
        return self._db()["items"].get(key, {}).get("comments", [])

    def item(self, key):
        it = self._db()["items"].get(key, {})
        return {"title": it.get("title", ""), "body": it.get("body", ""), "status": it.get("status", "")}

    def put(self, key, kind, body, write_id):
        db = self._db()
        it = db["items"].setdefault(key, {"updated": _now(), "comments": []})
        mark = WRITE_MARK.format(id=write_id)
        cs = it.setdefault("comments", [])
        if any(mark in c["body"] for c in cs) or any(mark in str(x) for x in it.get("log", [])):
            return {"done": True, "again": True}                 # this write was done before: a retry changes nothing
        if kind == "summary":
            old = next((c for c in cs if SUMMARY_MARK in c["body"] and own(c, self.me)), None)
            text = f"{SUMMARY_MARK}\n{body}\n{mark}"
            if old:
                old["body"], old["edited"] = text, _now()
            else:
                cs.append({"id": len(cs) + 1, "author": self.me, "body": text, "at": _now()})
        elif kind == "comment":
            cs.append({"id": len(cs) + 1, "author": self.me, "body": f"{body}\n{mark}", "at": _now()})
        else:                                                     # attach, link, transition, label: recorded on the item
            it.setdefault("log", []).append({"kind": kind, "value": body, "mark": mark, "at": _now()})
            if kind == "transition":
                it["status"] = body
            if kind == "label":
                it.setdefault("labels", []).append(body)
        _write_json(self.path, db)
        return {"done": True}


class Forgejo:
    """Forgejo issues through the forge's API (ops/forge.py)."""

    def __init__(self, cfg):
        import forge as F
        self.f, self.repo = F.FORGE, cfg["repo"]
        self.me = cfg.get("me") or "ai-stack"

    def changes(self, cursor):
        """The issues changed since the cursor (Forgejo's own time, its offset kept), page by page; the time goes into
        the query encoded, since a raw + of an offset reads as a space there."""
        since = f"&since={urllib.parse.quote(cursor)}" if cursor else ""
        got = []
        for page in range(1, FORGEJO_PAGES + 1):                 # limit: stops, FORGEJO_PAGES above
            batch = self.f.call("GET", f"/repos/{self.repo}/issues?type=issues&state=all&limit={FORGEJO_PAGE}&page={page}{since}") or []
            got += batch
            if len(batch) < FORGEJO_PAGE:
                break
        items = [{"key": str(i["number"]), "updated": i["updated_at"], "title": i["title"], "status": i["state"],
                  "labels": [x["name"] for x in i.get("labels") or []]} for i in got if not cursor or _when(i.get("updated_at") or cursor) > _when(cursor)]
        items = sorted({i["key"]: i for i in items}.values(), key=lambda i: _when(i["updated"]))
        return items, (items[-1]["updated"] if items else cursor)

    def comments(self, key):
        return [{"id": c["id"], "author": c["user"]["login"], "body": c["body"], "at": c["created_at"]}
                for c in self.f.call("GET", f"/repos/{self.repo}/issues/{key}/comments") or []]

    def item(self, key):
        i = self.f.call("GET", f"/repos/{self.repo}/issues/{key}") or {}
        return {"title": i.get("title", ""), "body": i.get("body") or "", "status": i.get("state", "")}

    def put(self, key, kind, body, write_id):
        mark = WRITE_MARK.format(id=write_id)
        cs = self.comments(key)
        if any(mark in c["body"] for c in cs):
            return {"done": True, "again": True}
        if kind == "summary":
            old = next((c for c in cs if SUMMARY_MARK in c["body"] and own(c, self.me)), None)
            text = f"{SUMMARY_MARK}\n{body}\n{mark}"
            if old:
                self.f.call("PATCH", f"/repos/{self.repo}/issues/comments/{old['id']}", {"body": text})
            else:
                self.f.call("POST", f"/repos/{self.repo}/issues/{key}/comments", {"body": text})
        elif kind == "comment":
            self.f.call("POST", f"/repos/{self.repo}/issues/{key}/comments", {"body": f"{body}\n{mark}"})
        elif kind == "transition":
            self.f.call("PATCH", f"/repos/{self.repo}/issues/{key}", {"state": "closed" if body.lower() in ("closed", "done") else "open"})
        elif kind == "label":
            self.f.call("POST", f"/repos/{self.repo}/issues/{key}/labels", {"labels": [body]})
        else:
            self.f.call("POST", f"/repos/{self.repo}/issues/{key}/comments", {"body": f"{kind}: {body}\n{mark}"})
        return {"done": True}


def _when(s):
    """A Jira time (2026-11-09T10:05:10.000+0100), a Forgejo time (2026-11-09T10:05:10+01:00 or ...Z) or an older cursor
    without an offset, as a datetime."""
    return dt.datetime.fromisoformat(re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", str(s)))


def _minute(s):
    t = _when(s)
    return (t.astimezone(dt.timezone.utc) if t.tzinfo else t).strftime("%Y-%m-%d %H:%M")


class Jira:
    """Jira Data Center through atlassian-python-api (a token, never a password).

    Its cursor is the newest change's `updated` as Jira gives it (with the server's offset), and the (key, updated) pairs
    of that minute already handed on. JQL reads a time to the minute and in the token user's time zone: the cursor is
    turned into that zone (/rest/api/2/myself, timeZone) and asked with >= of its minute, the pairs handed on drop out,
    and a pass pages on until Jira has given every match, so a minute with more items than a page never holds it."""

    def __init__(self, cfg, client=None):
        why = refused({"name": cfg.get("name", "jira"), **cfg, "kind": "jira"})
        if why:
            raise ValueError(why)
        if client is None:
            from atlassian import Jira as J                      # pinned for the runner (ops/runner-requirements.txt, hashed in its lock)
            client = J(url=cfg["url"], token=os.environ.get(cfg.get("token_env") or "JIRA_TOKEN", ""))
        self.j, self.query, self.me = client, str(cfg.get("query") or "").strip(), cfg.get("me") or "ai-stack"
        self._zone = None

    def zone(self):
        if self._zone is None:
            from zoneinfo import ZoneInfo
            self._zone = ZoneInfo((self.j.myself() or {}).get("timeZone") or "UTC")
        return self._zone

    def jql(self, cursor):
        at = cursor.get("at") if isinstance(cursor, dict) else cursor
        since = ""
        if at:
            t = _when(at)
            since = f'updated >= "{(t.astimezone(self.zone()) if t.tzinfo else t):%Y-%m-%d %H:%M}"'
        where = " AND ".join(x for x in (f"({self.query})" if self.query else "", since) if x)
        return f"{where} ORDER BY updated ASC" if where else "ORDER BY updated ASC"

    def changes(self, cursor):
        held = {tuple(p) for p in (cursor.get("seen") or [])} if isinstance(cursor, dict) else set()
        q, got, start = self.jql(cursor), {}, 0
        for _ in range(JIRA_PAGES):                              # limit: stops, JIRA_PAGES above
            page = self.j.jql(q, start=start, limit=JIRA_PAGE, fields="summary,status,labels,updated") or {}
            issues = page.get("issues") or []
            for i in issues:
                got[(i["key"], i["fields"]["updated"])] = {"key": i["key"], "updated": i["fields"]["updated"], "title": i["fields"].get("summary", ""),
                                                           "status": (i["fields"].get("status") or {}).get("name", ""), "labels": i["fields"].get("labels") or []}
            start += len(issues)
            if not issues or start >= int(page.get("total") or 0):
                break
        if not got:
            return [], cursor
        items = sorted(got.values(), key=lambda i: _when(i["updated"]))
        newest = items[-1]["updated"]
        seen = sorted(p for p in held | set(got) if _minute(p[1]) == _minute(newest))
        return [i for i in items if (i["key"], i["updated"]) not in held], {"at": newest, "seen": [list(p) for p in seen]}

    def comments(self, key):
        got = self.j.issue_get_comments(key) or {}
        return [{"id": c["id"], "author": (c.get("author") or {}).get("name", ""), "body": c.get("body", ""), "at": c.get("created", "")}
                for c in got.get("comments") or []]

    def item(self, key):
        f = (self.j.issue(key, fields="summary,description,status") or {}).get("fields") or {}
        return {"title": f.get("summary") or "", "body": f.get("description") or "", "status": (f.get("status") or {}).get("name", "")}

    def put(self, key, kind, body, write_id):
        mark = WRITE_MARK.format(id=write_id)
        cs = self.comments(key)
        if any(mark in c["body"] for c in cs):
            return {"done": True, "again": True}
        if kind == "summary":
            old = next((c for c in cs if SUMMARY_MARK in c["body"] and own(c, self.me)), None)
            text = f"{SUMMARY_MARK}\n{body}\n{mark}"
            if old:
                self.j.issue_edit_comment(key, old["id"], text)
            else:
                self.j.issue_add_comment(key, text)
        elif kind == "comment":
            self.j.issue_add_comment(key, f"{body}\n{mark}")
        elif kind == "transition":
            self.j.set_issue_status(key, body)
        elif kind == "attach" and body.startswith("artifact:"):          # a file the stack made (GEN-29)
            from domain import artifacts as AR
            self.j.add_attachment(key, str(AR.path_of(body.split()[0])))
        elif kind == "label":
            self.j.update_issue_field(key, {"labels": [*self.j.issue_field_value(key, "labels"), body]})
        else:
            self.j.issue_add_comment(key, f"{kind}: {body}\n{mark}")
        return {"done": True}


ADAPTERS = {"standin": StandIn, "forgejo": Forgejo, "jira": Jira}


def adapter(cfg):
    return ADAPTERS[cfg["kind"]](cfg)


def find(name, cfg=None):
    return next((t for t in (cfg or config())["trackers"] if t["name"] == name), None)


# ---------- reading ----------
def run_id(t, key):
    return f"{t.get('workflow', '')}:{t['name']}/{key}"


def poll(cfg=None, ad=None, hand=None):
    """One pass: every tracker's changes since its cursor, each as one event {tracker, key, run, ref, comments} for the
    run named after its item; a comment is handed on once, and the stack's own never. The cursor moves only after a
    tracker's events are made and handed on (hand(events): the run register's outbox, ops/runreg.py), so a pass that
    fails hands its items on again next time. A tracker its entry refuses (refused()) is not asked."""
    cfg = cfg or config()
    events = []
    for t in cfg["trackers"]:
        if refused(t):
            continue
        st = _read(state_dir() / f"{t['name']}.json", {"cursor": "", "seen": {}})
        a = (ad or {}).get(t["name"]) or adapter(t)
        items, cursor = a.changes(st["cursor"])
        mine = []
        for it in items:
            key = it["key"]
            ext = [c for c in a.comments(key) if not own(c, a.me) and str(c["id"]) not in st["seen"].get(key, [])]
            mine.append({"tracker": t["name"], "key": key, "run": run_id(t, key), "ref": f"item:{t['name']}/{key}@{it['updated']}",
                         "comments": [f"comment:{t['name']}/{key}/{c['id']}" for c in ext]})
            st["seen"].setdefault(key, []).extend(str(c["id"]) for c in ext)
        if hand:
            hand(mine)
        events += mine
        st["cursor"] = cursor
        _write_json(state_dir() / f"{t['name']}.json", st)
    return events


def item_text(tracker, key, cfg=None, ad=None):
    """WFL-25: the item as an agent step that names it reads it: its title and status, its text, and every comment in
    order, the stack's own marked as yours and the others by their author, without the stack's marks. A long text
    keeps its start; long comments keep the newest."""
    cfg = cfg or config()
    t = find(tracker, cfg)
    if not t or refused(t):
        raise ValueError(f"no tracker {tracker!r} in this deployment's trackers.yaml" if not t else refused(t))
    a = (ad or {}).get(tracker) or adapter(t)
    it = a.item(key)
    whole = f"Title: {it.get('title') or ''}\nStatus: {it.get('status') or 'unknown'}\n\n{it.get('body') or '(no text)'}"
    head = TC.cut(whole, ITEM_HEAD, "the whole text is on the item")   # cap: prompt, ITEM_HEAD above
    talk = [f"--- {'You (the AI Stack)' if own(c, a.me) else c.get('author') or 'someone'}{', ' + str(c['at']) if c.get('at') else ''}:\n"
            f"{unmarked(c.get('body'))}" for c in a.comments(key)]
    said = TC.tail("\n\n".join(talk), ITEM_TALK, "the oldest comments are on the item")   # cap: prompt, ITEM_TALK above
    return (f"The item {tracker}/{key}, as its tracker holds it now:\n\n{head}\n\n"
            + (f"Its comments, oldest first:\n\n{said}" if talk else "It has no comments yet."))


# ---------- writing ----------
def shadow_path():
    return state_dir() / "shadow.json"


def _shadow():
    return _read(shadow_path(), {k: {"live": False, "approved": 0, "items": []} for k in KINDS})


def write(d, cfg=None, ad=None):
    """One write: {tracker, kind, key, body, write_id, run, node}. In shadow it is kept for the owner and nothing
    leaves; live it is written once, whatever the retries."""
    cfg = cfg or config()
    kind = d["kind"]
    if kind not in KINDS:
        return {"refused": True, "why": f"a tracker write is one of {', '.join(KINDS)}, not {kind!r}"}
    t = find(d["tracker"], cfg)
    if not t:
        return {"refused": True, "why": f"no tracker {d['tracker']!r} in this deployment's trackers.yaml"}
    body = TC.cut(str(d.get("body") or ""), BODY_CHARS)       # cap: store
    sh = _shadow()
    k = sh.setdefault(kind, {"live": False, "approved": 0, "items": []})
    if not k["live"]:
        if not any(i["id"] == d["write_id"] for i in k["items"]):
            k["items"].append({"id": d["write_id"], "tracker": t["name"], "key": d["key"], "body": body, "run": d.get("run", ""),
                               "node": d.get("node", ""), "at": _now(), "status": "pending"})
            _write_json(shadow_path(), sh)
        return {"pass": True, "shadow": True, "ref": f"shadow:{kind}/{d['write_id']}"}
    r = ((ad or {}).get(t["name"]) or adapter(t)).put(d["key"], kind, body, d["write_id"])
    return {"pass": True, "ref": f"tracker:{t['name']}/{d['key']}/{kind}/{d['write_id']}", **r}


def decisions(make, cfg=None):
    cfg = cfg or config()
    need = cfg["shadow_needed"]
    for kind, k in _shadow().items():
        for i in k["items"]:
            if i["status"] == "pending":
                yield make(f"shadow:{kind}:{i['id']}", f"tracker-{kind}", f"Would the stack's {kind} on {i['tracker']}/{i['key']} be right?",
                           TC.cut(i["body"], 400), "#/system?tab=connections&at=packs",   # cap: preview, the whole is on the page
                           unanswered="nothing leaves the stack: this kind of write is in shadow",
                           answers=[{"label": "Right", "act": {"action": "tracker_shadow_approve", "kind": kind, "id": i["id"]}},
                                    {"label": "Wrong", "act": {"action": "tracker_shadow_reject", "kind": kind, "id": i["id"]}}])
        if not k["live"] and k["approved"] >= need:
            yield make(f"tracker-live:{kind}", f"tracker-{kind}", f"Let the stack's {kind} writes go live?",
                       f"you approved {k['approved']} of its shadow writes (the measure is {need})", "#/system?tab=connections&at=packs",
                       unanswered=f"{kind} writes stay in shadow",
                       answers=[{"label": "Go live", "act": {"action": "tracker_live", "kind": kind, "live": True}}])


def handle(req):
    a, kind = req.get("action"), str(req.get("kind") or "")
    sh = _shadow()
    if kind not in sh:
        return {"ok": False, "error": f"no kind of write {kind!r}"}
    k = sh[kind]
    if a in ("tracker_shadow_approve", "tracker_shadow_reject"):
        it = next((i for i in k["items"] if i["id"] == req.get("id")), None)
        if not it or it["status"] != "pending":
            return {"ok": False, "error": "that shadow write is not waiting"}
        it["status"] = "approved" if a == "tracker_shadow_approve" else "rejected"
        it["who"], it["answered"] = str(req.get("who") or "owner"), _now()
        k["approved"] += a == "tracker_shadow_approve"
    elif a == "tracker_live":
        k["live"] = bool(req.get("live"))
        k["switched"] = {"live": k["live"], "who": str(req.get("who") or "owner"), "at": _now()}
    else:
        return {"ok": False, "error": f"unknown tracker action {a}"}
    _write_json(shadow_path(), sh)
    return {"ok": True, "kind": kind, "live": k["live"], "approved": k["approved"]}


def view(cfg=None):
    """What the app shows: each tracker and its cursor, and each kind of write with its shadow state."""
    cfg = cfg or config()
    sh = _shadow()
    def cursor(t):
        c = _read(state_dir() / f"{t['name']}.json", {}).get("cursor", "")
        return c.get("at", "") if isinstance(c, dict) else c
    return {"trackers": [{"name": t["name"], "kind": t["kind"], "workflow": t.get("workflow", ""), "cursor": cursor(t),
                          "restart": t.get("restart", "never"), "refused": refused(t)} for t in cfg["trackers"]],
            "kinds": [{"kind": k, "live": sh.get(k, {}).get("live", False), "approved": sh.get(k, {}).get("approved", 0),
                       "pending": sum(1 for i in sh.get(k, {}).get("items", []) if i["status"] == "pending"),
                       "items": sh.get(k, {}).get("items", [])[-20:]} for k in KINDS],          # cap: list, the newest; the log keeps all
            "shadow_needed": cfg["shadow_needed"]}

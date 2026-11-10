"""Trackers and the forge (GEN-25, GEN-26, docs/AI-STACK.md §8): read by polling with a cursor, written only through
gates, every kind of write in shadow until the owner lets it go live.

The deployment lists its trackers in trackers.yaml beside its deployment.env:
    shadow_needed: 5                 # approved shadow items a kind of write needs before the owner may let it go live
    trackers:
      - {name: bugs, kind: jira, url: https://jira.example, query: 'project = DEMO', workflow: toy/bug}
      - {name: home, kind: forgejo, repo: owner/repo, workflow: home/triage}
      - {name: test, kind: standin, path: /tmp/standin.json, workflow: toy/bug}
Tokens are secrets (sops), never in the file: JIRA_TOKEN, FORGEJO_TOKEN.

Reading. poll() asks each tracker for the items changed since its cursor and hands each change on as one event for
the run named after its item (<workflow>:<tracker>/<key>), with the comments from someone other than the stack that it
has not handed on before. The cursor and the comments seen are kept on disk, so a restart hands nothing on twice.
Which run an event starts or wakes is the workflow's business (n8n, DEC-51), never this module's.

Writing. A write is one call with a write id, so a retry is harmless. The kinds: comment, summary (the stack's one
summary comment, edited, never duplicated), attach, link, transition, label. Each kind starts in shadow: the write goes
to the shadow log and the owner's queue, never outward. Once the owner approved shadow_needed of a kind's items, the
queue asks whether that kind may go live; a live kind writes outward.

    adapter(cfg)               a tracker's adapter: StandIn, Forgejo, Jira
    poll(cfg)                  one pass over every tracker -> the events it hands on
    write(d)                   one write, in shadow or live
    decisions(make)            the queue's items: shadow writes to approve, kinds ready to go live
    handle(req)                the app's actions: tracker_shadow_approve, tracker_shadow_reject, tracker_live
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import textcap as TC  # noqa: E402

KINDS = ("comment", "summary", "attach", "link", "transition", "label")
SUMMARY_MARK = "<!-- ai-stack:summary -->"     # the stack's one summary comment carries this, so it is edited, not added
WRITE_MARK = "<!-- ai-stack:write {id} -->"    # every write carries its id, so a retry finds it written
SHADOW_NEEDED = 5                              # limit: waits, approved shadow items a kind of write needs before it may go live (the deployment may set more)
BODY_CHARS = 20000                             # cap: store, one write's text (a tracker refuses far less than this)


def _deployment():
    import deployment as D
    return D.chosen()


def config(path=None):
    p = Path(path or os.environ.get("AISTACK_TRACKERS") or _deployment() / "trackers.yaml")
    try:
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except OSError:
        d = {}
    return {"shadow_needed": int(d.get("shadow_needed") or SHADOW_NEEDED), "trackers": list(d.get("trackers") or [])}


def state_dir():
    return Path(os.environ.get("AISTACK_TRACKER_STATE") or "/srv/ai/state/trackers")


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _read(p, default):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


def _write_json(p, d):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False))
    tmp.replace(p)


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

    def put(self, key, kind, body, write_id):
        db = self._db()
        it = db["items"].setdefault(key, {"updated": _now(), "comments": []})
        mark = WRITE_MARK.format(id=write_id)
        cs = it.setdefault("comments", [])
        if any(mark in c["body"] for c in cs) or any(mark in str(x) for x in it.get("log", [])):
            return {"done": True, "again": True}                 # this write was done before: a retry changes nothing
        if kind == "summary":
            old = next((c for c in cs if SUMMARY_MARK in c["body"] and c["author"] == self.me), None)
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
        q = f"/repos/{self.repo}/issues?type=issues&state=all&sort=updated&limit=50" + (f"&since={cursor}" if cursor else "")
        got = self.f.call("GET", q) or []
        items = [{"key": str(i["number"]), "updated": i["updated_at"], "title": i["title"], "status": i["state"],
                  "labels": [x["name"] for x in i.get("labels") or []]} for i in got if i.get("updated_at", "") > (cursor or "")]
        items.sort(key=lambda i: i["updated"])
        return items, (items[-1]["updated"] if items else cursor)

    def comments(self, key):
        return [{"id": c["id"], "author": c["user"]["login"], "body": c["body"], "at": c["created_at"]}
                for c in self.f.call("GET", f"/repos/{self.repo}/issues/{key}/comments") or []]

    def put(self, key, kind, body, write_id):
        mark = WRITE_MARK.format(id=write_id)
        cs = self.comments(key)
        if any(mark in c["body"] for c in cs):
            return {"done": True, "again": True}
        if kind == "summary":
            old = next((c for c in cs if SUMMARY_MARK in c["body"]), None)
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


class Jira:
    """Jira Data Center through atlassian-python-api (a token, never a password)."""

    def __init__(self, cfg, client=None):
        if client is None:
            from atlassian import Jira as J                      # in the runner's environment (ops/runner-requirements.txt)
            client = J(url=cfg["url"], token=os.environ.get(cfg.get("token_env") or "JIRA_TOKEN", ""))
        self.j, self.query, self.me = client, cfg.get("query") or "", cfg.get("me") or "ai-stack"

    def changes(self, cursor):
        since = f' AND updated > "{cursor[:16].replace("T", " ")}"' if cursor else ""
        got = self.j.jql(f"{self.query}{since} ORDER BY updated ASC", limit=50, fields="summary,status,labels,updated") or {}
        items = [{"key": i["key"], "updated": i["fields"]["updated"], "title": i["fields"].get("summary", ""),
                  "status": (i["fields"].get("status") or {}).get("name", ""), "labels": i["fields"].get("labels") or []}
                 for i in got.get("issues") or []]
        return items, (items[-1]["updated"] if items else cursor)

    def comments(self, key):
        got = self.j.issue_get_comments(key) or {}
        return [{"id": c["id"], "author": (c.get("author") or {}).get("name", ""), "body": c.get("body", ""), "at": c.get("created", "")}
                for c in got.get("comments") or []]

    def put(self, key, kind, body, write_id):
        mark = WRITE_MARK.format(id=write_id)
        cs = self.comments(key)
        if any(mark in c["body"] for c in cs):
            return {"done": True, "again": True}
        if kind == "summary":
            old = next((c for c in cs if SUMMARY_MARK in c["body"]), None)
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


def poll(cfg=None, ad=None):
    """One pass: every tracker's changes since its cursor, each as one event {tracker, key, run, ref, comments} for the
    run named after its item; a comment is handed on once, and the stack's own never. The cursor moves only after a
    tracker's events are made, so a pass that fails hands its items on again next time."""
    cfg = cfg or config()
    events = []
    for t in cfg["trackers"]:
        st = _read(state_dir() / f"{t['name']}.json", {"cursor": "", "seen": {}})
        a = (ad or {}).get(t["name"]) or adapter(t)
        items, cursor = a.changes(st["cursor"])
        for it in items:
            key = it["key"]
            ext = [c for c in a.comments(key) if c["author"] != a.me and str(c["id"]) not in st["seen"].get(key, [])]
            events.append({"tracker": t["name"], "key": key, "run": run_id(t, key), "ref": f"item:{t['name']}/{key}@{it['updated']}",
                           "comments": [f"comment:{t['name']}/{key}/{c['id']}" for c in ext]})
            st["seen"].setdefault(key, []).extend(str(c["id"]) for c in ext)
        st["cursor"] = cursor
        _write_json(state_dir() / f"{t['name']}.json", st)
    return events


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
    return {"trackers": [{"name": t["name"], "kind": t["kind"], "workflow": t.get("workflow", ""),
                          "cursor": _read(state_dir() / f"{t['name']}.json", {}).get("cursor", "")} for t in cfg["trackers"]],
            "kinds": [{"kind": k, "live": sh.get(k, {}).get("live", False), "approved": sh.get(k, {}).get("approved", 0),
                       "pending": sum(1 for i in sh.get(k, {}).get("items", []) if i["status"] == "pending"),
                       "items": sh.get(k, {}).get("items", [])[-20:]} for k in KINDS],          # cap: list, the newest; the log keeps all
            "shadow_needed": cfg["shadow_needed"]}

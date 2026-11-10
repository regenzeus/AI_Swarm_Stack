"""GEN-45: home's inbox, the work deployment's item flow at home every day. The owner's private repository <owner>/inbox
on home's Forgejo is home's tracker (deployments/home/trackers.yaml); an issue there starts the stack's own item
workflow home/inbox (n8n/workflows/item-home-inbox.json), whose agent reads the issue and answers it on the issue, waits
for the owner's reply, answers that and closes the issue. Home's Forgejo token is the owner's own account, so the
stack's comments and the owner's replies have the same author: the stack knows its own by its write mark (WFL-26).

The end-to-end test runs that workflow in the stand-in n8n of tests/test_work_deployment.py, around the real step
service and run register, against a stand-in Forgejo that answers the tracker adapter's calls as Forgejo does."""
import datetime as dt
import json
import re
import sys
import threading
import types
import urllib.parse
import uuid
from pathlib import Path

import pytest
from test_work_deployment import N8n, settle, waiting_at

import conductor as CD
import dataguard as DG
import deployment as DEPLOY
import flows as FW
import runreg as RR
from domain import trackers as TR

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "deployments/home"
WF = ROOT / "n8n/workflows/item-home-inbox.json"
T0 = 1_800_000_000.0
ANSWERS = ("Three backups ran last night (NAS, mail, vault) and each passed.",
           "The night before, the NAS backup failed at 02:10 and passed on its retry at 02:40.")


class Forgejo:
    """Home's Forgejo as ops/forge.py's call() reaches it, for one repository: its issues and their comments, every
    write made with the owner's own account (the token's), its times with the server's offset (+01:00), the newest
    change first, and the query read as Forgejo reads it (a raw + is a space)."""

    def __init__(self, repo, owner):
        self.repo, self.owner, self.issues, self.ids, self.calls = repo, owner, {}, 100, []
        self.t = dt.datetime(2026, 11, 10, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=1)))

    def tick(self):
        self.t += dt.timedelta(minutes=1)
        return self.t.isoformat()

    def open(self, title, body):
        n = len(self.issues) + 1
        self.issues[n] = {"number": n, "title": title, "body": body, "state": "open", "labels": [], "comments": [], "updated_at": self.tick()}
        return n

    def say(self, n, body):
        self.ids += 1
        at = self.tick()
        self.issues[n]["comments"].append({"id": self.ids, "user": {"login": self.owner}, "body": body, "created_at": at})
        self.issues[n]["updated_at"] = at
        return dict(self.issues[n]["comments"][-1])

    def call(self, method, path, body=None):
        self.calls.append((method, path))
        u = urllib.parse.urlsplit(path)
        base = f"/repos/{self.repo}/issues"
        assert u.path.startswith(base), path
        rest = u.path[len(base):]
        if rest == "" and method == "GET":
            q = urllib.parse.parse_qs(u.query)
            since = dt.datetime.fromisoformat(q["since"][0]) if "since" in q else None   # a raw + would be a space: refused
            page, limit = int(q.get("page", ["1"])[0]), int(q["limit"][0])
            hits = sorted((i for i in self.issues.values() if since is None or dt.datetime.fromisoformat(i["updated_at"]) >= since),
                          key=lambda i: i["updated_at"], reverse=True)
            return [{k: v for k, v in i.items() if k != "comments"} for i in hits[(page - 1) * limit:page * limit]]
        m = re.fullmatch(r"/(\d+)(/comments)?", rest)
        if m and m.group(2):
            i = self.issues[int(m.group(1))]
            if method == "GET":
                return [dict(c) for c in i["comments"]]
            assert method == "POST"
            return self.say(i["number"], body["body"])
        if m:
            if int(m.group(1)) not in self.issues:
                raise OSError("HTTP Error 404: Not Found")
            i = self.issues[int(m.group(1))]
            if method == "PATCH":
                i["state"], i["updated_at"] = body["state"], self.tick()
            return {k: v for k, v in i.items() if k != "comments"}
        m = re.fullmatch(r"/comments/(\d+)", rest)
        assert m and method == "PATCH", (method, path)
        for i in self.issues.values():
            for c in i["comments"]:
                if c["id"] == int(m.group(1)):
                    c["body"] = body["body"]
                    i["updated_at"] = self.tick()
        return {}


@pytest.fixture
def home(K, tmp_path, monkeypatch):
    """Home's deployment as it is: its trackers.yaml and deployment.env, its data class (answers whole), the main
    agent; the stand-in Forgejo, the stand-in n8n holding the inbox workflow published, the step service and the run
    register on temp paths."""
    w = types.SimpleNamespace(tmp=tmp_path, clock={"now": T0}, logs=[], told=[], errors=[], threads={}, lock=threading.Lock(),
                              n8n_restarts=0, prompts=[], B=types.SimpleNamespace(work=lambda: None))
    w.owner = DEPLOY.load(HOME / "deployment.env", env={})["FORGEJO_OWNER"]
    monkeypatch.setenv("AISTACK_TRACKERS", str(HOME / "trackers.yaml"))
    monkeypatch.setenv("AISTACK_TRACKER_STATE", str(tmp_path / "state"))
    monkeypatch.setattr(DG, "DATA", DG.load(HOME))
    w.forge = Forgejo(f"{w.owner}/inbox", w.owner)
    monkeypatch.setitem(sys.modules, "forge", types.SimpleNamespace(FORGE=w.forge))
    main = CD.cards()["main"]
    w.cards = {"main": {"id": "main", "harness": main["harness"], "prompt": main.get("purpose", "")}}
    monkeypatch.setattr(CD, "ADAPTERS", {"hermes": lambda c, t, s, prompt, card: w.prompts.append(str(prompt)) or ANSWERS[len(w.prompts) - 1]})
    w.wf = {**json.loads(WF.read_text()), "active": True}         # the lead's switch publishes it (ops/n8n_switch.py)
    w.n8n_db = tmp_path / "n8n-executions.json"

    def drop(body):                                  # the app's step port: the request whole, or none of it
        rid = uuid.uuid4().hex[:16]
        (FW.PENDING / f".{rid}.tmp").write_text(json.dumps(body))
        (FW.PENDING / f".{rid}.tmp").rename(FW.PENDING / f"{rid}.json")
    w.drop = drop
    w.n8n = N8n(w.wf, w.n8n_db, drop, scale={})
    for name in ("PENDING", "DONE", "ASKS", "BUILDS", "JOBS"):
        monkeypatch.setattr(FW, name, tmp_path / "flows" / name.lower())
    FW.PENDING.mkdir(parents=True)
    monkeypatch.setattr(RR, "ROOT", tmp_path / "flows/register")
    monkeypatch.setattr(RR, "_now", lambda: w.clock["now"])
    FW.M = types.SimpleNamespace(db=K.conn, stop=threading.Event(), log=w.logs.append, notify=w.told.append, event=lambda *a, **k: None)
    w.K = K
    assert TR.poll() == []                           # the inbox's first pass (start: now), as home's live inbox had it long ago
    yield w
    FW.M.stop.set()


def poll(w):
    w.clock["now"] += 600                            # every pass is due (poll_minutes 5)
    return RR.poll(forge=types.SimpleNamespace(), post=lambda req, timeout=30: w.n8n(req, timeout),
                   status=lambda ex: w.n8n.status(ex), now=w.clock["now"])["said"]


def go_live(*kinds):
    for kind in kinds:                               # the owner's Go live (Stack > Connections), the action tracker_live
        assert TR.handle({"action": "tracker_live", "kind": kind, "live": True, "who": "owner"})["live"]


def test_homes_tracker_is_its_inbox_repository_and_its_entry_is_valid():
    values = DEPLOY.load(HOME / "deployment.env", env={})
    cfg = TR.config(HOME / "trackers.yaml", values)
    assert TR.problems(cfg) == [] and cfg["poll_minutes"] == 5
    (t,) = cfg["trackers"]
    assert t == {"name": "inbox", "kind": "forgejo", "repo": f"{values['FORGEJO_OWNER']}/inbox", "workflow": "home/inbox", "restart": "on_comment"}
    assert "me" not in t                             # the stack writes with the owner's account: its mark tells its comments
    assert values["FORGEJO_OWNER"] not in (HOME / "trackers.yaml").read_text()     # named once, in deployment.env
    assert RR.WORKFLOW.fullmatch(t["workflow"])


def test_the_inbox_workflow_listens_where_the_run_register_starts_it_and_is_built_from_the_real_kinds():
    wf = json.loads(WF.read_text())
    t = TR.config(HOME / "trackers.yaml", DEPLOY.load(HOME / "deployment.env", env={}))["trackers"][0]
    hook = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.webhook")
    assert hook["parameters"]["path"] == f"item/{t['workflow']}" and hook["parameters"]["httpMethod"] == "POST"
    assert hook["parameters"]["options"]["responseData"] == "={{ JSON.stringify({execution: $execution.id}) }}"
    steps = {n["name"]: n["parameters"] for n in wf["nodes"] if n["type"] == "CUSTOM.aistackStep"}
    assert [p["kind"] for p in steps.values()].count("agent") == 2 and all(p["agent"] == "main" for p in steps.values() if p["kind"] == "agent")
    assert FW.runs_steps(CD.cards()["main"])                                     # main may do a step
    assert {p["from_step"] for p in steps.values() if p.get("from_step")} <= set(steps)
    assert all(not p.get("from_step") or p["body"] == "" for p in steps.values())    # the whole answer, not a summary
    assert sorted(p["write"] for p in steps.values() if p["kind"] == "tracker") == ["comment", "comment", "summary", "transition"]
    assert steps["Wait for the owner's reply"]["timeout_hours"] == 168 and steps["Close the issue"]["body"] == "closed"
    assert not any(n["name"] == "Run now" for n in wf["nodes"])                 # an item workflow starts from its item only
    assert DEPLOY.load(HOME / "deployment.env", env={})["FORGEJO_OWNER"] not in WF.read_text()


def test_forgejos_changes_are_asked_with_the_cursor_encoded_and_page_by_page(monkeypatch):
    f = Forgejo("someone/inbox", "someone")
    for n in range(60):
        f.open(f"issue {n}", "")
    monkeypatch.setitem(sys.modules, "forge", types.SimpleNamespace(FORGE=f))
    ad = TR.Forgejo({"repo": "someone/inbox"})
    items, cur = ad.changes("")
    assert len(items) == 60 and cur == f.issues[60]["updated_at"] and [i["key"] for i in items][:2] == ["1", "2"]   # oldest first
    assert [p for m, p in f.calls if "page=" in p][-1].endswith("&page=2")
    f.say(7, "one more")
    again, cur2 = ad.changes(cur)
    assert [i["key"] for i in again] == ["7"] and "+" not in f.calls[-1][1] and "%2B01%3A00" in f.calls[-1][1]


def test_an_issue_in_the_inbox_is_answered_waits_for_the_owners_reply_and_is_closed(home):
    w = home
    assert not FW.lean_answers()                     # home is not customer class: n8n holds whole answers
    go_live("comment", "summary", "transition")

    # 1. the owner writes an issue; its run starts once, also when its change comes twice
    n = w.forge.open("Which backups ran last night?", "Please list last night's backups and whether each passed.")
    assert poll(w) == {"started": 1}
    assert list(w.n8n.ex) == ["101"] and RR.item("inbox", str(n))["runs"][0]["execution"] == "101"
    st = json.loads((w.tmp / "state/inbox.json").read_text())
    st["cursor"], st["seen"] = "", {}                # the same change, handed on again
    (w.tmp / "state/inbox.json").write_text(json.dumps(st))
    assert poll(w) == {"seen": 1} and list(w.n8n.ex) == ["101"]

    # 2. the main agent reads the issue and answers it; the whole answer goes on the issue, with the owner's account
    settle(w)
    assert "Title: Which backups ran last night?" in w.prompts[0] and "Please list last night's backups" in w.prompts[0]
    assert waiting_at(w, "101") == "Wait for the owner's reply"
    (c1,) = w.forge.issues[n]["comments"]
    assert c1["user"]["login"] == w.owner and c1["body"].startswith(ANSWERS[0]) and TR.own({"author": w.owner, "body": c1["body"]}, "ai-stack")

    # 3. the stack's own comment, by the owner's account, changes the issue and does not wake the run
    assert poll(w) == {"recorded": 1}
    settle(w)
    assert waiting_at(w, "101") == "Wait for the owner's reply"

    # 4. the owner's reply, same account, without the mark, wakes it; the agent answers with the whole conversation
    w.forge.say(n, "Thanks. And the night before?")
    assert poll(w) == {"woke": 1}
    settle(w)
    assert len(w.prompts) == 2 and "--- You (the AI Stack)" in w.prompts[1] and ANSWERS[0] in w.prompts[1]
    assert f"--- {w.owner}" in w.prompts[1] and "ai-stack:write" not in w.prompts[1]
    assert w.prompts[1].index("Please list last night") < w.prompts[1].index(ANSWERS[0]) < w.prompts[1].index("Thanks. And the night before?")

    # 5. the second answer, the summary, the issue closed, the run ended
    assert w.n8n.status("101") == "success"
    cs = w.forge.issues[n]["comments"]
    assert [c["body"].split("\n")[0] for c in cs] == [ANSWERS[0], "Thanks. And the night before?", ANSWERS[1], TR.SUMMARY_MARK]
    assert "closes the issue" in cs[3]["body"] and w.forge.issues[n]["state"] == "closed"
    assert all(c["user"]["login"] == w.owner for c in cs)
    took = w.n8n.ex["101"]["took"]
    assert took[0]["output"] == ANSWERS[0] and "lean" not in took[0]          # whole answers in n8n at home

    # 6. its own writes changed the issue again: recorded, no new run; a new comment of the owner's takes it up again
    assert poll(w) == {"recorded": 1} and list(w.n8n.ex) == ["101"]
    w.forge.say(n, "One more question about the vault backup.")
    assert poll(w) == {"started": 1} and list(w.n8n.ex) == ["101", "102"]     # restart: on_comment


def test_with_nothing_live_and_no_reply_in_seven_days_the_inbox_run_holds_its_writes_and_ends(home):
    """Home's writes start in shadow like every tracker's: the answer, the summary and the close wait in the owner's
    queue and nothing reaches the issue; with no reply in 7 days the run sums up and closes (in shadow) and ends."""
    w = home
    n = w.forge.open("Is the NAS disk healthy?", "")
    assert poll(w) == {"started": 1}
    settle(w)
    assert waiting_at(w, "101") == "Wait for the owner's reply" and w.forge.issues[n]["comments"] == []
    w.clock["now"] += 168 * 3600 + 60
    settle(w)
    assert w.n8n.status("101") == "success" and len(w.prompts) == 1
    sh = TR._shadow()
    assert [i["body"] for i in sh["comment"]["items"]] == [ANSWERS[0]] and sh["transition"]["items"][0]["body"] == "closed"
    assert len(sh["summary"]["items"]) == 1 and w.forge.issues[n]["comments"] == [] and w.forge.issues[n]["state"] == "open"
    make = lambda *a, **k: {"id": a[0], **k}                                   # noqa: E731
    assert {d["id"] for d in TR.decisions(make)} >= {f"shadow:comment:{sh['comment']['items'][0]['id']}"}   # in the owner's queue


def test_an_agent_step_whose_item_cannot_be_read_fails_with_the_reason_and_an_unknown_tracker_is_refused(home):
    w = home

    def step(rid, **req):
        p = FW.PENDING / f"{rid}.json"
        p.write_text(json.dumps({"kind": "agent", "agent": "main", "brief": "Answer it", "execution": "7", **req}))
        FW.handle(rid, p, cards=w.cards, crew={}, post=lambda *a, **k: None, sleep=lambda s: None)
        return json.loads((FW.DONE / f"{rid}.json").read_text())
    a = step("r1", tracker="inbox", key="99")
    assert a["status"] == "failed" and a["error"].startswith("the item inbox/99 could not be read: OSError: HTTP Error 404") and w.prompts == []
    assert step("r2", tracker="nope", key="1") == {"status": "refused", "error": "no tracker 'nope' in this deployment's trackers.yaml"}


def test_the_node_lets_an_agent_step_read_its_item():
    js = (ROOT / "n8n/custom/AistackStep.node.js").read_text()
    assert "if (kind === 'agent' && p('tracker', '')) Object.assign(body, { tracker: p('tracker'), key: String(p('key')) });" in js
    assert "displayName: 'Read the item of', name: 'tracker', type: 'options', default: '', displayOptions: show('agent')," in js
    assert "async getItemTrackers() { return [{ name: 'No item', value: '' }, ...(await pick(this, 'trackers'))]; }," in js
    assert "displayOptions: show('wait_item', 'tracker', 'agent', 'item')" in js
    assert "if (kind === 'agent' && p('tracker', '')) body.from_item = true;" in js

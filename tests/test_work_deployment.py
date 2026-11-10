"""The work deployment's CR, end to end (its "Done when"): the toy pack in a customer-class test deployment, against
stand-ins, without n8n itself. A stand-in n8n runs the toy's item workflow (tests/fixtures/packs/toy/workflows/
ticket.json) node by node the way n8n does: its webhook starts a run and answers with the execution, each AI Stack step
is posted to the step service as the node posts it (the app drops it in flows/pending), the run waits until the runner
posts the answer to its resume URL, and the IF node branches on a wait's outcome. Around it: a stand-in tracker, a
stand-in forge, the local worker in a temp folder for the wsl-host place, the step service (ops/flows.py) and the run
register (ops/runreg.py) with temp paths. The runner side is restarted mid-wait and mid-job by reloading its modules
(their state comes back from disk only), n8n mid-wait (its executions come back from its database).

The boundary: the stand-in domain's names never appear in the core (ops/, images/, compose/, config/, n8n/)."""
import importlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import types
import uuid
import zipfile
from pathlib import Path

import pytest

import conductor as CD
import dataguard as DG
import deployment as DEPLOY
import flows as FW
import localworker as LW
import runreg as RR
from domain import places as PL
from domain import packs as PK
from domain import record as RC
from domain import trackers as TR

ROOT = Path(__file__).resolve().parents[1]
TOY = ROOT / "tests/fixtures/packs/toy"
WORK = ROOT / "deployments/example-work"
N8N = "http://127.0.0.1:5678"                       # n8n's own port: no tailnet in a customer-class deployment
T0 = 1_800_000_000.0
KEY = "TOY-7"
TRIAGE = ("To reproduce the export failure we need three answers.\n1. How large is the file you export?\n"
          "2. Which version shows it first?\n3. Does it fail every time, or only after a restart?\n"
          + "The log of the failed run would settle the second question at once. " * 6)
STEP = "CUSTOM.aistackStep"


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@localhost", *a], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


class Resp:
    def __init__(self, body=b"", status=200):
        self.body, self.status = body, status

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class N8n:
    """The stand-in n8n: the item workflow's logic as n8n runs it, its executions kept in a file (its database), so a
    restart loses nothing. Each AI Stack step's request is built as AistackStep.node.js builds it."""

    def __init__(self, wf, db, drop, scale):
        self.wf, self.db, self.drop, self.scale = wf, db, drop, scale
        self.nodes = {n["name"]: n for n in wf["nodes"]}
        self.ex = json.loads(db.read_text()) if db.exists() else {}
        self.down = False

    def save(self):
        self.db.write_text(json.dumps(self.ex))

    def status(self, ex):
        return (self.ex.get(str(ex)) or {}).get("status", "")

    # ---- what n8n answers over HTTP (the runner's urlopen), one request at a time ----
    LOCK = threading.RLock()

    def __call__(self, req, timeout=30):
        with self.LOCK:
            return self.answer(req)

    def answer(self, req):
        if self.down:
            raise OSError("n8n is restarting")
        body = json.loads(req.data)
        if req.full_url.startswith(f"{N8N}/webhook/"):
            path = req.full_url.removeprefix(f"{N8N}/webhook/")
            hook = next((n for n in self.wf["nodes"] if n["type"] == "n8n-nodes-base.webhook" and n["parameters"]["path"] == path), None)
            if hook is None or not self.wf.get("active"):
                raise OSError(f"HTTP Error 404: no published webhook {path}")
            ex = self.start(hook, body)
            return Resp(str(self.value(ex, hook["parameters"]["options"]["responseData"], {})).encode())
        m = re.fullmatch(re.escape(N8N) + r"/webhook-waiting/(\w+)/(\w+)", req.full_url)
        assert m, req.full_url
        ex = self.ex[m.group(1)]
        assert ex["status"] == "waiting" and ex["resume"] == m.group(2), (ex, req.full_url)
        ex.setdefault("took", []).append(body)
        self.resume(ex, body)
        return Resp()

    # ---- the run ----
    def start(self, hook, body):
        ex = {"id": str(101 + len(self.ex)), "status": "running", "data": {}, "last": hook["name"], "took": []}
        self.ex[ex["id"]] = ex
        ex["data"][hook["name"]] = {"headers": {}, "params": {}, "query": {}, "body": body}
        self.advance(ex, hook["name"], 0)
        return ex

    def advance(self, ex, name, out):
        outs = (self.wf["connections"].get(name) or {}).get("main") or []
        nxt = outs[out] if out < len(outs) else []
        if not nxt:
            ex["status"], ex["at"] = "success", None
            self.save()
            return
        node = self.nodes[nxt[0]["node"]]
        cur = ex["data"][ex["last"]]
        if node["type"] == "n8n-nodes-base.if":
            c = node["parameters"]["conditions"]["conditions"][0]
            assert c["operator"] == {"type": "string", "operation": "equals"}
            yes = self.value(ex, c["leftValue"], cur) == c["rightValue"]
            ex["data"][node["name"]], ex["last"] = cur, node["name"]
            return self.advance(ex, node["name"], 0 if yes else 1)
        assert node["type"] == STEP, node["type"]
        ex["status"], ex["at"], ex["resume"] = "waiting", node["name"], f"n{len(ex['data'])}"
        self.save()
        self.drop(self.request(ex, node, cur))

    def resume(self, ex, answer):
        failed = answer.get("status") in ("failed", "refused", "cancelled")
        if failed or (answer.get("status") != "done" and "outcome" not in answer):
            ex["status"], ex["error"] = "error", answer.get("error", "")
            return self.save()
        ex["status"], ex["last"] = "running", ex["at"]
        ex["data"][ex["at"]] = answer
        self.advance(ex, ex["at"], 0)

    # ---- expressions and the node's request ----
    def value(self, ex, v, cur):
        if not (isinstance(v, str) and v.startswith("=")):
            return v
        whole = re.fullmatch(r"=\{\{\s*(.*?)\s*\}\}", v)
        if whole and "}}" not in whole.group(1):
            return self.expr(ex, whole.group(1), cur)
        return re.sub(r"\{\{\s*(.*?)\s*\}\}", lambda m: str(self.expr(ex, m.group(1), cur)), v[1:])

    def expr(self, ex, e, cur):
        if e == "JSON.stringify({execution: $execution.id})":
            return json.dumps({"execution": ex["id"]})
        m = re.fullmatch(r"\$\('([^']+)'\)\.item\.json((?:\.\w+)*)|\$json((?:\.\w+)*)", e)
        assert m, f"the stand-in n8n does not read {e}"
        got = ex["data"][m.group(1)] if m.group(1) else cur
        for k in filter(None, (m.group(2) or m.group(3) or "").split(".")):
            got = got.get(k) if isinstance(got, dict) else None
        return got

    def request(self, ex, node, cur):
        p = lambda k, d=None: self.value(ex, node["parameters"].get(k, d), cur)   # noqa: E731
        kind = p("kind")
        body = {"kind": kind, "title": p("title", "") or None, "workflow": self.wf.get("id") or "packtoyticket01", "workflow_name": self.wf["name"],
                "node": node["name"], "execution": ex["id"], "resume_url": f"{N8N}/webhook-waiting/{ex['id']}/{ex['resume']}"}
        if kind == "agent":
            body.update(agent=p("agent"), brief=p("brief"))
            if p("tracker", ""):                     # an agent step that reads its item
                body.update(tracker=p("tracker"), key=str(p("key")))
        if kind == "build":
            body.update(repo=p("repo"), brief=p("brief"), item=p("item"), base=p("base", ""), target=p("target", ""))
        if kind == "command":
            body.update(place=p("place"), command=p("command"), values={**json.loads(p("values", "{}")), **self.scale.get(p("command"), {})})
        if kind == "wait_item":
            body.update(tracker=p("tracker"), key=str(p("key")), timeout_hours=float(p("timeout_hours", 0)))
        if kind == "tracker":
            body.update(tracker=p("tracker"), key=str(p("key")), write=p("write"), body=p("body", ""), from_step=p("from_step", "") or None)
            body = {k: v for k, v in body.items() if v is not None}
        return body


class Forge:
    """The forge stand-in: the pull requests it was asked to open, and the comments on them."""

    def __init__(self):
        self.opened, self.cs = [], []

    @staticmethod
    def repo_of(origin):
        return tuple(str(origin).rstrip("/").removesuffix(".git").split("/")[-2:])

    def open_pr(self, origin, head, base, title, body, draft=False, from_repo=None):
        self.opened.append({"origin": origin, "head": head, "base": base, "title": title, "draft": draft})
        return {"number": 7, "url": "https://forge.example/projects/TOYPROJ/repos/toy/pull-requests/7"}

    def comments(self, origin, number):
        return self.cs


def builds_standin(tmp, conn):
    """builds.py as a change for an item uses it: a clone of the upstream with tag v1.0, build_assign, and a builder
    that commits onto the item's branch when the step waits for it."""
    seed, up, clone, push = tmp / "seed", tmp / "upstream.git", tmp / "clone", tmp / "fork.git"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    (seed / "export.txt").write_text("holds the whole file\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "one")
    git(seed, "tag", "v1.0")
    git(seed, "branch", "release/1")
    (seed / "export.txt").write_text("later work\n")
    git(seed, "commit", "-q", "-am", "two")
    git(tmp, "clone", "-q", "--bare", str(seed), str(up))
    git(tmp, "clone", "-q", str(up), str(clone))
    git(tmp, "init", "-q", "--bare", str(push))
    c = conn()
    c.execute("create table builds (id integer primary key, repo text, title text, status text, branch text, summary text, error text, "
              "pr text, pr_number integer, onto text)")
    c.commit()
    B = types.ModuleType("builds")
    B.assigned = []
    B.DEPLOY = types.SimpleNamespace(VALUES={"FORGE_PUSH": str(push)})
    B.clone = lambda repo: clone
    B.git = lambda path, *a, timeout=300, check=True: git(path, *a)
    B.origin = lambda repo: "ssh://forge.example:7999/TOYPROJ/toy.git"

    def put(c, bid, **kw):
        for k, v in kw.items():
            c.execute(f"update builds set {k}=? where id=?", (v, bid))
        c.commit()

    def handle(req, c):
        B.assigned.append(req)
        bid = c.execute("insert into builds (repo, title, status, onto) values (?,?,?,?)", (req["repo"], req["title"], "queued", req["onto"])).lastrowid
        c.execute("update builds set branch=? where id=?", (f"builder/{bid}-fix", bid))
        c.commit()
        return {"id": bid}
    B.put, B.handle = put, handle

    def work():                                      # the builder: one commit onto its branch, from the item's branch
        w = conn()
        row = w.execute("select id, onto from builds where status='queued'").fetchone()
        if not row:
            return
        bid, onto = row
        wd = tmp / f"work{bid}"
        git(tmp, "clone", "-q", str(up), str(wd))
        git(wd, "checkout", "-q", "-B", f"builder/{bid}-fix", f"origin/{onto}")
        (wd / "export.txt").write_text("streams the file\n")
        git(wd, "commit", "-q", "-am", "Stream the export instead of holding it")
        git(wd, "push", "-q", "origin", f"builder/{bid}-fix")
        w.execute("update builds set status='review', summary='Streams the export instead of holding the whole file' where id=?", (bid,))
        w.commit()
    B.work = work
    return B, up, push


@pytest.fixture
def world(K, tmp_path, monkeypatch):
    """The customer-class test deployment around the toy pack."""
    w = types.SimpleNamespace(tmp=tmp_path, clock={"now": T0}, logs=[], told=[], errors=[], threads={}, lock=threading.Lock(), n8n_restarts=0)
    # the deployment: example-work's data class and n8n settings (no tailnet, its logic nodes)
    work = DEPLOY.load(WORK / "deployment.env", env={})
    monkeypatch.setattr(DG, "DATA", DG.load(WORK))
    monkeypatch.setitem(DG.DEPLOY.VALUES, "N8N_NODES_INCLUDE", work["N8N_NODES_INCLUDE"])
    w.work = work
    # the toy pack, outside the repository, approved by its commit
    src = tmp_path / "elsewhere/toy"
    shutil.copytree(TOY, src)
    git(src, "init", "-q", "-b", "main")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "first")
    for k, v in {"AISTACK_PACKS_TXT": "packs.txt", "AISTACK_PACKS": "cache", "AISTACK_PACK_APPROVALS": "approvals.json",
                 "AISTACK_PACK_FLOWS": "pack-workflows.json", "AISTACK_TRACKERS": "trackers.yaml", "AISTACK_TRACKER_STATE": "state",
                 "AISTACK_ARTIFACTS": "artifacts", "AISTACK_PLACES": "places.yaml", "AISTACK_PLACE_ROOT": "places"}.items():
        monkeypatch.setenv(k, str(tmp_path / v))
    head = git(src, "rev-parse", "HEAD")
    (tmp_path / "packs.txt").write_text(f"toy {src} {head}\n")
    monkeypatch.setattr(PK, "sync_n8n", lambda: [])
    assert PK.handle({"action": "pack_approve", "name": "toy", "commit": head})["ok"]
    w.pack = PK.load()["packs"][0]
    # the stand-in tracker
    w.store = tmp_path / "standin.json"
    w.store.write_text(json.dumps({"items": {}}))
    (tmp_path / "trackers.yaml").write_text(f"shadow_needed: 2\npoll_minutes: 5\ntrackers:\n"
                                            f"  - {{name: tickets, kind: standin, path: {w.store}, workflow: toy/ticket}}\n")
    # the wsl-host place: the local worker in a temp folder, its toy job kinds approved there
    root = tmp_path / "wslhost"
    for d in ("inbox", "outbox", "jobs.d", "repos", "scratch"):
        (root / d).mkdir(parents=True)
    (tmp_path / "places.yaml").write_text(f"places:\n  wsl-host: {{root: {root}, user: aiworker}}\n")
    monkeypatch.setattr(PL, "PICKUP_S", 0.5)       # the GEN-40 scale: 10 minutes are 2 s, the 5-minute pick-up 0.5 s
    monkeypatch.setattr(PL, "ALIVE_S", 2.5)
    PL.sync_jobs([w.pack])
    stop = threading.Event()
    worker = LW.Worker(root, beat_s=1)

    def loop():
        while not stop.is_set():
            if not worker.once():
                stop.wait(0.1)
    threading.Thread(target=loop, daemon=True).start()
    w.host, w.stop_worker = root, stop
    # the agents, the builder and the forge
    intake = next(a for a in w.pack["agents"] if a["id"] == "toy:intake")
    w.cards = {"toy:intake": {"id": "toy:intake", "harness": "hermes", "prompt": intake["prompt"]}}
    w.briefs = []
    monkeypatch.setattr(CD, "ADAPTERS", {"hermes": lambda c, t, s, prompt, card: w.briefs.append(str(prompt)) or TRIAGE})
    w.B, w.upstream, w.push = builds_standin(tmp_path, K.conn)
    monkeypatch.setitem(sys.modules, "builds", w.B)
    w.forge = Forge()
    monkeypatch.setitem(sys.modules, "forge", types.SimpleNamespace(FORGE=w.forge))
    # n8n, holding the pack's workflow from the pack's running commit
    wf = json.loads(Path(next(f["path"] for f in w.pack["workflows"] if f["name"] == "toy/ticket")).read_text())
    w.wf = wf
    w.n8n_db = tmp_path / "n8n-executions.json"

    def drop(body):                                  # the app's step port (server.flows.py): the request whole, or none of it
        rid = uuid.uuid4().hex[:16]
        tmp = FW.PENDING / f".{rid}.tmp"
        tmp.write_text(json.dumps(body))
        tmp.rename(FW.PENDING / f"{rid}.json")
    w.drop = drop
    w.n8n = N8n(wf, w.n8n_db, drop, scale={"toy.soak": {"seconds": 2}})

    def point():                                     # the runner side's paths and clock, again after each restart
        for name in ("PENDING", "DONE", "ASKS", "BUILDS", "JOBS"):
            monkeypatch.setattr(FW, name, tmp_path / "flows" / name.lower())
        FW.PENDING.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(RR, "ROOT", tmp_path / "flows/register")
        monkeypatch.setattr(RR, "_now", lambda: w.clock["now"])
        FW.M = types.SimpleNamespace(db=K.conn, stop=threading.Event(), log=w.logs.append, notify=w.told.append,
                                     event=lambda *a, **k: None)
    point()
    w.point = point
    w.K = K
    yield w
    stop.set()                                       # the worker of this temp folder ends with the test
    FW.M.stop.set()


def n8n_call(w):
    return lambda req, timeout=30: w.n8n(req, timeout)


def nap(w):
    def sleep(s):
        with w.lock:
            if w.n8n.down:                           # n8n's restart ends: its executions come back from its database
                w.n8n = N8n(w.wf, w.n8n_db, w.drop, w.n8n.scale)
                w.n8n_restarts += 1
            w.B.work()
        time.sleep(0.05)
    return sleep


def scan(w):
    """One pass of the runner's step worker (flows.worker): each pending request in a thread of its own."""
    for f in sorted(FW.PENDING.glob("*.json")):
        t = w.threads.get(f.stem)
        if t and t.is_alive():
            continue

        def run(rid=f.stem, path=f):
            try:
                FW.handle(rid, path, cards=w.cards, crew={}, post=n8n_call(w), sleep=nap(w), repos=["toy"])
            except Exception as e:                   # the test fails on it below
                w.errors.append(f"{rid}: {type(e).__name__}: {e}")
        w.threads[f.stem] = threading.Thread(target=run, daemon=True)
        w.threads[f.stem].start()


def settle(w, timeout=60):
    """The runner's passes until nothing moves: every step that can answer has, the others wait."""
    for _ in range(40):
        before = sorted(p.name for p in FW.PENDING.glob("*.json"))
        scan(w)
        end = time.time() + timeout
        for t in list(w.threads.values()):
            t.join(max(0.0, end - time.time()))
        assert not [t for t in w.threads.values() if t.is_alive()], "a step did not settle"
        assert w.errors == [], w.errors
        if sorted(p.name for p in FW.PENDING.glob("*.json")) == before:
            return
    raise AssertionError("the runner never came to rest")


def poll(w, **k):
    w.clock["now"] += 600                            # every pass is due (poll_minutes 5)
    return RR.poll(forge=w.forge, post=n8n_call(w), status=lambda ex: w.n8n.status(ex), now=w.clock["now"], **k)["said"]


def item(w, updated, comments=()):
    db = json.loads(w.store.read_text())
    db["items"][KEY] = {"updated": updated, "title": "The export fails at 2 GB",
                        "comments": [{"id": i + 1, "author": a, "body": b} for i, (a, b) in enumerate(comments)]}
    w.store.write_text(json.dumps(db))


def restart_runner(w):
    """The runner stops (its threads leave their steps where they are) and starts again: its modules are loaded anew,
    so everything it knows comes back from disk."""
    FW.M.stop.set()
    for t in w.threads.values():
        t.join(30)
    w.threads.clear()
    for m in (TR, RR, FW):
        importlib.reload(m)
    w.point()


def waiting_at(w, ex):
    return w.n8n.ex[ex]["at"] if w.n8n.ex[ex]["status"] == "waiting" else w.n8n.ex[ex]["status"]


def test_the_toy_pack_runs_end_to_end_in_a_customer_class_deployment_against_stand_ins(world):
    w = world
    # the deployment: customer data, no tailnet, n8n on 127.0.0.1 with its logic nodes only, answers kept lean
    assert DG.customer(DG.DATA) and "tailnet" not in DEPLOY.features(w.work) and DEPLOY.gate_problems(w.work) == []
    assert w.work["N8N_WEBHOOK_URL"] == "http://127.0.0.1:5678/" and FW.lean_answers()
    assert w.pack["problems"] == [] and "toy/ticket" in [f["name"] for f in w.pack["workflows"]]   # passed the node allowlist
    http = {"name": "Fetch", "type": "n8n-nodes-base.httpRequest", "parameters": {}}
    assert "httpRequest, which this deployment's n8n does not load" in PK._flow_problems("toy", [*w.wf["nodes"], http], PK.n8n_nodes())
    for kind in ("toy.soak",):                       # the owner approves the toy tool at the WSL host (Needs you)
        act = next(d for d in PL.decisions(lambda *a, **k: {"what": a[2], **k}) if d["what"] == f"Approve the command {kind} at wsl-host?")
        assert PL.handle(act["answers"][0]["act"])["ok"]
    for _ in range(100):
        if (((PL.place("wsl-host").status() or {}).get("kinds") or {}).get("toy.soak") or {}).get("approved"):
            break
        time.sleep(0.05)

    # 1. a stand-in item appears and the item's workflow starts, once, also when its event comes twice
    item(w, "2026-11-10T09:00:00")
    assert poll(w) == {"started": 1}
    assert list(w.n8n.ex) == ["101"] and RR.item("tickets", KEY)["runs"][0]["execution"] == "101"   # the webhook named its run
    (w.tmp / "state/tickets.json").unlink()                                                          # the same change, handed on again
    assert poll(w) == {"seen": 1} and list(w.n8n.ex) == ["101"]

    # 2. the agent triages it, and the run comments on the item in shadow, with the triage's whole text
    settle(w)
    assert KEY in w.briefs[0] and waiting_at(w, "101") == "Wait for the reply"
    shadow = TR._shadow()["comment"]["items"]
    assert len(shadow) == 1 and shadow[0]["body"] == "Thank you for the report. To reproduce it we need to know:\n\n" + TRIAGE
    assert json.loads(w.store.read_text())["items"][KEY]["comments"] == []                          # in shadow: nothing left the stack

    # the stack's own comment changes the item, and does not wake the run
    item(w, "2026-11-10T09:05:00", [("ai-stack", "Thank you for the report.")])
    assert poll(w) == {"recorded": 1}
    settle(w)
    assert waiting_at(w, "101") == "Wait for the reply"
    # a restart of the runner side mid-wait: the wait is still registered, nothing is answered
    wait = RR.item("tickets", KEY)["wait"]
    restart_runner(w)
    settle(w)
    assert RR.item("tickets", KEY)["wait"] == wait and waiting_at(w, "101") == "Wait for the reply"

    # 3. wait_item times out once, while n8n restarts: the answer waits for n8n, the run reminds and waits again
    w.clock["now"] += 72 * 3600 + 60
    w.n8n.down = True
    settle(w)
    ex = w.n8n.ex["101"]
    assert w.n8n_restarts == 1 and [a.get("outcome") for a in ex["took"] if "outcome" in a][:1] == ["timeout"]
    assert ex["data"]["Timed out?"]["outcome"] == "timeout" and "Remind the reporter" in ex["data"]
    assert waiting_at(w, "101") == "Wait for the reply" and RR.item("tickets", KEY)["wait"]["rid"] != wait["rid"]   # the second wait
    reminder = TR._shadow()["comment"]["items"][1]
    assert reminder["body"].startswith("A reminder: could you answer the questions above?")

    # 4. a reply comment wakes the run
    item(w, "2026-11-12T08:00:00", [("ai-stack", "Thank you for the report."), ("reporter", "2.4 GB, since 3.1, every time")])
    assert poll(w) == {"woke": 1}
    w.clock["now"] += 60
    scan(w)                                          # the wait answers; the run goes on to the toy tool at wsl-host
    for t in list(w.threads.values()):
        t.join(30)
    assert [a.get("outcome") for a in ex_took(w, "101") if "outcome" in a] == ["timeout", "reply"]
    assert waiting_at(w, "101") == "Reproduce"

    # 5. a job of ten minutes (2 s here) at wsl-host, a second one queued behind it, the runner and n8n restarted mid-job
    scan(w)
    seen = wait_until(lambda: (PL.place("wsl-host").status() or {}).get("running"))
    assert seen["kind"] == "toy.soak"
    w.n8n.ex["202"] = {"id": "202", "status": "waiting", "at": "another run's job", "resume": "n1", "data": {}, "last": "", "took": []}
    w.n8n.save()
    w.drop({"kind": "command", "place": "wsl-host", "command": "toy.soak", "values": {"seconds": 2}, "title": "Another run's job",
            "workflow": "packtoyticket01", "execution": "202", "resume_url": f"{N8N}/webhook-waiting/202/n1"})
    scan(w)
    assert wait_until(lambda: (PL.place("wsl-host").status() or {}).get("queued") == 1)              # one runs, one waits behind it
    restart_runner(w)                                                                                # mid-job
    w.n8n.down = True                                                                                # and n8n: back when the job ends
    settle(w, timeout=90)
    assert w.n8n_restarts == 2
    jobs = [d for d in (w.host / "outbox").iterdir() if d.is_dir()]
    assert len(jobs) == 2                                                                            # each submitted once
    ends = sorted(json.loads((d / "result.json").read_text())["ended"] for d in jobs)
    assert all(json.loads((d / "result.json").read_text())["status"] == "done" for d in jobs) and ends[1] - ends[0] >= 1
    other = w.n8n.ex["202"]["took"][0]
    assert other["status"] == "done" and other["command"] == "toy.soak"                             # neither given up
    ran = w.n8n.ex["101"]["data"]["Reproduce"]
    assert ran["status"] == "done" and ran["place"] == "wsl-host" and ran["artifact_ids"] and "log" not in ran   # its log by id only

    # 6. the change goes to a draft pull request on the stand-in forge, and a review comment wakes the run
    assert waiting_at(w, "101") == "Wait for the review"
    from domain import forgework as FWK
    branch = FWK.branch_name(KEY, "Make the change")
    assert w.forge.opened == [{"origin": "ssh://forge.example:7999/TOYPROJ/toy.git", "head": branch, "base": "release/1",
                               "title": f"{KEY}: Make the change", "draft": True}]
    assert w.B.assigned[0]["onto"] == branch and git(w.upstream, "rev-parse", branch) == git(w.upstream, "rev-parse", "v1.0^{commit}")   # from the tag
    assert git(w.push, "log", "-1", "--format=%s", branch) == "Stream the export instead of holding it"   # pushed through FORGE_PUSH
    built = w.n8n.ex["101"]["data"]["Make the change"]
    assert built["draft"] is True and built["pr"].endswith("/pull-requests/7") and "merge" not in json.dumps(w.B.assigned).lower()
    w.forge.cs = [{"id": 1, "author": "ai-stack", "body": "opened"}, {"id": 2, "author": "reviewer", "body": "please add a test"}]
    assert poll(w) == {"woke": 1}

    # 7. the run writes its summary in shadow and ends
    settle(w)
    assert w.n8n.status("101") == "success"
    summary = TR._shadow()["summary"]["items"]
    assert len(summary) == 1 and summary[0]["body"] == f"A fix is in the draft pull request {built['pr']}; its review has begun."
    assert json.loads(w.store.read_text())["items"][KEY]["comments"][-1]["author"] == "reporter"     # every write stayed in shadow

    # one run for the item, n8n got only summaries, the register holds the whole
    assert list(RR.item("tickets", KEY)["runs"]) and len(RR.item("tickets", KEY)["runs"]) == 1 and set(w.n8n.ex) == {"101", "202"}
    took = ex_took(w, "101")
    assert took and all(a.get("lean") is True for a in took)
    assert TRIAGE not in w.n8n_db.read_text() and TRIAGE[:300] not in w.n8n_db.read_text()          # nothing of the whole text in n8n
    assert RR.output_of("101", "Triage") == TRIAGE

    # the run's record exports as one zip a person can follow
    out = RC.export_run("101", w.tmp / "out/run.zip", db=w.K.conn(), packs=PK.load()["packs"])
    z = zipfile.ZipFile(out)
    run = json.loads(z.read("run.json"))
    assert [n["block"] for n in run["nodes"]] == ["agent", "tracker", "wait_item", "tracker", "wait_item", "command", "build", "wait_item", "tracker"]
    assert run["id"] == f"toy/ticket:tickets/{KEY}" and run["status"] == "done" and run["nodes"][0]["result"]["output"] == TRIAGE
    assert [w_["write"] for w_ in run["tracker_writes"]] == ["comment", "comment", "summary"] and all(w_["shadow"] for w_ in run["tracker_writes"])
    assert run["pull_requests"][0]["draft"] is True and run["pull_requests"][0]["url"] == built["pr"]
    shape = json.loads(z.read("workflow.json"))
    assert shape["name"] == "toy/ticket" and shape["source"].startswith("pack toy")


def ex_took(w, ex):
    return w.n8n.ex[ex]["took"]


def wait_until(f, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        got = f()
        if got:
            return got
        time.sleep(0.05)
    raise AssertionError("it never happened")


# The stand-in domain's words: the toy pack's name in each namespaced form (its workflows, agents, job kinds and
# webhooks), its agents and job kinds by name, the stand-in item's key and the stand-in forge's project.
STAND_IN_WORDS = (r"\btoy[/:.]\w", r"\bitem/toy\b", r"\bintake\b.*\breproducer\b", r"\btoy\.(soak|reproduce)\b", r"\bTOY-\d", r"\bTOYPROJ\b",
                  r"\bticket\.json\b")


def test_the_core_names_nothing_of_the_stand_in_domain():
    """The CR's boundary: the core learns nothing about a domain. The stand-in domain's words over ops/, images/,
    compose/, config/ and n8n/ find nothing (and they do find the toy pack itself, so the words are right)."""
    def hits(dirs):
        got = []
        for d in dirs:
            for f in (ROOT / d).rglob("*"):
                if not f.is_file() or "__pycache__" in f.parts or "node_modules" in f.parts:
                    continue
                try:
                    text = f.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                got += [f"{f.relative_to(ROOT)}: {w}" for w in STAND_IN_WORDS if re.search(w, text)]
        return got
    assert hits(["ops", "images", "compose", "config", "n8n"]) == []
    assert len(hits(["tests/fixtures/packs/toy"])) >= 4

"""The preview (docs/AI-STACK-PLAN.md §11, M2): the AI Stack's new screens, seen before the cutover, on a dark engine.

It is not the live stack. It runs only the demo templates of config/templates/demo, the toy pack and a stand-in
tracker, in a namespace of its own (preview) of the live Temporal (until the cutover it had a Temporal of its own, the
compose project aipreview), with demo activities that touch nothing outside: they sleep for a
while and answer references. Everything else the screens show comes from the live app, read only.

    python3 ops/engine/preview.py serve [port]     the worker, the starter, the projector and the web server
                                                   (127.0.0.1:8097 by default; it stops at the cutover)

The web server serves the integration branch's screens (images/mission-control/web), passes every other read to the
live app with the Tailscale headers the app expects from its front door, adds the preview engine's runs to the state,
and takes one action: Approve or Refuse on a demo run's gate. Every other write is refused: the preview is read only.
"""
import asyncio
import datetime as dt
import http.client
import json
import os
import random
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))
from temporalio import activity  # noqa: E402

from engine import client as CL  # noqa: E402
from engine import converter as CV  # noqa: E402
from engine import graph as G  # noqa: E402
from engine import projector as P  # noqa: E402
from engine import runner as R  # noqa: E402
from engine import packs as PK  # noqa: E402
from engine import trackers as TR  # noqa: E402
from engine import roles as RL  # noqa: E402
import decisions as DQ  # noqa: E402
from engine import templates as T  # noqa: E402
from engine import worker as EW  # noqa: E402

NAMESPACE = "preview"
HOME = Path.home() / ".local/share/aistack/preview"
SHOWN = HOME / "engine.json"
DRAFTS = HOME / "drafts"                         # the builder's drafts in the preview, never the live ones
WEB = ROOT / "images/mission-control/web"
TEMPLATES = sorted((ROOT / "config/templates/demo").glob("*.yaml"))
LIVE = ("127.0.0.1", 8090)
HEADERS = {"Tailscale-User-Login": "preview", "Tailscale-User-Name": "Preview"}
PACE = (4, 25)                  # limit: paces, a demo step takes 4 to 25 seconds, so a run is seen moving
VERSION = int(time.time())       # the preview's scripts and styles, fetched fresh after each start
RESULTS = {}                    # the preview's slow requests (a template drafted from a description) by id, as the runner's results
READS = {"memory_browse"}        # the app's actions that only read: the preview passes them to the live app
KEEP = 1                        # limit: paces, one running run of each demo template; a new one starts when it ends


# ---------- demo activities: they touch nothing outside ----------
@activity.defn(name="load_graph")
async def load_graph(ref: dict) -> G.Graph:
    return G.canonical(Path(ref["path"]).read_text(encoding="utf-8"))


@activity.defn(name="step")
async def step(inp: R.StepInput) -> dict:
    await asyncio.sleep(random.uniform(*PACE))
    n = inp.node
    if n.id in ("spec", "collect"):
        return {"ref": f"artifact:{n.id}", "pass": True, "items": [f"case {i + 1}" for i in range(random.randint(3, 6))]}
    if n.block == "branch":                                  # the decider names one of its branches
        return {"ref": f"artifact:{n.id}", "pass": True, "branch": random.choice(n.branches)}
    if n.loop_to and inp.round == 0 and random.random() < 0.5:
        return {"ref": f"artifact:{n.id}", "pass": False, "problems": random.randint(1, 3)}     # a first round that sends work back
    return {"ref": f"artifact:{n.id}{':' + inp.item if inp.item else ''}", "pass": True}


@activity.defn(name="decision")
async def decision(d: dict) -> dict:
    return {"queued": True, "people": RL.people(d.get("role") or "")}


@activity.defn(name="remind")
async def remind(d: dict) -> dict:
    return {"sent": True}


@activity.defn(name="finish")
async def finish(d: dict) -> dict:
    return {"finished": True}


@activity.defn(name="command")
async def command(d: dict) -> dict:
    await asyncio.sleep(random.uniform(*PACE))
    return {"pass": True, "ref": f"job:{d['place']}/demo"}


@activity.defn(name="tracker_write")
async def tracker_write(d: dict) -> dict:
    return TR.write({**d, "tracker": d.get("tracker") or "demo"})


@activity.defn(name="checkpoint")
async def checkpoint(d: dict) -> R.Look:
    return R.Look(changed=False)


ACTS = [load_graph, step, decision, remind, finish, checkpoint, tracker_write, command]


# ---------- the engine's side ----------
async def keep_going(client):
    """Each demo template has a run going; a ticket's reporter answers after a while, as a person would."""
    running = {}
    async for w in client.list_workflows("WorkflowType = 'graph-run' AND ExecutionStatus = 'Running'"):
        running[w.id.split(":")[0]] = w.id
    for path in TEMPLATES:
        g = G.canonical(path.read_text(encoding="utf-8"))
        if g.name in running:
            wid = running[g.name]
            try:
                st = await client.get_workflow_handle(wid).query(R.GraphRun.state)
            except Exception as e:                         # a run that cannot answer now (its task is retried): the others go on
                print(f"preview: run {wid} does not answer now: {type(e).__name__}", flush=True)
                continue
            for n in g.nodes:
                s = (st.get("nodes") or {}).get(n.id, {})
                if n.block == "wait" and s.get("status") == "waiting" and random.random() < 0.15:
                    await client.get_workflow_handle(wid).signal(R.GraphRun.event, args=[wid, {"ref": "reply:demo"}])
            continue
        item = f"{g.name}:{dt.datetime.now().strftime('%H%M%S')}"
        await client.start_workflow(R.GraphRun.run, R.RunInput(task=item, ref={"kind": "template", "path": str(path)}),
                                    id=item, task_queue=R.QUEUE)


def reporter():
    """The preview's stand-in tracker gets a new ticket now and then, and a reporter answers a ticket's question, as
    people would; the poller starts each ticket's run of the toy pack's template once."""
    store = HOME / "standin.json"
    db = json.loads(store.read_text()) if store.is_file() else {"items": {}}
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    open_ = [k for k, v in db["items"].items() if not v.get("status")]
    if len(open_) < 2 and random.random() < 0.1:
        key = f"DEMO-{len(db['items']) + 1}"
        db["items"][key] = {"updated": now, "title": random.choice(["The export stops at 2 GB", "Login fails after the update", "How do I export one folder?"]),
                            "comments": []}
    store.write_text(json.dumps(db, indent=1))


def toy_pack():
    """The preview's own pack: the stack's toy pack as a git repository outside the repository, listed in a packs.txt of
    the preview's, with approvals of its own; the owner approves its commit in the preview's queue like a real one."""
    import shutil
    import subprocess
    src = HOME / "packsrc/toy"
    if not (src / ".git").is_dir():
        shutil.copytree(ROOT / "tests/fixtures/packs/toy", src, dirs_exist_ok=True)
        for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["-c", "user.name=preview", "-c", "user.email=preview@localhost", "commit", "-q", "-m", "The toy pack"]):
            subprocess.run(["git", *args], cwd=src, check=True)
    shutil.copytree(ROOT / "tests/fixtures/packs/toy", src, dirs_exist_ok=True)     # the fixture changed: a new commit, as a pack's author would
    if subprocess.run(["git", "status", "--porcelain"], cwd=src, capture_output=True, text=True).stdout.strip():
        subprocess.run(["git", "add", "-A"], cwd=src, check=True)
        subprocess.run(["git", "-c", "user.name=preview", "-c", "user.email=preview@localhost", "commit", "-q", "-m", "The toy pack, updated"], cwd=src, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True, check=True).stdout.strip()
    (HOME / "packs.txt").write_text(f"# the preview's packs (ops/engine/preview.py toy_pack)\ntoy {src} {head}\n")
    (HOME / "trackers.yaml").write_text(f"# the preview's stand-in tracker (ops/engine/preview.py)\nshadow_needed: 3\ntrackers:\n"
                                        f"  - {{name: demo, kind: standin, path: {HOME / 'standin.json'}, template: toy/bug}}\n")
    os.environ.update({"AISTACK_PACKS_TXT": str(HOME / "packs.txt"), "AISTACK_PACKS": str(HOME / "packs"),
                       "AISTACK_PACK_APPROVALS": str(HOME / "pack-approvals.json"), "AISTACK_TRACKERS": str(HOME / "trackers.yaml"),
                       "AISTACK_TRACKER_STATE": str(HOME / "trackers")})


def engine():
    key = HOME / "codec.key"
    if not key.is_file():
        HOME.mkdir(parents=True, exist_ok=True)
        key.write_text(CV.new_key())
        key.chmod(0o600)
    k = CV.key_from_env({CV.KEY_ENV: key.read_text()})
    return EW.Engine(workflows=[R.GraphRun, R.NodeRun], activities=ACTS, queues={R.QUEUE: 4, R.STEP_QUEUE: 4, "place-wsl": 2, "place-wsl-host": 2, "place-windows": 2},
                     connect=lambda: CL.connect(ns=NAMESPACE, data_converter=CV.data_converter(False, k))).start()


def projector_loop(eng, stop):
    while not stop.is_set():
        try:
            eng.call(keep_going)
            snap = eng.call(P.snapshot)
            loaded = PK.load()
            snap["templates"], snap["agents"] = T.listing(DRAFTS, loaded["packs"]), T.agents(loaded["packs"])
            snap["packs"] = loaded
            reporter()
            eng.call(lambda cl: TR.poll(cl, start=TR.starter(loaded["packs"])))
            snap["trackers"] = TR.view()
            P.write(SHOWN, snap)
        except Exception as e:
            P.down(SHOWN, f"{type(e).__name__}: {e}")
        stop.wait(3)


# ---------- the web side ----------
def live(method, path, body=None):
    c = http.client.HTTPConnection(*LIVE, timeout=60)
    c.request(method, path, body=body, headers={**HEADERS, **({"Content-Type": "application/json"} if body else {})})
    r = c.getresponse()
    return r.status, r.getheaders(), r.read()


def shown():
    try:
        return json.loads(SHOWN.read_text())
    except (OSError, ValueError):
        return None


def make_handler(eng):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json", extra=()):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def state(self):
            code, _, body = live("GET", "/api/state")
            s = json.loads(body) if code == 200 else {}
            s["engine"] = shown()
            ours = list(PK.decisions(DQ._d, (s["engine"] or {}).get("packs") or {"pending": []}))   # the preview's own pack commits
            ours += list(TR.decisions(DQ._d))                                            # and its stand-in tracker's shadow writes
            s["decisions"] = ours + [d for d in s.get("decisions") or [] if not str(d.get("id", "")).startswith(("pack:", "shadow:", "tracker-live:"))]
            return s

        def do_GET(self):
            path = self.path.split("?")[0]
            if path.startswith("/static/") and (WEB / path.lstrip("/")).is_file():
                f = WEB / path.lstrip("/")
                ctype = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png",
                         ".woff2": "font/woff2", ".json": "application/json"}.get(f.suffix, "application/octet-stream")
                return self.send(200, f.read_bytes(), ctype)
            if path.startswith("/api/result/") and path.split("/")[-1] in RESULTS:
                return self.send(200, json.dumps(RESULTS[path.split("/")[-1]]).encode())
            if path == "/api/state":
                return self.send(200, json.dumps(self.state(), ensure_ascii=False).encode())
            if path == "/api/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                last = None
                try:
                    self.wfile.write(b"retry: 3000\n\n")
                    while True:
                        s = json.dumps(self.state(), ensure_ascii=False)
                        if s != last:
                            last = s
                            self.wfile.write(f"data: {s}\n\n".encode())
                        else:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        time.sleep(2)
                except (BrokenPipeError, ConnectionResetError):
                    return
            code, headers, body = live("GET", self.path)
            ctype = dict((k.lower(), v) for k, v in headers).get("content-type", "text/html")
            if path in ("/", "/index.html"):                # the live app's page, with the new screen's script, never cached
                ours = re.findall(rb'<script src="/static/(app-[^"]+\.js)"></script>', (WEB / "index.html").read_bytes())
                for name in ours:                          # every screen script of the branch that the live page lacks
                    if b"/static/" + name not in body:
                        body = body.replace(b'<script src="/static/app.js"></script>', b'<script src="/static/' + name + b'"></script>\n<script src="/static/app.js"></script>')
                body = re.sub(rb'((?:src|href)="/static/[^"?]+)"', lambda m: m.group(1) + f"?v={VERSION}".encode() + b'"', body)
                body = body.replace(b"<title>", b"<title>Preview: ", 1)
            self.send(code, body, ctype)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}") if n else {}
            if self.path.startswith("/api/request") and req.get("action") == "engine_decide":
                answer = "yes" if req.get("answer") == "yes" else "no"
                eng.call(lambda cl: cl.get_workflow_handle(str(req["run"])).signal(R.GraphRun.decide, args=[str(req["node"]), answer, "owner (preview)"]))
                return self.send(200, json.dumps({"ok": True, "id": "preview", "result": {"ok": True}}).encode())
            if self.path.startswith("/api/request") and req.get("action") in ("template_save", "template_test", "template_describe"):
                def start(name, path):
                    wid = f"test/{name}:{dt.datetime.now().strftime('%H%M%S')}"
                    eng.call(lambda cl: cl.start_workflow(R.GraphRun.run, R.RunInput(task=wid, ref={"kind": "template", "path": path}), id=wid, task_queue=R.QUEUE))
                    return wid
                if req.get("action") == "template_describe":     # a model call takes longer than a request: answered as pending
                    rid = f"describe-{time.time_ns()}"
                    RESULTS[rid] = {"pending": True, "id": rid}
                    threading.Thread(target=lambda: RESULTS.update({rid: {**T.handle(req, drafts=DRAFTS), "id": rid}}), daemon=True).start()
                    return self.send(200, json.dumps(RESULTS[rid]).encode())
                res = T.handle(req, start=start, drafts=DRAFTS, packs=PK.load()["packs"])
                return self.send(200, json.dumps({**res, "id": "preview"}).encode())
            if self.path.startswith("/api/request") and req.get("action") in ("pack_approve", "pack_refuse"):   # the preview's toy pack
                return self.send(200, json.dumps({**PK.handle(req), "id": "preview"}).encode())
            if self.path.startswith("/api/request") and req.get("action") in ("tracker_shadow_approve", "tracker_shadow_reject", "tracker_live"):
                return self.send(200, json.dumps({**TR.handle(req), "id": "preview"}).encode())
            if self.path.startswith("/api/request") and req.get("action") in READS:     # a read: the live app answers it
                code, _, body = live("POST", "/api/request", json.dumps(req).encode())
                return self.send(code, body)
            if self.path.startswith("/api/clienterror") or self.path.startswith("/api/view"):
                return self.send(204, b"")
            return self.send(403, json.dumps({"ok": False, "error": "the preview is read only: only a demo gate can be answered here"}).encode())
    return H


def serve(port=8097):
    toy_pack()
    eng = engine()
    stop = threading.Event()
    threading.Thread(target=projector_loop, args=(eng, stop), daemon=True, name="preview-projector").start()
    print(f"preview on http://127.0.0.1:{port}/#/engine", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), make_handler(eng)).serve_forever()


if __name__ == "__main__":
    if sys.argv[1:2] == ["serve"]:
        serve(int(sys.argv[2]) if len(sys.argv) > 2 else 8097)
    else:
        sys.exit(__doc__)

"""WFL-14: n8n inside the app. The app serves n8n's editor under its own address at /n8n/, behind its own gate (the
owner's Tailscale login, no write from another site), takes the prefix off for n8n, passes methods, query strings,
bodies, cookies and the answer as it streams, and lets only its own pages frame it. WFL-11: the runner's view of every
workflow and its recent runs (ops/flows_view.py), which the app's Workflows page, task pages and agent pages read."""
import json
from pathlib import Path

import httpx
import pytest
import yaml

import flows as FW
import flows_view as FV

ROOT = Path(__file__).resolve().parents[1]
GATE = {"tailscale-user-login": "owner@example.com"}


def answer_of(status=200, headers=None, body=b""):
    """n8n's answer as the network gives it: a stream, read once by the app as it passes it on."""
    async def chunks():
        yield body
    return httpx.Response(status, headers=headers, content=chunks())


@pytest.fixture
def n8n(monkeypatch):
    """A fake n8n behind the app: it records what it was sent and answers what the test sets."""
    import server as S
    from starlette.testclient import TestClient
    seen, answer = [], {}

    def handle(req):
        seen.append(req)
        if answer.get("raise"):
            raise httpx.ConnectError("n8n is down", request=req)
        return answer.get("response") or answer_of(200, {"content-type": "application/json"}, b'{"data": {}}')
    monkeypatch.setattr(S, "_frame_transport", httpx.MockTransport(handle))
    return TestClient(S.app, base_url="https://pc.example.ts.net:8447"), seen, answer


def test_n8n_is_served_under_the_apps_address_behind_its_gate(n8n):
    cl, seen, answer = n8n
    assert cl.get("/n8n/home/workflows").status_code == 403 and not seen          # no Tailscale login: n8n is never asked
    answer["response"] = answer_of(200, [("content-type", "text/html"), ("x-frame-options", "SAMEORIGIN"),
                                                      ("set-cookie", "n8n-auth=a; Path=/; HttpOnly"), ("set-cookie", "n8n-browser=b; Path=/")], b"<html>n8n</html>")
    r = cl.get("/n8n/rest/settings?include=all", headers={**GATE, "cookie": "n8n-auth=a", "browser-id": "b1"})
    assert r.status_code == 200 and r.text == "<html>n8n</html>"
    sent = seen[-1]
    assert sent.url.path == "/rest/settings" and sent.url.params["include"] == "all" and sent.url.host == "n8n"   # the prefix is n8n's to not know
    assert sent.headers["cookie"] == "n8n-auth=a" and sent.headers["browser-id"] == "b1"
    assert "tailscale-user-login" not in sent.headers and sent.headers["x-forwarded-host"] == "pc.example.ts.net:8447"
    assert sent.headers["x-forwarded-proto"] == "https" and sent.headers["accept-encoding"] == r.request.headers["accept-encoding"]
    import types
    import server as S
    from starlette.datastructures import Headers
    assert ("accept-encoding", "identity") in S.frame_headers_in(types.SimpleNamespace(headers=Headers({"host": "h"})))   # never httpx's own gzip
    assert r.headers.get_list("set-cookie") == ["n8n-auth=a; Path=/; HttpOnly", "n8n-browser=b; Path=/"]
    assert "x-frame-options" not in r.headers and r.headers["content-security-policy"] == "frame-ancestors 'self'"   # only the app frames it
    answer["response"] = answer_of(302, {"location": "/signin?redirect=%2F"})
    assert cl.get("/n8n/", headers=GATE, follow_redirects=False).headers["location"] == "/n8n/signin?redirect=%2F"
    answer.pop("response")
    r = cl.post("/n8n/rest/login", headers={**GATE, "content-type": "application/json"}, content=b'{"emailOrLdapLoginId": "x"}')
    assert r.status_code == 200 and seen[-1].method == "POST" and seen[-1].read() == b'{"emailOrLdapLoginId": "x"}'
    n = len(seen)
    assert cl.post("/n8n/rest/login", headers={**GATE, "sec-fetch-site": "cross-site"}, content=b"{}").status_code == 403 and len(seen) == n   # SEC-20
    assert cl.get("/n8n", headers=GATE, follow_redirects=False).headers["location"] == "/n8n/"
    answer["raise"] = True
    r = cl.get("/n8n/home/workflows", headers=GATE)
    assert r.status_code == 502 and "not reachable" in r.text


def test_n8ns_live_updates_stream_through_the_app(n8n):
    cl, seen, answer = n8n

    async def events():
        for i in range(3):
            yield f"data: {i}\n\n".encode()
    answer["response"] = httpx.Response(200, headers={"content-type": "text/event-stream"}, content=events())
    with cl.stream("GET", "/n8n/rest/push?pushRef=p1", headers={**GATE, "accept": "text/event-stream"}) as r:
        assert r.headers["content-type"] == "text/event-stream"
        assert b"".join(r.iter_bytes()) == b"data: 0\n\ndata: 1\n\ndata: 2\n\n"
    assert seen[-1].url.path == "/rest/push" and seen[-1].url.params["pushRef"] == "p1"


def test_compose_puts_n8n_under_n8n_with_live_updates_over_plain_http():
    core = yaml.safe_load((ROOT / "compose/core.yaml").read_text())
    apps = yaml.safe_load((ROOT / "compose/apps.yaml").read_text())
    env = core["services"]["n8n"]["environment"]
    assert env["N8N_PATH"] == "/n8n/" and env["N8N_PUSH_BACKEND"] == "sse"
    # the app's tailnet address, and webhooks and resume URLs at n8n's root; without the tailnet the deployment's own
    # addresses on 127.0.0.1 (WFL-15, tests/test_customer_deployment.py)
    assert env["N8N_EDITOR_BASE_URL"] == "${N8N_EDITOR_URL:-https://${PC_TAILNET_HOST:-localhost}:8447/n8n/}"
    assert env["WEBHOOK_URL"] == "${N8N_WEBHOOK_URL:-https://${PC_TAILNET_HOST:-localhost}:8450/}"
    assert "stepnet" in core["services"]["n8n"]["networks"] and "stepnet" in apps["services"]["mission-control"]["networks"]
    server = (ROOT / "images/mission-control/server.py").read_text()
    assert '"/share", *(f"/{n}" for n in FRAMES))) and not request.headers.get("tailscale-user-login")' in server
    assert "*FRAME_ROUTES," in server and '_part("server.frames.py")' in server and '_part("server.n8n.py")' in server
    assert '"n8n": os.environ.get("N8N_URL", "http://n8n:5678")' in (ROOT / "images/mission-control/server.frames.py").read_text()
    sw = (ROOT / "images/mission-control/web/sw.js").read_text()
    assert 'url.pathname.startsWith("/n8n") || url.pathname.startsWith("/phoenix")) return;' in sw                                    # never cached by the app's worker


def test_a_resume_url_stays_at_n8ns_root():
    """n8n answers at its root whatever N8N_PATH says; under /n8n/ it answers with its page. So the resume URLs keep
    n8n's root (WEBHOOK_URL), and a resume URL under /n8n/ is refused instead of being 'delivered' to a page."""
    assert FW.resume_target("https://pc.example.ts.net:8450/webhook-waiting/7?signature=" + "a" * 64).startswith("http://127.0.0.1:5678/webhook-waiting/7")
    assert FW.resume_target("https://pc.example.ts.net:8447/n8n/webhook-waiting/7") == ""


def wf(i, name, nodes, conn=None, active=False):
    return {"id": i, "name": name, "active": active, "nodes": nodes, "connections": conn or {}}


def step(name, x=260, **p):
    return {"name": name, "type": "CUSTOM.aistackStep", "position": [x, 0], "parameters": {"title": name, **p}}


def repo(tmp_path):
    r = tmp_path / "wf"
    r.mkdir(exist_ok=True)
    cron = {"name": "On its schedule", "type": "n8n-nodes-base.scheduleTrigger", "position": [0, 0],
            "parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": "0 * * * *"}]}}}
    (r / "a.json").write_text(json.dumps(wf("w1", "Crew: Checker", [cron, step("Crew: Checker", kind="crew", job="checker")],
                                            {"On its schedule": {"main": [[{"node": "Crew: Checker"}]]}}, active=True)))
    hook = {"name": "Called", "type": "n8n-nodes-base.webhook", "position": [0, 0], "parameters": {"path": "x"}}
    (r / "b.json").write_text(json.dumps(wf("w2", "Research", [hook, step("Write", 520, kind="agent", agent="writer"),
                                                               step("Find", 260, kind="agent", agent="scout"), step("Ask you", 780, kind="ask")],
                                            {"Called": {"main": [[{"node": "Find"}]]}, "Find": {"main": [[{"node": "Write"}]]}, "Write": {"main": [[{"node": "Ask you"}]]}})))
    return r


def drop(d, rid, **req):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{rid}.json").write_text(json.dumps(req))


def test_the_view_has_every_workflow_its_schedule_its_steps_and_its_recent_runs(tmp_path):
    pend, done = tmp_path / "pending", tmp_path / "done"
    drop(pend, "s1", kind="agent", agent="scout", title="Find", workflow="w2", execution="40", resume_url="x")
    drop(pend, "s2", kind="crew", job="checker", title="Crew: Checker", workflow="w1", execution="41")
    drop(pend, "s3", kind="agent", agent="scout", title="Find", resume_url="x")      # names no run: not one of n8n's
    seen = {}
    assert FV.look(seen, pend) == 2 and FV.look(seen, pend) == 0
    (pend / "s1.json").unlink()                                                     # n8n took its answer: the request is gone
    drop(done, "s1", status="done", output="facts")
    drop(pend, "s4", kind="agent", agent="writer", title="Write", workflow="w2", execution="40")
    assert FV.look(seen, pend) == 1
    v = FV.view(repo(tmp_path), seen, done)
    w1, w2 = sorted(v["workflows"], key=lambda w: w["id"])
    assert (w1["name"], w1["active"], w1["schedule"], w1["for"], w1["crew"]) == ("Crew: Checker", True, "hourly at :00", "crew:checker", ["checker"])
    assert [s["title"] for s in w2["steps"]] == ["Find", "Write", "Ask you"] and w2["agents"] == ["scout", "writer"] and w2["schedule"] == "when called"
    r = w2["runs"][0]
    assert (r["execution"], r["state"], r["on"]) == ("40", "running", "Write") and r["ended"] is None
    assert [(s["title"], s["state"]) for s in r["steps"]] == [("Find", "done"), ("Write", "running")]
    assert w1["runs"][0]["state"] == "running" and w2["runs_total"] == 1
    drop(done, "s4", status="failed", error="no headroom")
    r = FV.view(repo(tmp_path), seen, done)["workflows"][1]["runs"][0]
    assert r["state"] == "failed" and r["on"] == "Write" and r["ended"]


def test_a_question_waits_for_the_owner_and_old_runs_leave_the_view(tmp_path, monkeypatch):
    pend, done = tmp_path / "pending", tmp_path / "done"
    drop(pend, "q1", kind="ask", title="Ask you", workflow="w2", execution="9", question="Go?")
    seen = {}
    FV.look(seen, pend)
    assert FV.view(repo(tmp_path), seen, done)["workflows"][1]["runs"][0]["state"] == "waiting"
    monkeypatch.setattr(FV, "RUNS_SHOWN", 2)
    monkeypatch.setattr(FV, "SEEN_KEPT", 3)
    for i in range(5):
        drop(pend, f"r{i}", kind="crew", job="checker", workflow="w1", execution=str(100 + i))
    FV.look(seen, pend)
    assert len(seen) == 3
    w1 = FV.view(repo(tmp_path), seen, done)["workflows"][0]
    assert len(w1["runs"]) == 2 and w1["runs_total"] == 3


def test_a_schedule_reads_in_words():
    assert [FV.cron_words(e) for e in ("30 4 * * *", "0 * * * *", "*/10 * * * *", "0 */6 * * *", "0 9 * * 1", "15 7 * * 1-5", "0 6 02 * *", "* * * * *", "0 4 1 1 *")] == \
        ["daily 04:30", "hourly at :00", "every 10 minutes", "every 6 hours", "Mondays 09:00", "weekdays 07:15", "monthly on day 2, 06:00", "every minute", "0 4 1 1 *"]
    assert FV.schedule_of({"nodes": [{"type": "n8n-nodes-base.rssFeedReadTrigger"}]}) == "on an event"
    assert FV.schedule_of({"nodes": [{"type": "n8n-nodes-base.manualTrigger"}]}) == "by hand"
    assert FV.schedule_of({"nodes": []}) == "by hand"


def test_the_runner_writes_the_view_beside_the_step_service(tmp_path):
    import types
    seen = {}
    m = types.SimpleNamespace(PUBLIC=tmp_path)
    FV.M = m
    FV.write(tmp_path, seen)
    assert "workflows" in json.loads((tmp_path / FV.OUT).read_text())
    FV.save({"a": {"started": "x"}}, tmp_path / "seen.json")
    assert FV.load(tmp_path / "seen.json") == {"a": {"started": "x"}} and FV.load(tmp_path / "none.json") == {}
    src = (ROOT / "ops/missions.py").read_text()
    assert "    FW.start(sys.modules[__name__])\n    import flows_view as FV" in src and "FV.start(sys.modules[__name__])" in src
    import server as S
    from starlette.testclient import TestClient
    cl = TestClient(S.app)
    assert cl.get("/api/workflows").status_code == 403


def test_phoenix_is_served_inside_the_app_like_n8n_and_a_step_s_call_opens_on_the_traces_page(n8n, monkeypatch):
    """APP-66: Phoenix (PHOENIX_HOST_ROOT_PATH=/phoenix) under the app's address, behind its gate, framed by the app only;
    "Open in Phoenix" lands on the app's Traces page with the call's trace."""
    cl, seen, answer = n8n
    assert cl.get("/phoenix/projects").status_code == 403 and not seen                 # no Tailscale login: Phoenix is never asked
    answer["response"] = answer_of(200, [("content-type", "text/html"), ("x-frame-options", "DENY")], b"<html>phoenix</html>")
    r = cl.get("/phoenix/projects/UHJ", headers=GATE)
    assert r.status_code == 200 and seen[-1].url.host == "phoenix" and seen[-1].url.path == "/projects/UHJ"
    assert "x-frame-options" not in r.headers and r.headers["content-security-policy"] == "frame-ancestors 'self'"
    assert cl.get("/phoenix", headers=GATE, follow_redirects=False).headers["location"] == "/phoenix/"
    import server as S
    real = httpx.AsyncClient

    def fake(req):
        if req.url.path == "/v1/projects":
            return httpx.Response(200, json={"data": [{"name": "default", "id": "P1"}]})
        return httpx.Response(200, json={"data": [{"name": "litellm_request", "start_time": "2026-11-10T10:00:00+00:00", "end_time": "2026-11-10T10:00:02+00:00", "context": {"trace_id": "T9"}, "attributes": {}}]})
    monkeypatch.setattr(S.httpx, "AsyncClient", lambda **k: real(transport=httpx.MockTransport(fake), **k))
    ts = __import__("datetime").datetime(2026, 11, 10, 10, 0, 2, tzinfo=__import__("datetime").timezone.utc).timestamp()
    r = cl.get(f"/api/phoenix?ts={ts}&ms=2000", headers=GATE, follow_redirects=False)
    assert r.headers["location"] == "/#/traces?open=%2Fprojects%2FP1%2Ftraces%2FT9"
    assert cl.get("/api/phoenix", headers=GATE, follow_redirects=False).headers["location"] == "/#/traces?open=%2Fprojects%2FP1"
    core = yaml.safe_load((ROOT / "compose/core.yaml").read_text())["services"]["phoenix"]
    assert core["environment"]["PHOENIX_HOST_ROOT_PATH"] == "/phoenix" and "obs" in core["networks"]
    wf = (ROOT / "images/mission-control/web/static/app-workflows.js").read_text()
    assert 'toolPage("Traces", `/phoenix${path}`' in wf and "traces: vTraces" in (ROOT / "images/mission-control/web/static/app-base.js").read_text()
    assert next(t for t in json.loads((ROOT / "images/mission-control/web/static/tools.json").read_text())["tools"] if t["id"] == "phoenix")["host"] == "app"

"""APP-85 to APP-87 (the factory design v3, §4 B): n8n's own canvas in the app. The app holds n8n's session for the
owner's own signed-in session (make n8n-login stores the login once); the workflow page shows n8n's read-only canvas,
Edit opens the draft in n8n's editor with publishing and running refused, a run's page shows n8n's view of its
execution, and the AI Stack node leads to its agent's page. n8n here is a fake behind httpx's MockTransport; the real
one was checked with a browser on a throwaway n8n (the branch's report)."""
import json
import re
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

import webjs

ROOT = Path(__file__).resolve().parents[1]
OWNER = {"tailscale-user-login": "owner@example.com"}
COOKIE = "jwt-of-the-app"


def answer(status, body=b"", headers=()):
    """n8n's answer as the network gives it: a stream, read once as the app passes it on."""
    async def chunks():
        yield body
    return httpx.Response(status, headers=list(headers), content=chunks())


@pytest.fixture
def n8n(monkeypatch, tmp_path):
    """A fake n8n: it signs in the stored test login (setting n8n-auth), answers each request, and records what it got."""
    import server as S
    seen, state = [], {"logins": 0, "expire": False, "login_ok": True}

    def handle(req):
        seen.append(req)
        if req.url.path == "/rest/login" and req.method == "POST":
            state["logins"] += 1
            if not state["login_ok"]:
                return answer(401, b'{"message": "Wrong username or password"}', [("content-type", "application/json")])
            return answer(200, b'{"data": {}}', [("content-type", "application/json"), ("set-cookie", f"n8n-auth={COOKIE}{state['logins']}; Path=/; HttpOnly")])
        if state["expire"] and req.headers.get("cookie", "").find(f"n8n-auth={COOKIE}1") >= 0:
            return answer(401, b'{"message": "Unauthorized"}', [("content-type", "application/json")])
        if req.url.path.startswith("/rest/workflows/w1"):
            return answer(200, json.dumps({"data": WF}).encode(), [("content-type", "application/json"), ("set-cookie", "n8n-auth=leak; Path=/")])
        return answer(200, b"<html>n8n</html>", [("content-type", "text/html")])
    monkeypatch.setattr(S, "_frame_transport", httpx.MockTransport(handle))
    monkeypatch.setattr(S, "N8N_LOGIN", {"email": "test@example.com", "password": "test-only-password"})
    monkeypatch.setattr(S, "N8N_SESSION", {"cookie": "", "browser": "", "at": 0.0})
    m = tmp_path / "public"
    m.mkdir()
    (m / "state.json").write_text("{}")
    monkeypatch.setattr(S, "STATE", m / "state.json")
    return S, TestClient(S.app, base_url="http://127.0.0.1:8090"), seen, state


WF = {"id": "w1", "name": "Weekly news", "versionId": "v2", "activeVersionId": "v1", "settings": {"executionOrder": "v1"},
      "nodes": [{"name": "Draft only", "type": "n8n-nodes-base.set"}], "connections": {},
      "activeVersion": {"nodes": [{"name": "On its schedule (0 8 * * 1)", "type": "n8n-nodes-base.scheduleTrigger"},
                                  {"name": "Run now", "type": "n8n-nodes-base.webhook"},
                                  {"name": "Research and write", "type": "CUSTOM.aistackStep", "parameters": {"kind": "task"}}],
                        "connections": {"On its schedule (0 8 * * 1)": {"main": [[{"node": "Research and write", "type": "main", "index": 0}]]},
                                        "Run now": {"main": [[{"node": "Research and write", "type": "main", "index": 0}]]}}}}


def test_the_app_holds_n8ns_session_for_the_owners_own_session_only(n8n):
    """APP-85: the owner's request carries the app's session (its n8n-auth and the browser id it is bound to), the
    browser's own n8n-auth is replaced and one n8n sets never reaches the browser; the stack's own checks get none."""
    S, cl, seen, state = n8n
    r = cl.get("/n8n/rest/workflows/w1", headers={**OWNER, "cookie": "n8n-auth=the-browsers; other=1", "browser-id": "browsers-own"})
    assert r.status_code == 200 and state["logins"] == 1
    sent = seen[-1]
    assert sent.headers["cookie"] == f"other=1; n8n-auth={COOKIE}1" and sent.headers["browser-id"] == S.N8N_SESSION["browser"] != "browsers-own"
    login = next(x for x in seen if x.url.path == "/rest/login")
    assert login.headers["browser-id"] == S.N8N_SESSION["browser"] and json.loads(login.content) == {"emailOrLdapLoginId": "test@example.com", "password": "test-only-password"}
    assert "n8n-auth" not in "".join(r.headers.get_list("set-cookie"))                      # never handed to the browser
    cl.get("/n8n/rest/workflows/w1", headers={**OWNER})
    assert state["logins"] == 1                                                              # kept in memory, one sign-in
    r = cl.get("/n8n/rest/workflows/w1", headers={"tailscale-user-login": "journeys@stack.local", "cookie": "n8n-auth=theirs"})
    assert seen[-1].headers["cookie"] == "n8n-auth=theirs" and "browser-id" not in seen[-1].headers   # the stack's checks: no session
    assert cl.get("/n8n/rest/workflows/w1").status_code == 403                               # the gate first


def test_an_expired_session_signs_in_again_once(n8n):
    """APP-85: a 401 from n8n with the app's session signs in again and sends the request once more."""
    S, cl, seen, state = n8n
    cl.get("/n8n/rest/workflows/w1", headers=OWNER)
    state["expire"] = True
    r = cl.patch("/n8n/rest/workflows/w1", headers=OWNER, content=b'{"name": "x"}')
    assert r.status_code == 200 and state["logins"] == 2 and seen[-1].headers["cookie"].endswith(f"n8n-auth={COOKIE}2") and seen[-1].content == b'{"name": "x"}'


def test_without_the_login_stored_n8n_says_how_to_store_it(n8n, monkeypatch):
    """APP-85: no login stored: n8n's pages say in one line to run make n8n-login; a refused login is not tried again at once."""
    S, cl, seen, state = n8n
    monkeypatch.setattr(S, "N8N_LOGIN", {"email": "", "password": ""})
    r = cl.get("/n8n/workflow/w1", headers={**OWNER, "accept": "text/html"})
    assert "make n8n-login" in r.text and not [x for x in seen if x.url.path == "/rest/login"]
    monkeypatch.setattr(S, "N8N_LOGIN", {"email": "test@example.com", "password": "wrong"})
    state["login_ok"] = False
    cl.get("/n8n/workflow/w1", headers={**OWNER, "accept": "text/html"})
    cl.get("/n8n/workflow/w1", headers={**OWNER, "accept": "text/html"})
    assert state["logins"] == 1                                                              # a minute before the next try (N8N_RELOGIN_S)
    d = cl.get("/api/factory/workflow/w1/canvas", headers=OWNER).json()
    assert d["fallback"] is True and d.get("login") is True


@pytest.mark.parametrize("method,path,refused", [("POST", "/rest/workflows/w1/activate", True), ("POST", "/rest/workflows/w1/deactivate", True),
                                                 ("POST", "/rest/workflows/w1/run", True), ("POST", "/rest/workflows/w1/archive", True),
                                                 ("DELETE", "/rest/workflows/w1", True), ("POST", "/rest/executions/42/retry", True),
                                                 ("PUT", "/rest/workflows/w1/share", True), ("POST", "/rest/logout", True),
                                                 ("POST", "/rest/executions/delete", True), ("DELETE", "/rest/executions/7", True),
                                                 ("PATCH", "/rest/workflows/w1", False), ("GET", "/rest/workflows/w1", False), ("POST", "/rest/workflows", False)])
def test_edit_saves_a_draft_and_never_publishes_or_runs(n8n, method, path, refused):
    """APP-86: from the app's frame a save is a draft (n8n 2.44.7 keeps the published version); publishing, running,
    archiving, deleting, sharing and retrying are refused with the way a change goes live."""
    S, cl, seen, state = n8n
    r = cl.request(method, f"/n8n{path}", headers=OWNER, content=b"{}" if method != "GET" else None)
    assert (r.status_code == 403) is refused
    if refused:
        assert "go through the factory" in r.json()["message"] and not [x for x in seen if x.url.path == path]


def test_the_canvas_gets_what_runs_with_its_triggers_named_by_what_they_are(n8n):
    """APP-86: read mode draws the published version (not the draft), a schedule trigger named "On its schedule · <when>"
    (never its cron), the connections renamed with it, and says when a saved draft differs."""
    S, cl, seen, state = n8n
    d = cl.get("/api/factory/workflow/w1/canvas", headers=OWNER).json()
    names = [n["name"] for n in d["workflow"]["nodes"]]
    assert names == ["On its schedule", "Run now", "Research and write"] and d["published"] and d["draft_differs"]
    assert set(d["workflow"]["connections"]) == {"On its schedule", "Run now"}
    assert S.canvas_of(WF, "Mondays 08:00")["workflow"]["nodes"][0]["name"] == "On its schedule · Mondays 08:00"
    assert cl.get("/api/factory/workflow/w1/canvas", headers={"tailscale-user-login": "journeys@stack.local"}).status_code == 403
    assert cl.get("/api/factory/workflow/../canvas", headers=OWNER).status_code in (403, 404)


def test_the_workflow_page_shows_n8ns_canvas_edit_and_a_runs_execution():
    """APP-86: n8n's read-only demo canvas fed by postMessage once it says n8nReady; on a phone wider than the screen,
    panned; Edit: the draft in n8n's editor with Publish and Execute hidden and the factory's line; a run: n8n's
    execution view; the app's own drawing only as the fallback; the live layer's hook (CANVAS_LAYERS)."""
    js = webjs.app_js()
    c = re.search(r"^async function canvasInto\(.*?^\}$", js, re.M | re.S)[0]
    assert 'src="/n8n/workflows/demo"' in c and '"n8nReady"' in c and 'command: "openWorkflow"' in c and "canvasFallback(" in c
    assert "N8N_PHONE_W" in c and "wfDesk() ? 0" in c
    e = re.search(r"^function editInto\(.*?^\}$", js, re.M | re.S)[0]
    assert 'src="/n8n/workflow/${encodeURIComponent(w.id)}"' in e and "n8nHide(" in e and "through the factory" in e and "APP_PROMOTE" in e
    hide = re.search(r"^const N8N_HIDE = `.*?`;$", js, re.M | re.S)[0]
    assert "workflow-open-publish-modal-button" in hide and "execute-workflow-button" in hide and "execute-node-button" in hide
    assert "execution-preview-delete-button" in hide and "/^Production Checklist/" in js
    x = re.search(r"^async function executionInto\(.*?^\}$", js, re.M | re.S)[0]
    assert "/executions/${encodeURIComponent(r.execution)}" in x and "fallback()" in x
    assert "const CANVAS_LAYERS = [canvasAgentLinks];" in js and "for (const fn of CANVAS_LAYERS)" in js
    assert 'canvasInto($("#wfdiagram"), w)' in js and "executionInto($(\"#wfdiagram\"), w, r, ours)" in js


def test_the_ai_stack_node_leads_to_its_agents_page():
    """APP-87: the node's subtitle names its agent (n8n draws it; the app's canvas makes it a link to the agent's page),
    and its settings link to the agents in the app (target _top)."""
    node = (ROOT / "n8n/custom/AistackStep.node.js").read_text()
    assert 'agent: "Agent: " + $parameter["agent"]' in node
    assert "name: 'agentPage', type: 'notice'" in node and 'href="/#/agents" target="_top"' in node
    js = webjs.app_js()
    links = re.search(r"^function canvasAgentLinks\(doc\) \{.*?^\}$", js, re.M | re.S)[0]
    assert "/^Agent: ([\\w-]+)/" in links and "location.hash = agentHref(m[1])" in links


def test_make_n8n_login_stores_the_login_by_name_and_never_shows_it():
    """APP-85: two prompts with no echo, a check against n8n, then sops by name; a refused login stores nothing."""
    import n8n_login as NL
    said, stored = [], []
    run = lambda cmd, **kw: (stored.append((cmd[-1], kw["input"])), type("P", (), {"returncode": 0, "stderr": ""})())[1]   # noqa: E731
    asks = iter(["test@example.com", "s3cret-test"])
    assert NL.main(ask=lambda _: next(asks), check=lambda e, p: (True, ""), run=run, say=said.append) == 0
    assert stored == [('["N8N_LOGIN_EMAIL"]', '"test@example.com"'), ('["N8N_LOGIN_PASSWORD"]', '"s3cret-test"')]
    assert "s3cret-test" not in " ".join(said)
    stored.clear()
    asks = iter(["test@example.com", "wrong"])
    assert NL.main(ask=lambda _: next(asks), check=lambda e, p: (False, "n8n did not accept this email and password"), run=run, say=said.append) == 1
    assert stored == [] and "Nothing was stored" in said[-1]
    import getpass
    assert NL.main.__defaults__[0] is getpass.getpass                                       # no echo
    make = (ROOT / "Makefile").read_text()
    assert "n8n-login:" in make and "python3 ops/n8n_login.py" in make
    compose = (ROOT / "compose/apps.yaml").read_text()
    assert "N8N_LOGIN_EMAIL: ${N8N_LOGIN_EMAIL:-}" in compose and "N8N_LOGIN_PASSWORD: ${N8N_LOGIN_PASSWORD:-}" in compose

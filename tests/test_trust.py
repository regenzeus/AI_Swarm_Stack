"""The trust boundary around the app and n8n (SEC-24..SEC-28; review 10 Nov O1-O4): the app believes the owner only
through its published port, its MCP servers answer only LiteLLM with their tokens, the step service only n8n's node with
its token, every n8n webhook asks for the runner's header, and n8n sits off the flat backend, hardened."""
import json
import socket
import subprocess
import urllib.error
from pathlib import Path

import pytest
import yaml
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import n8n_gen as G
import n8n_sync as NS
import runreg as RR
import trust_keys as TK

ROOT = Path(__file__).resolve().parent.parent
H = {"Tailscale-User-Login": "owner@test"}
GATE, N8N, BACKEND, LITELLM = "172.27.0.1", "172.30.128.3", "172.18.0.5", "172.26.0.4"   # measured on the home PC, 11 Nov 2026
# /proc/net/route inside the app, as read on the home PC on 11 Nov 2026 (default route via mcui's gateway 172.27.0.1)
ROUTES = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
eth4\t00000000\t01001BAC\t0003\t0\t0\t0\t00000000\t0\t0\t0
eth0\t000016AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0
eth1\t0080A8C0\t00000000\t0001\t0\t0\t0\t00F0FFFF\t0\t0\t0
"""


@pytest.fixture
def S(tmp_path, monkeypatch):
    import server as S
    m = tmp_path / "missions"
    for d in ("inbox", "public/results", "flows"):
        (m / d).mkdir(parents=True)
    (m / "public/state.json").write_text(json.dumps({"missions": [], "activity": [], "calls": [], "system": {}, "running": None, "queue": []}))
    for k, v in {"STATE": m / "public/state.json", "INBOX": m / "inbox", "RESULTS": m / "public/results", "FLOWS": m / "flows"}.items():
        monkeypatch.setattr(S, k, v)
    route = tmp_path / "route"
    route.write_text(ROUTES)
    monkeypatch.setattr(S, "ROUTE", route)
    monkeypatch.setitem(S._gate, "addr", None)
    monkeypatch.setattr(S, "TRUST_ON", True)
    return S


def client(S, app, peer, **kw):
    return TestClient(app, client=(peer, 50123), **kw)


def test_the_gate_path_is_accepted_and_a_container_on_stepnet_or_backend_is_refused(S, monkeypatch):
    assert S.default_gateway(S.ROUTE) == GATE                       # the published port's address, from the app's own routes
    assert client(S, S.app, GATE).get("/api/state", headers=H).json()["viewer"] == "owner@test"
    for peer in (N8N, BACKEND, LITELLM, "127.0.0.1"):                # n8n, the builder's flat network, the gateway, the app itself
        r = client(S, S.app, peer).get("/api/state", headers=H)
        assert r.status_code == 403 and "published port" in r.json()["error"], peer
        assert client(S, S.app, peer).get("/").status_code == 403    # nothing on the app's port answers them
    assert client(S, S.app, N8N).post("/api/request", headers=H, json={"action": "run", "slug": "u"}).status_code == 403
    assert not list(S.INBOX.glob("*.json"))
    monkeypatch.setattr(S, "APP_GATE", "local")                      # without the tailnet: the service's name is no owner either
    assert client(S, S.app, N8N, base_url="http://mission-control:8090").get("/api/state").status_code == 403
    assert client(S, S.app, GATE, base_url="http://127.0.0.1:8090").get("/api/state").json()["viewer"] == S.LOCAL_LOGIN


def test_log_mode_refuses_nothing_and_says_what_it_would_refuse(S, monkeypatch, capsys):
    monkeypatch.setattr(S, "TRUST_ON", False)
    assert client(S, S.app, N8N).get("/api/state", headers=H).status_code == 200
    said = capsys.readouterr().out
    assert f"trust (log mode): would refuse a request to the app's port from outside its published port from {N8N} for /api/state" in said
    assert f"the published port's address is {GATE}" in said
    assert client(S, S.app, GATE).get("/api/state", headers=H).status_code == 200
    assert "would refuse" not in capsys.readouterr().out             # the gate path is never logged


def test_the_switch_is_one_deployment_setting_and_a_typo_only_logs(S):
    assert S.trust_on("on") and S.trust_on(" ON ") and not any(S.trust_on(v) for v in ("log", "", None, "onn", "true"))
    env = yaml.safe_load((ROOT / "compose/apps.yaml").read_text())["services"]["mission-control"]["environment"]
    assert env["APP_TRUST"] == "${APP_TRUST:-log}"                   # one line in deployments/<name>/deployment.env
    for d in ("home", "example-work"):
        assert "APP_TRUST" not in (ROOT / f"deployments/{d}/deployment.env").read_text()   # log until the lead's switch
    import journeys as J                                             # the stack's own browser check takes the gate path too
    assert (J.APP, J.NET) == ("http://127.0.0.1:8090", "host")
    assert S.default_gateway(S.ROUTE.with_name("none")) == ""        # no route table: no gate, so on mode refuses


def mcp_app():
    return Starlette(routes=[Route("/mcp", lambda r: PlainTextResponse("tools"), methods=["GET", "POST"])])


def test_an_mcp_server_answers_only_litellm_with_its_token(S, monkeypatch):
    monkeypatch.setenv("MCP_TOKEN_HOUSE", "house-token")
    monkeypatch.setattr(socket, "gethostbyname_ex", lambda name: (name, [], [LITELLM] if name == "litellm" else []))
    monkeypatch.setattr(socket, "gethostbyaddr", lambda ip: {"172.30.48.3": ("aistack-litellm-1.aistack_swarmmcp", [], [ip]),
                                                             N8N: ("aistack-n8n-1.aistack_stepnet", [], [ip])}[ip])
    app = S.mcp_guard(mcp_app(), "house")
    ok = {"Authorization": "Bearer house-token"}
    assert client(S, app, LITELLM).post("/mcp", headers=ok).text == "tools"
    assert client(S, app, "172.30.48.3").post("/mcp", headers=ok).text == "tools"    # LiteLLM on the other shared network
    assert client(S, app, LITELLM).post("/mcp", headers={"Authorization": "Bearer memory-token"}).status_code == 401
    assert client(S, app, LITELLM).post("/mcp").status_code == 401
    assert client(S, app, N8N).post("/mcp", headers=ok).status_code == 401            # the token alone is not enough
    monkeypatch.delenv("MCP_TOKEN_HOUSE")
    assert client(S, app, LITELLM).post("/mcp", headers={"Authorization": "Bearer "}).status_code == 401   # no token set: none passes
    # every one of the app's MCP servers in the gateway's config sends its own token, which compose gives both sides
    core, apps = (yaml.safe_load((ROOT / f"compose/{f}.yaml").read_text())["services"] for f in ("core", "apps"))
    for f in ("config/litellm/config.yaml", "deployments/example-work/litellm.yaml"):
        servers = yaml.safe_load((ROOT / f).read_text())["mcp_servers"]
        for name, srv in servers.items():
            if "mission-control:" in srv["url"]:
                assert (srv["auth_type"], srv["authentication_token"]) == ("bearer_token", f"os.environ/{S.MCP_TOKENS[name]}"), (f, name)
    for env in S.MCP_TOKENS.values():
        assert core["litellm"]["environment"][env] == apps["mission-control"]["environment"][env] == f"${{{env}:-}}"
    server = (ROOT / "images/mission-control/server.py").read_text()
    assert server.count("uvicorn.Config(mcp_guard(") == len(S.MCP_TOKENS) == 7


def test_the_step_service_refuses_a_step_without_its_token(S, monkeypatch):
    monkeypatch.setattr(S, "STEP_TOKEN", "step-token")
    c = client(S, S.flows_app, N8N, base_url="http://mission-control:8099")
    assert c.post("/steps", json={"kind": "notify", "message": "hi"}).status_code == 401
    assert c.post("/steps", json={"kind": "notify"}, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/catalog").status_code == 401
    assert not list(S.FLOWS.glob("pending/*.json"))                  # nothing reached the runner
    r = c.post("/steps", json={"kind": "notify", "message": "hi"}, headers={"Authorization": "Bearer step-token"})
    assert r.json()["status"] == "pending" and len(list((S.FLOWS / "pending").glob("*.json"))) == 1
    monkeypatch.setattr(S, "STEP_TOKEN", "")                         # no token set: nothing passes in on mode
    assert c.post("/steps", json={}, headers={"Authorization": "Bearer "}).status_code == 401
    # n8n's AI Stack step sends it from its own environment (tried on a throwaway n8n 2.44.7, 11 Nov 2026), on both calls
    node = (ROOT / "n8n/custom/AistackStep.node.js").read_text()
    assert "process.env.AISTACK_STEP_TOKEN" in node and node.count("headers: stepAuth()") == 2
    core, apps = (yaml.safe_load((ROOT / f"compose/{f}.yaml").read_text())["services"] for f in ("core", "apps"))
    assert core["n8n"]["environment"]["AISTACK_STEP_TOKEN"] == apps["mission-control"]["environment"]["AISTACK_STEP_TOKEN"] == "${AISTACK_STEP_TOKEN:-}"


def hooked(wf):
    return [n for n in wf["nodes"] if n["type"] == G.WEBHOOK]


def has_auth(n):
    return n["parameters"].get("authentication") == "headerAuth" and n.get("credentials") == {"httpHeaderAuth": G.HOOK_CRED}


def test_every_webhook_asks_for_the_runners_header(tmp_path):
    files = sorted((ROOT / "n8n/workflows").glob("*.json"))
    hooks = [n for f in files for n in hooked(json.loads(f.read_text()))]
    assert len(hooks) >= 33 and all(has_auth(n) for n in hooks)       # every Run now, the inbox, the self-test
    made = G.workflow("crew", "x", "Crew: X", "0 3 * * *", {"kind": "crew", "job": "x"}, "", area="upkeep")
    assert [has_auth(n) for n in hooked(made)] == [True]              # a new job's Run now
    toy = sorted((ROOT / "tests/fixtures/packs/toy/workflows").glob("*.json"))
    assert toy and all(has_auth(n) for f in toy for n in hooked(NS.prepared(f)))   # a pack's webhooks, whatever its file says
    raw = tmp_path / "in.json"
    raw.write_text(json.dumps({"id": "aisCanvas0000001", "name": "Made on the canvas", "connections": {}, "nodes": [
        {"name": "Hook", "type": G.WEBHOOK, "parameters": {"path": "x", "authentication": "none"}}]}))
    NS.write_stable([raw], tmp_path / "out")
    assert has_auth(hooked(json.loads((tmp_path / "out/made-on-the-canvas.json").read_text()))[0])   # an export gets it


def test_the_webhooks_credential_is_written_from_the_secret_and_an_import_without_it_stops(tmp_path, monkeypatch):
    calls = []

    def run(cmd, **k):
        calls.append((cmd, k.get("input")))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    assert NS.hook_credential(run=run, token="hook-secret") == ""
    cmd, given = calls[0]
    assert "hook-secret" not in " ".join(cmd) and "import:credentials" in cmd[-1] and "rm -f /tmp/hook.json" in cmd[-1]
    assert json.loads(given) == [{**G.HOOK_CRED, "type": "httpHeaderAuth", "data": {"name": G.HOOK_HEADER, "value": "hook-secret"}}]
    monkeypatch.delenv("N8N_HOOK_TOKEN", raising=False)
    calls.clear()
    assert NS.import_all(repo=tmp_path, run=run, made=tmp_path, names=["*"]) == 1 and calls == []   # nothing touched without it


def test_the_runner_starts_an_item_workflow_with_its_header_and_says_why_not_without_it(monkeypatch):
    sent = []

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"execution": "41"}'

    def post(req, timeout=30):
        sent.append(req)
        if req.get_header("X-aistack-hook") != "hook-secret":
            raise urllib.error.HTTPError(req.full_url, 403, "Authorization data is wrong!", {}, None)
        return Resp()
    monkeypatch.setenv("N8N_HOOK_TOKEN", "hook-secret")
    assert RR.start("toy/ticket", {"key": "T-1"}, post=post) == ("", "41")
    assert sent[0].full_url == "http://127.0.0.1:5678/webhook/item/toy/ticket"
    monkeypatch.delenv("N8N_HOOK_TOKEN")
    why, ex = RR.start("toy/ticket", {"key": "T-1"}, post=post)
    assert "N8N_HOOK_TOKEN" in why and ex == "" and len(sent) == 1   # said, and n8n not even asked


def test_n8n_is_off_the_flat_backend_hardened_and_its_tailnet_port_serves_resume_links_only():
    core = yaml.safe_load((ROOT / "compose/core.yaml").read_text())
    apps = yaml.safe_load((ROOT / "compose/apps.yaml").read_text())
    svc = {**core["services"], **apps["services"]}
    n8n = svc["n8n"]
    assert n8n["networks"] == ["n8ndb", "flows", "stepnet"] and core["networks"]["n8ndb"] == {"internal": True}
    assert [s for s, v in svc.items() if "n8ndb" in (v.get("networks") or [])] == ["postgres", "n8n-db", "n8n"]
    assert "backend" in svc["builder"]["networks"] and "n8ndb" not in svc["builder"]["networks"]
    assert n8n["read_only"] is True and n8n["cap_drop"] == ["ALL"] and n8n["security_opt"] == ["no-new-privileges:true"]
    assert "/tmp" in n8n["tmpfs"] and {"type": "tmpfs", "target": "/home/node/.cache", "tmpfs": {"mode": 0o1777}} in n8n["volumes"]
    assert n8n["environment"]["N8N_PUBLIC_API_DISABLED"] == n8n["environment"]["N8N_PUBLIC_API_SWAGGERUI_DISABLED"] == "true"
    ps1 = (ROOT / "ops/windows/host-setup.ps1").read_text()
    lines = [x for x in ps1.splitlines() if "--https=8450" in x and not x.lstrip().startswith("#")]
    assert lines == ['& "C:\\Program Files\\Tailscale\\tailscale.exe" serve --https=8450 off',
                     '& "C:\\Program Files\\Tailscale\\tailscale.exe" serve --bg --https=8450 --set-path=/webhook-waiting http://127.0.0.1:5678/webhook-waiting']


def test_the_trust_keys_are_made_once_and_never_on_a_command_line():
    calls = []

    def run(cmd, **k):
        calls.append((cmd, k["input"]))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    have = {n: "x" for n in TK.NAMES if n != "N8N_HOOK_TOKEN"}
    assert TK.main(env=have, run=run) == 0
    assert [c[0][-1] for c in calls] == ['["N8N_HOOK_TOKEN"]']        # the one missing; the others kept
    value = json.loads(calls[0][1])
    assert len(value) >= 40 and value not in " ".join(calls[0][0])
    calls.clear()
    assert TK.main(env={n: "x" for n in TK.NAMES}, run=run) == 0 and calls == []

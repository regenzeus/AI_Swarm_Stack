"""A customer-class deployment with n8n (WFL-15 to WFL-18, docs/N8N-MIGRATION.md §10): without the tailnet n8n and the
app stay on 127.0.0.1 and the app's gate takes this PC as the owner; n8n loads only its logic nodes and the AI Stack
step; n8n's executions stay on the PC, and the backup stays off. The example is deployments/example-work."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
import yaml
from starlette.testclient import TestClient

import dataguard as DG
import deployment as DEPLOY

ROOT = Path(__file__).resolve().parents[1]
HOME, WORK = ROOT / "deployments/home", ROOT / "deployments/example-work"


def values(folder):
    return DEPLOY.load(folder / "deployment.env", env={})


def test_without_the_tailnet_n8n_and_the_app_stay_on_127_0_0_1():
    work, home = values(WORK), values(HOME)
    assert "tailnet" not in DEPLOY.features(work) and DG.customer(DG.load(WORK))
    assert DEPLOY.gate_problems(work) == [] and DEPLOY.gate_problems(home) == []
    assert work["APP_GATE"] == "local" and work["N8N_EDITOR_URL"] == "http://127.0.0.1:8090/n8n/" and work["N8N_WEBHOOK_URL"] == "http://127.0.0.1:5678/"
    said = "\n".join(DEPLOY.gate_problems({**work, "APP_GATE": "tailnet", "N8N_WEBHOOK_URL": "https://pc.example.ts.net:8450/"}))
    assert "APP_GATE is not local, and the tailnet is off" in said and "N8N_WEBHOOK_URL is not on 127.0.0.1" in said
    assert "N8N_EDITOR_URL is not on 127.0.0.1" in "\n".join(DEPLOY.gate_problems({k: v for k, v in work.items() if k != "N8N_EDITOR_URL"}))
    assert "the tailnet is on" in "\n".join(DEPLOY.gate_problems({**home, "APP_GATE": "local"}))     # home keeps Tailscale's login
    core = yaml.safe_load((ROOT / "compose/core.yaml").read_text())
    apps = yaml.safe_load((ROOT / "compose/apps.yaml").read_text())
    env = core["services"]["n8n"]["environment"]
    assert env["N8N_EDITOR_BASE_URL"] == "${N8N_EDITOR_URL:-https://${PC_TAILNET_HOST:-localhost}:8447/n8n/}"
    assert env["WEBHOOK_URL"] == "${N8N_WEBHOOK_URL:-https://${PC_TAILNET_HOST:-localhost}:8450/}"
    assert apps["services"]["mission-control"]["environment"]["APP_GATE"] == "${APP_GATE:-tailnet}"


@pytest.fixture
def app(tmp_path, monkeypatch):
    """The app with a fake n8n behind it, as test_n8n_inapp.py has it."""
    import server as S
    (tmp_path / "state.json").write_text(json.dumps({"missions": [], "activity": [], "calls": [], "system": {}, "running": None, "queue": []}))
    monkeypatch.setattr(S, "STATE", tmp_path / "state.json")
    seen = []

    def handle(req):
        seen.append(req)

        async def body():
            yield b'{"data": {}}'
        return httpx.Response(200, headers={"content-type": "application/json"}, content=body())
    monkeypatch.setattr(S, "_frame_transport", httpx.MockTransport(handle))
    return S, seen


def test_without_the_tailnet_the_apps_gate_takes_this_pc_as_the_owner_and_still_refuses_a_write_from_another_site(app, monkeypatch):
    S, seen = app
    monkeypatch.setattr(S, "APP_GATE", "local")
    pc = TestClient(S.app, base_url="http://127.0.0.1:8090")
    r = pc.get("/api/state", headers={"tailscale-user-login": "someone@else"})     # no tailnet: a header names nobody
    assert r.status_code == 200 and r.json()["viewer"] == S.LOCAL_LOGIN
    assert pc.get("/n8n/rest/settings").status_code == 200
    sent = seen[-1]
    assert sent.url.path == "/rest/settings" and sent.headers["x-forwarded-proto"] == "http" and sent.headers["x-forwarded-host"] == "127.0.0.1:8090"
    assert "tailscale-user-login" not in sent.headers
    assert TestClient(S.app, base_url="http://localhost:8090").get("/api/state").status_code == 200
    n = len(seen)
    assert pc.post("/n8n/rest/login", headers={"sec-fetch-site": "cross-site"}, content=b"{}").status_code == 403 and len(seen) == n   # SEC-20
    assert pc.post("/api/request", headers={"sec-fetch-site": "same-site"}, json={"action": "run", "slug": "u"}).status_code == 403
    other = TestClient(S.app, base_url="http://pc.example.org:8090")                 # a name that points here: another site's page
    assert other.get("/api/state").status_code == 403 and other.get("/n8n/").status_code == 403 and len(seen) == n
    monkeypatch.setattr(S, "APP_GATE", "tailnet")                                   # with the tailnet, as before
    assert pc.get("/api/state").status_code == 403 and pc.get("/n8n/").status_code == 403 and len(seen) == n
    tail = TestClient(S.app, base_url="https://pc.example.ts.net:8447")
    assert tail.get("/api/state", headers={"tailscale-user-login": "owner@example.com"}).json()["viewer"] == "owner@example.com"
    assert tail.get("/n8n/", headers={"tailscale-user-login": "owner@example.com"}).status_code == 200
    assert seen[-1].headers["x-forwarded-proto"] == "https"


def test_a_customer_deployments_n8n_loads_only_the_logic_nodes_and_the_aistack_step():
    work = values(WORK)
    assert DG.n8n_nodes(work) == DG.N8N_NODES and DG.n8n_nodes(values(HOME)) is None       # home: every node but the excluded
    assert "CUSTOM.aistackStep" in DG.N8N_NODES and "n8n-nodes-base.splitInBatches" in DG.N8N_NODES
    assert not {"n8n-nodes-base.httpRequest", "n8n-nodes-base.code", "n8n-nodes-base.jira", "n8n-nodes-base.emailSend"} & set(DG.N8N_NODES)
    nodes = json.dumps([*DG.N8N_NODES, "n8n-nodes-base.httpRequest"])
    said = "\n".join(DG.problems(DG.load(WORK), DEPLOY.features(work), WORK, values={**work, "N8N_NODES_INCLUDE": nodes}))
    assert "n8n loads n8n-nodes-base.httpRequest, which is not one of its logic nodes" in said
    said = "\n".join(DG.problems(DG.load(WORK), DEPLOY.features(work), WORK, values={**work, "N8N_NODES_INCLUDE": ""}))
    assert "customer data, and n8n loads every node" in said
    with pytest.raises(SystemExit, match="no JSON list"):
        DG.n8n_nodes({"N8N_NODES_INCLUDE": "httpRequest"})
    core = yaml.safe_load((ROOT / "compose/core.yaml").read_text())
    assert core["services"]["n8n"]["environment"]["NODES_INCLUDE"] == "${N8N_NODES_INCLUDE:-}"   # n8n reads it; empty loads all


def test_n8ns_database_and_volume_stay_on_the_pc_and_the_backup_stays_off_for_customer_data(tmp_path):
    assert DG.stays_local() == []
    assert set(DG.N8N_DATA["leaves_by"]) <= set(DG.OUTBOUND)                       # the only ways out are features customer data has off
    core = yaml.safe_load((ROOT / "compose/core.yaml").read_text())
    assert "postgres" in core["services"]["n8n"]["environment"]["DB_POSTGRESDB_HOST"] and "pgdata:/var/lib/postgresql/data" in core["services"]["postgres"]["volumes"]
    assert any(v.startswith("n8n:") for v in core["services"]["n8n"]["volumes"])
    said = "\n".join(DG.problems({"class": "customer"}, {"core", "home", "offsite"}, WORK))
    assert "the feature home is on: the backup" in said and "the feature offsite is on: the backup goes to OneDrive" in said
    bad = tmp_path / "repo"
    (bad / "compose").mkdir(parents=True)
    for f in DG.COMPOSE:
        shutil.copyfile(ROOT / f, bad / f)
    c = yaml.safe_load((bad / "compose/core.yaml").read_text())
    c["volumes"]["n8n"] = {"driver": "local", "driver_opts": {"type": "nfs", "device": ":/volume1/n8n"}}
    c["services"]["n8n"]["ports"] = ["5678:5678"]
    c["services"]["n8n"]["environment"]["N8N_DIAGNOSTICS_ENABLED"] = "true"
    (bad / "compose/core.yaml").write_text(yaml.safe_dump(c))
    said = "\n".join(DG.stays_local(bad))
    assert "the volume n8n holds n8n's executions and is not a local volume" in said and "n8n publishes 5678:5678" in said and "N8N_DIAGNOSTICS_ENABLED" in said
    backup = (ROOT / "ops/backup.sh").read_text().splitlines()
    gate = next(i for i, ln in enumerate(backup) if "deployment.py\")\" need home || exit 0" in ln or "deployment.py\" need home || exit 0" in ln)
    first = next(i for i, ln in enumerate(backup) if ln.startswith(("docker ", "ssh ", "tar ", "live_tar ")) or "pg_dumpall" in ln)
    assert gate < first and any("pg_dumpall" in ln for ln in backup)               # the dump holds n8n's database, behind the gate
    bin_ = tmp_path / "bin"                                                         # no docker, ssh or age: a call would fail
    bin_.mkdir()
    for tool in ("python3", "bash", "grep", "cut", "dirname", "env"):
        if shutil.which(tool):
            os.symlink(shutil.which(tool), bin_ / tool)
    p = subprocess.run(["bash", "ops/backup.sh"], cwd=ROOT, capture_output=True, text=True, timeout=60,
                       env={"PATH": str(bin_), "HOME": str(tmp_path), "AISTACK_DEPLOYMENT": "example-work"})
    assert p.returncode == 0 and "refused: the deployment example-work refuses home (REFUSE in its deployment.env)" in p.stdout, p.stdout + p.stderr   # PLT-47

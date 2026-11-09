"""A deployment's deployment.env (deployments/<name>/), the one place for this deployment's hosts, paths and accounts (PLT-33): how each reader gets the
values, that the environment wins, and that no value comes back as a literal in running code. The values are read from
the file, so this test names none of them and goes on working on the public snapshot, whose file holds placeholders."""
import webjs
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml
from starlette.testclient import TestClient

import deployment as DEPLOY

ROOT = Path(__file__).resolve().parents[1]
RUNNING = ("ops", "images", "compose", "config", "deployments", "smoke", "Makefile")
NOT_CODE = {".md", ".png", ".jpg", ".ico", ".woff2"}          # the guide and the AGENTS.md files describe; pictures are not text
SKIP_DIRS = {"__pycache__", "node_modules", "vendor"}
# The values that must not come back. Names and accounts that are also ordinary words stay out: the snapshot writes those as "owner".
GUARDED = ("DEPLOY_HOME", "DOCKER_SOCKET", "GIT_EMAIL", "NAS_HOST", "PC_LAN_HOST", "PC_TAILNET_HOST", "PHONE_HOST", "FORGEJO_OWNER")
HOME_PATHS = re.compile(r'Path\.home\(\)\s*/\s*"(code|ai-stack|hermes-skills)\b')
ALLOWED = {
    "deployments/": "the one place the values are set, one folder per deployment",
    "ops/publish.py": "the public GitHub repository's own account, not this deployment's Forgejo",
    "ops/windows/": "runs on Windows, copied there by hand, where nothing reads the file",
}
PUBLIC_REPO = "AI_Swarm_Stack"                                # a line naming the public repository (an example in the app) is no Forgejo owner


def hard_coded(root, values):
    """-> ["path:line: NAME"] for every value written out in running code under root."""
    patterns = {k: re.compile(r"(?<![\w.])" + re.escape(v) + r"(?![\w])") for k, v in values.items()}
    hits = []
    for top in RUNNING:
        base = root / top
        for f in ([base] if base.is_file() else sorted(base.rglob("*"))):
            rel = f.relative_to(root).as_posix()
            if not f.is_file() or f.suffix in NOT_CODE or SKIP_DIRS & set(f.parts) or rel.startswith(tuple(ALLOWED)):
                continue
            for n, line in enumerate(f.read_bytes().decode("utf-8", "replace").splitlines(), 1):
                hits += [f"{rel}:{n}: {k}" for k, p in patterns.items() if p.search(line) and PUBLIC_REPO not in line]
                if HOME_PATHS.search(line):
                    hits.append(f"{rel}:{n}: a folder under Path.home()")
    return hits


def test_no_converted_value_is_hard_coded_in_running_code():
    values = DEPLOY.load(env={})
    assert not hard_coded(ROOT, {k: values[k] for k in GUARDED})


def test_the_guard_finds_a_value_written_out_and_respects_its_allowlist(tmp_path):
    lan = "192" + ".168.7.7"
    (tmp_path / "ops" / "windows").mkdir(parents=True)
    (tmp_path / "ops" / "bad.py").write_text(f'URL = "http://{lan}:3000"\nHOME = "/srv/x"\nCODE = Path.home() / "code"\nOK = "{lan}0"\n')
    (tmp_path / "ops" / "windows" / "fine.ps1").write_text(f"$nas = '{lan}'\n")
    (tmp_path / "ops" / "publish.py").write_text(f"# {lan}\n")
    (tmp_path / "ops" / "AGENTS.md").write_text(f"{lan}\n")
    for top in ("images", "compose", "config", "smoke"):
        (tmp_path / top).mkdir()
    (tmp_path / "Makefile").write_text(f"x:\n\tcurl {lan}\n")
    assert sorted(hard_coded(tmp_path, {"NAS_HOST": lan})) == ["Makefile:2: NAS_HOST", "ops/bad.py:1: NAS_HOST", "ops/bad.py:3: a folder under Path.home()"]


def test_a_line_may_name_a_line_above_and_the_environment_wins(tmp_path):
    f = tmp_path / "d.env"
    f.write_text("# a comment with = in it\n\nHOST=one\nURL=http://${HOST}:1\nOWNER=me\n")
    assert DEPLOY.load(f, env={}) == {"HOST": "one", "URL": "http://one:1", "OWNER": "me"}
    assert DEPLOY.load(f, env={"HOST": "two", "OWNER": "you"}) == {"HOST": "two", "URL": "http://two:1", "OWNER": "you"}
    assert DEPLOY.load(f, env={"URL": "https://x"})["URL"] == "https://x"


def test_shell_and_python_read_the_same_values_and_the_environment_wins_in_the_shell_too():
    values = DEPLOY.load(env={})
    clean = {"PATH": os.environ["PATH"]}
    plain = subprocess.run(["bash", "-c", f"set -a; . {DEPLOY.FILE}; env"], cwd=ROOT, env=clean, capture_output=True, text=True, check=True).stdout
    assert values.items() <= dict(ln.split("=", 1) for ln in plain.splitlines() if "=" in ln).items()
    script = f'eval "$("{sys.executable}" ops/deployment.py shell)"; printf "%s %s" "$NAS_HOST" "$FORGEJO_URL"'
    said = subprocess.run(["bash", "-c", script], cwd=ROOT, env=clean, capture_output=True, text=True, check=True).stdout
    assert said == f"{values['NAS_HOST']} {values['FORGEJO_URL']}"
    moved = subprocess.run(["bash", "-c", script], cwd=ROOT, env={**clean, "NAS_HOST": "elsewhere"}, capture_output=True, text=True, check=True).stdout
    assert moved == f"elsewhere {values['FORGEJO_URL'].replace(values['NAS_HOST'], 'elsewhere')}"
    one = subprocess.run([sys.executable, "ops/deployment.py", "CODE_DIR"], cwd=ROOT, env=clean, capture_output=True, text=True, check=True).stdout
    assert one.strip() == values["CODE_DIR"]


def test_every_compose_call_reads_the_file_and_a_changed_file_is_applied():
    import deploy
    assert "--env-file versions.env --env-file $(DEPLOYMENT_FILE)" in (ROOT / "Makefile").read_text()
    assert '--env-file versions.env --env-file "$env"' in (ROOT / "ops/ci-compose-check.sh").read_text()
    assert f"--env-file versions.env --env-file {DEPLOY.FILE}" in " ".join(deploy.COMPOSE)
    assert "deployments/" in deploy.COMPOSE_INPUTS and deploy.runner_changed(["deployments/home/deployment.env"])
    names = set(re.findall(r"\$\{(\w+):\?run via make\}", (ROOT / "compose/apps.yaml").read_text())) & set(DEPLOY.VALUES)
    assert {"CODE_DIR", "STACK_DIR"} <= names                             # required, so a call without the file stops loudly
    assert "${PHONE_HOST:-}" in (ROOT / "compose/apps.yaml").read_text()   # a home host is optional: its feature checks it


def test_the_page_carries_the_apps_addresses_and_the_tools_name_only_those(monkeypatch):
    import server as S
    compose = yaml.safe_load((ROOT / "compose/apps.yaml").read_text().replace("!reset ", "").replace("!override ", ""))
    assert {*S.DEPLOY, "PHONE_HOST"} <= set(compose["services"]["mission-control"]["environment"]) and set(S.DEPLOY) <= set(DEPLOY.VALUES)
    web = ROOT / "images/mission-control/web"
    tools = (web / "static/tools.json").read_text()
    assert set(re.findall(r"\{\{(\w+)\}\}", tools)) <= set(S.DEPLOY) and "{{" not in DEPLOY.fill(tools)
    assert {t["id"]: t["host"] for t in json.loads(DEPLOY.fill(tools))["tools"]}["forgejo"] == DEPLOY.FORGEJO_URL
    assert r"t.replace(/\{\{(\w+)\}\}/g" in webjs.app_js()      # app.js fills them as DEPLOY.fill does
    monkeypatch.setattr(S, "DEPLOY", {"NAS_HOST": "</script>"})
    assert 'window.DEPLOY = {"NAS_HOST": "\\u003c/script>"};' in TestClient(S.app).get("/").text
    assert "window.DEPLOY = {/*DEPLOY*/};" in (web / "index.html").read_text()       # still a valid script when served as a plain file


def test_units_name_the_home_and_docker_by_specifier():
    units = sorted((ROOT / "ops/systemd").glob("*.service"))
    assert units and not [u.name for u in units if re.search(r"/home/|/run/user/", u.read_text())]
    runner = (ROOT / "ops/systemd/missions.service").read_text()
    assert "WorkingDirectory=%h/ai-stack" in runner and "DOCKER_HOST=unix://%t/docker.sock" in runner

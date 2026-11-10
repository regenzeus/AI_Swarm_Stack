"""The workflow pillar's service (WFL-01 to WFL-04, DEC-51, docs/N8N-MIGRATION.md): n8n in the core, its role and
database made by a one-shot job that is safe to repeat, its secrets from sops, a pinned image, nothing published beyond
127.0.0.1, nothing sent home, no shell command node, and its execution data pruned."""
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CORE = yaml.safe_load((ROOT / "compose/core.yaml").read_text())
S = CORE["services"]
VERSIONS = (ROOT / "versions.env").read_text()


def env(svc):
    return S[svc]["environment"]


def test_n8n_is_part_of_the_core_and_starts_after_its_database():
    assert {"n8n-db", "n8n"} <= set(S)
    assert S["n8n-db"]["depends_on"] == {"postgres": {"condition": "service_healthy"}}
    assert S["n8n"]["depends_on"] == {"n8n-db": {"condition": "service_completed_successfully"}}
    assert S["n8n-db"]["restart"] == "no" and S["n8n"]["restart"] == "unless-stopped"
    assert "profiles" not in S["n8n"] and "profiles" not in S["n8n-db"]
    assert S["n8n"]["healthcheck"]["test"][1].endswith("http://127.0.0.1:5678/healthz || exit 1")
    assert "mem_limit" in S["n8n"]


def test_the_n8n_image_is_pinned_by_digest():
    assert S["n8n"]["image"] == "${N8N_IMAGE}"
    assert re.search(r"^N8N_IMAGE=n8nio/n8n:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}$", VERSIONS, re.M)


def test_n8n_is_reached_only_from_this_machine():
    assert all(p.startswith("127.0.0.1:") for p in S["n8n"]["ports"])
    assert "ports" not in S["n8n-db"]
    assert CORE["networks"]["backend"].get("internal") is True and "backend" in S["n8n"]["networks"]
    assert env("n8n")["N8N_EDITOR_BASE_URL"].startswith("https://") and env("n8n")["N8N_PROXY_HOPS"] == "1"


def test_n8n_uses_its_own_role_database_and_secrets():
    e = env("n8n")
    assert (e["DB_TYPE"], e["DB_POSTGRESDB_HOST"], e["DB_POSTGRESDB_DATABASE"], e["DB_POSTGRESDB_USER"]) == ("postgresdb", "postgres", "n8n", "n8n")
    assert e["DB_POSTGRESDB_PASSWORD"] == "${N8N_DB_PASSWORD:?run via make up}"
    assert e["N8N_ENCRYPTION_KEY"] == "${N8N_ENCRYPTION_KEY:?run via make up}"
    assert env("n8n-db")["N8N_DB_PASSWORD"] == "${N8N_DB_PASSWORD:?run via make up}"
    assert S["n8n-db"]["volumes"] == ["../config/n8n:/setup:ro"] and S["n8n-db"]["entrypoint"] == ["sh", "/setup/db.sh"]


def test_the_database_setup_is_safe_to_repeat():
    sh = (ROOT / "config/n8n/db.sh").read_text()
    assert "set -eu" in sh
    assert "select 1 from pg_roles where rolname = 'n8n'" in sh and "|| psql_admin -c \"create role n8n login\"" in sh
    assert "select 1 from pg_database where datname = 'n8n'" in sh and "create database n8n owner n8n" in sh
    assert "alter role n8n password :'pw'" in sh and "$N8N_DB_PASSWORD" in sh      # the password never on a command line


def test_the_boot_check_counts_the_database_job_as_set_up():
    import stack_ready as SR
    assert "n8n-db" in SR.ONE_SHOT


def test_n8n_sends_nothing_home_and_keeps_its_command_node_off():
    e = env("n8n")
    assert e["N8N_DIAGNOSTICS_ENABLED"] == e["N8N_VERSION_NOTIFICATIONS_ENABLED"] == e["N8N_PERSONALIZATION_ENABLED"] == "false"
    assert {"n8n-nodes-base.executeCommand", "n8n-nodes-base.localFileTrigger"} <= set(json.loads(e["NODES_EXCLUDE"]))
    assert e["N8N_BLOCK_ENV_ACCESS_IN_NODE"] == "true"


def test_n8n_prunes_executions_after_30_days():
    e = env("n8n")
    assert e["EXECUTIONS_DATA_PRUNE"] == "true" and e["EXECUTIONS_DATA_MAX_AGE"] == "720"
    src = (ROOT / "compose/core.yaml").read_text()
    assert re.search(r'EXECUTIONS_DATA_MAX_AGE: "720" +# limit: drops', src)

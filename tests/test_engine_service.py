"""The engine's service (GEN-33, GEN-36, docs/AI-STACK-PLAN.md WP0 and WP1): Temporal in the core, its databases and
schema made by one-shot services that are safe to repeat, pinned images, nothing published beyond 127.0.0.1, and its
databases kept out of a backup that leaves the machine when the deployment holds customer data."""
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CORE = yaml.safe_load((ROOT / "compose/core.yaml").read_text())
S = CORE["services"]
VERSIONS = (ROOT / "versions.env").read_text()


def test_the_engine_is_part_of_the_core_and_starts_only_after_its_databases_and_schema():
    assert {"temporal-db", "temporal-schema", "temporal", "temporal-ui"} <= set(S)
    assert S["temporal-db"]["depends_on"] == {"postgres": {"condition": "service_healthy"}}
    assert S["temporal-schema"]["depends_on"] == {"temporal-db": {"condition": "service_completed_successfully"}}
    assert S["temporal"]["depends_on"] == {"temporal-schema": {"condition": "service_completed_successfully"}}
    assert S["temporal-ui"]["depends_on"] == {"temporal": {"condition": "service_healthy"}}
    assert S["temporal-db"]["restart"] == S["temporal-schema"]["restart"] == "no"     # one-shots: they run and end
    assert "profiles" not in S["temporal"]                                           # core: never switched off


def test_the_engine_images_are_pinned_by_digest_in_versions_env():
    for name in ("TEMPORAL_IMAGE", "TEMPORAL_ADMIN_IMAGE", "TEMPORAL_UI_IMAGE"):
        pin = re.search(rf"^{name}=(\S+)$", VERSIONS, re.M).group(1)
        assert re.fullmatch(r"temporalio/[a-z-]+:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", pin), pin
    assert S["temporal"]["image"] == "${TEMPORAL_IMAGE}" and S["temporal-schema"]["image"] == "${TEMPORAL_ADMIN_IMAGE}"
    assert S["temporal-ui"]["image"] == "${TEMPORAL_UI_IMAGE}"


def test_the_engine_is_reached_only_from_this_machine():
    for svc in ("temporal", "temporal-ui"):
        assert all(p.startswith("127.0.0.1:") for p in S[svc]["ports"]), svc
    assert CORE["networks"]["backend"]["internal"] is True and "backend" in S["temporal"]["networks"]
    assert set(S["temporal-db"]["networks"]) == set(S["temporal-schema"]["networks"]) == {"backend"}


def test_the_engine_uses_its_own_role_and_the_secret_of_that_role():
    env = S["temporal"]["environment"]
    assert env["DB"] == "postgres12" and env["POSTGRES_USER"] == "temporal"
    assert env["POSTGRES_PWD"] == "${TEMPORAL_DB_PASSWORD:?run via make up}"
    assert env["DBNAME"] == "temporal" and env["VISIBILITY_DBNAME"] == "temporal_visibility"
    db = (ROOT / "config/temporal/db.sh").read_text()
    assert "create role temporal login" in db and "owner temporal" in db
    assert "select 1 from pg_roles" in db and "select 1 from pg_database" in db             # safe to repeat
    assert "TEMPORAL_DB_PASSWORD" in db and "PG_PASSWORD" in db and "echo $TEMPORAL" not in db  # never printed


def test_the_schema_is_set_up_then_moved_to_the_pinned_version_every_start():
    sh = (ROOT / "config/temporal/schema.sh").read_text()
    assert "setup-schema -v 0.0" in sh and "update-schema -d" in sh and "postgresql/v12" in sh
    assert "--overwrite" not in sh and " -o " not in sh                                       # never drops what is there


def test_the_server_reads_a_dynamic_config_that_names_the_history_limits():
    env = S["temporal"]["environment"]
    assert env["DYNAMIC_CONFIG_FILE_PATH"] == "/etc/temporal/dynamic/dynamicconfig.yaml"
    dyn = yaml.safe_load((ROOT / "config/temporal/dynamicconfig.yaml").read_text())
    assert dyn["limit.historyCount.error"][0]["value"] == 51200
    assert dyn["limit.historySize.error"][0]["value"] == 50 * 1024 * 1024
    assert "# limit: refuses" in (ROOT / "config/temporal/dynamicconfig.yaml").read_text()


def test_the_data_guard_tells_scripts_whether_the_deployment_holds_customer_data():
    def rc(name):
        env = {**os.environ, "AISTACK_DEPLOYMENT": name}
        return subprocess.run([sys.executable, str(ROOT / "ops/dataguard.py"), "customer"], env=env, timeout=30).returncode
    assert rc("home") == 1 and rc("example-work") == 0


def test_a_customer_class_backup_leaves_the_engine_databases_out():
    sh = (ROOT / "ops/backup.sh").read_text()
    assert "dataguard.py\" customer; then PG_SKIP=(--exclude-database='temporal*')" in sh
    assert 'pg_dumpall -U litellm "${PG_SKIP[@]}"' in sh


def test_the_runner_environment_is_pinned_checksummed_and_follows_its_lock():
    sh = (ROOT / "ops/runner_env.sh").read_text()
    assert re.search(r"^UV_VERSION=\d+\.\d+\.\d+$", sh, re.M) and re.search(r"^UV_SHA256=[0-9a-f]{64}\b", sh, re.M)
    assert "sha256sum -c" in sh and "--require-hashes" in sh and "# limit: refuses" in sh
    lock = (ROOT / "ops/runner-requirements.lock").read_text()
    pins = dict(re.findall(r"^([a-z0-9_.-]+)==(\S+)", lock, re.M))
    req = dict(re.findall(r"^([a-z0-9_.-]+)==(\S+)", (ROOT / "ops/runner-requirements.txt").read_text(), re.M))
    tests = dict(re.findall(r"^([a-z0-9_.-]+)==(\S+)", (ROOT / "tests/requirements.txt").read_text(), re.M))
    assert all(pins[k] == v for k, v in req.items())                                    # the lock holds the pins
    assert tests["temporalio"] == req["temporalio"] and tests["cryptography"] == req["cryptography"]
    assert lock.count("--hash=sha256:") >= len(pins)

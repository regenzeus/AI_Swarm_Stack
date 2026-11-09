"""Temporal upgrades in the update path (GEN-39): across two minor versions the schema and the server of each run in order,
each checked, and a failing step restores the snapshot and the old server; a skipped minor version, a step back and a
major version are refused; the pinned version is in the table."""
from pathlib import Path

import pytest
import yaml

import temporal_upgrade as TU

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = {v: {"server": f"temporalio/server:{v}", "admin": f"temporalio/admin-tools:{v}"} for v in ("1.32.1", "1.33.0", "1.33.2", "1.34.1", "1.35.0")}


def world(fail=None):
    log = []

    def step(what):
        def fn(v, imgs):
            log.append(f"{v} {what}")
            return (v, what) != fail
        return fn
    return log, dict(snapshot=lambda: log.append("snapshot") or "snap-1", restore=lambda s: log.append(f"restore {s}"),
                     schema=step("schema"), server=step("server"), check=step("check"))


def test_an_update_across_two_minor_versions_runs_each_schema_server_and_check_in_order():
    assert TU.plan("1.32.1", "1.34.1", VERSIONS) == ["1.33.2", "1.34.1"]
    log, fns = world()
    r = TU.run("1.32.1", "1.34.1", VERSIONS, **fns)
    assert r["ok"] and log == ["snapshot", "1.33.2 schema", "1.33.2 server", "1.33.2 check", "1.34.1 schema", "1.34.1 server", "1.34.1 check"]


def test_a_failing_step_restores_the_snapshot_and_starts_the_old_server_again():
    log, fns = world(fail=("1.34.1", "schema"))
    r = TU.run("1.32.1", "1.34.1", VERSIONS, **fns)
    assert not r["ok"] and "Temporal 1.34.1: the schema step failed" in r["why"] and "back at 1.32.1" in r["why"]
    assert log[-2:] == ["restore snap-1", "1.32.1 server"] and r["done"] == ["1.33.2 schema", "1.33.2 server", "1.33.2 check"]


@pytest.mark.parametrize("old, new, words", [
    ("1.34.1", "1.32.1", "does not go back"),
    ("1.32.1", "2.0.0", "a major version"),
    ("1.32.1", "1.36.0", "no pinned image for Temporal 1.36"),
])
def test_a_step_back_a_major_version_and_a_skipped_minor_are_refused(old, new, words):
    with pytest.raises(ValueError, match=words):
        TU.plan(old, new, VERSIONS)
    assert not TU.run(old, new, VERSIONS, **world()[1])["ok"]


def test_the_pinned_version_is_in_the_step_table_with_the_same_images():
    pins = dict(line.split("=", 1) for line in (ROOT / "versions.env").read_text().splitlines() if line.startswith("TEMPORAL_"))
    table = yaml.safe_load((ROOT / "config/temporal/steps.yaml").read_text())["versions"]
    v = pins["TEMPORAL_IMAGE"].split(":")[1].split("@")[0]
    assert table[v]["server"] == pins["TEMPORAL_IMAGE"] and table[v]["admin"] == pins["TEMPORAL_ADMIN_IMAGE"]
    assert TU.plan(v, v, TU.table()) == []


def test_the_update_moves_temporal_first_and_stays_put_when_that_fails(monkeypatch):
    import update as UP
    calls = []
    monkeypatch.setattr(UP, "check", lambda repo, tag, signers: None)
    monkeypatch.setattr(UP, "git", lambda repo, *a, check=True: type("P", (), {"stdout": {"rev-parse": "new\n"}.get(a[0], "") if a[0] != "rev-parse" or a[1] != "HEAD" else "old\n", "returncode": 0})())
    said = UP.apply(".", "v2026.11.10", "signers", lambda c: True, lambda o, n: calls.append("deploy") or True,
                    lambda o, n: calls.append("temporal") or {"ok": False, "why": "Temporal 1.34.1: the schema step failed"})
    assert said.startswith("NOT UPDATED: Temporal 1.34.1: the schema step failed") and calls == ["temporal"]
    assert TU.pinned("TEMPORAL_IMAGE=temporalio/server:1.32.1@sha256:abc\n") == "1.32.1"

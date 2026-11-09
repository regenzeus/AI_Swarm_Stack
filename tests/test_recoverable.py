"""Recoverable and reproducible (PLT-15, PLT-20, PLT-23, CST-14, QA-17; review 2026-10-30, FND-66 to FND-68, FND-74):
the board says when no restore drill has passed for 8 days, when swap is full, when a container runs another build
than its tag or the lock file lacks it, and when a container is cut off from the network it shares; failed writes are
logged, and silent broad catches can only become fewer."""
import pysrc
import ast
import json
import time
from pathlib import Path

import crew

ROOT = Path(__file__).resolve().parent.parent
MEM = "MemTotal: 10000000 kB\nMemAvailable: {avail} kB\nSwapTotal: 3000000 kB\nSwapFree: {free} kB\n"


def drill_item():
    return {"kind": "crew", "id": "restore-drill", "name": "Restore drill", "issues": []}


def test_no_drill_for_eight_days_is_an_alert_and_a_recent_one_is_quiet(tmp_path):
    now = time.time()
    b = tmp_path / "backups.jsonl"
    b.write_text("\n".join(json.dumps(r) for r in [{"ts": now - 9 * 86400, "kind": "restore-drill", "result": "ok"},
                                                    {"ts": now - 3600, "kind": "backup", "size": "772M"}]))
    it = drill_item()
    assert crew.recovery_alarms([it], now=now, backups=b, meminfo="", drift="", nets=[]) == []
    assert it["issues"][0]["kind"] == "drill-old" and "drill-old" in crew.ALERTS
    assert "no restore drill has passed for 9 days" in it["issues"][0]["text"] and "772M" in it["issues"][0]["text"]
    b.write_text(json.dumps({"ts": now - 2 * 86400, "kind": "restore-drill", "result": "ok"}))
    it = drill_item()
    crew.recovery_alarms([it], now=now, backups=b, meminfo="", drift="", nets=[])
    assert it["issues"] == []


def test_full_swap_is_a_note_and_an_alert_when_ram_is_short_too(tmp_path):
    full = crew.recovery_alarms([], backups=tmp_path / "none", meminfo=MEM.format(avail=5000000, free=10000), drift="", nets=[])
    assert full[0]["name"] == "This PC" and full[0]["issues"][0]["kind"] == "swap-full" and "100 % full" in full[0]["issues"][0]["text"]
    short = crew.recovery_alarms([], backups=tmp_path / "none", meminfo=MEM.format(avail=500000, free=10000), drift="", nets=[])
    assert short[0]["issues"][0]["kind"] == "memory-low" and "memory-low" in crew.ALERTS
    assert crew.recovery_alarms([], backups=tmp_path / "none", meminfo=MEM.format(avail=5000000, free=2000000), drift="", nets=[]) == []


def test_a_container_on_another_build_than_its_tag_and_an_unlocked_image_are_named():
    images = {"aistack-hermes-1": ("aistack/hermes:1", "sha:old", "sha:new"), "aistack-qmd-1": ("aistack/qmd:2", "sha:q", "sha:q"),
              "aistack-mail-1": ("aistack/mail:1", "sha:m", "sha:m")}

    def run(*a):
        if a[0] == "ps":
            return "\n".join(f"{n}\t{v[0]}" for n, v in images.items())
        if a[0] == "inspect":
            return images[a[3]][0] if a[2] == "{{.Config.Image}}" else images[a[3]][1]
        return next(v[2] for v in images.values() if v[0] == a[4])
    text = crew.image_drift(lock="aistack-qmd-1 aistack/qmd:2 sha:q\n", run=run)
    assert "hermes runs another build than its image tag names" in text and "versions.lock lacks 1 running image (aistack/mail:1)" in text
    assert crew.image_drift(lock="aistack/qmd:2\naistack/mail:1\naistack/hermes:1\n", run=lambda *a: run(*a).replace("sha:old", "sha:new")) == ""


def test_a_container_cut_off_from_the_network_it_shares_is_an_alert_until_it_is_recreated(tmp_path):
    crew._cut.clear()                                    # docker's own output shapes; the gate kept the old Hermes's network

    def run(*a):
        if a[:2] == ("ps", "-q"):
            return "idhermesnew\nidgate\niddash\n"
        if a[0] == "ps":
            return ("aistack-hermes-1\thermes\naistack-gate-hermes-dashboard-1\tgate-hermes-dashboard\naistack-hermes-dashboard-1\thermes-dashboard\n"
                    "aistack-ua-viewer-port\t\n")     # not in compose: no service label
        assert a[0] == "inspect" and set(a[3:]) == {"aistack-hermes-1", "aistack-gate-hermes-dashboard-1", "aistack-hermes-dashboard-1",
                                                    "aistack-ua-viewer-port"}
        return ("/aistack-hermes-1\tbridge\n/aistack-gate-hermes-dashboard-1\tcontainer:idhermesold\n"
                "/aistack-hermes-dashboard-1\tcontainer:idhermesnew\n/aistack-ua-viewer-port\tcontainer:idviewerold\n")
    cut = crew.cut_networks(run=run, now=100)
    assert [i["kind"] for i in cut] == ["network-cut"] * 2 and "network-cut" in crew.ALERTS
    assert cut[0]["text"].startswith("gate-hermes-dashboard shares the network of a container that no longer runs")
    assert 'make up UP_SERVICES="--no-deps --force-recreate gate-hermes-dashboard"' in cut[0]["text"]
    assert cut[1]["text"] == ("aistack-ua-viewer-port shares the network of a container that no longer runs, so nothing reaches it: "
                              "recreate it after the container whose network it shares")
    assert crew.cut_networks(run=run, now=200)[0]["at"] == 100       # the same issue, so it alerts once
    pc = crew.recovery_alarms([], backups=tmp_path / "none", meminfo="", drift="", nets=cut)
    assert pc[0]["name"] == "This PC" and pc[0]["issues"] == cut
    healed = lambda *a: run(*a).replace("container:idhermesold", "container:idhermesnew").replace("idviewerold", "idgate")
    assert crew.cut_networks(run=healed, now=300) == [] and crew._cut == {}


def silent_catches():
    n = 0
    for f in sorted((ROOT / "ops").rglob("*.py")) + sorted((ROOT / "images").rglob("*.py")) + sorted((ROOT / "config").rglob("*.py")):
        for h in ast.walk(ast.parse(f.read_text())):
            if isinstance(h, ast.ExceptHandler) and (h.type is None or getattr(h.type, "id", "") in ("Exception", "BaseException")):
                b = h.body
                n += len(b) == 1 and (isinstance(b[0], (ast.Pass, ast.Continue))
                                      or (isinstance(b[0], ast.Return) and (b[0].value is None or isinstance(b[0].value, ast.Constant))))
    return n


SILENT_MAX = 67      # FND-68: may only go down. A new broad catch logs what it caught, or catches the exact error it expects.


def test_broad_catches_that_drop_the_error_can_only_become_fewer():
    n = silent_catches()
    assert n <= SILENT_MAX, f"{n} broad excepts drop their error silently (at most {SILENT_MAX}): log it or catch the exact error"
    src = pysrc.server() + pysrc.builds()
    assert "not closed after the restart" in src and "CI status not read" in src


def test_an_ai_phone_down_for_half_an_hour_is_an_alert_unless_the_owner_stopped_it(tmp_path, monkeypatch):
    """FND-116: the AI phone stood still for 8.5 hours (a request it could not read) and nothing said so. Disconnected for
    30 minutes, or its service silent for 10, it is an alert on This PC; switched off by the owner, it is not."""
    import os
    monkeypatch.setattr(crew, "_phone_down", {"since": None})
    st = tmp_path / "state.json"
    now = time.time()
    st.write_text(json.dumps({"connected": False, "error": "Permission denied: /phone/control/x.json"}))
    assert crew.phone_down(now, tmp_path) is None                             # just went down
    os.utime(st, (now + 31 * 60, now + 31 * 60))                              # its service keeps writing its state, with the error
    i = crew.phone_down(now + 31 * 60, tmp_path)
    assert i["kind"] == "phone-down" and "disconnected for 31 min" in i["text"] and "Permission denied" in i["text"]
    assert "phone-down" in crew.ALERTS
    (tmp_path / "STOP").write_text("")
    assert crew.phone_down(now + 40 * 60, tmp_path) is None                   # the owner switched it off
    (tmp_path / "STOP").unlink()
    st.write_text(json.dumps({"connected": True}))
    os.utime(st, (now - 900, now - 900))
    assert "has not reported for 15 min" in crew.phone_down(now, tmp_path)["text"]   # connected, but its service went silent
    os.utime(st, (now, now))
    assert crew.phone_down(now, tmp_path) is None and crew._phone_down["since"] is None
    assert crew.phone_down(now, tmp_path / "none") is None                    # no AI phone here


def test_a_fault_the_checker_finds_is_an_alert_not_its_failed_run(tmp_path):
    """FND-112: the checker failed 25 runs for a fault it had found and reported (the Ledger refusing the requirements
    sync), which made its failure rate mean two things. Its run ends done with the faults kept; each is an alert on its
    card, and its next clean run clears them."""
    f = tmp_path / "checker.json"
    f.write_text(json.dumps({"last": 5, "faults": ["system had 64 refused swarm writes in 24 h"]}))
    assert crew.checker_faults(f, now=10) == [{"kind": "swarm-fault", "at": 5, "text": "system had 64 refused swarm writes in 24 h"}]
    assert "swarm-fault" in crew.ALERTS
    f.write_text(json.dumps({"last": 6, "faults": []}))
    assert crew.checker_faults(f, now=10) == []
    src = (crew.Path(crew.__file__).parent / "checker.py").read_text()
    run = src[src.index("def run(c):"):]
    assert "raise RuntimeError" not in run and "faults=bad" in run


def test_a_check_s_report_that_is_missing_broken_or_old_is_no_pass(tmp_path):
    """The review of 6 Nov: a checker that could not be read looked exactly like one that found nothing."""
    import crew
    day = 86400
    none = tmp_path / "none.json"
    for got in (crew.checker_faults(none), crew.journey_issues(none)):
        assert [i["kind"] for i in got] == ["report-none"] and "has not run yet" in got[0]["text"]
    assert "report-none" not in crew.ALERTS and "report-unknown" in crew.ALERTS     # a new install is told, not alarmed
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    for got in (crew.checker_faults(bad), crew.journey_issues(bad)):
        assert [i["kind"] for i in got] == ["report-unknown"] and "cannot be read" in got[0]["text"]
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"last": 1000, "at": 1000, "faults": ["a fault"], "journeys": []}))
    got = crew.checker_faults(old, now=1000 + 3 * day)
    assert [i["kind"] for i in got] == ["swarm-fault", "report-unknown"] and "over 2 days old" in got[1]["text"]
    assert [i["kind"] for i in crew.journey_issues(old, now=1000 + 3 * day)] == ["report-unknown"]
    assert crew.checker_faults(old, now=1000 + day)[0]["kind"] == "swarm-fault" and crew.journey_issues(old, now=1000 + day) == []
    nostamp = tmp_path / "nostamp.json"
    nostamp.write_text(json.dumps({"journeys": []}))
    assert [i["kind"] for i in crew.journey_issues(nostamp)] == ["report-unknown"]    # no date: no way to call it recent


def test_a_test_touches_no_folder_of_this_machine(tmp_path):
    """QA-24: what made CI red: tests wrote to /srv/ai and /srv/vault, which only the builder's container could create."""
    import crew
    import journal
    import notify
    for path in (notify.STATE, notify.EVENTS, journal.VAULT, crew.OUT, crew.BACKUPS):
        assert str(path).startswith(str(tmp_path)), path
    import postmaster
    import pytest
    import subprocess

    def no_ssh(*a, **k):
        raise FileNotFoundError("ssh")
    real, subprocess.run = subprocess.run, no_ssh
    try:
        with pytest.raises(postmaster.CopyUnread, match="ssh could not start"):      # no ssh: said, and never a real ssh in a test
            postmaster.fetch("status.json")
    finally:
        subprocess.run = real


def test_the_ci_runner_has_an_init_that_reaps_what_its_jobs_leave_behind():
    """QA-25: 11,904 zombie git processes filled the runner's process limit; a job hung for 30 minutes, then every push
    "failed after 1s", which read as failing code."""
    import yaml
    apps = yaml.safe_load((ROOT / "compose/apps.yaml").read_text())
    assert apps["services"]["ci-runner"]["init"] is True

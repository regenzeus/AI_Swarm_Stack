"""PLT-27: the services that grow while idle are restarted each night, only when the stack is idle; busy for an hour,
the night is skipped; before and after are logged."""
import json
import time

import recycle as R

STATS = "aistack-qmd-1\t1.2GiB / 3GiB\naistack-phoenix-1\t442.4MiB / 1GiB\naistack-openwebui-1\t655MiB / 1GiB\naistack-hermes-1\t500MiB / 2GiB\n"


def test_busy_names_what_runs_and_ignores_a_stale_task():
    now = time.time()
    iso = lambda s: __import__("datetime").datetime.fromtimestamp(now - s).astimezone().isoformat()
    assert R.busy({"running": {"slug": "x"}}, []) == "a mission is running"
    assert R.busy({"tasks": [{"id": 5, "status": "running", "updated": iso(60)}]}, [], now) == "task #5 is running"
    assert R.busy({"tasks": [{"id": 93, "status": "planning", "updated": iso(3 * 86400)}]}, [], now) == ""   # a leftover
    assert R.busy({"builds": [{"id": 7, "status": "deploying"}]}, []) == "build #7 is deploying"
    assert R.busy({}, ["trial-stack-night.service", "docker.service"]) == "trial-stack-night.service is running"
    assert R.busy({}, ["docker.service", "missions.service"]) == ""
    assert R.busy({}, ["graphify-sync.service"]) == "graphify-sync.service is running"   # the code graph's merge (review O9)


def test_an_idle_night_restarts_the_three_and_logs_memory_before_and_after(tmp_path):
    calls = []
    def sh(*cmd, timeout=0):
        calls.append(cmd)
        return STATS if cmd[:2] == ("docker", "stats") else ""
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("SwapTotal:  3145728 kB\nSwapFree:  1048576 kB\n")
    R_mem = R.memory
    R.memory = lambda sh: R_mem(sh, meminfo)
    try:
        st = tmp_path / "state.json"
        st.write_text(json.dumps({"tasks": [], "builds": []}))
        row = R.run(sh=sh, state=st, log=tmp_path / "log.jsonl", sleep=lambda s: None)
    finally:
        R.memory = R_mem
    assert [c[3] for c in calls if c[:2] == ("docker", "restart")] == ["20", "20", "20"]
    assert [c[-1] for c in calls if c[:2] == ("docker", "restart")] == ["aistack-qmd-1", "aistack-phoenix-1", "aistack-openwebui-1"]
    assert row["before"] == {"qmd": 1229, "phoenix": 442, "openwebui": 655, "swap": 2048} and "after" in row
    assert json.loads((tmp_path / "log.jsonl").read_text())["before"]["swap"] == 2048


def test_a_busy_hour_skips_the_night_without_restarting(tmp_path):
    calls, clock = [], [1000.0]
    sh = lambda *cmd, timeout=0: calls.append(cmd) or (STATS if cmd[:2] == ("docker", "stats") else "")
    st = tmp_path / "state.json"
    st.write_text(json.dumps({"running": {"slug": "copper"}}))
    R_mem = R.memory
    R.memory = lambda sh: {"swap": 1}
    try:
        row = R.run(sh=sh, state=st, log=tmp_path / "log.jsonl", sleep=lambda s: clock.__setitem__(0, clock[0] + s), now=lambda: clock[0])
    finally:
        R.memory = R_mem
    assert row["skipped"] == "a mission is running" and not [c for c in calls if c[:2] == ("docker", "restart")]
    assert clock[0] - 1000.0 >= R.WAIT_S                                       # it looked again for the whole hour

"""PLT-36: when Windows C: (which holds WSL's disk) runs low, the runner prunes the Docker build cache and tells the
owner once; nearly full, it alerts urgently at most once an hour; a fresh low after recovery is a new episode."""


def guard():
    import diskguard as DG
    ran, told = [], []
    st = {"relief_at": 0.0, "crit_at": 0.0, "episode": False}

    def sh(*cmd, timeout=60):
        ran.append(cmd)
        return "Total:\t12.5GB\n" if cmd[1] == "builder" else "Total reclaimed space: 0B\n"
    return DG, ran, told, st, sh, lambda text, cat: told.append((text, cat))


def test_low_disk_prunes_the_build_cache_and_tells_the_owner_once():
    DG, ran, told, st, sh, notify = guard()
    assert DG.check({"disk_c_free_gb": 12.0}, sh, notify, now=10_000, st=st) == "pruned"
    assert ran == [("docker", "builder", "prune", "-af"), ("docker", "image", "prune", "-f")]
    assert len(told) == 1 and "12.0 GB free" in told[0][0] and "Total:" in told[0][0] and told[0][1] == "system"
    assert DG.check({"disk_c_free_gb": 12.0}, sh, notify, now=10_020, st=st) == ""          # paced: once an hour
    assert DG.check({"disk_c_free_gb": 12.0}, sh, notify, now=10_000 + 3600, st=st) == "pruned"
    assert len(told) == 1                                                                   # same episode: no new alert


def test_nearly_full_alerts_urgently_at_most_once_an_hour():
    DG, ran, told, st, sh, notify = guard()
    assert DG.check({"disk_c_free_gb": 0.2}, sh, notify, now=10_000, st=st) == "pruned+critical"
    assert any("only 0.2 GB" in t for t, _ in told)
    assert DG.check({"disk_c_free_gb": 0.2}, sh, notify, now=10_600, st=st) == ""
    assert DG.check({"disk_c_free_gb": 0.2}, sh, notify, now=13_700, st=st) == "pruned+critical"


def test_enough_space_or_no_reading_does_nothing_and_recovery_ends_the_episode():
    DG, ran, told, st, sh, notify = guard()
    for h in ({"disk_c_free_gb": 80}, {"disk_c_free_gb": 22}, None, {}, {"disk_c_free_gb": "?"}):
        assert DG.check(h, sh, notify, now=10_000, st=st) == ""
    assert ran == [] and told == []
    DG.check({"disk_c_free_gb": 15}, sh, notify, now=10_000, st=st)
    DG.check({"disk_c_free_gb": 30}, sh, notify, now=11_000, st=st)                        # recovered
    DG.check({"disk_c_free_gb": 15}, sh, notify, now=20_000, st=st)                        # a new episode
    assert len(told) == 2


def test_the_runner_checks_every_reading_of_the_host_probe():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "ops" / "missions.py").read_text()
    assert "import diskguard as DG" in src and "DG.check(host, sh, notify)" in src

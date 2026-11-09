"""PLT-35: WSL's kernel keeps whole blocks of memory free, so a call into WSL from Windows always gets its channel
(9 Nov 2026: order-7 allocations for the Hyper-V socket's ring failed, and calls timed out with WSAETIMEDOUT)."""
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "ops/wsl-memory.sh"


def test_the_settings_are_written_to_sysctl_d_and_applied_at_once():
    s = SH.read_text()
    conf = re.search(r"<<'EOF'\n(.*?)\nEOF", s, re.S).group(1)
    values = dict(re.findall(r"^(vm\.\w+) = (\d+)$", conf, re.M))
    assert values == {"vm.min_free_kbytes": "262144", "vm.watermark_scale_factor": "200", "vm.compaction_proactiveness": "50"}
    assert "CONF=/etc/sysctl.d/90-aistack-memory.conf" in s and 'sysctl -q -p "$CONF"' in s
    assert "echo 1 > /proc/sys/vm/compact_memory" in s                      # compacted now, not only after a restart
    assert "# limit: waits" in conf or "limit: waits" in conf


def test_it_refuses_to_run_without_root_and_says_how():
    if os.geteuid() == 0:
        return                                                             # a root test runner would change its own kernel
    r = subprocess.run(["bash", str(SH)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "refused: run as root" in r.stderr and "-u root" in r.stderr


def test_the_file_cache_goes_back_to_windows_every_30_minutes():
    """9 Nov 2026: the programs used 2.6 GB, the cache 4.3 GB, Windows had 0.4 GB free; WSL drops it only when idle."""
    s = SH.read_text()
    assert "ExecStart=/bin/sh -c 'sync; echo 1 > /proc/sys/vm/drop_caches; echo 1 > /proc/sys/vm/compact_memory'" in s
    assert "OnUnitActiveSec=30min" in s and "# limit: paces" in s and "WantedBy=timers.target" in s
    assert "systemctl enable --now aistack-drop-cache.timer" in s
    assert "systemctl enable aistack-drop-cache.timer" in s                   # the bootstrap, before systemd runs


def test_a_new_machine_gets_it_from_the_root_bootstrap():
    assert 'bash "$STAGE/ops/wsl-memory.sh"' in (ROOT / "ops/bootstrap-wsl-1-root.sh").read_text()

"""ops/bootstrap-wsl-2-user.sh refuses a move (review OPS-R7: run on a PC being restored it rewrote .sops.yaml and pushed
fresh root commits over the real history). Its guard runs alone, with a stand-in git that cannot reach Forgejo."""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("backup,first,refused", [(True, "", True), (False, "", False), (True, "1", False)])
def test_the_first_install_script_refuses_a_pc_with_a_backup_to_restore(tmp_path, backup, first, refused):
    text = (ROOT / "ops/bootstrap-wsl-2-user.sh").read_text()
    guard = re.search(r'^if \[ -z "\$\{FIRST_INSTALL:-\}" \]; then\n.*?^fi$', text, re.M | re.S).group(0)
    (tmp_path / "restore").mkdir()
    if backup:
        (tmp_path / "restore" / "aistack-2026-11-08.tar.gz.age").write_text("x")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "git").write_text("#!/bin/sh\nexit 128\n")          # Forgejo out of reach
    (tmp_path / "bin" / "git").chmod(0o755)
    env = {"HOME": str(tmp_path), "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin", "FORGEJO_OWNER": "o", "FIRST_INSTALL": first}
    r = subprocess.run(["bash", "-c", guard + "\necho RAN"], capture_output=True, text=True, env=env)
    assert (r.returncode == 2) is refused and ("RAN" in r.stdout) is not refused
    if refused:
        assert "new-machine.sh" in r.stderr

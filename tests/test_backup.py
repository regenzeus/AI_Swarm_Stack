"""PLT-13 (FND-76): a file the backup user cannot read is skipped and named, and the backup still completes; any other
copy error still fails it. rsync is replaced by a fake that answers like the real one did on 2026-10-31."""
import re
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DENIED = ('rsync: [sender] send_files failed to open "/srv/ai/workbench/ai-stack.1/.serena/project.yml": Permission denied (13)\n'
          "rsync error: some files/attrs were not transferred (see previous errors) (code 23) at main.c(1356) [sender=3.2.7]\n")


def copy(tmp_path, err, rc):
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    (bin_ / "rsync").write_text(f"#!/bin/sh\necho \"$@\" > {tmp_path}/args\nprintf '%s' '{err}' >&2\nexit {rc}\n")
    (bin_ / "rsync").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}"}
    return subprocess.run(["bash", str(ROOT / "ops/backup-copy.sh"), "/srv/ai/", str(tmp_path / "stage")], capture_output=True, text=True, env=env)


def test_an_unreadable_file_is_skipped_and_named_and_the_backup_goes_on(tmp_path):
    r = copy(tmp_path, DENIED, 23)
    assert r.returncode == 0 and "skipped 1 file(s) the backup user cannot read" in r.stdout
    assert ".serena/project.yml" in r.stdout
    args = (tmp_path / "args").read_text()
    assert "--exclude workbench" in args and "--exclude phone/home" in args and "--exclude backup-outbox" in args


def test_any_other_copy_error_still_fails_the_backup(tmp_path):
    r = copy(tmp_path, DENIED + "rsync: write failed on /tmp/stage/x: No space left on device (28)\n", 23)
    assert r.returncode == 23 and "No space left" in r.stderr
    r = copy(tmp_path, "rsync error: error in socket IO (code 10)\n", 10)
    assert r.returncode == 10
    assert copy(tmp_path, "", 0).returncode == 0
    backup = (ROOT / "ops/backup.sh").read_text()
    assert '"$(dirname "$0")/backup-copy.sh" /srv/ai/ $STAGE/srv-ai/' in backup
    live = re.search(r"^live_tar\(\) .*$", backup, re.M)[0]                                  # a file changed while tar read it: not a failed backup
    for code, want in ((0, 0), (1, 0), (2, 2)):
        script = f"set -euo pipefail\ntar() {{ return {code}; }}\n{live}\nlive_tar -cf x y\necho on\n"
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        assert r.returncode == want and ("on" in r.stdout) == (want == 0)
    assert "live_tar -C /srv -cf $STAGE/vault.tar vault" in backup and "live_tar -C ~ -cf $STAGE/home.tar" in backup

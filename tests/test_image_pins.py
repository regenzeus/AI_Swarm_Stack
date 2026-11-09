"""The helper images run by the scripts are pinned (review OPS-R9: `alpine` was whatever latest was, and the restore drill
pulled the floating pgvector/pgvector:pg17 instead of the image the live long-term memory runs)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ["ops/backup.sh", "ops/desk.sh", "ops/hindsight-models.sh", "ops/restore.sh"]


def test_every_helper_run_uses_the_pinned_alpine_and_the_drill_the_live_memory_image():
    pin = re.search(r"^ALPINE_IMAGE=(\S+)$", (ROOT / "versions.env").read_text(), re.M).group(1)
    assert re.fullmatch(r"alpine@sha256:[0-9a-f]{64}", pin)
    for f in SCRIPTS:
        sh = (ROOT / f).read_text()
        assert 'grep -m1 "^ALPINE_IMAGE=" "$(dirname "$0")/../versions.env"' in sh, f
        assert not re.search(r"\salpine(\s|$)", "\n".join(ln.split("#")[0] for ln in sh.splitlines())), f
    drill = (ROOT / "ops/restore.sh").read_text()
    assert "pgvector/pgvector:pg17" not in drill and 'docker inspect -f "{{.Config.Image}}" aistack-hindsight-db-1' in drill

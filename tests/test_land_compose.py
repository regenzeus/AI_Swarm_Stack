"""ops/land.sh validates the landing commit's compose files on the host before it lands (review OPS-R14: its checks run
in the builder, which has no Docker, so "compose files valid" was never run and a broken compose file would deploy)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_a_landing_validates_its_compose_files_on_the_host_before_main_moves():
    sh = (ROOT / "ops/land.sh").read_text()
    check = sh.index('CSAID=$(bash "$CTREE/ops/ci-compose-check.sh"')
    assert sh.index('git archive --format=tar "$TIP" | tar -xf - -C "$CTREE"') < check     # the commit that lands, not the tree here
    assert check < sh.index("git merge -q --ff-only") and "NOT LANDED: the compose files" in sh

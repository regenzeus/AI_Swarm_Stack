"""PLT-25: no source file over 1,500 lines. A long file is cut at its own sections into parts that run where they stood:
the app's scripts load in index.html's order into one global scope; a Python file runs its parts in its own namespace
(_part, server.chat.py, ...), linted joined (ops/py_parts_lint.py)."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOST = 1500                                          # limit: refuses, lines in a source file (PLT-25)
SOURCE = (".py", ".js", ".mjs", ".sh")


def test_no_source_file_is_over_1500_lines():
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True).stdout.split()
    long = {f: n for f in files if f.endswith(SOURCE) and "/vendor/" not in f and not f.startswith("tests/") and (ROOT / f).exists()
            for n in [(ROOT / f).read_text(errors="replace").count("\n")] if n > MOST}
    assert long == {}, f"over {MOST} lines: {long}"


def test_every_part_is_run_by_its_parent_and_no_part_is_left_over():
    pat = re.compile(r'^_part\("([^"]+)"\)', re.M)
    for parent in ("images/mission-control/server.py", "ops/missions.py", "ops/builds.py", "images/swarm/ledger.py"):
        p = ROOT / parent
        named = set(pat.findall(p.read_text()))
        on_disk = {x.name for x in p.parent.glob(f"{p.stem}.*.py")}
        assert named and named == on_disk, (parent, named, on_disk)
        assert "def _part(name):" in p.read_text()
    assert "server.*.py" in (ROOT / "images/mission-control/Dockerfile").read_text() and "ledger.*.py" in (ROOT / "images/swarm/Dockerfile").read_text()
    assert "ops/py_parts_lint.py" in (ROOT / "ops/check.sh").read_text()


def test_a_split_module_has_every_name_it_had():
    import ledger
    import missions
    import builds
    assert hasattr(missions, "slugify") and hasattr(missions, "write_state") and hasattr(builds, "ai_review") and hasattr(builds, "recheck")
    assert issubclass(ledger.Ledger, ledger._LedgerWork) and hasattr(ledger.Ledger, "scorecard") and hasattr(ledger.Ledger, "context")
    assert missions.slugify.__module__ == "missions" and builds.ai_review.__globals__ is vars(builds)   # one namespace, patches hold

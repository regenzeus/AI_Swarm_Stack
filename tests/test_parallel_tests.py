"""QA-27: the landing's tests run in parallel and every test process has a temp folder of its own."""
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_checks_run_the_suite_over_workers_when_xdist_is_there():
    sh = (ROOT / "ops/check.sh").read_text()
    assert 'if "${PYTEST:-pytest}" -p xdist --version >/dev/null 2>&1; then PAR=(-n "${PYTEST_WORKERS:-6}"); fi' in sh
    assert '-q -p no:cacheprovider "${PAR[@]}" tests' in sh
    assert "pytest-xdist==3.6.1" in (ROOT / "tests/requirements.txt").read_text()


def test_each_test_process_has_a_temp_folder_of_its_own():
    here = Path(tempfile.gettempdir())
    assert here.name.startswith(f"aistack-tests-{os.getuid()}-") and here.name.endswith(f"-{os.getpid()}")
    assert os.environ["TMPDIR"] == str(here) and here.is_dir()


def test_the_publish_runs_the_snapshots_tests_over_workers_too():
    py = (ROOT / "ops/publish.py").read_text()
    assert "/opt/tools/bin/pytest -p xdist --version >/dev/null 2>&1 && PAR='-n 6'" in py and "-p no:cacheprovider $PAR tests" in py

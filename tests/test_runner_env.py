"""The host runner's own Python environment (PLT-37): uv pinned by version and checksum, the packages by a hashed lock
that follows the pins, and the tests on the same pins."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pins(text):
    return dict(re.findall(r"^([a-z0-9_.-]+)==(\S+)", text, re.M))


def test_the_runner_environment_is_pinned_checksummed_and_follows_its_lock():
    sh = (ROOT / "ops/runner_env.sh").read_text()
    assert re.search(r"^UV_VERSION=\d+\.\d+\.\d+$", sh, re.M) and re.search(r"^UV_SHA256=[0-9a-f]{64}\b", sh, re.M)
    assert "sha256sum -c" in sh and "--require-hashes" in sh and "# limit: refuses" in sh
    lock = (ROOT / "ops/runner-requirements.lock").read_text()
    locked, req = pins(lock), pins((ROOT / "ops/runner-requirements.txt").read_text())
    assert req and all(locked.get(k) == v for k, v in req.items())                         # the lock holds the pins
    blocks = re.split(r"\n(?=[a-z0-9_.-]+==)", lock.strip())
    assert len(blocks) == len(locked) and all("--hash=sha256:" in b for b in blocks)     # every package it pulls in, hashed
    assert "atlassian-python-api" in req and "requests" in locked                          # the Jira tracker's client and what it needs
    assert '--exclude-newer "$aged"' in sh and "date -u -d '14 days ago'" in sh           # no release younger than the pin rule
    tests = pins((ROOT / "tests/requirements.txt").read_text())
    assert all(tests[k] == v for k, v in req.items() if k in tests)                       # the tests run on the same pins
    unit = (ROOT / "ops/systemd/missions.service").read_text()
    assert "/.local/share/aistack/runner/bin/python ops/missions.py" in unit              # the runner runs in it

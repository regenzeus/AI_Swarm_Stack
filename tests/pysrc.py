"""A Python file kept in parts (PLT-25) as one text: its parts in place of their _part(...) lines, as it runs."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PART = re.compile(r'^_part\("([^"]+)"\).*$', re.M)


def joined(path):
    p = Path(path) if Path(path).is_absolute() else ROOT / path
    return PART.sub(lambda m: p.with_name(m.group(1)).read_text().rstrip("\n"), p.read_text())


def server():
    return joined("images/mission-control/server.py")


def missions():
    return joined("ops/missions.py")


def builds():
    return joined("ops/builds.py")


def ledger():
    return joined("images/swarm/ledger.py")

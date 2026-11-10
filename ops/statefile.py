"""State files written whole or not at all (WFL-05).

A runner killed in the middle of a plain write (a deploy restarts it) leaves the file empty or cut, and a reader that
trusts it fails on every pass after. So a state file is written to a temp file in its own folder, flushed to disk and
put in place with os.replace: a reader sees the old file, the new one, or none. And a reader takes an empty or
unreadable file as no state (load's default), so one bad file can never wedge the work that reads it.
"""
import json
import os
import tempfile
from pathlib import Path

MODE = 0o644                                         # as a plain write leaves it: the app (another uid) reads the step service's answers


def save(path, data, indent=None):
    """Write data as JSON to path atomically: the whole new file or the old one, never a part."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, MODE)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load(path, default=None):
    """The JSON in path, or default when it is missing, empty or not JSON."""
    try:
        text = Path(path).read_text(encoding="utf-8")
        return json.loads(text) if text.strip() else default
    except (OSError, ValueError):
        return default

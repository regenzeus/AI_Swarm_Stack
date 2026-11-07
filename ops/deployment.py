#!/usr/bin/env python3
"""This deployment's hosts, paths and accounts, as config/deployment.env sets them (PLT-33).

    import deployment as DEPLOY; DEPLOY.NAS_HOST     in the host-side Python of ops/
    python3 ops/deployment.py CODE_DIR               one value (the Makefile)
    eval "$(python3 ops/deployment.py shell)"        every value as a shell variable (the scripts of ops/ and smoke/)

A variable of the same name in the environment wins over the file. Reads that one file and nothing else. Containers do
not import this: compose reads the same file, and compose/apps.yaml hands each container what it needs."""
import os
import re
import shlex
import sys
from pathlib import Path

FILE = Path(__file__).resolve().parent.parent / "config" / "deployment.env"


def load(path=FILE, env=os.environ):
    """-> {name: value} of the file, in its order. ${NAME} names a line above, as in a shell and in compose."""
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and not line.startswith("#"):
            values[name] = env[name] if name in env else re.sub(r"\$\{(\w+)\}", lambda m: values[m.group(1)], value)
    return values


VALUES = load()
globals().update(VALUES)


def fill(text, values=None):
    """A file that names values as {{NAME}} -> with the values in it (the app's tools.json; app.js does the same)."""
    return re.sub(r"\{\{(\w+)\}\}", lambda m: (VALUES if values is None else values)[m.group(1)], text)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["shell"]:
        print("\n".join(f"{k}={shlex.quote(v)}" for k, v in VALUES.items()))
    elif len(args) == 1 and args[0] in VALUES:
        print(VALUES[args[0]])
    else:
        sys.exit(__doc__)

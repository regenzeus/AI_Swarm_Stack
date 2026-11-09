#!/usr/bin/env python3
"""This deployment's hosts, paths, accounts and features, as its deployments/<name>/deployment.env sets them (PLT-33, DEC-45).

    import deployment as DEPLOY; DEPLOY.NAS_HOST     in the host-side Python of ops/; DEPLOY.has("home") for a feature
    python3 ops/deployment.py CODE_DIR               one value (the Makefile)
    eval "$(python3 ops/deployment.py shell)"        every value as a shell variable (the scripts of ops/ and smoke/)
    python3 ops/deployment.py file                   the file compose is given as its second --env-file
    python3 ops/deployment.py need home || exit 0    a script of a feature: says "not configured" and stops when it is off
    python3 ops/deployment.py timers                 the timers of ops/systemd whose feature is on

Which deployment: $AISTACK_DEPLOYMENT, else the first line of ~/.config/aistack/deployment, else home. A name is a folder of
deployments/; a path is a folder anywhere (a real work deployment's, kept off the repository). A variable of the same name
in the environment wins over the file. Containers do not import this: compose reads the same file."""
import os
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Every feature a deployment may switch on (docs/PLATFORM.md §3). core is always on and is not listed in FEATURES.
KNOWN = {
    "builder": "the builder sandbox, OpenCode, the code graph, the CI runner and their package proxies",
    "mission-control": "the app and the Hermes dashboard",
    "memory": "Hindsight, qmd and the memory agent",
    "home": "the NAS (backup, the restore drill, the skills mirror), Home Assistant and the router",
    "phone": "the AI phone service",
    "mail": "the mail connector, the postmaster and the inbox digest",
    "voice": "the NAS voice services",
    "telegram": "messages to Telegram",
    "tailnet": "the tailnet addresses",
    "web": "the scout, the page reader, the browser, the price watch and the Topic Desk",
    "publish": "the public GitHub snapshot",
    "offsite": "the off-site copy to OneDrive",
    "windows-desk": "the Windows desk (DEC-43)",
    "windows-worker": "the Windows worker (docs/PLATFORM.md §6)",
}


def chosen(env=os.environ, home=None):
    """The folder of the deployment this machine runs."""
    name = str(env.get("AISTACK_DEPLOYMENT") or "").strip()
    if not name:
        f = Path(home or Path.home()) / ".config" / "aistack" / "deployment"
        lines = f.read_text(encoding="utf-8").split() if f.is_file() else []
        name = lines[0] if lines else "home"
    folder = Path(name).expanduser() if "/" in name else ROOT / "deployments" / name
    if not (folder / "deployment.env").is_file():
        raise SystemExit(f"deployment {name!r}: {folder}/deployment.env does not exist (docs/PLATFORM.md §2)")
    return folder


def load(path=None, env=os.environ):
    """-> {name: value} of the file, in its order. ${NAME} names a line above, as in a shell and in compose."""
    values = {}
    for line in Path(path or FILE).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and not line.startswith("#"):
            values[name] = env[name] if name in env else re.sub(r"\$\{(\w+)\}", lambda m: values[m.group(1)], value)
    return values


def features(values):
    """The features a deployment's values switch on, core included; an unknown name stops it, with the known ones."""
    named = [f for f in re.split(r"[\s,]+", values.get("FEATURES", "")) if f]
    odd = sorted(set(named) - set(KNOWN))
    if odd:
        raise SystemExit(f"FEATURES names {', '.join(odd)}, which no part of the stack is (known: {', '.join(sorted(KNOWN))})")
    return {"core", *named}


def unit_feature(path):
    """The feature a unit of ops/systemd belongs to, from its "# feature: <name>" line; core without one."""
    m = re.search(r"^# feature: ([a-z-]+)\s*$", Path(path).read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "core"


FOLDER = chosen()
FILE = FOLDER / "deployment.env"
VALUES = load()
globals().update(VALUES)
ON = features(VALUES)                       # the features switched on, core included (FEATURES is the line of the file)


def has(feature):
    if feature != "core" and feature not in KNOWN:
        raise ValueError(f"no feature {feature!r} (known: {', '.join(sorted(KNOWN))})")
    return feature in ON


def timers(root=ROOT):
    """The timers of ops/systemd whose feature this deployment switches on."""
    return sorted(t.name for t in (root / "ops" / "systemd").glob("*.timer") if unit_feature(t) in ON)


# The values a feature needs when it is on (compose takes them as optional, so a deployment without the feature needs
# none: a work site, 9 Nov 2026, had to write "off.invalid" for every home host). A host ending in .invalid counts as none.
NEEDS = {"home": ("NAS_HOST", "HA_URL", "ROUTER_URL"), "phone": ("PHONE_HOST",), "tailnet": ("PC_TAILNET_HOST",)}


def missing(values=None):
    """-> what the switched-on features need and the deployment file leaves empty, one line each."""
    v = VALUES if values is None else values
    on = features(v)
    need = [(f, n) for f, names in NEEDS.items() if f in on for n in names]
    if v.get("FORGE", "forgejo") == "forgejo" and "builder" in on:
        need += [("FORGE=forgejo", "FORGEJO_URL"), ("FORGE=forgejo", "FORGEJO_OWNER")]
    if v.get("FORGE") == "bitbucket-dc":
        need += [("FORGE=bitbucket-dc", "FORGE_URL")]
    empty = lambda x: not str(x or "").strip() or str(x).strip().endswith(".invalid")
    return [f"{n} is empty, and {f} needs it" for f, n in need if empty(v.get(n))]


def fill(text, values=None):
    """A file that names values as {{NAME}} -> with the values in it (the app's tools.json; app.js does the same)."""
    return re.sub(r"\{\{(\w+)\}\}", lambda m: (VALUES if values is None else values)[m.group(1)], text)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["shell"]:
        print("\n".join(f"{k}={shlex.quote(v)}" for k, v in VALUES.items()))
    elif args == ["file"]:
        print(FILE)
    elif args == ["check"]:                      # make up: a switched-on feature with an empty value stops here, not in compose
        bad = missing()
        print("\n".join(bad) or f"   the deployment {VALUES.get('DEPLOYMENT') or FOLDER.name} has every value its features need")
        sys.exit(1 if bad else 0)
    elif args == ["timers"]:
        print("\n".join(timers()))
    elif len(args) == 2 and args[0] == "need":
        if not has(args[1]):
            print(f"not configured: the feature {args[1]} is off in the deployment {VALUES.get('DEPLOYMENT') or FOLDER.name}")
            sys.exit(1)
    elif len(args) == 1 and args[0] in VALUES:
        print(VALUES[args[0]])
    else:
        sys.exit(__doc__)

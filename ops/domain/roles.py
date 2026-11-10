"""Roles (GEN-27, docs/AI-STACK.md): a question for people names a role, the deployment maps each role to people, and a
decision from anyone outside the role is refused.

The map is a YAML file: {roles: {<role>: [<person>, ...]}, default: [<person>, ...]}. A role the file does not name
goes to the default people; with no file at all every role is the owner's (home: one person decides everything). A
work deployment keeps its file in its own deployment folder (AISTACK_ROLES), so no person's name is ever in git.

    people(role)       -> [person, ...]   who may decide a gate of this role
    may(role, who)     -> bool
"""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OWNER = "owner"


def path():
    return Path(os.environ.get("AISTACK_ROLES") or ROOT / "config/roles.yaml")


def load(p=None):
    p = Path(p or path())
    try:
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except OSError:
        d = {}
    roles = {str(k): [str(x) for x in v or []] for k, v in (d.get("roles") or {}).items()}
    return roles, [str(x) for x in d.get("default") or [OWNER]]


def people(role, p=None):
    roles, default = load(p)
    return roles.get(str(role)) or default


def may(role, who, p=None):
    return str(who) in people(role, p)

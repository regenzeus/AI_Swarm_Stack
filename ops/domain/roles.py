"""Roles (GEN-27, ASK-04, docs/AI-STACK.md): a question for people names a role, the deployment maps each role to people,
and a decision from anyone outside the role is refused.

The map is a YAML file:
    owner: [<login>, ...]                     who "owner" is (optional; see below)
    default: [<person>, ...]                  the people of a role the file does not name
    roles: {<role>: [<person>, ...]}          or {<role>: {people: [...], escalate: [<role or person>, ...]}}
A person is a sign-in login (the app's identity header, never the page's word). Which file: $AISTACK_ROLES, else the
running deployment's roles.yaml (deployments/<name>/roles.yaml, review 10 Nov O8: it was never read), else
config/roles.yaml. With no file every role is the owner's (home: one person decides everything). A work deployment keeps
its file in its own deployment folder, so no person's name is ever in git.

"owner" is a word, not a login. When the file names the owner's logins, only those are the owner. At home (no
deployment file) the owner is whoever signed in through the app's gate: the person must still be named, so an answer
without a person is refused (review 10 Nov O8: "owner" meant anyone, and a missing person became the owner). A
deployment's file that does not name the owner's logins makes "owner" nobody's sign-in.

    people(role)          -> [person, ...]   who may decide a gate of this role
    holds(role, person)   -> bool            whether this signed-in person holds the role
    may(role, who)        -> bool            named for the role, or holds it
    escalation(role)      -> [role or person, ...] who a gate goes to when its deadline passes, the owner last
"""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OWNER = "owner"


def path():
    if os.environ.get("AISTACK_ROLES"):
        return Path(os.environ["AISTACK_ROLES"])
    try:
        import deployment as DEPLOY
        mine = DEPLOY.chosen() / "roles.yaml"
        if mine.is_file():
            return mine
    except (ImportError, SystemExit, OSError):
        pass
    return ROOT / "config/roles.yaml"


def _doc(p=None):
    p = Path(p or path())
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


def _people_of(v):
    return [str(x) for x in ((v or {}).get("people") if isinstance(v, dict) else v) or []]


def load(p=None):
    d = _doc(p)
    roles = {str(k): _people_of(v) for k, v in (d.get("roles") or {}).items()}
    return roles, [str(x) for x in d.get("default") or [OWNER]]


def people(role, p=None):
    roles, default = load(p)
    return roles.get(str(role)) or default


def owners(p=None):
    """The owner's logins when the file names them; [] when it does not (home: the owner is who signed in)."""
    return [str(x) for x in _doc(p).get("owner") or []]


def holds(role, person, p=None):
    """-> True when this person, as the sign-in names them, holds the role. Nobody holds a role without a name."""
    person = str(person or "").strip()
    if not person or person == OWNER:                 # the page's word "owner" is no sign-in
        return False
    ps = people(role or OWNER, p)
    if person in ps:
        return True
    if OWNER in ps:
        own = owners(p)
        return person in own if own else home(p)
    return False


def home(p=None):
    """One person decides everything: no roles file of a deployment, only the repository's generic one (or none). A
    deployment's own file that does not name the owner's logins makes "owner" no one's sign-in."""
    p = Path(p or path())
    return not p.is_file() or p.resolve() == (ROOT / "config/roles.yaml").resolve()


def may(role, who, p=None):
    """A person the file names for the role, or one who holds it by sign-in (holds). The records' gate hook asks this with
    the person an Ask's answer recorded from the sign-in (ops/domain/records.py check_transition)."""
    return str(who) in people(role, p) or holds(role, who, p)


def escalation(role, p=None):
    """The order a gate of this role goes to when nobody answered by its deadline: the file's escalate list, then the
    owner."""
    v = (_doc(p).get("roles") or {}).get(str(role))
    order = [str(x) for x in (v.get("escalate") or [])] if isinstance(v, dict) else []
    return [x for x in order if x != str(role)] + ([OWNER] if OWNER not in order and str(role) != OWNER else [])

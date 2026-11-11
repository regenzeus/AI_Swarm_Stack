"""A change on the forge (GEN-26, docs/AI-STACK.md): it starts from the base ref its workflow names (a tag or a branch),
its branch ai/<item>-<slug> is pushed through FORGE_PUSH, it opens a draft pull request into the workflow's target
branch, and the pull request's comments from others are handed on to its run, as a tracker's are.

    start(clone, base, branch)                 a branch at the base ref, in the change's clone
    base_commit(clone, base)                   the commit of the base ref (a tag, else the origin's branch), nothing checked out
    publish(clone, branch, push, forge, origin, target, title, body, run, key)   push and open the draft; watched from then on
    poll_prs(forge, hand=None)                 each watched pull request's new comments from others -> events for its run

The stack never merges: a change leaves as a draft pull request, which people review and merge on the forge. With
FORGE_PUSH it is pushed and opened at once, without a shadow step (the owner's decision of 10 Nov 2026, DEC-54): a draft
changes nothing people use until they merge it. Its run is the item's, so a reviewer's comment reaches the run through
the run register's routing (ops/runreg.py) as a tracker comment does; the key is <tracker>/<item key>.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import statefile as SF  # noqa: E402

PREFIX = "ai/"


def _git(clone, *args):
    """git in the change's clone through the runner's one git (ops/builds.py): the clone is the builder's workbench, which
    the sandbox writes, so hooks and fsmonitor stay off and a rigged clone is refused (SEC-21), and a push passes the
    never-in-git guard (SEC-22). Review 10 Nov (RUNNER2-R1): this ran plain git, so a hook the sandbox planted ran here."""
    import builds as B
    try:
        return B.git(clone, *args)
    except RuntimeError as e:
        raise ValueError(f"{e}") from e


def branch_name(key, title):
    slug = re.sub(r"[^a-z0-9]+", "-", str(title).lower()).strip("-")[:40].strip("-") or "change"   # cap: id, a branch name stays short; the title is in the pull request
    return f"{PREFIX}{re.sub(r'[^A-Za-z0-9._-]+', '-', str(key))}-{slug}"


def base_commit(clone, base):
    """The base ref's commit, fetched from the clone's origin first: the tag of that name, else the origin's branch."""
    _git(clone, "fetch", "--quiet", "--tags", "origin")
    return _git(clone, "rev-parse", f"refs/tags/{base}^{{commit}}" if _git(clone, "tag", "--list", base) else f"origin/{base}")


def start(clone, base, branch):
    """The change's branch, at the template's base ref (a tag or a branch), fetched from the clone's origin first."""
    _git(clone, "fetch", "--quiet", "--tags", "origin")
    ref = base if _git(clone, "tag", "--list", base) else f"origin/{base}"
    _git(clone, "checkout", "--quiet", "-B", branch, ref)
    return _git(clone, "rev-parse", "HEAD")


def prs_path():
    return Path(os.environ.get("AISTACK_TRACKER_STATE") or "/srv/ai/state/trackers") / "prs.json"


def _prs():
    try:
        return json.loads(prs_path().read_text())
    except (OSError, ValueError):
        return []


def _save(prs):
    SF.save(prs_path(), prs, indent=1)              # whole or not at all


def publish(clone, branch, push, forge, origin, target, title, body, run, key):
    """Pushes the branch (FORGE_PUSH, GEN-18) and opens a draft pull request into the target branch; from then on its
    comments are handed on to the run."""
    _git(clone, "push", "--quiet", "-f", push, f"{branch}:refs/heads/{branch}")
    of = getattr(forge, "repo_of", None)
    fork = of(push) if of and of(push) and of(push) != of(origin) else None   # pushed to a fork: the pull request says where from
    pr = forge.open_pr(origin, branch, target, title, body, draft=True, **({"from_repo": fork} if fork else {}))
    if pr:
        prs = [p for p in _prs() if p["run"] != run]
        prs.append({"run": run, "key": key, "origin": origin, "number": pr["number"], "url": pr.get("url", ""), "seen": []})
        _save(prs)
    return pr


def poll_prs(forge, me="ai-stack", hand=None):
    """Each watched pull request's new comments from someone else, as one event {run, key, ref, comments, said} for its
    run, as a tracker comment is (the stack's own by its author or its write mark, trackers.own); each comment is handed
    on once: hand(events) takes them before they count as seen. Their source is the pull request (pr-comment:<pr>/<id>),
    so only a wait on: pr or on: any takes them (ops/runreg.py, WFL-32)."""
    from domain import trackers as TR
    prs, events = _prs(), []
    for p in prs:
        new = [c for c in forge.comments(p["origin"], p["number"]) if not TR.own(c, me) and str(c["id"]) not in p["seen"]]
        if not new:
            continue
        refs = [f"pr-comment:{p['number']}/{c['id']}" for c in new]
        events.append({"run": p["run"], "key": p["key"], "ref": f"pr:{p['number']}", "comments": refs,
                       "said": [TR.said_of(r, c) for r, c in zip(refs, new)]})
        p["seen"] += [str(c["id"]) for c in new]
    if hand:
        hand(events)
    _save(prs)
    return events

"""A template's change on the forge (GEN-26, docs/AI-STACK.md §8): it starts from the base ref its template names (a tag
or a branch), its branch ai/<item>-<slug> is pushed through FORGE_PUSH, it opens a draft pull request into the
template's target branch, and the pull request's comments signal its run, through the same poller as the trackers.

    start(clone, base, branch)                 a branch at the base ref, in the change's clone
    publish(clone, branch, push, forge, origin, target, title, body, run, key)   push and open the draft; watched from then on
    poll_prs(client, forge)                    each watched pull request's new comments, from others, signal its run (async)
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import textcap as TC  # noqa: E402

PREFIX = "ai/"


def _git(clone, *args):
    p = subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True, timeout=300)
    if p.returncode:
        raise ValueError(f"git {args[0]}: {TC.cut((p.stderr or p.stdout).strip(), 300)}")   # cap: preview
    return p.stdout.strip()


def branch_name(key, title):
    slug = re.sub(r"[^a-z0-9]+", "-", str(title).lower()).strip("-")[:40].strip("-") or "change"   # cap: id, a branch name stays short; the title is in the pull request
    return f"{PREFIX}{re.sub(r'[^A-Za-z0-9._-]+', '-', str(key))}-{slug}"


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
    p = prs_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(prs, indent=1))
    tmp.replace(p)


def publish(clone, branch, push, forge, origin, target, title, body, run, key):
    """Pushes the branch (FORGE_PUSH, GEN-18) and opens a draft pull request into the target branch; from then on its
    comments signal the run."""
    _git(clone, "push", "--quiet", "-f", push, f"{branch}:refs/heads/{branch}")
    pr = forge.open_pr(origin, branch, target, title, body, draft=True)
    if pr:
        prs = [p for p in _prs() if p["run"] != run]
        prs.append({"run": run, "key": key, "origin": origin, "number": pr["number"], "url": pr.get("url", ""), "seen": []})
        _save(prs)
    return pr


async def poll_prs(client, forge, me="ai-stack"):
    """Each watched pull request's new comments from someone else signal its run's item, as a tracker comment does."""
    from engine import runner as R
    prs, done = _prs(), []
    for p in prs:
        new = [c for c in forge.comments(p["origin"], p["number"]) if c["author"] != me and str(c["id"]) not in p["seen"]]
        if not new:
            continue
        await client.get_workflow_handle(p["run"]).signal(R.GraphRun.event, args=[p["key"], {"ref": f"pr:{p['number']}", "comments": [f"pr-comment:{p['number']}/{c['id']}" for c in new]}])
        p["seen"] += [str(c["id"]) for c in new]
        done.append((p["run"], len(new)))
    _save(prs)
    return done

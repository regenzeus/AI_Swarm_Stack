#!/usr/bin/env python3
"""The never-in-git guard (SEC-22): a deployment's private list of what must never reach git, checked on every commit and
every push of the stack's repositories. The list is in no repository: /srv/ai/private/never-in-git.txt (one regular
expression per line, matched without regard to case; # starts a comment), or NEVER_IN_GIT. The guard never prints a
match, only which line of the list it was.

    python3 ops/termguard.py install [repo]          the repository (and its worktrees) runs ops/git-hooks on commit and push
    python3 ops/termguard.py staged                  pre-commit: the staged changes and the new files' names
    python3 ops/termguard.py message <file>          commit-msg: the message
    python3 ops/termguard.py pushed                  pre-push: every commit the push sends (git's lines on stdin)
    python3 ops/termguard.py range <repo> <rev...>   every commit reachable from the revisions and on no remote

Where hooks cannot run (the runner's git in the builder's clones runs no hook, SEC-21), ops/builds.py calls refused()
before each push. The public snapshot has its own scan (ops/publish.py). Without a list the guard lets everything pass."""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIST = Path(os.environ.get("NEVER_IN_GIT", "/srv/ai/private/never-in-git.txt"))
HOOKS = ROOT / "ops" / "git-hooks"
ZERO = "0" * 40


def patterns(path=None):
    """[(line number, compiled pattern)] of the private list; none when there is no list."""
    p = Path(path or LIST)
    if not p.is_file():
        return []
    out = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip() and not line.lstrip().startswith("#"):
            out.append((n, re.compile(line.strip(), re.I)))
    return out


def found(text, pats=None):
    """-> the list's line numbers that match the text (never the matches themselves)."""
    pats = patterns() if pats is None else pats
    return sorted({n for n, rx in pats if rx.search(text or "")})


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, errors="replace").stdout


def added(patch):
    """The added lines and the file names of a patch (a removed line is no leak)."""
    keep = []
    for line in patch.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            keep.append(line[4:])
        elif line.startswith("+") or line.startswith("rename to ") or line.startswith("diff --git "):
            keep.append(line)
    return "\n".join(keep)


def commits_text(repo, revs):
    """Every message and added line of the commits reachable from revs and on no remote-tracking ref."""
    if not revs:
        return ""
    return git(repo, "log", "-p", "--no-color", "--no-ext-diff", "--format=%n%B", *revs, "--not", "--remotes")


def refused(repo, revs, pats=None):
    """-> why a push of these revisions must not happen, or "" (ops/builds.py, before every push of the runner's git)."""
    pats = patterns() if pats is None else pats
    if not pats:
        return ""
    text = commits_text(repo, revs)
    patch_line = ("+", "-", " ", "@@", "diff ", "index ", "new file", "deleted file", "similarity", "rename ", "old mode", "new mode", "Binary")
    messages = "\n".join(ln for ln in text.splitlines() if not ln.startswith(patch_line))
    lines = found(added(text) + "\n" + messages, pats)
    return (f"refused: a commit holds what the deployment's never-in-git list forbids (its line {', '.join(map(str, lines))}); "
            f"rewrite the commit before it leaves this machine") if lines else ""


def push_revs(args):
    """The local revisions a `git push` argument list sends (its refspecs' sources; deletes send nothing)."""
    out, rest = [], [a for a in args if not a.startswith("-")]
    if "--delete" in args or "-d" in args:
        return []
    for spec in rest[1:]:                               # the first is the remote
        src = spec.lstrip("+").split(":", 1)[0]
        if src:
            out.append(src)
    return out


def hook_staged(repo="."):
    pats = patterns()
    if not pats:
        return 0
    text = added(git(repo, "diff", "--cached", "--no-color", "--no-ext-diff"))
    lines = found(text, pats)
    if lines:
        print(f"commit refused: a staged change holds what the never-in-git list forbids (its line {', '.join(map(str, lines))}; "
              f"{LIST})", file=sys.stderr)
        return 1
    return 0


def hook_message(path):
    lines = found(Path(path).read_text(encoding="utf-8", errors="replace"))
    if lines:
        print(f"commit refused: the message holds what the never-in-git list forbids (its line {', '.join(map(str, lines))})", file=sys.stderr)
        return 1
    return 0


def hook_pushed(repo=".", stdin=None):
    """pre-push: git gives "<local ref> <local sha> <remote ref> <remote sha>" per ref."""
    pats = patterns()
    if not pats:
        return 0
    bad = []
    for line in (stdin or sys.stdin).read().splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[1] == ZERO:
            continue
        revs = [parts[1]] if parts[3] == ZERO else [parts[1], f"^{parts[3]}"]
        why = refused(repo, revs, pats)
        if why:
            bad.append(f"{parts[0]}: {why}")
    if bad:
        print("push refused:\n" + "\n".join(bad), file=sys.stderr)
        return 1
    return 0


def install(repo=None):
    """The repository (its worktrees share its configuration) runs ops/git-hooks; deploy.py calls this on every deploy."""
    repo = Path(repo or ROOT)
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", str(HOOKS)], check=True)
    return str(HOOKS)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["install"]:
        print("hooks:", install(a[1] if len(a) > 1 else None), "| list:", LIST if LIST.is_file() else "none (everything passes)")
    elif a == ["staged"]:
        sys.exit(hook_staged())
    elif a[:1] == ["message"] and len(a) == 2:
        sys.exit(hook_message(a[1]))
    elif a == ["pushed"]:
        sys.exit(hook_pushed())
    elif a[:1] == ["range"] and len(a) >= 3:
        why = refused(a[1], a[2:])
        print(why or "   nothing the list forbids")
        sys.exit(1 if why else 0)
    else:
        sys.exit(__doc__)

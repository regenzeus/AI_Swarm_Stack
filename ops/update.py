#!/usr/bin/env python3
"""Updates from signed-off release tags (GEN-16, DEC-45, docs/PLATFORM.md §7). A deployment other than home takes only a
release tag the owner signed, never main and never a bare commit:

    python3 ops/update.py check <tag>      the tag is a release tag, annotated, and signed by a key the deployment allows
    python3 ops/update.py apply <tag>      check it, run the whole check on its tree, then move the stack to it and deploy

The owner's sign-off is an ssh signature on the tag (git tag -s, with gpg.format=ssh): `make release TAG=vYYYY.MM.DD` in
the public snapshot's clone, after a publish. The deployment names the keys it accepts in deployments/<name>/allowed_signers
(git's format: "<principal> <key type> <key>"). Home updates by its own landings and has no such file."""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deployment as DEPLOY  # noqa: E402

TAG = re.compile(r"v\d{4}\.\d{2}\.\d{2}(?:\.\d+)?")


def git(repo, *args, check=True):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=300)
    if check and p.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {(p.stderr or p.stdout).strip()}")
    return p


def check(repo, tag, signers):
    """-> None when the tag may be deployed, else why not."""
    if not TAG.fullmatch(str(tag)):
        return f"{tag!r} is no release tag (vYYYY.MM.DD): a deployment takes only release tags the owner signed, never a branch or a commit"
    if not Path(signers).is_file():
        return f"no allowed signers ({signers}): the deployment names the owner's key it trusts"
    if git(repo, "cat-file", "-t", f"refs/tags/{tag}", check=False).stdout.strip() != "tag":
        return f"{tag} is not an annotated tag, so nobody signed it"
    v = git(repo, "-c", f"gpg.ssh.allowedSignersFile={signers}", "verify-tag", tag, check=False)
    if v.returncode:
        return f"{tag} is not signed by a key this deployment allows: {(v.stderr or v.stdout).strip().splitlines()[-1] if (v.stderr or v.stdout).strip() else 'no signature'}"
    return None


def temporal_with(repo):
    """Moves Temporal when the new commit pins another version (ops/temporal_upgrade.py), on this machine."""
    import temporal_upgrade as TU

    def run(old, new):
        at = lambda c: TU.pinned(git(repo, "show", f"{c}:versions.env", check=False).stdout)   # noqa: E731
        was, will = at(old), at(new)
        if not was or not will or was == will:
            return {"ok": True, "why": "Temporal stays"}
        import deploy as DP
        return TU.run(was, will, TU.table(), **TU.real(repo, DP.COMPOSE))
    return run


def apply(repo, tag, signers, run_checks, deploy, temporal=lambda old, new: {"ok": True}):
    """Check the tag, run the whole check on its tree (run_checks(commit) -> bool), then move the stack to it and deploy
    (deploy(old, new) -> bool). -> what happened."""
    git(repo, "fetch", "-q", "--tags", "origin", check=False)
    why = check(repo, tag, signers)
    if why:
        return f"NOT UPDATED: {why}"
    new = git(repo, "rev-parse", f"{tag}^{{commit}}").stdout.strip()
    old = git(repo, "rev-parse", "HEAD").stdout.strip()
    if old == new:
        return f"already at {tag}"
    if not run_checks(new):
        return f"NOT UPDATED: the checks failed on {tag}; the stack stays at {old[:8]}"
    tu = temporal(old, new)                               # GEN-39: Temporal steps through each minor version first
    if not tu["ok"]:
        return f"NOT UPDATED: {tu['why']}; the stack stays at {old[:8]}"
    git(repo, "checkout", "-q", "--detach", new)
    if not deploy(old, new):
        git(repo, "checkout", "-q", "--detach", old)
        deploy(new, old)
        return f"DEPLOY FAILED for {tag}: back at {old[:8]}"
    return f"UPDATED to {tag} ({new[:8]})"


def builder_checks(repo):
    """The whole check (ops/check.sh) on a commit's tree, in the builder, as a landing runs it."""
    def run(commit):
        tar = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", commit], capture_output=True, timeout=300).stdout
        p = subprocess.run(["docker", "exec", "-i", "aistack-builder-1", "sh", "-c",
                            "rm -rf /tmp/upd && mkdir -p /tmp/upd && tar -xf - -C /tmp/upd && cd /tmp/upd && PATH=/opt/tools/bin:$PATH "
                            "PYTEST=/opt/tools/bin/pytest bash ops/check.sh"], input=tar, capture_output=True, timeout=3600)
        out = p.stdout.decode(errors="replace")
        print(out[-3000:], flush=True)                    # cap: list (the end of the check's output: its summary)
        return p.returncode == 0 and "ALL CHECKS PASSED" in out
    return run


def deploy_with(repo):
    def run(old, new):
        return subprocess.run([sys.executable, "ops/deploy.py", old, new], cwd=repo, timeout=7200).returncode == 0
    return run


if __name__ == "__main__":
    a = sys.argv[1:]
    signers = DEPLOY.FOLDER / "allowed_signers"
    repo = Path(DEPLOY.VALUES.get("STACK_DIR") or DEPLOY.ROOT)
    if len(a) == 2 and a[0] == "check":
        why = check(repo, a[1], signers)
        print(why or f"{a[1]} is signed off")
        sys.exit(1 if why else 0)
    if len(a) == 2 and a[0] == "apply":
        if DEPLOY.FOLDER.name == "home":
            sys.exit("home updates by its own landings (ops/land.sh), not from tags")
        said = apply(repo, a[1], signers, builder_checks(repo), deploy_with(repo), temporal_with(repo))
        print(said)
        sys.exit(0 if said.startswith(("UPDATED", "already")) else 1)
    sys.exit(__doc__)

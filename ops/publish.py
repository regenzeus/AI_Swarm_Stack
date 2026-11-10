#!/usr/bin/env python3
"""The public snapshot (SEC-19): the committed stack with every personal identifier replaced, pushed to the public
GitHub repository only when nothing personal is left and its own tests pass.

    python3 ops/publish.py check    build it in /srv/ai/publish/tree, scan it, run its tests; push nothing
    python3 ops/publish.py push     the same, then commit it on top of the public repository and push (make publish)

A snapshot without history: the private history carries the owner's e-mail on every commit. The identifiers live
outside every repository, in /srv/ai/private/publish-map.tsv (term, tab, public replacement), so the snapshot names
none of them. Fail-closed: a term left in any case, an e-mail address, a LAN or Tailscale address, a tailnet name, a
key or token outside the allowed placeholders, or a failing test stops it. Each run is logged in
/srv/ai/state/publish.jsonl."""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP = Path("/srv/ai/private/publish-map.tsv")
WORK = Path("/srv/ai/publish")
LOG = Path("/srv/ai/state/publish.jsonl")
REMOTE = "git@github-publish:regenzeus/AI_Swarm_Stack.git"     # a deploy key for this one repository (~/.ssh/config)
AUTHOR = ("regenzeus", "regenzeus@users.noreply.github.com")
BUILDER = "aistack-builder-1"                                   # the snapshot's tests run in the builder sandbox

# Left out of the snapshot, each with its reason; an example names the values a new install needs.
EXCLUDE = {
    "secrets/secrets.enc.yaml": "the owner's credentials: encrypted, but ciphertext is not published",
    "secrets/agent-keys.enc.yaml": "the agents' virtual keys: encrypted, but ciphertext is not published",
}
# Real runs' records hold real answers and details of the owner's setup. The ones a requirement cites as its evidence stay.
LEFT_OUT = re.compile(r"^eval/results/(?!20261031-140852-|20261031-152501-|20261101-020317-)")
# Addresses that are placeholders or test fixtures, not anyone's mailbox. A new one stops the publish until it is here.
ALLOW_EMAILS = {"owner@example.com", "test@example.com", "test@example.org", "anna@example.com", "noreply@anthropic.com",
                "builder@ai-stack.local", "x@spam.ru", "service@paypal.de", "secret@github.com", "newsletter@x.com",
                "n@shop.de", "journeys@stack.local", "trials@stack.local", "a@example.com", "friend@example.org",
                "news@u.example", "a@shop.example", "b@bank.example", AUTHOR[1]}   # the journeys' and trials' own identities
# The one place a binary file may be (a screenshot for the public page): it cannot be scanned as text, so it comes as it is,
# only as an image, without metadata, and small. docs/PUBLISHING.md says how such a picture is made. Any other binary stops.
ASSETS = "docs/screenshots/"
ASSET_TYPES = {".jpg": b"\xff\xd8\xff", ".png": b"\x89PNG\r\n\x1a\n"}
# limit: refuses, an image over this stops a publish, with its name (SEC-19)
ASSET_MAX = 1_000_000
# Words that hold a private term by chance; the scan matches terms inside words, so each one is named here.
ALLOW_WORDS = {"mmarco",                                         # the mMARCO dataset in a reranker model's name
               "metasearch", "phonetaskhtml"}                    # words that hold a short private term by chance (9 Nov 2026)
# Fake tokens in tests (the redaction tests need something token-shaped to redact).
ALLOW_TOKENS = {"123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawabc", "sk-abcdefghijklmnopqrstuvwx"}
CHECKS = [
    ("e-mail address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), lambda m: m.lower() in ALLOW_EMAILS),
    ("LAN address", re.compile(r"(?<![\d.])192\.168\.\d{1,3}\.\d{1,3}(?![\d.]\d)"),     # no \b: "\n192.168..." in JSON
     lambda m: re.fullmatch(r"192\.168\.(0\.0|1\.\d{1,3})", m)),
    ("Tailscale address", re.compile(r"(?<![\d.])100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}(?![\d.]\d)"),
     lambda m: re.fullmatch(r"100\.64\.0\.\d{1,3}", m)),
    ("tailnet name", re.compile(r"\b[A-Za-z0-9-]+\.ts\.net\b"), lambda m: m.split(".")[-3].lower() in ("example", "pc")),
    ("token", re.compile(r"\b(sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|xox[abpr]-[A-Za-z0-9-]{10,}"
                         r"|AKIA[0-9A-Z]{16}|\d{8,10}:AA[0-9A-Za-z_-]{30,}|AIza[0-9A-Za-z_-]{30,})"), lambda m: m in ALLOW_TOKENS),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|AGE-SECRET-KEY-1[0-9A-Z]{20,}"), lambda m: False),
    ("age recipient", re.compile(r"\bage1[0-9a-z]{50,}\b"), lambda m: False),
    ("sops value", re.compile(r"ENC[\[]AES256_GCM,"), lambda m: False),
]


def load_map(path=None):
    """The private map -> [(term, replacement)] in file order; comments and blank lines skipped."""
    rows = []
    for ln in (path or MAP).read_text(encoding="utf-8").splitlines():
        if ln.strip() and not ln.startswith("#"):
            term, _, rep = ln.partition("\t")
            if term and _:
                rows.append((term, rep))
    return rows


def _pattern(term, flags=0):
    """A term that starts or ends with a letter or digit matches only as a whole word there; an escape such as \\n
    in a JSON string ("\\nthe owner") counts as a word break."""
    return re.compile((r"(?:(?<![A-Za-z0-9])|(?<=\\[ntr]))" if term[0].isalnum() else "") + re.escape(term)
                      + ("(?![A-Za-z0-9])" if term[-1].isalnum() else ""), flags)


# a sentence starts here: start of a line (after a list mark, a heading or a quote), after . ! ? or a table bar,
# or at the start of a quoted string, double or single (a tool description that opens with the owner's name; a
# single quote after a letter is an apostrophe, not a string)
_START = re.compile(r'(?:^\s*(?:[-*>]\s+|#+\s+|\d+\.\s+)?|[.!?]\s+|\|\s*|"\s*|(?<![A-Za-z0-9])\'\s*)$')


def redact(text, terms):
    """Every term replaced in order. A capitalised term at the start of a sentence gets a capitalised replacement
    ("The owner approves" -> "The owner approves"); a lowercase one keeps its case, as code compares it ("owner@test")."""
    for term, rep in terms:
        def sub(m, rep=rep):
            line = m.string[m.string.rfind("\n", 0, m.start()) + 1:m.start()]
            up = m.group(0)[:1].isupper() and rep[:1].islower() and _START.search(line)
            return rep[:1].upper() + rep[1:] if up else rep
        text = _pattern(term).sub(sub, text)
    return text


def reversion_prompts(before, files):
    """prompts/replays.json records each prompt section by the hash of its text; the snapshot's texts differ from the
    private ones only by their placeholders, so each recorded hash moves to the public text's (MEM-11's gate holds)."""
    import prompts as PR
    rec = files.get("prompts/replays.json")
    if rec is None:
        return
    for path, text in before.items():
        if path.startswith("prompts/") and path.endswith(".md") and path in files:
            old, new = PR.parse(text), PR.parse(files[path])
            for name, body in old.items():
                if name in new and PR.sha(body) != PR.sha(new[name]):
                    rec = rec.replace(f'"{PR.sha(body)}"', f'"{PR.sha(new[name])}"')
    files["prompts/replays.json"] = rec


def scan(files, terms):
    """{path: text} -> problems "path:line: what" (the private term itself is never printed)."""
    out = []
    # stricter than the replacement: a term anywhere, also inside a word (a device named after the owner), unless the
    # word is in ALLOW_WORDS
    pats = [(re.compile(re.escape(t), re.IGNORECASE), f"private term #{i + 1} of the map") for i, (t, _) in enumerate(terms)]

    def hit(p, line):
        return any(re.findall(r"[A-Za-z0-9]*$", line[:m.start()])[0].lower() + m.group(0).lower()
                   + re.match(r"[A-Za-z0-9]*", line[m.end():]).group(0).lower() not in ALLOW_WORDS for m in p.finditer(line))
    for path, text in sorted(files.items()):
        if any(hit(p, path) for p, _ in pats):
            out.append(f"{path}: the file name holds a private term")
        for n, line in enumerate(text.splitlines(), 1):
            line = re.sub(r"\\+(?=[^A-Za-z0-9])", "", line)   # a term written as a regular expression is still the term (FND-124)
            for p, what in pats:
                if hit(p, line):
                    out.append(f"{path}:{n}: {what}")
            for what, rx, allowed in CHECKS:
                for m in rx.finditer(line):
                    if not allowed(m.group(0)):
                        out.append(f"{path}:{n}: {what} {m.group(0)[:4]}…")
    return out


def asset_problems(assets):
    """{path: bytes} -> problems: only an image of the allowed kinds, nothing hidden in it (a camera's or an editor's metadata), small."""
    out = []
    for path, data in sorted(assets.items()):
        magic = ASSET_TYPES.get(Path(path).suffix.lower())
        if not magic or not data.startswith(magic):
            out.append(f"{path}: not an image of an allowed kind")
        elif len(data) > ASSET_MAX:
            out.append(f"{path}: {len(data):,} bytes, {ASSET_MAX:,} at most")
        elif any(m in data[:4096] for m in (b"Exif", b"xmpmeta", b"tEXt", b"iTXt", b"eXIf", b"Photoshop")):   # cap: parse: metadata sits at the start of an image
            out.append(f"{path}: holds metadata")
    return out


def example(enc_text, source):
    """A sops file -> the same names with empty values (the names a new install fills in; no value, no ciphertext)."""
    names = [m.group(1) for m in re.finditer(r"^([A-Za-z_][A-Za-z0-9_]*):", enc_text, re.M) if m.group(1) != "sops"]
    return (f"# The values a new install needs, by name only. Fill them in, then encrypt the file with your own age key:\n"
            f"#   sops --encrypt secrets/{source.replace('.enc.yaml', '.example.yaml')} > secrets/{source}\n"
            f"# (the private repository keeps them in {source}; this snapshot holds no value)\n"
            + "".join(f'{n}: ""\n' for n in names))


def build(head="HEAD", terms=None, archive=None, assets=None):
    """The committed tree at head -> ({path: text} of the public snapshot, the paths git marks executable). The images of
    ASSETS go into `assets`, {path: bytes}; left out when it is not given."""
    terms = load_map() if terms is None else terms
    raw = archive if archive is not None else subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", head],
                                                              check=True, capture_output=True).stdout
    files, executable = {}, set()
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        for m in tar.getmembers():
            if m.isfile() and m.name.startswith(ASSETS) and Path(m.name).suffix.lower() in ASSET_TYPES:
                if assets is not None:
                    assets[m.name] = tar.extractfile(m).read()
            elif m.isfile():
                files[m.name] = tar.extractfile(m).read().decode("utf-8")    # every other tracked file is text; a binary stops it
                if m.mode & 0o111:
                    executable.add(redact(m.name, terms))
    files = {p: t for p, t in files.items() if not LEFT_OUT.match(p)}
    executable = {p for p in executable if not LEFT_OUT.match(p)}
    for path in EXCLUDE:
        if path in files:
            files["secrets/" + Path(path).name.replace(".enc.yaml", ".example.yaml")] = example(files.pop(path), Path(path).name)
    if ".sops.yaml" in files:
        files[".sops.yaml"] = re.sub(r"\bage1[0-9a-z]{50,}\b", '"<your age public key (age-keygen -y key.txt)>"', files[".sops.yaml"])
    before = files
    files = {redact(p, terms): redact(t, terms) for p, t in files.items()}
    reversion_prompts(before, files)
    frozen = files.get("eval/FROZEN.sha256")           # the public bench differs from the private one by its placeholders
    if frozen:
        files["eval/FROZEN.sha256"] = "".join(
            f"{hashlib.sha256(files['eval/' + name].encode()).hexdigest()}  {name}\n" if f"eval/{name}" in files else ln + "\n"
            for ln in frozen.splitlines() if ln.strip() for name in [ln.split()[-1]])
    return files, executable


GENERATED = [(["python3", "ops/req.py", "render"], "requirements/REQUIREMENTS.md"),   # drawn from the files above, so they
             (["python3", "ops/api_doc.py"], "docs/API.md")]                          # are drawn again from the public ones


def write(files, executable, dest, assets=None):
    """The snapshot on disk, its generated documents drawn again from it. -> {path: text} as written."""
    if dest.exists():
        shutil.rmtree(dest)
    for path, data in (assets or {}).items():
        p = dest / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    for path, text in files.items():
        p = dest / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        p.chmod(0o755 if path in executable else 0o644)
    for cmd, out in GENERATED:
        if (dest / cmd[1]).exists():
            subprocess.run(cmd, cwd=dest, check=True, capture_output=True)
            files = {**files, out: (dest / out).read_text(encoding="utf-8")}
    return files


def tests(dest):
    """The snapshot's own test suite in the builder sandbox -> (passed, last lines)."""
    tar = subprocess.run(["tar", "-C", str(dest), "-cf", "-", "."], check=True, capture_output=True).stdout
    r = subprocess.run(["docker", "exec", "-i", "-u", "hermes", BUILDER, "sh", "-c",            # not as root (review SEC-R12)
                        "rm -rf /tmp/pub-hermes && mkdir -p /tmp/pub-hermes && cd /tmp/pub-hermes && tar -xf - && "
                        # QA-27: over 6 workers when the builder has pytest-xdist, as the landing's checks do
                        "PAR=; /opt/tools/bin/pytest -p xdist --version >/dev/null 2>&1 && PAR='-n 6'; "   # limit: paces, 6 test workers
                        "PATH=/opt/tools/bin:$PATH /opt/tools/bin/pytest -q -p no:cacheprovider $PAR tests 2>&1 | tail -15"],
                       input=tar, capture_output=True, timeout=1800)
    lines = r.stdout.decode(errors="replace").strip().splitlines()
    summary = lines[-1] if lines else ""                 # pytest's last line: "585 passed in 160s" or "2 failed, 583 passed ..."
    return bool(re.search(r"\b\d+ passed\b", summary) and not re.search(r"\b(failed|errors?)\b", summary)), lines[-12:]


def record(**row):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps({"ts": int(time.time()), **row}) + "\n")


FRESH_NOTE = ("A fresh history: this snapshot shares no history with the earlier ones, so a pull refuses. A copy that tracked "
              "them moves its branch instead: git fetch origin, then git rebase --onto origin/main <the snapshot it was on> "
              "(or keep a backup branch, reset to origin/main and put its own commits back on top). docs/PUBLISHING.md says more.")


def push(dest, head, fresh=False):
    """Commit the snapshot on top of the public repository's history and push it. -> the public commit or None.
    fresh: the snapshot becomes the whole public history, replacing what was there (only on the owner's word)."""
    repo = WORK / "repo"
    git = lambda *a, **k: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True, **k)
    if fresh and repo.exists():
        shutil.rmtree(repo)
    if not (repo / ".git").exists():
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        git("remote", "add", "origin", REMOTE)
    if not fresh and git("ls-remote", "--heads", "origin", "main").stdout.strip():
        git("fetch", "-q", "origin", "main")
        git("reset", "-q", "--hard", "origin/main")
    for p in repo.iterdir():                             # the snapshot replaces the tree; the public history stays
        if p.name != ".git":
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    shutil.copytree(dest, repo, dirs_exist_ok=True)
    git("add", "-A", "--force")                          # the snapshot is the file list, whatever its .gitignore says (a fresh
                                                         # history, 9 Nov 2026: three files the private repo tracks were left out)
    tracked = set(git("ls-files").stdout.splitlines())    # what git would commit is exactly the snapshot, no file dropped
    want = {str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file()}
    if tracked != want:                                   # (an ignore rule dropped the secrets examples once, 31 Oct 2026)
        raise SystemExit(f"not pushed: git would commit {len(tracked)} files, the snapshot has {len(want)}: "
                         + ", ".join(sorted(want ^ tracked)[:10]))  # cap: top
    if not git("status", "--porcelain").stdout.strip():
        return None
    sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", head], check=True, capture_output=True, text=True).stdout.strip()
    env = {"GIT_AUTHOR_NAME": AUTHOR[0], "GIT_AUTHOR_EMAIL": AUTHOR[1], "GIT_COMMITTER_NAME": AUTHOR[0],
           "GIT_COMMITTER_EMAIL": AUTHOR[1]}
    msg = [f"Snapshot of {time.strftime('%Y-%m-%d')} (private {sha})"]
    if fresh:                                             # a site that tracked the old history must move its branch, not pull
        msg.append(FRESH_NOTE)
    git("commit", "-q", *[x for m in msg for x in ("-m", m)], env={**os.environ, **env})
    git("push", "-q", *(["--force"] if fresh else []), "origin", "main")
    return git("rev-parse", "--short", "HEAD").stdout.strip()


def committed():
    """The commit the snapshot is made of: what is committed, never the working tree."""
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def scan_only(head):
    """The privacy scan alone on one commit, for every landing (ops/land.sh): what would stop the next publish stops here,
    while it is still one change's fault. No map on this machine: nothing to compare with. -> problems."""
    if not MAP.exists():
        return []
    terms, assets = load_map(), {}
    files, _ = build(head, terms, assets=assets)
    return scan({**files, **{p: "" for p in assets}}, terms) + asset_problems(assets)


def main(mode, fresh=False):
    head = committed()
    terms = load_map()
    assets = {}
    files, executable = build(head, terms, assets=assets)
    dest = WORK / "tree"
    files = write(files, executable, dest, assets)
    problems = scan({**files, **{p: "" for p in assets}}, terms) + asset_problems(assets)    # an image: its name, and its kind
    print(f"snapshot of {head[:8]}: {len(files)} files and {len(assets)} images, {len(problems)} problem{'s' if len(problems) != 1 else ''}")
    for p in problems:
        print("  " + p)
    if problems:
        shutil.rmtree(dest)                              # a snapshot with a problem does not stay on disk
        record(mode=mode, head=head, files=len(files), result="stopped", problems=len(problems))
        return 1
    ok, tail = tests(dest)
    print("\n".join("  " + x for x in tail))
    if not ok:
        print("the snapshot's tests fail: nothing pushed")
        record(mode=mode, head=head, files=len(files), result="tests failed")
        return 1
    if mode == "check":
        print(f"clean: {dest} (push it with make publish)")
        record(mode=mode, head=head, files=len(files), result="clean")
        return 0
    public = push(dest, head, fresh)
    print(f"pushed {public} to {REMOTE}" if public else "the public repository already has this snapshot")
    record(mode=mode, head=head, files=len(files), result="pushed" if public else "unchanged", public=public, fresh=fresh)
    return 0


def release(tag):
    """The owner's sign-off of the public snapshot as it stands (GEN-16): an ssh-signed tag on the public repository's
    newest commit, pushed. Signed with the owner's own key (git config gpg.format ssh, user.signingkey): only the owner
    runs this. A work deployment takes this tag and nothing else (ops/update.py)."""
    import update as U
    if not U.TAG.fullmatch(tag):
        return f"{tag!r} is no release tag: vYYYY.MM.DD"
    repo = WORK / "repo"
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True)
    if git("rev-parse", "--verify", "-q", "HEAD").returncode:
        return "there is no public snapshot to release yet: make publish first"
    made = git("tag", "-s", tag, "-m", f"Released by the owner: {tag}")
    if made.returncode:
        return f"the tag was not made (is the owner's signing key set? git config gpg.format ssh; user.signingkey): {made.stderr.strip()}"
    pushed = git("push", REMOTE, f"refs/tags/{tag}")
    return f"released {tag} on {REMOTE}" if not pushed.returncode else f"the tag is made but not pushed: {pushed.stderr.strip()}"


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "release":
        said = release(args[1])
        print(said)
        sys.exit(0 if said.startswith("released") else 1)
    if len(args) == 2 and args[0] == "scan":
        found = scan_only(args[1])
        print("\n".join(found) or "   the privacy scan is clean")
        sys.exit(1 if found else 0)
    if args not in (["check"], ["push"], ["push", "--fresh"]):
        sys.exit(__doc__)
    sys.exit(main(args[0], fresh="--fresh" in args))

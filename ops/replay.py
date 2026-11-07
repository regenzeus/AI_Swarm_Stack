#!/usr/bin/env python3
"""The replay exam (CHG-17, docs/CHANGE-REQUESTS.md): does the swarm do a real change as well as the person who made it?

A case is a real commit C of a repository that changed its tests and its code, with its parent P. The agents start from a
snapshot of P with no history, are given C's message as the request, and never see C. The score is a program's: the tests
C made pass (they fail at P and pass at C: the hidden suite), and the tests that passed at both (regressions). Arms compare
the swarm with one coder, the wiki with no wiki, and skills with none, on the same case.

  python3 ops/replay.py pick <repo> [n]            cases from the repository's history, into its key folder
  python3 ops/replay.py check <repo> <case>        run C's tests at P and at C in the sandbox; fixes what counts as hidden
  python3 ops/replay.py run <repo> <case> <arm>    one run; arm: one-coder, swarm, swarm+wiki, swarm+wiki+skills

The key folder (/srv/ai/private/trials/replay/<repo>/: a full clone and cases.json) is in no container. Known bias, said in
every report: the wiki arm reads a wiki seeded from the repository's newest code, which can know more than P did.
"""
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ops"))
import textcap as TC                              # visible caps (AGENTS.md, truncation)
import trials as TR
import deployment as DEPLOY                        # this deployment's hosts and paths (config/deployment.env)

KEYS = Path("/srv/ai/private/trials/replay")
WORK = Path("/srv/ai/workbench/.replay")          # scoring happens here, after the agents are done; removed again
BUILDER = "aistack-builder-1"
TEST_PATH = re.compile(r"(^|/)(tests?|testing|__tests__)/|(^|/)test_[^/]*$|_test\.[a-z]+$|\.(test|spec)\.[a-z]+$")
CODE_EXT = {".py", ".go", ".js", ".ts", ".tsx", ".rs", ".java"}
SKIP = re.compile(r"^(merge|bump|release|revert|update (changelog|deps)|version|typo|docs?\b|fix typo|ci\b)", re.I)
# limit: drops, a commit past 200 changed lines or 5 code files is no case: the exam measures one change, not a rewrite
CASE_LINES, CASE_CODE_FILES = 200, 5
# limit: stops, one run past its hours is cancelled and scored as it stands
HOURS = 12
ARMS = {"one-coder": {}, "swarm": {"no_wiki": True}, "swarm+wiki": {}, "swarm+wiki+skills": {"skills": True}}


def key_dir(repo):
    return KEYS / repo


def clone_of(repo):
    return key_dir(repo) / "clone"


def git(path, *args, timeout=600, check=True):
    p = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f"git {args[0]}: {(p.stderr or p.stdout).strip()}")
    return p.stdout.strip()


# ---------- the cases ----------
def is_case(message, files):
    """files: [(added, removed, path)]. -> does this commit make a case: tests and code changed, one change's size."""
    if len(message.strip()) < 20 or SKIP.match(message.strip()):
        return False
    tests = [f for _, _, f in files if TEST_PATH.search(f)]
    code = [f for _, _, f in files if not TEST_PATH.search(f) and Path(f).suffix in CODE_EXT]
    lines = sum(a + r for a, r, f in files if not TEST_PATH.search(f))
    return bool(tests) and 0 < len(code) <= CASE_CODE_FILES and lines <= CASE_LINES


def numstat(path, sha):
    out = []
    for ln in git(path, "show", "--numstat", "--format=", sha).splitlines():
        a, r, f = (ln.split("\t") + ["", "", ""])[:3]
        if f:
            out.append((int(a) if a.isdigit() else 0, int(r) if r.isdigit() else 0, f))
    return out


def request_of(message):
    """The owner's words for it: the commit's text without its trailers and issue links."""
    lines = [ln for ln in message.splitlines() if not re.match(r"^(Signed-off-by|Co-authored-by|Reviewed-by|fixes|closes)\b", ln, re.I)]
    return re.sub(r"\s*\(#\d+\)", "", "\n".join(lines)).strip()


def pick(repo, n=10, source=None):
    """Up to n cases from the repository's history, spread over it, newest first; cases that were checked stay checked."""
    d, c = key_dir(repo), clone_of(repo)
    if not c.exists():
        d.mkdir(parents=True, exist_ok=True)
        url = source or git(TR.CODE / repo, "remote", "get-url", "origin")
        subprocess.run(["git", "clone", "-q", url, str(c)], check=True, capture_output=True, timeout=1800)
    found = []
    # limit: drops, commits older than the newest 3000 are not looked at: an old code base differs from today's
    for ln in git(c, "log", "--no-merges", "-n", "3000", "--format=%H%x00%P").splitlines():
        sha, _, parent = ln.partition("\0")
        if not parent or " " in parent:
            continue
        message = git(c, "log", "-1", "--format=%B", sha)
        if is_case(message, numstat(c, sha)):
            found.append({"sha": sha, "parent": parent, "request": request_of(message), "tests": [f for _, _, f in numstat(c, sha) if TEST_PATH.search(f)]})
    step = max(1, len(found) // max(1, n))
    cases = found[::step][:n]  # cap: top (spread over the history; the exam's size)
    f = d / "cases.json"
    old = {x["sha"]: x for x in json.loads(f.read_text())} if f.exists() else {}
    cases = [{**x, **{k: v for k, v in old.get(x["sha"], {}).items() if k in ("hidden", "keep", "setup", "error")}} for x in cases]
    f.write_text(json.dumps(cases, indent=1, ensure_ascii=False))
    return cases


def load_case(repo, i):
    return json.loads((key_dir(repo) / "cases.json").read_text())[i]


# ---------- running tests in the sandbox, read by name ----------
def setup_of(path):
    """How a copy gets its dependencies: nothing but the package proxy, inside the copy."""
    if (path / "pyproject.toml").exists() or (path / "setup.py").exists():
        return "python3 -m venv .venv-stack && .venv-stack/bin/pip install -q -e . pytest"
    if (path / "requirements.txt").exists():
        return "python3 -m venv .venv-stack && .venv-stack/bin/pip install -q -r requirements.txt pytest"
    if (path / "go.mod").exists():
        return "go mod download"
    return ""


def tests_command(path, files):
    if (path / "go.mod").exists():
        return "go test -v ./... 2>&1"
    pytest = ".venv-stack/bin/pytest" if (path / "pyproject.toml").exists() or (path / "setup.py").exists() or (path / "requirements.txt").exists() else "pytest"
    return f"{pytest} -q -rA --no-header -p no:cacheprovider {' '.join(files)} 2>&1"


RESULT = re.compile(r"^(PASSED|FAILED|ERROR)\s+(\S+)", re.M)
GO_RESULT = re.compile(r"^\s*--- (PASS|FAIL): (\S+)", re.M)


def outcomes(text):
    """A test run's output -> {test: passed?}, by name; pytest -rA and go test -v."""
    out = {name: word == "PASSED" for word, name in RESULT.findall(text)}
    out.update({name: word == "PASS" for word, name in GO_RESULT.findall(text)})
    return out


def sandbox(rel, setup, command, timeout=1800, run=subprocess.run):
    """In the builder's sandbox, in a copy under the workbench. -> its output."""
    script = f"umask 000; export PATH=/opt/tools/bin:$PATH; {setup + ' >/dev/null 2>&1; ' if setup else ''}{command}"
    return run(["docker", "exec", "-u", "hermes", "-w", f"/work/.replay/{rel}", BUILDER, "sh", "-c", script], capture_output=True, text=True, timeout=timeout).stdout


def materialise(c, ref, dest):
    """A commit's tree in a folder of its own."""
    dest.mkdir(parents=True, exist_ok=True)
    data = subprocess.run(["git", "-C", str(c), "archive", ref], capture_output=True, check=True, timeout=600).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=data, check=True, timeout=600)
    subprocess.run(["chmod", "-R", "a+rwX", str(dest)], check=True, timeout=120)


def put_tests(c, sha, files, dest):
    """C's test files over a tree, as they were at C."""
    for f in files:
        data = subprocess.run(["git", "-C", str(c), "show", f"{sha}:{f}"], capture_output=True)
        if data.returncode:                               # a test file C deleted
            (dest / f).unlink(missing_ok=True)
            continue
        (dest / f).parent.mkdir(parents=True, exist_ok=True)
        (dest / f).write_bytes(data.stdout)
    subprocess.run(["chmod", "-R", "a+rwX", str(dest)], check=True, timeout=120)


def runnable(files):
    return [f for f in files if Path(f).name.startswith("test_") or f.endswith("_test.py")]


def check(repo, i, run=sandbox):
    """What counts: the tests that fail at P and pass at C are hidden, those that pass at both are kept. A case with no hidden test
    cannot score anything and says so."""
    cases = json.loads((key_dir(repo) / "cases.json").read_text())
    x, c = cases[i], clone_of(repo)
    WORK.mkdir(parents=True, exist_ok=True)
    os_mode(WORK)
    rel = f"check-{repo}-{i}"
    res = {}
    try:
        for label, ref in (("after", x["sha"]), ("before", x["parent"])):
            d = WORK / rel / label
            materialise(c, ref, d)
            put_tests(c, x["sha"], x["tests"], d)
            setup = setup_of(d)
            res[label] = outcomes(run(f"{rel}/{label}", setup, tests_command(d, runnable(x["tests"]))))
        x["hidden"] = sorted(t for t, ok in res["after"].items() if ok and not res["before"].get(t))
        x["keep"] = sorted(t for t, ok in res["after"].items() if ok and res["before"].get(t))
        x["setup"] = setup
        x["error"] = None if x["hidden"] else "no test fails before the commit and passes after it"
    finally:
        shutil.rmtree(WORK / rel, ignore_errors=True)
    (key_dir(repo) / "cases.json").write_text(json.dumps(cases, indent=1, ensure_ascii=False))
    return x


def os_mode(p):
    subprocess.run(["chmod", "a+rwx", str(p)], check=False, timeout=30)


def score_of(x, got):
    """The run's outcomes against the key -> a trial's score: the hidden suite and regressions."""
    cases = [{"id": t, "area": "hidden suite", "ok": bool(got.get(t)), "detail": "passes" if got.get(t) else "fails or was not run"} for t in x.get("hidden") or []]
    cases += [{"id": t, "area": "regressions", "ok": bool(got.get(t)), "detail": "still passes" if got.get(t) else "broke"} for t in x.get("keep") or []]
    return TR.summarise({"cases": cases, "error": None if cases else "the case has no key: run check first"})


def score_branch(repo, i, trial_repo, branch, run=sandbox):
    """C's tests over the delivered branch, in the sandbox, once the agents are done."""
    x, c = load_case(repo, i), clone_of(repo)
    rel = f"score-{trial_repo}"
    d = WORK / rel
    WORK.mkdir(parents=True, exist_ok=True)
    os_mode(WORK)
    try:
        git(TR.CODE / trial_repo, "fetch", "-q", "origin", branch, timeout=180)
        materialise(TR.CODE / trial_repo, "FETCH_HEAD", d)
        put_tests(c, x["sha"], x["tests"], d)
        return score_of(x, outcomes(run(rel, x.get("setup") or setup_of(d), tests_command(d, runnable(x["tests"])))))
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------- one run ----------
def make_repo(repo, x, run_id):
    """A snapshot of P with no history, on Forgejo: the agents cannot read C from it."""
    name = f"trial-{run_id}"
    d = TR.CODE / name
    materialise(clone_of(repo), x["parent"], d)
    TR.git(d, "init", "-q", "-b", "main")
    TR.git(d, "add", "-A")
    TR.git(d, "-c", "user.name=AI stack trials", "-c", "user.email=trials@stack.local", "commit", "-q", "-m", "The repository as it stands")
    TR.git(d, "remote", "add", "origin", f"forgejo:{DEPLOY.FORGEJO_OWNER}/{name}.git")
    TR.git(d, "push", "-q", "-u", "origin", "main", timeout=300)
    return name


def give(repo, trial_repo, x, arm, request=TR.request):
    """The case through the door this arm has. -> the task."""
    if arm not in ARMS:
        raise ValueError(f"arm must be one of: {', '.join(ARMS)}")
    source = f"trial:replay-{repo}"
    if arm == "one-coder":                                # the builder alone, as before change requests: the intake may not plan other agents
        r = request({"action": "task_create", "text": TC.limit(x["request"], 4000, "the request"), "kind": "coding", "repo": trial_repo, "source": source, "agents": ["builder"]})
    else:
        r = request({"action": "change_request", "repo": trial_repo, "text": TC.limit(x["request"], 4000, "the request"), "source": source,
                     "auto_go": True, "trial": True, "wiki_of": repo, **ARMS[arm]})
    return int(r["task"])


def branch_of(c, tid):
    """The delivered branch: a change's own, or the builder's. -> (branch, build ids)."""
    row = c.execute("select spec, door, ref from tasks where id=?", (tid,)).fetchone()
    ch = (json.loads(row["spec"] or "{}").get("change") or {})
    if ch.get("branch"):
        return ch["branch"]
    if c.execute("select 1 from builds where repo=(select json_extract(spec, '$.repo') from tasks where id=?) and status='merged'", (tid,)).fetchone():
        return "main"                                     # a trial's build merges into its scratch repository's main (TRL-05)
    if row["door"] == "build" and str(row["ref"] or "").isdigit():
        b = c.execute("select branch from builds where id=?", (int(row["ref"]),)).fetchone()
        return b["branch"] if b else None
    return None


def run(repo, i, arm, log=print):
    x = load_case(repo, i)
    if not x.get("hidden"):
        raise ValueError(f"case {i} of {repo} has no key: {x.get('error') or 'run check first'}")
    run_id = f"replay-{re.sub(r'[^a-z0-9]+', '-', repo.lower())}-{i}-{arm.replace('+', '-')}-{time.strftime('%Y%m%d-%H%M')}"
    t = {"name": f"replay-{repo}", "title": f"Replay exam: {repo}", "budget": {"hours": HOURS, "tokens": 0}, "flag_similarity": 1}
    d = TR.RUNS / run_id
    d.mkdir(parents=True)
    trial_repo = make_repo(repo, x, run_id)
    started = time.time()
    tid = give(repo, trial_repo, x, arm)
    log(f"{run_id}: case {x['sha'][:10]}, task #{tid}; watching it")
    row, asked, over = TR.watch(t, tid, started, log=log)
    if over:
        TR.request({"action": "task_cancel", "id": tid})
    with TR.db() as c:
        branch = branch_of(c, tid)
        bids = TR.build_ids(c, tid, trial_repo)
        m = TR.metrics(c, tid, bids, TR.tree(tid) or ([], []))
    s = score_branch(repo, i, trial_repo, branch) if branch else TR.summarise({"cases": [], "error": "no branch delivered"})
    r = {"trial": t["name"], "run": run_id, "dir": str(d), "repo": trial_repo, "task": tid, "started_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(started)),
         "version": TR.git(ROOT, "rev-parse", "--short", "HEAD").strip(), "over_budget": over, "asked": asked, "builds": bids, "arm": arm, "case": x["sha"],
         "score": s, "audit": {"ok": True, "forbidden": []}, "similarity": {"share": 0.0, "files": []}, "metrics": m}
    (d / "result.json").write_text(json.dumps(r, indent=1, ensure_ascii=False))
    rel = f"trials/{t['name']}/{run_id}.md"
    (TR.VAULT / rel).parent.mkdir(parents=True, exist_ok=True)
    (TR.VAULT / rel).write_text(f"# {arm} on {x['sha'][:10]}\n\nThe request: {x['request']}\n\nKnown bias: the wiki arm's wiki was seeded from the repository's newest code.\n\n" + TR.report(t, {**r, "build": None}))
    for act in ({"action": "build_reject", "id": b} for b in bids):
        try:
            TR.request(act, wait=120)
        except RuntimeError as e:                         # one that merged into the trial's branch is no longer in review
            log(f"{run_id}: {e}")
    try:
        TR.request({"action": "repo_remove", "repo": trial_repo}, wait=300)
        TR.publish(log=log)
    except (RuntimeError, OSError) as e:                  # the run's record is in its folder either way
        log(f"{run_id}: {e}")
    log(f"{run_id}: {s['passed']} of {s['total']}: {s['areas']} · {m['tokens']:,} tokens · {m['minutes']} min")
    return r


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "pick":
        got = pick(a[1], int(a[2]) if len(a) > 2 else 10)
        for n, y in enumerate(got):
            print(n, TC.fit(y["sha"], 10), TC.fit(y["request"].splitlines()[0], 90), len(y["tests"]))  # cap: preview
    elif len(a) == 3 and a[0] == "check":
        y = check(a[1], int(a[2]))
        print(f"{len(y['hidden'])} hidden, {len(y['keep'])} kept" + (f": {y['error']}" if y["error"] else ""))
    elif len(a) == 4 and a[0] == "run":
        run(a[1], int(a[2]), a[3])
    else:
        sys.exit(__doc__)

"""Change requests (CHG-01 to CHG-07, CHG-11, CHG-15, CHG-16): a sentence becomes a specification, a plan by size, one
branch with the evidence, and nothing lands without the owner. The agents and the sandbox are stubbed; git, the database,
the Conductor's graph and the judge's decisions are the real ones."""
import json
import sqlite3
import subprocess
import threading
import types
from pathlib import Path

import pytest

import builds as B
import changes as CH
import conductor as CD
import notify as N
import repowiki as RW
import runtime as RTM
import tasks as TK

ROOT = Path(__file__).resolve().parent.parent
SPEC = {"title": "Show the copy's progress", "goal": "The owner sees it move", "size": "M", "scope": ["the mail page"], "out_of_scope": ["the NAS"],
        "criteria": ["When the copy runs, the page shall show the mails copied so far.", "When the copy is done, the page shall say so."],
        "files": ["src/app.py", "src/page.py"], "risks": ["the status file"], "assumptions": ["once a minute is enough"], "questions": []}


@pytest.fixture
def K(tmp_path, monkeypatch):
    """A real bare Forgejo stand-in with a repository, real clones, a real database; the sandbox and the agents are stubs."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(seed)], check=True, capture_output=True)
    gitc = lambda p, *a: subprocess.run(["git", "-C", str(p), "-c", "user.name=t", "-c", "user.email=t" + chr(64) + "t", *a], check=True, capture_output=True, text=True).stdout.strip()
    (seed / "src").mkdir()
    (seed / "tests").mkdir()
    (seed / "src/app.py").write_text("x = 1\n")
    (seed / "tests/test_app.py").write_text("def test_x(): pass\n")
    gitc(seed, "add", ".")
    gitc(seed, "commit", "-qm", "first")
    gitc(seed, "push", "-q", "origin", "HEAD:main")
    db = tmp_path / "m.sqlite"

    def conn():
        c = sqlite3.connect(db, timeout=5, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c
    c = conn()
    TK.table(c)
    CD.table(c)
    B.table(c) if hasattr(B, "table") else None
    c.execute("create table if not exists builds (id integer primary key, repo text, title text, description text, status text, branch text, base text, head text, summary text, files text, checks text, ci text, created text, updated text, attempts integer, engine text, ai_review text, source text, pr text, pr_number integer, onto text, note text, merged text, error text, feedback text, calls integer, tokens integer)")
    c.commit()
    events, sent = [], []
    import datetime as dt
    ns = types.SimpleNamespace(db=conn, event=lambda *a, **k: events.append(a[2] if len(a) > 2 else a), log=print, paused=lambda s: "usage limit" in s, VAULT=tmp_path / "vault", PUBLIC=tmp_path / "public",
                               vault_commit=lambda paths, msg: None, X=types.SimpleNamespace(APP="https://x", write_index=lambda r, t: None), stop=threading.Event(),
                               now=lambda: dt.datetime.now().astimezone(), notify_task=lambda tid, title, what: sent.append(what), reindex=lambda: None,
                               split_front=lambda t: ({}, t), write_front=lambda f, m, b: (f.parent.mkdir(parents=True, exist_ok=True), f.write_text(b)) and None)
    CD.M = TK.M = CH.M = RW.M = B.M = ns
    wb = tmp_path / "wb"
    monkeypatch.setattr(B, "WB", wb)
    monkeypatch.setattr(RW, "WB", wb)
    monkeypatch.setattr(RW, "CODE", tmp_path / "code")
    monkeypatch.setattr(B, "OUT", tmp_path / "builds")
    (tmp_path / "builds").mkdir()
    monkeypatch.setattr(B, "origin", lambda repo: str(origin))
    monkeypatch.setattr(B, "repos", lambda: ["demo", "ai-stack"])
    monkeypatch.setattr(B, "swarm", lambda *a, **k: None)
    monkeypatch.setattr(B, "open_pr", lambda c, bid: None)
    monkeypatch.setattr(B, "save_files", lambda bid: None)
    real_run = subprocess.run

    def quiet_docker(cmd, *a, **k):                    # the sandbox's chmod in clone(): nothing to do here
        if cmd[0] == "docker":
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(B.subprocess, "run", quiet_docker)
    monkeypatch.setattr(CD, "headroom", lambda s: None)
    monkeypatch.setattr(CD, "over_budget", lambda c, t, s: None)
    monkeypatch.setattr(CD, "RESULTS", tmp_path / "vault/tasks")
    monkeypatch.setattr(CD, "mapped", lambda *a, **k: None)
    monkeypatch.setattr(CD, "spent", lambda c, t, s: (0.5, 1234))
    monkeypatch.setattr(CD, "cards", lambda: yaml_cards())
    monkeypatch.setattr(N, "send", lambda text, category, **k: sent.append(text) or {})
    monkeypatch.setattr(RTM, "start", lambda *a, **k: None)
    monkeypatch.setattr(RTM, "end", lambda *a, **k: None)
    monkeypatch.setattr(RTM, "set_ref", lambda *a, **k: None)
    monkeypatch.setattr(CH, "journal", lambda *a, **k: None)
    runs = {}
    monkeypatch.setattr(CH, "sandbox", lambda repo, cmd, timeout=1800: runs["fn"](cmd))
    runs["fn"] = lambda cmd: (0, "3 passed")
    return types.SimpleNamespace(c=c, tmp=tmp_path, origin=origin, seed=seed, gitc=gitc, runs=runs, events=events, sent=sent, conn=conn)


def yaml_cards():
    import yaml
    return {a["id"]: a for a in yaml.safe_load((ROOT / "config/agents.yaml").read_text())["agents"]}


def req(K, size="M", **kw):
    t = CH.create({"action": "change_request", "repo": "demo", "text": "Show the copy's progress on the mail page", **kw}, K.c)["task"]
    CH.specify(K.c, TK.row(K.c, t), ask=lambda p: {**SPEC, "size": size})
    return t


def steps(K, tid):
    return CD.steps(K.c, tid, CD.occ_of(K.c, tid))


def step(K, tid, harness):
    return next(s for s in steps(K, tid) if s["harness"] == harness)


def run(K, tid, s, card=None):
    """One step through its adapter, as the Conductor would: fresh from the database."""
    t = TK.row(K.c, tid)
    s = next(x for x in steps(K, tid) if x["id"] == s["id"])
    return CD.ADAPTERS[s["harness"]](K.c, t, s, CH.prompt_for(t, s, steps(K, tid), yaml_cards()), card or {})


def coder_commits(K, ch, file="src/app.py", text="x = 2\n", msg="work"):
    """What a step's build would have pushed: a commit on a branch of its own, onto the change's branch."""
    work = K.tmp / "work"
    if not work.exists():
        subprocess.run(["git", "clone", "-q", str(K.origin), str(work)], check=True, capture_output=True)
    K.gitc(work, "fetch", "-q", "origin")
    name = f"builder/{abs(hash((file, text, msg))) % 100000}"
    K.gitc(work, "checkout", "-q", "-B", name, f"origin/{ch['branch']}")
    (work / file).parent.mkdir(exist_ok=True)
    (work / file).write_text(text)
    K.gitc(work, "add", ".")
    K.gitc(work, "commit", "-qm", msg)
    K.gitc(work, "push", "-q", "-f", "origin", name)
    return name


def built(K, tid, s, branch, files, summary="done"):
    """A step's build in review, as the builder leaves it."""
    cur = K.c.execute("insert into builds (repo, title, status, branch, files, summary, created, updated, attempts) values ('demo',?,?,?,?,?,?,?,1)",
                      (f"{s['agent']}: x", "review", branch, json.dumps([["M", f] for f in files]), summary, TK.now(), TK.now()))
    K.c.commit()
    CD.put(K.c, s["id"], resume={**s["resume"], "build": cur.lastrowid})
    return cur.lastrowid


# ---------- the door and the specification ----------
def test_a_repository_the_builder_may_not_change_is_refused_with_what_to_do(K):
    with pytest.raises(ValueError, match="Let the builder change it"):
        CH.create({"repo": "elsewhere", "text": "Change something in it please"}, K.c)


def test_the_intake_writes_criteria_a_test_can_check_and_refuses_vague_ones(K):
    s = CH.valid_spec(SPEC)
    assert [x["id"] for x in s["criteria"]] == ["C1", "C2"] and s["size"] == "M" and s["assumptions"]
    with pytest.raises(ValueError, match="no acceptance criteria"):
        CH.valid_spec({**SPEC, "criteria": []})
    with pytest.raises(ValueError, match="cannot be written"):
        CH.valid_spec({**SPEC, "criteria": ["It works well"]})
    with pytest.raises(ValueError, match="size class"):
        CH.valid_spec({**SPEC, "size": "XL"})
    assert len(CH.valid_spec({**SPEC, "questions": ["a", "b", "c", "d"]})["questions"]) == 3


def test_the_size_follows_the_code_it_will_touch_not_its_tests_and_requirements():
    """Tasks 163 and 166: an API field with its page came back L, a wording fix M, and a small change never existed."""
    one = ["When it waits, it shall name its engine."]
    assert CH.size_of("M", ["images/app.js", "tests/test_x.py", "requirements/app.yaml", "docs/GUIDE.md"], one) == "S"
    assert CH.size_of("L", ["images/server.py", "images/app.js", "tests/test_x.py"], one * 9) == "M"
    assert CH.size_of("L", ["a.py", "b.py", "c.py", "d.py"], one) == "L"                 # four code files stay large
    assert CH.size_of("M", ["a.py"], one * 4) == "M"                                      # one file, many criteria: tests are worth a tester
    assert CH.size_of("L", [], one) == "L"                                                # nothing named: the intake's word stands
    s = CH.valid_spec({**SPEC, "size": "M", "files": ["images/app.js"], "criteria": one})
    assert s["size"] == "S" and s["asked_size"] == "M"


def test_a_small_change_starts_at_once_and_a_medium_one_waits_for_the_go_with_his_edits(K, monkeypatch):
    began = []
    monkeypatch.setattr(CH, "begin", lambda c, t: began.append(t["id"]))
    small = req(K, "S")
    assert began == [small]
    medium = req(K, "M")
    t = TK.row(K.c, medium)
    assert t["status"] == "waiting_approval" and began == [small] and t["spec"]["budget"] == CH.BUDGETS["M"] and t["kind"] == "change"
    assert "waits for your Go" in K.sent[-1]
    CH.handle({"action": "change_go", "id": medium, "criteria": "When X, it shall Y.\n\nWhen Z, it shall W.\n"}, K.c)
    t = TK.row(K.c, medium)
    assert began == [small, medium] and [x["text"] for x in t["spec"]["change"]["criteria"]] == ["When X, it shall Y.", "When Z, it shall W."]
    with pytest.raises(ValueError, match="does not wait"):
        CH.handle({"action": "change_go", "id": medium}, K.c)


def test_a_question_that_blocks_the_plan_comes_back_and_its_answer_reaches_the_next_pass(K):
    t = CH.create({"repo": "demo", "text": "Show the copy's progress on the mail page"}, K.c)["task"]
    CH.specify(K.c, TK.row(K.c, t), ask=lambda p: {**SPEC, "questions": ["Which page?"]})
    assert TK.row(K.c, t)["status"] == "needs_answer"
    TK.handle({"action": "task_answer", "id": t, "answers": ["the mail page"]}, K.c)
    seen = []
    TK.intake(K.c, t, ask=lambda p: seen.append(p) or {**SPEC, "questions": []})
    assert "Which page?: the mail page" in seen[0] and TK.row(K.c, t)["status"] == "waiting_approval"


def test_a_failed_specification_says_why_on_the_task(K):
    t = CH.create({"repo": "demo", "text": "Show the copy's progress on the mail page"}, K.c)["task"]
    CH.specify(K.c, TK.row(K.c, t), ask=lambda p: {**SPEC, "criteria": ["vague"]})
    r = TK.row(K.c, t)
    assert r["status"] == "failed" and "cannot be written" in r["error"]


# ---------- the plan ----------
def test_the_plan_by_size_class_runs_the_right_agents_in_the_right_order():
    agents = yaml_cards()
    names = lambda size: [s["harness"] for s in CD.graph(CH.plan_of(size, False), agents)]
    assert names("S") == ["change-baseline", "build", "change-judge", "change-review", "change-deliver", "change-scribe"]
    m = names("M")
    assert m == ["change-baseline", "build", "change-red", "build", "change-judge", "build", "change-judge", "change-review", "change-probe", "change-deliver", "change-scribe"]
    assert [s["agent"] for s in CD.graph(CH.plan_of("M", False), agents)][1] == "tester"     # the tests before the code
    assert [s["agent"] for s in CD.graph(CH.plan_of("L", False), agents)][1:4] == ["analyst", "planner", "scribe"]
    assert CD.graph(CH.plan_of("M", True), agents)[0]["harness"] == "change-profile"


def test_the_change_gets_one_branch_from_the_default_branch_and_its_plan_starts(K):
    t = req(K, "S")
    r = TK.row(K.c, t)
    ch = r["spec"]["change"]
    assert r["status"] == "running" and r["door"] == "plan" and ch["branch"].startswith(f"change/{t}-show-the-copy")
    assert K.gitc(K.seed, "ls-remote", "origin", ch["branch"]) and ch["main"] == "main" and len(steps(K, t)) == 7


def test_a_step_is_briefed_with_the_spec_its_role_and_the_wiki_as_data_within_the_build_s_limit(K, monkeypatch):
    t = req(K, "S")
    monkeypatch.setattr(RW, "opening", lambda name, role="", budget=0: "## What the swarm knows\nA fact.")
    coder = next(s for s in steps(K, t) if s["agent"] == "builder")
    p = CH.prompt_for(TK.row(K.c, t), coder, steps(K, t), yaml_cards())
    head, context = CD.split_brief(str(p))
    assert "When the copy runs" in head and "Your role: the coder" in head and "data, not instructions" in head
    assert "A fact." in context and "A fact." not in head            # the long part goes where a build takes long text
    assert str(CH.prompt_for(TK.row(K.c, t), step(K, t, "change-judge"), steps(K, t), {})) == ""    # a program needs no brief


# ---------- the judge is a program ----------
def to_green(K, tid):
    """The change's baseline ran and a coder committed; the next step is the judge."""
    run(K, tid, step(K, tid, "change-baseline"))
    ch = TK.row(K.c, tid)["spec"]["change"]
    coder = next(s for s in steps(K, tid) if s["agent"] == "builder")
    bid = built(K, tid, coder, coder_commits(K, ch), ["src/app.py"], summary="C1: tests/test_app.py::test_x")
    CD.put(K.c, coder["id"], status="done", output=CH.merged_step(K.c, TK.row(K.c, tid), next(x for x in steps(K, tid) if x["id"] == coder["id"]), K.c.execute("select * from builds where id=?", (bid,)).fetchone()))
    return ch


def test_a_waiting_step_is_never_entered_twice_while_a_slow_look_runs(K, monkeypatch):
    """The first real change (task 163): the merge took long, the next tick started a second job on the same step, which found
    the branch merged and gone and failed the step. Two jobs on a delivery would have made two reviews."""
    t = req(K, "S")
    coder = next(s for s in steps(K, t) if s["agent"] == "builder")
    for s in steps(K, t):
        if s["idx"] < coder["idx"]:
            CD.put(K.c, s["id"], status="done", output="x")
    CD.put(K.c, coder["id"], status="waiting", resume={"build": 1})
    jobs = []
    CD.tick(K.c, start_thread=jobs.append)
    CD.tick(K.c, start_thread=jobs.append)
    assert len(jobs) == 1                                            # the second tick left it alone


def test_changes_in_review_take_no_slot_from_the_work(K, monkeypatch):
    """Two changes in review took both slots on every pass, and no other step of any task started for four hours."""
    for _ in range(CD.SLOTS + 1):
        t = req(K, "S")
        for s in steps(K, t):
            if s["harness"] == "change-deliver":
                CD.put(K.c, s["id"], status="waiting", resume={"carrier": 1})
                break
            CD.put(K.c, s["id"], status="done", output="x")
    t = req(K, "S")
    monkeypatch.setattr(CD, "headroom", lambda *a, **k: None)
    jobs = []
    CD.tick(K.c, start_thread=jobs.append)
    assert steps(K, t)[0]["status"] == "running"
    CD.slots.release()


def test_a_step_s_build_merged_twice_is_merged_once(K):
    t = req(K, "S")
    ch = to_green(K, t)
    b = dict(K.c.execute("select * from builds where status='merged' order by id desc").fetchone())
    assert B.change_merge(K.c, b, ch["branch"]) == b["merged"]       # its branch is gone by now: the answer is the merge it made


def test_a_step_s_build_lands_on_the_change_s_branch_not_on_main(K):
    t = req(K, "S")
    ch = to_green(K, t)
    log = K.gitc(K.seed, "ls-remote", "origin")
    main = [ln.split()[0] for ln in log.splitlines() if ln.endswith("refs/heads/main")][0]
    tip = [ln.split()[0] for ln in log.splitlines() if ln.endswith(ch["branch"])][0]
    assert main == ch["base"] and tip != main
    assert "builder/" not in log                                    # the step's own branch is gone


def test_failures_that_were_there_before_are_no_fault_of_the_change_and_new_ones_go_back_to_the_coder(K):
    t = req(K, "S")
    K.runs["fn"] = lambda cmd: (0, "1 passed") if cmd.startswith("pytest -q tests/") else (1, "FAILED tests/test_old.py::test_flaky_forever - boom\n1 failed, 2 passed")
    to_green(K, t)
    assert TK.row(K.c, t)["spec"]["change"]["baseline"]["failed"] == ["tests/test_old.py::test_flaky_forever"]
    judge = step(K, t, "change-judge")
    out = run(K, t, judge)                                           # only the old failure: passes against the baseline
    ch = TK.row(K.c, t)["spec"]["change"]
    assert ch["judge"]["ok"] and "All good against the baseline" in out and ch["judge"]["known"] == ["tests/test_old.py::test_flaky_forever"]
    K.runs["fn"] = lambda cmd: (1, "1 failed") if "test_new" in cmd else (0, "1 passed") if cmd.startswith("pytest -q tests/") else (1, "FAILED tests/test_old.py::test_flaky_forever - boom\nFAILED tests/test_app.py::test_new - bad\n2 failed")
    with pytest.raises(CD.Reopened):
        run(K, t, judge)
    coder = next(s for s in steps(K, t) if s["agent"] == "builder")
    assert coder["status"] == "pending" and "tests/test_app.py::test_new" in coder["resume"]["feedback"] and coder["resume"]["round"] == 1
    assert "test_flaky_forever" not in coder["resume"]["feedback"].split("The end of the test run")[0]
    assert TK.row(K.c, t)["spec"]["change"]["rounds"]["builder"] == 1


def test_a_test_that_fails_once_and_passes_again_is_a_flake_and_goes_into_the_wiki_not_back_to_the_coder(K, monkeypatch):
    t = req(K, "S")
    to_green(K, t)
    noted = []
    monkeypatch.setattr(CH, "RW_note", lambda repo, ch, text, ev: noted.append(text))
    K.runs["fn"] = lambda cmd: (0, "1 passed") if cmd.startswith("pytest -q tests/") else (1, "FAILED tests/test_app.py::test_new - once\n1 failed")
    out = run(K, t, step(K, t, "change-judge"))
    assert "flaky" in out and TK.row(K.c, t)["spec"]["change"]["judge"]["flaky"] == ["tests/test_app.py::test_new"] and "test_new" in noted[0]


def test_after_its_fix_rounds_the_failure_goes_to_the_owner_not_on_forever(K):
    t = req(K, "S")
    to_green(K, t)
    K.runs["fn"] = lambda cmd: (1, "FAILED tests/test_app.py::test_new - bad\n1 failed")
    row = TK.row(K.c, t)
    TK.put(K.c, t, spec={**row["spec"], "change": {**row["spec"]["change"], "rounds": {"builder": CH.ROUNDS}}})
    out = run(K, t, step(K, t, "change-judge"))
    assert "still fails after its fix rounds" in out and not TK.row(K.c, t)["spec"]["change"]["judge"]["ok"]


def test_an_acceptance_test_that_passes_before_the_change_goes_back_to_the_tester(K):
    t = req(K, "M", auto_go=True)
    CD.put(K.c, step(K, t, "change-baseline")["id"], status="done")
    tester = next(s for s in steps(K, t) if s["agent"] == "tester")
    CD.put(K.c, tester["id"], status="done", output="C1: tests/test_app.py::test_one\nC2: tests/test_app.py::test_two")
    K.runs["fn"] = lambda cmd: (0, "1 passed") if "test_one" in cmd else (1, "1 failed")
    with pytest.raises(CD.Reopened):
        run(K, t, step(K, t, "change-red"))
    tester = next(s for s in steps(K, t) if s["agent"] == "tester")
    assert tester["status"] == "pending" and "C1 (tests/test_app.py::test_one)" in tester["resume"]["feedback"]
    CD.put(K.c, tester["id"], status="done", output="C1: tests/test_app.py::test_one\nC2: tests/test_app.py::test_two")
    K.runs["fn"] = lambda cmd: (1, "1 failed")
    assert "C1: fails" in run(K, t, step(K, t, "change-red"))


def test_a_tester_or_breaker_may_change_only_tests(K):
    assert CH.lane_problem("tester", ["tests/test_x.py", "src/foo.test.ts", "pkg/a_test.go", "requirements/builder.yaml"]) == []  # a test its requirement claims
    assert CH.lane_problem("breaker", ["src/app.py", "tests/test_x.py"]) == ["src/app.py"]
    assert CH.lane_problem("builder", ["src/app.py"]) == []


def test_the_coder_may_not_change_the_acceptance_tests(K):
    t = req(K, "M", auto_go=True)
    CD.put(K.c, step(K, t, "change-baseline")["id"], status="done", output="x")
    ch = TK.row(K.c, t)["spec"]["change"]
    tester = next(s for s in steps(K, t) if s["agent"] == "tester")
    bid = built(K, t, tester, coder_commits(K, ch, "tests/test_new.py", "def test_new(): assert 0\n", "tests"), ["tests/test_new.py"], "C1: tests/test_new.py::test_new")
    CH.merged_step(K.c, TK.row(K.c, t), next(x for x in steps(K, t) if x["id"] == tester["id"]), K.c.execute("select * from builds where id=?", (bid,)).fetchone())
    CD.put(K.c, tester["id"], status="done", output="C1: tests/test_new.py::test_new")
    coder = next(s for s in steps(K, t) if s["agent"] == "builder")
    bid = built(K, t, coder, coder_commits(K, ch, "tests/test_new.py", "def test_new(): pass\n", "weakened"), ["tests/test_new.py"])
    CH.merged_step(K.c, TK.row(K.c, t), next(x for x in steps(K, t) if x["id"] == coder["id"]), K.c.execute("select * from builds where id=?", (bid,)).fetchone())
    with pytest.raises(CD.Reopened):
        run(K, t, step(K, t, "change-judge"))
    coder = next(s for s in steps(K, t) if s["agent"] == "builder")
    assert "changed after the tester wrote them" in coder["resume"]["feedback"] and "tests/test_new.py" in coder["resume"]["feedback"]


def test_the_coder_may_keep_requirements_current_after_the_tester_touched_them(K):
    """Task 166: a tester's claim in requirements/ made the coder's own update count as tampering, and sent it back for nothing."""
    t = req(K, "M", auto_go=True)
    CD.put(K.c, step(K, t, "change-baseline")["id"], status="done", output="x")
    ch = TK.row(K.c, t)["spec"]["change"]
    tester = next(s for s in steps(K, t) if s["agent"] == "tester")
    bid = built(K, t, tester, coder_commits(K, ch, "requirements/a.yaml", "x: 1\n", "claim"), ["tests/test_new.py", "requirements/a.yaml"], "C1: tests/test_new.py::test_new")
    CH.merged_step(K.c, TK.row(K.c, t), next(x for x in steps(K, t) if x["id"] == tester["id"]), K.c.execute("select * from builds where id=?", (bid,)).fetchone())
    assert TK.row(K.c, t)["spec"]["change"]["tester_files"] == ["tests/test_new.py"]


def test_rechecking_a_build_waits_for_no_other_build_s_files(monkeypatch):
    """Build #37 sat in recheck for hours because builds in review held the whole repository."""
    monkeypatch.setattr(B, "swarm", lambda *a, **k: {"granted": False, "held_by": [{"holder": "build:30"}]})
    b = {"id": 37, "status": "recheck", "repo": "r", "note": "", "task": None, "onto": None, "files_plan": None}
    assert B.take_lease(None, b) is True
    monkeypatch.setattr(B, "put", lambda *a, **k: None)
    assert B.take_lease(None, {**b, "status": "queued"}) is False


def test_the_nas_away_for_a_moment_fails_nothing():
    """Task 171: two builds failed in a minute on "No route to host" and took the change with them."""
    assert RTM.unreachable("RuntimeError: git fetch -q origin: ssh: connect to host nas port 2222: No route to host")
    assert not RTM.unreachable("RuntimeError: git push: remote rejected")
    conductor = (ROOT / "ops/conductor.py").read_text()
    builds = (ROOT / "ops/builds.py").read_text()
    assert "elif RTM.unreachable(msg):" in conductor and 'RTM.unreachable(str(e))' in builds


def test_a_change_s_budget_counts_tokens_not_the_hours_it_waited():
    """Task 170: a small change was stopped at 8.5 hours, nearly all of them spent waiting for memory."""
    assert all(set(b) == {"tokens"} for b in CH.BUDGETS.values())


def test_a_sentence_about_a_criterion_names_no_test():
    """Task 171: the tester's "C3: the mixed-input tests" made the judge run a test called "the", which failed the change."""
    out = """- C3: the mixed-input tests.
- C5: the prompt tests, which check the value.

C1: tests/a.py::t[eot]
C2: `tests/b.py::u[a b]`
C3: tests/c.py::mixed
C5: TestPrompt
"""
    assert CH.acceptance_of([{"agent": "tester", "output": out}]) == {"C1": "tests/a.py::t[eot]", "C2": "tests/b.py::u[a b]", "C3": "tests/c.py::mixed", "C5": "TestPrompt"}


def test_a_step_with_nothing_to_commit_goes_to_the_judge_not_to_failure():
    """Task 166: a coder sent back over nothing rightly changed nothing, and the change failed for it."""
    src = (ROOT / "ops/builds.py").read_text()
    assert 'if n == 0 and b["onto"]:' in src and 'startswith("breaker:")' not in src


def test_ai_stack_s_own_gates_are_protected_unless_the_owner_names_the_path(K):
    assert CH.protected_hits("ai-stack", ["ops/check.sh", "eval/bench.yaml", "ops/x.py"]) == ["ops/check.sh", "eval/bench.yaml"]
    assert CH.protected_hits("ai-stack", ["ops/check.sh"], ["ops/check.sh"]) == []
    assert CH.protected_hits("demo", ["ops/check.sh"]) == []


def test_main_moved_on_while_the_change_ran_the_judge_merges_it_and_the_diff_stays_the_change_s_own(K):
    t = req(K, "S")
    ch = to_green(K, t)
    (K.seed / "other.py").write_text("y = 1\n")
    K.gitc(K.seed, "add", ".")
    K.gitc(K.seed, "commit", "-qm", "someone else landed")
    K.gitc(K.seed, "push", "-q", "origin", "HEAD:main")
    run(K, t, step(K, t, "change-judge"))
    path = B.clone("demo", CH.JUDGE_SLOT)
    assert (path / "other.py").exists()
    assert CH.changed_files("demo", CH.base_of(path, ch)) == ["src/app.py"]


def test_a_conflict_with_main_goes_back_to_the_coder(K):
    t = req(K, "S")
    to_green(K, t)
    (K.seed / "src/app.py").write_text("x = 99\n")
    K.gitc(K.seed, "add", ".")
    K.gitc(K.seed, "commit", "-qm", "the same line elsewhere")
    K.gitc(K.seed, "push", "-q", "origin", "HEAD:main")
    with pytest.raises(CD.Reopened):
        run(K, t, step(K, t, "change-judge"))
    assert "no longer merges" in next(s for s in steps(K, t) if s["agent"] == "builder")["resume"]["feedback"]


def test_a_fix_round_reruns_one_judge_keeps_the_breaker_s_tests_and_waits_for_the_fix(K):
    t = req(K, "M", auto_go=True)
    ss = steps(K, t)
    for s in ss:
        CD.put(K.c, s["id"], status="done", output="x")
    judge2 = [s for s in ss if s["harness"] == "change-judge"][1]
    t_row = TK.row(K.c, t)
    assert CH.reopen(K.c, t_row, judge2, "builder", "fix it", "failures")
    now = {s["idx"]: s for s in steps(K, t)}
    coder = next(s for s in ss if s["agent"] == "builder")
    breaker = next(s for s in ss if s["agent"] == "breaker")
    judge1 = [s for s in ss if s["harness"] == "change-judge"][0]
    assert now[coder["idx"]]["status"] == "pending" and now[coder["idx"]]["resume"]["feedback"] == "fix it"
    assert now[breaker["idx"]]["status"] == "done" and now[judge1["idx"]]["status"] == "done"
    assert now[judge2["idx"]]["status"] == "pending" and coder["idx"] in now[judge2["idx"]]["after"]
    _, go = CD.ready(K.c, t)
    assert [s["idx"] for s in go] == [coder["idx"]]                  # the judge does not run before the fix


# ---------- the reviewers ----------
def test_three_lenses_look_on_the_other_engine_and_their_findings_go_back_once(K, monkeypatch):
    t = req(K, "S")
    to_green(K, t)
    monkeypatch.setattr(B, "reviewer_for", lambda e: "hermes")
    import codegraph as CG
    monkeypatch.setattr(CG, "pack", lambda *a, **k: {"files": {}})
    monkeypatch.setattr(CG, "text", lambda p, *a: "")
    seen = []

    def one(engine, b, path, diff, ok, lens, slot, ctx, reqs):
        seen.append((engine, lens, reqs))
        return {"engine": engine, "lens": lens, "verdict": "changes" if lens == "conventions" else "approve", "summary": "s", "findings": [{"severity": "low", "file": "a", "line": 1, "issue": "not our way", "fix": "do it our way"}] if lens == "conventions" else []}
    r = step(K, t, "change-review")
    t_row = TK.row(K.c, t)
    with pytest.raises(CD.Reopened):
        CH.run_review(K.c, t_row, r, "", {}, one=one)
    assert {x[1] for x in seen} == {"requirements", "security", "conventions"} and {x[0] for x in seen} == {"hermes"} and seen[0][2] == ["C1", "C2"]
    assert "not our way" in next(s for s in steps(K, t) if s["agent"] == "builder")["resume"]["feedback"]
    out = CH.run_review(K.c, TK.row(K.c, t), step(K, t, "change-review"), "", {}, one=one)    # the second time it goes to the owner
    assert "changes" in out and TK.row(K.c, t)["spec"]["change"]["review"]["verdict"] == "changes"


# ---------- the prober ----------
def test_the_prober_s_verdict_and_evidence_are_kept_and_could_not_try_is_said(K, monkeypatch):
    t = req(K, "M", auto_go=True)
    monkeypatch.setattr(CH, "EVIDENCE", K.tmp / "evidence")
    monkeypatch.setattr(B, "claude_text", lambda s: s)

    def fake(cmd, **k):
        (K.tmp / "evidence" / str(t) / "log.txt").write_text("it ran")
        return types.SimpleNamespace(stdout='{"ran": false, "ok": false, "notes": "it needs a phone"}', returncode=0)
    out = CH.run_probe(K.c, TK.row(K.c, t), step(K, t, "change-probe"), "", {}, run=fake)
    pr = TK.row(K.c, t)["spec"]["change"]["probe"]
    assert "could not be tried" in out and pr["evidence"] == ["log.txt"] and pr["notes"] == "it needs a phone"
    assert (K.tmp / f"public/changes/{t}/log.txt").exists()


# ---------- the report and the owner's review ----------
def through_deliver(K, t, monkeypatch=None):
    s = step(K, t, "change-deliver")
    with pytest.raises(CD.Waiting):
        run(K, t, s)
    return TK.row(K.c, t)["spec"]["change"]["carrier"]


def test_the_report_gives_every_criterion_its_evidence_and_the_carrier_waits_for_the_owner(K):
    t = req(K, "S")
    to_green(K, t)
    row = TK.row(K.c, t)
    ch = row["spec"]["change"]
    ch["acceptance"] = {"C1": {"test": "tests/test_app.py::test_x", "before": "fails", "after": "passes"}}
    ch["judge"] = {"ok": True, "counts": {"passed": 3}, "known": []}
    TK.put(K.c, t, spec={**row["spec"], "change": ch})
    bid = through_deliver(K, t)
    b = K.c.execute("select * from builds where id=?", (bid,)).fetchone()
    assert b["status"] == "review" and b["source"] == f"change:{t}" and b["branch"] == ch["branch"] and "PASSED" in b["checks"] and b["ci"] == "pending"
    assert "**C1 met**" in b["summary"] and "before the change it fails, after it passes" in b["summary"] and "**C2 no test run**" in b["summary"]
    assert "1,234 tokens" in b["summary"] and json.loads(b["files"]) == [["M", "src/app.py"]]
    assert any("ready for your review" in x for x in K.sent)
    CD_row = K.c.execute("select task from step_refs where kind='build' and ref=?", (str(bid),)).fetchone()
    assert CD_row["task"] == t                                       # the board shows it as this task's step


def test_a_change_whose_checks_failed_cannot_be_approved(K):
    t = req(K, "S")
    to_green(K, t)
    row = TK.row(K.c, t)
    TK.put(K.c, t, spec={**row["spec"], "change": {**row["spec"]["change"], "judge": {"ok": False, "counts": {"failed": 1}}}})
    bid = through_deliver(K, t)
    assert "PASSED" not in K.c.execute("select checks from builds where id=?", (bid,)).fetchone()[0]


def test_nothing_ends_without_the_owner_and_his_merge_ends_the_step(K):
    t = req(K, "S")
    to_green(K, t)
    bid = through_deliver(K, t)
    K.c.execute("update builds set status='deployed', merged='abcdef123456' where id=?", (bid,))
    K.c.commit()
    out = run(K, t, step(K, t, "change-deliver"))
    assert "deployed" in out and TK.row(K.c, t)["spec"]["change"]["outcome"] == "deployed"


def test_request_changes_reruns_the_coder_and_every_step_after_it_and_becomes_a_lesson(K, monkeypatch):
    t = req(K, "S")
    to_green(K, t)
    noted = []
    monkeypatch.setattr(CH, "RW_note", lambda repo, ch, text, ev: noted.append((text, ev)))
    bid = through_deliver(K, t)
    row = TK.row(K.c, t)
    TK.put(K.c, t, spec={**row["spec"], "budget": {"tokens": 1, "hours": 6}})
    r = B.handle({"action": "build_revise", "id": bid, "feedback": "Use the date helper"}, K.c)
    assert r["task"] == t and K.c.execute("select status from builds where id=?", (bid,)).fetchone()[0] == "cancelled"
    coder = next(s for s in steps(K, t) if s["agent"] == "builder")
    assert coder["status"] == "pending" and "Use the date helper" in coder["resume"]["feedback"]
    assert step(K, t, "change-judge")["status"] == "pending" and step(K, t, "change-review")["status"] == "pending"
    d = step(K, t, "change-deliver")
    assert d["status"] == "pending" and d["resume"] == {}
    assert noted == [("Use the date helper", f"the owner's review of change #{t}")]
    assert TK.row(K.c, t)["spec"]["budget"]["hours"] >= 6            # his reading time is not the change's


def test_a_rejection_is_a_lesson_and_the_change_ends_with_it(K, monkeypatch):
    t = req(K, "S")
    to_green(K, t)
    noted = []
    monkeypatch.setattr(CH, "RW_note", lambda repo, ch, text, ev: noted.append(text))
    monkeypatch.setattr(B, "close_pr", lambda *a: None)
    monkeypatch.setattr(B, "idea_follows", lambda *a: None)
    bid = through_deliver(K, t)
    B.handle({"action": "build_reject", "id": bid, "reason": "wrong idea"}, K.c)
    assert "wrong idea" in noted[0]
    assert "rejected" in run(K, t, step(K, t, "change-deliver"))


def test_the_scribe_folds_the_retro_and_its_failure_never_fails_the_change(K, monkeypatch):
    t = req(K, "S")
    row = TK.row(K.c, t)
    TK.put(K.c, t, spec={**row["spec"], "change": {**row["spec"]["change"], "report": "THE REPORT", "outcome": "merged"}})
    card = {"key": "vk-scribe"}
    monkeypatch.setenv("VK_SCRIBE", "k")
    assert "no wiki yet" in run(K, t, step(K, t, "change-scribe"), card)
    monkeypatch.setattr(RW, "exists", lambda n: True)
    monkeypatch.setattr(RW, "lines_without_evidence", lambda n: [])
    seen = {}
    monkeypatch.setattr(RW, "fold", lambda name, text, rel, key=None: seen.update(name=name, text=text, rel=rel) or ["lessons"])
    out = run(K, t, step(K, t, "change-scribe"), card)
    assert "1 pages: lessons" in out and out.startswith("THE REPORT") and seen["name"] == "demo" and "merged" in seen["text"] and (K.tmp / "vault" / seen["rel"]).exists()

    def boom(*a, **k):
        raise RuntimeError("the gateway is down")
    monkeypatch.setattr(RW, "fold", boom)
    assert "not written: RuntimeError" in run(K, t, step(K, t, "change-scribe"), card)


def test_a_trial_arm_without_the_wiki_neither_reads_nor_writes_it(K, monkeypatch):
    t = req(K, "S", no_wiki=True)
    monkeypatch.setattr(RW, "opening", lambda *a, **k: pytest.fail("the arm reads no wiki"))
    assert "leaves it as it is" in run(K, t, step(K, t, "change-scribe"), {"key": "vk-scribe"})
    assert CH.memory_of(TK.row(K.c, t)["spec"]["change"], "demo", "fresh-role-with-no-journal") == ""


# ---------- budgets and stops ----------
def test_a_stopped_change_goes_on_from_there_with_its_budget_doubled(K):
    t = req(K, "S")
    s = step(K, t, "change-judge")
    CD.put(K.c, s["id"], status="failed", error="not started: its budget is spent", attempts=2)
    TK.put(K.c, t, status="failed", error="spent")
    r = CH.handle({"action": "change_resume", "id": t}, K.c)
    row = TK.row(K.c, t)
    assert row["status"] == "running" and row["error"] is None and r["budget"]["tokens"] == CH.BUDGETS["S"]["tokens"] * 2
    assert step(K, t, "change-judge")["status"] == "pending"


def test_the_report_and_the_wiki_come_even_at_a_spent_budget(K):
    assert {"change-deliver", "change-scribe"} == set(CD.KINDS.even_spent)
    src = (ROOT / "ops/conductor.py").read_text()
    assert 'if s["harness"] in KINDS.even_spent' in src
    assert CH.BUDGETS["S"]["tokens"] < CH.BUDGETS["M"]["tokens"] < CH.BUDGETS["L"]["tokens"]


def test_a_rule_of_the_owner_s_goes_to_the_wiki_or_says_there_is_none(K, monkeypatch):
    with pytest.raises(ValueError, match="no wiki yet"):
        CH.handle({"action": "change_rule", "repo": "demo", "text": "Never use tabs here"}, K.c)
    got = []
    monkeypatch.setattr(RW, "lesson", lambda repo, text, ev, rule=False: got.append((repo, text, rule)) or "conventions")
    CH.handle({"action": "change_rule", "repo": "demo", "text": "Never use tabs here"}, K.c)
    assert got == [("demo", "Never use tabs here", True)]


# ---------- reading a test run ----------
def test_a_test_run_is_read_by_name_in_the_languages_the_stack_builds():
    r = CH.read_run(1, "FAILED tests/a.py::t_1 - x\nERROR tests/b.py - y\n2 failed, 3 passed")
    assert r["failed"] == ["tests/a.py::t_1", "tests/b.py"] and r["counts"]["passed"] == 3 and r["counts"]["failed"] == 2
    assert CH.read_run(1, "--- FAIL: TestThing (0.00s)\nFAIL\tgithub.com/x/y\t0.1s\n")["failed"] == ["TestThing", "github.com/x/y"]
    assert CH.read_run(2, "something else broke")["failed"] == ["(the test command failed: no test named)"]
    assert CH.read_run(0, "5 passed")["failed"] == []


def test_one_test_runs_by_its_id_and_a_hostile_id_never_reaches_a_shell():
    assert CH.one_command({}, "tests/a.py::t") == "pytest -q tests/a.py::t"
    assert CH.one_command({"test_one": "npx vitest {id}"}, "src/a.test.ts") == "npx vitest src/a.test.ts"
    assert CH.one_command({}, "pkg/a_test.go::TestX") == "go test ./pkg -run '^TestX$'"
    assert CH.one_command({}, "tests/a.py; rm -rf /") is None
    assert CH.one_command({}, "$(whoami)") is None
    assert CH.one_command({}, "thing.ts") is None


def test_the_step_lines_are_read_from_summaries():
    ss = [{"agent": "tester", "output": "Summary\nC1: tests/a.py::t\n- `C2`: `tests/b.py::u`\nunrelated: x"}, {"agent": "builder", "output": "C1: other.py::x\nC3: tests/c.py::v"}]
    assert CH.acceptance_of(ss) == {"C1": "tests/a.py::t", "C2": "tests/b.py::u", "C3": "tests/c.py::v"}


# ---------- the doors ----------
def test_the_app_and_the_chat_reach_it():
    server = (ROOT / "images/mission-control/server.py").read_text()
    for a in ("change_request", "change_go", "change_resume", "change_rule"):
        assert f'"{a}"' in server and a in CH.ACTIONS
    assert "async def change_request(repo: str, request: str)" in server and "/api/change/{tid:int}/{name}" in server
    js = (ROOT / "images/mission-control/web/static/task.js").read_text()
    assert "change_go" in js and "change_resume" in js and "changeHtml(t)" in js
    assert 'action: "change_request"' in (ROOT / "images/mission-control/web/static/app.js").read_text()


def test_a_coding_task_with_a_repository_becomes_a_change_request_and_a_trial_s_does_not():
    src = (ROOT / "ops/tasks.py").read_text()
    assert 's["kind"] in ("coding", "change") and s["repo"]' in src and 'startswith("trial:")' in src and 'get("agents")' in src


def test_the_sandbox_carries_each_toolchain_and_reaches_only_package_registries():
    image = (ROOT / "images/builder/Dockerfile").read_text()
    for tool in ("golang-go", "cargo", "default-jdk-headless", "maven", "chromium", "pnpm@", "playwright=="):
        assert tool in image
    allow = (ROOT / "images/pkgproxy/allow-builder.txt").read_text().split()
    assert "^proxy\\.golang\\.org$" in allow and "^index\\.crates\\.io$" in allow and "^repo\\.maven\\.apache\\.org$" in allow
    assert not any("github" in x or x in ("^.*$", ".*") for x in allow)   # no general internet: a package registry or nothing
    for found in ("go.mod", "Cargo.toml", "pom.xml", "pnpm-lock.yaml"):
        assert found in B.DEFAULT_CHECK

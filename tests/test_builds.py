"""ops/builds.py: request validation and the approve path, including the automatic rollback (real git, fake deploy)."""
import pysrc
import datetime as dt
import json
import sqlite3
import subprocess
import types
from pathlib import Path

import pytest


def sh(*a, cwd=None):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def B(runner, monkeypatch):
    import builds
    monkeypatch.setattr(builds, "repos", lambda: ["ai-stack", "TestRepo"])
    return builds


def mem_db(B):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    B.table(c)
    return c


def test_assign_validates_and_names_the_branch(B):
    c = mem_db(B)
    with pytest.raises(ValueError):
        B.handle({"action": "build_assign", "repo": "nanoGPT", "title": "Do it", "description": "something long enough"}, c)
    with pytest.raises(ValueError):
        B.handle({"action": "build_assign", "repo": "ai-stack", "title": "x", "description": "short"}, c)
    r = B.handle({"action": "build_assign", "repo": "ai-stack", "title": "Copy markdown button", "description": "Add a button that copies"}, c)
    b = c.execute("select * from builds where id=?", (r["id"],)).fetchone()
    assert (b["status"], b["branch"]) == ("queued", f"builder/{r['id']}-copy-markdown-button")


def test_approve_requires_review_checks_and_green_ci(B, monkeypatch):
    c = mem_db(B)
    monkeypatch.setattr(B, "ci_status", lambda repo, sha: ci[0])
    ci = ["failure"]
    c.execute("insert into builds (id, repo, title, status, checks, ci) values (1, 'ai-stack', 't', 'review', ?, 'running')",
              ("x\nALL CHECKS PASSED\nchecks exit 0",))
    with pytest.raises(ValueError, match="CI failed"):               # the live CI state is asked, not the stale one
        B.handle({"action": "build_approve", "id": 1}, c)
    c.execute("update builds set ci='success', checks='ruff failed'")
    with pytest.raises(ValueError, match="checks"):
        B.handle({"action": "build_approve", "id": 1}, c)
    c.execute("update builds set checks='ALL CHECKS PASSED'")
    assert B.handle({"action": "build_approve", "id": 1}, c) == {"approved": True}
    with pytest.raises(ValueError):
        B.handle({"action": "build_approve", "id": 1}, c)    # not in review any more


def test_revise_needs_feedback(B):
    c = mem_db(B)
    c.execute("insert into builds (id, repo, title, status) values (1, 'ai-stack', 't', 'review')")
    with pytest.raises(ValueError):
        B.handle({"action": "build_revise", "id": 1, "feedback": ""}, c)
    B.handle({"action": "build_revise", "id": 1, "feedback": "use the existing button style"}, c)
    assert c.execute("select status, feedback from builds").fetchone()["status"] == "queued"


def repo_with_branch(tmp_path):
    origin = tmp_path / "origin.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    sh("git", "clone", "-q", str(origin), str(seed))
    (seed / "app.txt").write_text("v1\n")
    sh("git", "add", "-A", cwd=seed); sh("git", "commit", "-qm", "v1", cwd=seed); sh("git", "push", "-q", "origin", "main", cwd=seed)
    sh("git", "checkout", "-q", "-b", "builder/1-t", cwd=seed)
    (seed / "app.txt").write_text("v2\n")
    sh("git", "commit", "-qam", "v2", cwd=seed); sh("git", "push", "-q", "origin", "builder/1-t", cwd=seed)
    live = tmp_path / "live"
    sh("git", "clone", "-q", str(origin), str(live))
    return origin, live


@pytest.mark.parametrize("deploy_ok", [True, False])
def test_approved_build_merges_deploys_or_rolls_back(B, tmp_path, monkeypatch, deploy_ok):
    origin, live = repo_with_branch(tmp_path)
    monkeypatch.setattr(B, "WB", tmp_path / "wb")
    monkeypatch.setattr(B, "STACK", live)
    monkeypatch.setattr(B, "origin", lambda repo: str(origin))
    deploys = []
    def fake_deploy(old, new):
        deploys.append((live / "app.txt").read_text().strip())
        return (deploy_ok or len(deploys) > 1), "log", False
    monkeypatch.setattr(B, "run_deploy", fake_deploy)
    monkeypatch.setattr(B.M, "now", lambda: dt.datetime.now().astimezone())
    monkeypatch.setattr(B.M, "X", types.SimpleNamespace(telegram=lambda *a, **k: None, APP="x"))
    c = mem_db(B)
    c.execute("insert into builds (id, repo, title, status, branch) values (1, 'ai-stack', 'change', 'approved', 'builder/1-t')")
    B.deploy(c, c.execute("select * from builds where id=1").fetchone())
    status = c.execute("select status from builds").fetchone()["status"]
    log = sh("git", "log", "--format=%s", "main", cwd=origin).splitlines()
    assert "builder/1-t" not in sh("git", "branch", "-a", cwd=origin)            # branch deleted after merge
    if deploy_ok:
        assert status == "deployed" and deploys == ["v2"] and log[0] == "Merge build #1: change"
    else:
        assert status == "rolled_back" and deploys == ["v2", "v1"]
        assert log[0].startswith('Revert "Merge build #1') and (live / "app.txt").read_text().strip() == "v1"


def test_an_approval_given_while_ci_runs_ends_when_the_build_works_again(B):
    c = mem_db(B)
    for i in (1, 2):
        c.execute("insert into builds (id, repo, title, status, checks, ci, head, approve_on_ci, approved_at) "
                  "values (?, 'ai-stack', 't', 'review', 'ALL CHECKS PASSED', 'pending', 'aaa', 1, 'then')", (i,))
    B.handle({"action": "build_revise", "id": 1, "feedback": "use the other colour"}, c)
    B.handle({"action": "build_recheck", "id": 2}, c)
    rows = [tuple(r) for r in c.execute("select status, approve_on_ci, approved_at from builds order by id")]
    assert rows == [("queued", 0, None), ("recheck", 0, None)]       # the CI poll can no longer deploy the next head


def test_every_build_action_the_app_sends_reaches_the_builds_handler(B):
    import ast
    import missions
    tree = ast.parse(pysrc.server())
    sent = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "ACTIONS")
    assert {a for a in sent if a.startswith("build_")} <= missions.BUILD_ACTIONS   # build_switch_engine was once "no mission ''"


def deploy_setup(B, tmp_path, monkeypatch):
    origin, live = repo_with_branch(tmp_path)
    monkeypatch.setattr(B, "WB", tmp_path / "wb")
    monkeypatch.setattr(B, "STACK", live)
    monkeypatch.setattr(B, "origin", lambda repo: str(origin))
    monkeypatch.setattr(B.M, "now", lambda: dt.datetime.now().astimezone())
    monkeypatch.setattr(B.M, "X", types.SimpleNamespace(telegram=lambda *a, **k: None, APP="x"))
    return origin, live


def test_only_the_reviewed_head_is_merged(B, tmp_path, monkeypatch):
    origin, live = deploy_setup(B, tmp_path, monkeypatch)
    monkeypatch.setattr(B, "run_deploy", lambda old, new: pytest.fail("nothing may deploy"))
    c = mem_db(B)
    c.execute("insert into builds (id, repo, title, status, branch, head) values (1, 'ai-stack', 'change', 'approved', 'builder/1-t', ?)", ("0" * 40,))
    before = sh("git", "rev-parse", "main", cwd=origin)
    B.deploy(c, c.execute("select * from builds where id=1").fetchone())
    b = c.execute("select status, error from builds").fetchone()
    assert b["status"] == "review" and "not the reviewed" in b["error"] and sh("git", "rev-parse", "main", cwd=origin) == before


def test_a_clone_the_sandbox_rigged_is_refused_and_its_hooks_never_run(B, tmp_path, monkeypatch):
    origin, _ = repo_with_branch(tmp_path)
    wb = tmp_path / "wb"
    monkeypatch.setattr(B, "WB", wb)
    sh("git", "clone", "-q", str(origin), str(wb / "demo"))
    sh("git", "clone", "-q", str(origin), str(wb / "other"))
    path, mark = wb / "demo", tmp_path / "ran"
    hook = path / ".git/hooks/post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch {mark}\n")
    hook.chmod(0o755)
    B.git(path, "checkout", "-q", "-b", "x")                       # a plain clone works, and its hook stays off
    assert not mark.exists()
    for key, value in (("core.sshCommand", f"touch {mark}"), ("merge.x.driver", f"touch {mark}"), ("include.path", "/tmp/x"),
                       ("remote.origin.url", str(wb / "other")), ("remote.origin.uploadpack", "x"), ("branch.main.remote", "/tmp")):
        clean = sh("git", "-C", str(path), "config", "--get-all", key) if key == "remote.origin.url" else None
        sh("git", "-C", str(path), "config", key, value)
        with pytest.raises(RuntimeError, match="SEC-21"):
            B.git(path, "status")
        if clean:
            sh("git", "-C", str(path), "config", key, clean)
        elif key == "branch.main.remote":
            sh("git", "-C", str(path), "config", key, "origin")
        else:
            sh("git", "-C", str(path), "config", "--unset-all", key)
        B.git(path, "status")
    assert not mark.exists()


def old_branch(tmp_path, clash=False, merged_main=False):
    """A build branch (app.txt v1 -> v2) whose main has moved on since; optionally the builder already merged main once."""
    origin, _ = repo_with_branch(tmp_path)
    other = tmp_path / "other"
    sh("git", "clone", "-q", str(origin), str(other))
    for i in range(2 if merged_main else 1):
        (other / ("app.txt" if clash else f"new{i}.txt")).write_text(f"main moved on {i}\n")
        sh("git", "add", "-A", cwd=other); sh("git", "commit", "-qm", f"newer work on main {i}", cwd=other)
        sh("git", "push", "-q", "origin", "main", cwd=other)
        if merged_main and i == 0:
            wb0 = tmp_path / "wb0"
            sh("git", "clone", "-q", str(origin), str(wb0)); sh("git", "checkout", "-q", "builder/1-t", cwd=wb0)
            sh("git", "merge", "-q", "--no-edit", "origin/main", cwd=wb0); sh("git", "push", "-q", "origin", "builder/1-t", cwd=wb0)
    wb = tmp_path / "wb"
    sh("git", "clone", "-q", str(origin), str(wb)); sh("git", "checkout", "-q", "builder/1-t", cwd=wb)
    return wb


@pytest.mark.parametrize("clash,merged_main", [(False, False), (False, True), (True, False)])
def test_an_old_build_branch_gets_todays_main(B, tmp_path, clash, merged_main):
    wb = old_branch(tmp_path, clash, merged_main)
    base, head, conflict, leftovers = B.onto_main(wb, "main")
    assert (conflict, leftovers) == (clash, 0)
    if not clash:                                                   # the diff for review is only the build's own change
        assert base == sh("git", "rev-parse", "origin/main", cwd=wb)
        assert sh("git", "diff", "--name-only", f"{base}..{head}", cwd=wb).split() == ["app.txt"]
    else:
        assert sh("git", "status", "--porcelain", cwd=wb) == ""          # merge aborted cleanly


def test_uncommitted_builder_leftovers_are_set_aside(B, tmp_path):
    wb = old_branch(tmp_path)
    (wb / "app.txt").write_text("half-finished edit\n")
    (wb / "stray.test.cjs").write_text("// untracked\n")
    base, head, conflict, leftovers = B.onto_main(wb, "main")
    assert (conflict, leftovers) == (False, 2)
    assert sh("git", "status", "--porcelain", cwd=wb) == "" and (wb / "app.txt").read_text() == "v2\n"   # checks see the commit
    assert "uncommitted builder leftovers" in sh("git", "stash", "list", cwd=wb)


def test_empty_tool_call_streak(B):
    call = lambda args: {"kind": "call", "text": args}
    assert B.empty_streak([call('{"command": "ls"}'), call("{}"), {"kind": "error", "text": "x"}, call("{}")]) == 2
    assert B.empty_streak([call("{}")] * 3 + [call('{"path": "a"}')]) == 0
    assert B.empty_streak([]) == 0


@pytest.mark.parametrize("path,flagged", [("AGENTS.md", True), ("tests/AGENTS.md", True), ("CLAUDE.md", True),
                                          ("images/litellm/patch_stream_args.py", True), ("compose/apps.yaml", True),
                                          ("ops/repos.py", False), ("README.md", False), ("docs/AGENTS-notes.md", False)])
def test_review_flags_sensitive_files(B, path, flagged):
    assert bool(B.SENSITIVE.search(path)) is flagged


CLAUDE_LOG = "\n".join(json.dumps(e) for e in [
    {"type": "system", "subtype": "init"},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Reading the code first."},
                                                  {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "git status"}},
                                                  {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "README.md"}}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "On branch main"},
                                             {"type": "tool_result", "tool_use_id": "t2", "is_error": True, "content": [{"type": "text", "text": "no such file"}]}]}},
    {"type": "result", "subtype": "success", "is_error": False, "num_turns": 7, "result": "## Summary\n- did it",
     "usage": {"input_tokens": 1200, "output_tokens": 300, "cache_creation_input_tokens": 50}}])


def test_claude_stream_becomes_steps_and_result(B):
    steps = B.claude_steps("noise line\n" + CLAUDE_LOG)
    assert [(s["kind"], s.get("tool")) for s in steps] == [("say", None), ("call", "Bash"), ("call", "Read"), ("result", "Bash"), ("error", "Read")]
    assert '"command": "git status"' in steps[1]["text"] and B.empty_streak(steps) == 0
    r = B.claude_result(CLAUDE_LOG)
    assert (r["turns"], r["tokens"], r["limit_reset"]) == (7, 1550, None) and r["text"].startswith("## Summary")


def test_claude_usage_limit_gives_the_reset_time(B):
    log = json.dumps({"type": "result", "is_error": True, "result": "Claude AI usage limit reached|1793200000"})
    assert B.claude_result(log)["limit_reset"] == 1793200000
    assert B.claude_result(json.dumps({"type": "result", "is_error": True, "result": "You've hit your limit"}))["limit_reset"] > 0


def test_engine_is_validated(B, monkeypatch):
    c = mem_db(B)
    req = {"action": "build_assign", "repo": "ai-stack", "title": "Do a thing", "description": "something long enough"}
    with pytest.raises(ValueError, match="engine"):
        B.handle({**req, "engine": "gpt9"}, c)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    with pytest.raises(ValueError, match="Claude Code is not connected"):
        B.handle({**req, "engine": "claude"}, c)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test")
    r = B.handle({**req, "engine": "claude"}, c)
    assert c.execute("select engine from builds where id=?", (r["id"],)).fetchone()["engine"] == "claude"


def test_the_other_engine_reviews(B, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "t")
    assert (B.reviewer_for("hermes"), B.reviewer_for("claude"), B.reviewer_for(None)) == ("claude", "hermes", "claude")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    assert B.reviewer_for("hermes") == "hermes"                   # Claude not connected: ChatGPT reviews


def test_review_verdicts_are_normalised(B, monkeypatch):
    monkeypatch.setattr(B.M, "now", lambda: dt.datetime(2026, 10, 28, 12, 0).astimezone())
    r = B.parse_review('Here it is: {"verdict": "block", "summary": "Leaks a key.", "findings": [{"severity": "high", '
                       '"file": "ops/x.py", "line": 12, "issue": "prints the token", "fix": "remove it"}, {"severity": "?", "issue": "nit"}, {"file": "a"}]}', "claude")
    assert (r["verdict"], r["engine"], len(r["findings"])) == ("block", "claude", 2)
    assert r["findings"][0]["line"] == 12 and r["findings"][1]["severity"] == "medium"
    assert B.parse_review('{"verdict": "maybe"}', "hermes")["verdict"] == "changes"
    assert "error" in B.parse_review("no json here", "hermes")


def test_both_engines_get_serena(B):
    from pathlib import Path
    cfg = json.loads(B.SERENA_FOR_CLAUDE)["mcpServers"]["serena"]
    assert cfg["command"] == "serena-mcp" and "claude-code" in cfg["args"]
    root = Path(B.__file__).resolve().parent.parent
    hermes = (root / "config/hermes/configure-builder.sh").read_text()
    assert "c mcp_servers.serena.command serena-mcp" in hermes and '"mcp-serena"' in hermes
    assert "serena-agent==" in (root / "images/builder/Dockerfile").read_text()


def test_builds_cut_off_by_a_runner_restart_are_resumed(B):
    c = mem_db(B)
    t = "2026-10-28T13:00:00+01:00"
    for st in ("working", "deploying", "review"):
        c.execute("insert into builds (repo, title, description, status, created, updated, attempts) values (?,?,?,?,?,?,1)",
                  ("ai-stack", st, "something long enough", st, t, t))
    c.commit()
    B.recover(c)
    got = {r["title"]: r["status"] for r in c.execute("select title, status from builds")}
    assert got == {"working": "waiting", "deploying": "failed", "review": "review"}
    assert c.execute("select retry_at from builds where title='working'").fetchone()[0]


def test_a_rate_limited_reviewer_hands_over_to_the_other_engine(B, monkeypatch, tmp_path):
    c = mem_db(B)
    t = "2026-10-28T13:00:00+01:00"
    c.execute("insert into builds (repo, title, description, status, created, updated, attempts, engine) values (?,?,?,?,?,?,1,?)",
              ("ai-stack", "x", "something long enough", "review", t, t, "claude"))
    c.commit()
    b = c.execute("select * from builds").fetchone()
    monkeypatch.setattr(B, "claude_ready", lambda: True)
    calls = []

    def fake(engine, *a):
        calls.append(engine)
        if engine == "hermes":
            raise RuntimeError("HTTP Error 429: Too Many Requests")
        return {"engine": engine, "verdict": "approve", "summary": "ok", "findings": []}
    monkeypatch.setattr(B, "review_with", fake)
    r = B.ai_review(c, b, tmp_path, "diff", True)
    assert sorted(calls) == ["claude", "claude", "hermes", "hermes"]       # each lens tried ChatGPT first, then Claude
    assert r["verdict"] == "approve" and r["same_engine"] and "usage limit" in r["note"]



def test_forgejo_connect_checks_then_stores_encrypted(runner, monkeypatch):
    import urllib.error
    import missions as M
    calls = []
    monkeypatch.setattr(M.subprocess, "Popen", lambda *a, **k: calls.append(("popen", a[0])))
    monkeypatch.setattr(M.subprocess, "run", lambda cmd, **k: calls.append((cmd, k.get("input"))) or types.SimpleNamespace(returncode=0))

    def refuse(*a, **k):
        raise urllib.error.HTTPError("u", 401, "no", {}, None)
    monkeypatch.setattr(M.urllib.request, "urlopen", refuse)
    with pytest.raises(ValueError, match="refused this token"):
        M.handle_forgejo_connect({"token": "a" * 40})
    assert not calls                                                       # nothing stored for a bad token

    class Resp:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, *a): return self.body
    monkeypatch.setattr(M.urllib.request, "urlopen", lambda r, timeout: Resp(b'{"login": "regenzeus"}' if r.full_url.endswith("/user") else b"[]"))
    assert M.handle_forgejo_connect({"token": "b" * 40}) == {"user": "regenzeus"}
    assert any(c[0][:2] == ["git", "commit"] for c in calls if c[0] != "popen")      # committed, so deploys keep working
    sops = next(c for c in calls if c[0] != "popen")
    assert sops[0][:3] == ["sops", "set", "--value-stdin"] and "b" * 40 not in " ".join(sops[0])   # never on the command line
    assert sops[1] == json.dumps("b" * 40)



def test_approve_all_takes_only_what_is_ready(B):
    c = mem_db(B)
    ids = []
    for title, checks, ci, verdict in (("ready one", "ALL CHECKS PASSED", "success", "approve"), ("checks failed", "FAILED", "success", None),
                                        ("ci pending", "ALL CHECKS PASSED", "pending", None), ("blocked by review", "ALL CHECKS PASSED", "success", "block"),
                                        ("ready two", "ALL CHECKS PASSED", "success", None)):
        r = B.handle({"action": "build_assign", "repo": "ai-stack", "title": title, "description": "something long enough"}, c)
        B.put(c, r["id"], status="review", checks=checks, ci=ci, ai_review=json.dumps({"verdict": verdict}) if verdict else None)
        ids.append(r["id"])
    out = B.handle({"action": "build_approve_all"}, c)
    assert out["approved"] == [ids[0], ids[2], ids[4]]
    assert [c.execute("select status from builds where id=?", (i,)).fetchone()[0] for i in ids] == ["approved", "review", "review", "review", "approved"]
    assert c.execute("select approve_on_ci from builds where id=?", (ids[2],)).fetchone()[0] == 1   # CI still running: deploys later


def test_approve_all_leaves_out_a_review_with_a_lens_not_done(B):
    """QA-26: the audit: a failed lens left "approve" standing, and `missing` was read nowhere. A review that failed whole, or
    is still going, is no look either; a build with no review record at all stays as it was."""
    c = mem_db(B)
    ids = []
    for rv in ({"verdict": "approve", "missing": []}, {"verdict": "incomplete", "missing": ["security"]}, {"verdict": "approve", "missing": ["security"]},
               {"error": "review not done: boom"}, {"pending": True}, None):
        r = B.handle({"action": "build_assign", "repo": "ai-stack", "title": "a build", "description": "something long enough"}, c)
        B.put(c, r["id"], status="review", checks="ALL CHECKS PASSED, but not run here: compose files valid", ci="success", ai_review=json.dumps(rv) if rv else None)
        ids.append(r["id"])
    assert B.handle({"action": "build_approve_all"}, c)["approved"] == [ids[0], ids[5]]
    B.handle({"action": "build_approve", "id": ids[1]}, c)                                 # your own look at the build still can
    assert c.execute("select status from builds where id=?", (ids[1],)).fetchone()[0] == "approved"


def test_switch_engine_allowed_and_refused(B, monkeypatch):
    c = mem_db(B)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test")
    c.execute("insert into builds (id, repo, title, status, engine, retry_at) values (1, 'ai-stack', 't', 'waiting', 'hermes', '2026-01-01T10:00:00')")
    B.handle({"action": "build_switch_engine", "id": 1, "engine": "claude"}, c)
    b = c.execute("select * from builds where id=1").fetchone()
    assert (b["status"], b["engine"]) == ("waiting", "claude")     # still waiting: run() resumes the unfinished worktree
    assert b["retry_at"] <= B.M.now().isoformat(timespec="seconds")
    c.execute("update builds set status='review'")                    # review: second attempt with the default feedback
    B.handle({"action": "build_switch_engine", "id": 1, "engine": "hermes"}, c)
    b = c.execute("select * from builds where id=1").fetchone()
    assert (b["status"], b["engine"]) == ("queued", "hermes")
    assert b["feedback"] == "Second attempt with ChatGPT · Hermes: continue from the current branch"
    c.execute("update builds set status='failed'")
    B.handle({"action": "build_switch_engine", "id": 1, "engine": "claude", "feedback": "try again, smaller"}, c)
    assert c.execute("select feedback from builds").fetchone()["feedback"] == "try again, smaller"
    for st in ("working", "deploying", "deployed", "merged"):
        c.execute("update builds set status=?", (st,))
        with pytest.raises(ValueError, match="cannot switch"):
            B.handle({"action": "build_switch_engine", "id": 1, "engine": "hermes"}, c)
    c.execute("update builds set status='queued'")
    with pytest.raises(ValueError, match="engine must be"):
        B.handle({"action": "build_switch_engine", "id": 1, "engine": "gpt9"}, c)
    with pytest.raises(ValueError, match="already uses"):
        B.handle({"action": "build_switch_engine", "id": 1, "engine": "claude"}, c)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    c.execute("update builds set engine='hermes'")
    with pytest.raises(ValueError, match="not connected"):
        B.handle({"action": "build_switch_engine", "id": 1, "engine": "claude"}, c)



def test_approve_while_ci_runs_deploys_when_it_passes(B, monkeypatch):
    c = mem_db(B)
    monkeypatch.setattr(B, "ci_status", lambda repo, sha: "running")
    c.execute("insert into builds (id, repo, title, status, checks, ci, head) values (1, 'ai-stack', 't', 'review', 'ALL CHECKS PASSED', 'running', 'abc')")
    assert B.handle({"action": "build_approve", "id": 1}, c) == {"approved": True, "when_ci_passes": True}
    row = c.execute("select status, approve_on_ci from builds where id=1").fetchone()
    assert (row["status"], row["approve_on_ci"]) == ("review", 1)              # waits for CI, then the poll deploys it



def test_both_engines_get_the_memory_tool_without_the_owner_s_facts(B):
    """MEM-28, MEM-30: the code graph reaches a coder through its opening and the memory tool, which holds none of the owner's facts."""
    import claude_tasks as CT
    cfg = json.loads(B.SERENA_FOR_CLAUDE)["mcpServers"]
    assert cfg["memory"]["url"] == "http://litellm:4000/mcp/" and "${LITELLM_BUILDER_KEY}" in cfg["memory"]["headers"]["Authorization"] and "graph" not in cfg
    assert "mcp__memory__memorypublic-search" in CT.MODES["ask"]["tools"] and "{graph}" not in CT.MODES["analyse"]["tools"]
    keys = (Path(__file__).resolve().parent.parent / "ops/keys.sh").read_text()
    assert '"vk-builder|gpt-sub,gpt-sub-fast|0.05|memorypublic"' in keys           # only the memory without the owner's facts, no vault or web
    conf = (Path(__file__).resolve().parent.parent / "config/hermes/configure-builder.sh").read_text()
    assert "mcp-memory" in conf and "mcp_servers.memory.url" in conf and "hermes config unset mcp_servers.graph" in conf


@pytest.mark.parametrize("also_code", [False, True])
def test_a_clash_only_in_the_generated_requirements_is_drawn_again(B, tmp_path, also_code):
    """Two builds that both change requirements clash in REQUIREMENTS.md, which is drawn from the yaml: render it again."""
    origin = tmp_path / "o.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(origin))
    a = tmp_path / "a"
    sh("git", "clone", "-q", str(origin), str(a))
    (a / "ops").mkdir(); (a / "requirements").mkdir()
    (a / "ops/req.py").write_text("import pathlib\npathlib.Path('requirements/REQUIREMENTS.md').write_text("
                                  "''.join(sorted(open(p).read() for p in pathlib.Path('requirements').glob('*.yaml'))))\n")
    (a / "requirements/REQUIREMENTS.md").write_text("start\n"); (a / "app.txt").write_text("v1\n")
    sh("git", "add", "-A", cwd=a); sh("git", "commit", "-qm", "v1", cwd=a); sh("git", "push", "-q", "origin", "main", cwd=a)
    sh("git", "checkout", "-q", "-b", "builder/1-t", cwd=a)
    (a / "requirements/x.yaml").write_text("build\n"); (a / "requirements/REQUIREMENTS.md").write_text("build\n")
    if also_code:
        (a / "app.txt").write_text("v2 from the build\n")
    sh("git", "add", "-A", cwd=a); sh("git", "commit", "-qm", "build", cwd=a); sh("git", "push", "-q", "origin", "builder/1-t", cwd=a)
    sh("git", "checkout", "-q", "main", cwd=a)
    (a / "requirements/y.yaml").write_text("main\n"); (a / "requirements/REQUIREMENTS.md").write_text("main\n")
    if also_code:
        (a / "app.txt").write_text("v2 from main\n")
    sh("git", "add", "-A", cwd=a); sh("git", "commit", "-qm", "main moved on", cwd=a); sh("git", "push", "-q", "origin", "main", cwd=a)
    sh("git", "checkout", "-q", "builder/1-t", cwd=a)
    base, head, conflict, _ = B.onto_main(a, "main")
    assert conflict is also_code                                     # a real clash elsewhere is still a conflict
    if also_code:
        assert sh("git", "status", "--porcelain", cwd=a) == ""
    else:
        assert (a / "requirements/REQUIREMENTS.md").read_text() == "build\nmain\n" and sh("git", "status", "--porcelain", cwd=a) == ""


@pytest.mark.parametrize("files, ran", [(["tests/test_a.py"], True), (["pkg/test_b.py"], True), (["README.md"], False)])
def test_a_repo_without_a_check_script_runs_its_tests(B, tmp_path, files, ran):
    """The default check finds tests as pytest does: a repo with only tests/ ran nothing and passed before (FND-94)."""
    import subprocess
    for f in files:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("def test_x():\n    pass\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "pytest").write_text("#!/bin/sh\necho '1 passed'\n")
    (bin_ / "pytest").chmod(0o755)
    out = subprocess.run(["sh", "-c", B.DEFAULT_CHECK], cwd=tmp_path, capture_output=True, text=True,
                         env={"PATH": f"{bin_}:/usr/bin:/bin"}).stdout
    assert ("1 passed" in out) is ran and ("no automatic checks" in out) is not ran
    assert out.strip().endswith("ALL CHECKS PASSED")

def test_the_checks_pass_only_on_exit_0_and_their_last_line(B):
    """Review RUN-R14: "PASSED" anywhere in the last 40 lines passed a build, its exit code unseen."""
    ok = "10 passed in 3s\nALL CHECKS PASSED\nchecks exit 0"
    assert B.checks_passed(ok)
    assert B.checks_passed(ok + "\n== requirements this build names (ops/req.py prove)\nREQUIREMENTS PROVEN")
    assert not B.checks_passed("FAILED tests/test_x.py - assert 'ALL CHECKS PASSED' in out\nALL CHECKS PASSED\nchecks exit 1")
    assert not B.checks_passed("E   assert 'PASSED' in log\n1 failed, 9 passed\nchecks exit 0")
    assert not B.checks_passed(ok.replace("ALL CHECKS PASSED", "CHECKS OK, REQUIREMENTS NOT PROVEN"))
    assert B.checks_passed("ALL CHECKS PASSED (the change's judge: 12 passed)\n\nthe tail")     # stored before, or a change's judge
    assert not B.checks_passed("x FAILED y PASSED") and not B.checks_passed("") and not B.checks_passed(None)


def test_the_checks_keep_their_exit_code_past_the_tail(B, monkeypatch):
    import subprocess
    real = subprocess.run
    monkeypatch.setattr(B, "CHECKS", {"demo": "echo one; echo ALL CHECKS PASSED; echo oops >&2; exit 3"})
    monkeypatch.setattr(B, "place", lambda repo, slot: repo)
    monkeypatch.setattr(B.subprocess, "run", lambda cmd, **kw: real(["sh", "-c", cmd[-1]], **kw))
    out = B.sandbox_checks("demo")
    assert out.strip().endswith("checks exit 3") and "oops" in out and not B.checks_passed(out)


def test_a_deployment_builds_its_local_repositories_in_the_stacks_own_copy(runner, tmp_path, monkeypatch):
    """GEN-18. A work site, 9 Nov 2026: its repositories are in ~/code from a bundle, their code must never go to Forgejo,
    and change requests accepted only Forgejo repositories. With BUILD_REPOS=local every repository in ~/code but the
    stack is buildable; its builds clone from and push to a bare copy the stack keeps outside the workbench; ~/code moves
    that copy's branches by fast-forward only; the stack never merges; a pull request goes to the forge only through the
    deployment's push remote, from a fork when that is another repository."""
    import builds as B
    code, wb, origins = tmp_path / "code", tmp_path / "wb", tmp_path / "origins"
    (code / "plugin").mkdir(parents=True)
    sh("git", "init", "-q", "-b", "main", cwd=code / "plugin")
    (code / "plugin/a.txt").write_text("one\n")
    sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=code / "plugin")
    sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "one", cwd=code / "plugin")
    sh("git", "remote", "add", "origin", "ssh://bitbucket.example.com:7999/PROJ/plugin.git", cwd=code / "plugin")
    monkeypatch.setattr(B, "CODE", code)
    monkeypatch.setattr(B, "WB", wb)
    monkeypatch.setattr(B, "ORIGINS", origins)
    monkeypatch.setitem(B.DEPLOY.VALUES, "BUILD_REPOS", "forgejo")
    assert "plugin" not in B.repos()
    monkeypatch.setitem(B.DEPLOY.VALUES, "BUILD_REPOS", "local")
    assert "plugin" in B.repos() and B.is_local("plugin") and not B.is_local("ai-stack")
    bare = B.source("plugin")
    assert bare == str(origins / "plugin.git") and wb not in Path(bare).parents and B.origin_ok(bare)
    work = tmp_path / "work"
    sh("git", "clone", "-q", bare, str(work))
    (work / "a.txt").write_text("two\n")
    sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "the build", cwd=work)
    sh("git", "push", "-q", "origin", "HEAD:refs/heads/main", cwd=work)          # a build moved main in the copy
    (code / "plugin/b.txt").write_text("other\n")
    sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=code / "plugin")
    sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "upstream", cwd=code / "plugin")
    B.source("plugin")
    assert sh("git", "-C", bare, "log", "-1", "--format=%s", "main") == "the build"   # not overwritten by ~/code
    src = (Path(B.__file__)).read_text()
    assert src.count("source(repo)") >= 3 and 'if is_local(repo):                                    # GEN-18' in src
    assert 'draft=not FG.may_merge() or is_local(b["repo"]), from_repo=from_repo' in src and "FORGE_PUSH" in src


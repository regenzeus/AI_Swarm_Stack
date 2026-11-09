"""ops/claude_tasks.py: Hermes' questions to Claude Code — validation, read-only command, live steps with thinking, limits."""
import io
import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def CT(runner, monkeypatch, tmp_path):
    import builds as B
    import claude_tasks as CT
    import missions as M
    CT.M, CT.B = M, B
    monkeypatch.setattr(CT, "OUT", tmp_path / "claude")
    monkeypatch.setattr(CT, "TMP", tmp_path / "tasks")
    monkeypatch.setattr(B, "repos", lambda: ["ai-stack"])
    monkeypatch.setattr(B, "CODE", tmp_path / "code")
    monkeypatch.setattr(B, "claude_ready", lambda: True)
    return CT


def mem(CT):
    import sqlite3
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    CT.table(c)
    return c


STREAM = [
    {"type": "assistant", "message": {"usage": {"input_tokens": 100, "cache_read_input_tokens": 900, "output_tokens": 40},
                                      "content": [{"type": "thinking", "thinking": "The rollback lives in deploy()."},
                                                  {"type": "tool_use", "id": "t1", "name": "Grep", "input": {"pattern": "revert"}}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ops/builds.py:640: git revert"}]}},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "It reverts the merge and redeploys."}]}},
    {"type": "result", "result": "It reverts the merge and redeploys.", "num_turns": 3, "usage": {"input_tokens": 100, "output_tokens": 40}},
]


def test_requests_are_validated(CT):
    c = mem(CT)
    with pytest.raises(ValueError):
        CT.handle({"action": "claude_task", "question": "hi"}, c)
    with pytest.raises(ValueError):
        CT.handle({"action": "claude_task", "question": "How does the deploy roll back?", "mode": "write"}, c)
    with pytest.raises(ValueError):
        CT.handle({"action": "claude_task", "question": "How does the deploy roll back?", "repo": "secret-repo"}, c)
    r = CT.handle({"action": "claude_task", "question": "How does the deploy roll back?", "repo": "ai-stack"}, c)
    assert c.execute("select status, mode from claude_tasks where id=?", (r["id"],)).fetchone()[:] == ("queued", "ask")


def test_steps_show_thinking_tools_and_tokens(CT):
    steps, tok = CT.steps_of([(1.0, json.dumps(e)) for e in STREAM])
    assert [s["kind"] for s in steps] == ["think", "call", "result", "say"]
    assert steps[1]["title"] == "Grep" and tok == {"in": 1000, "out": 40, "cached": 900}


def test_a_run_is_read_only_and_answers(CT, monkeypatch):
    c = mem(CT)
    tid = CT.handle({"action": "claude_task", "question": "Summarise this text for the owner please.", "context": "some long text"}, c)["id"]
    seen = {}

    class FakeP:
        def __init__(self, cmd, **kw):
            seen["cmd"] = cmd
            self.stdout = io.StringIO("\n".join(json.dumps(e) for e in STREAM) + "\n")
        def wait(self, timeout=None):
            return 0
        def kill(self):
            pass
    monkeypatch.setattr(CT.subprocess, "Popen", FakeP)
    CT.run(c, dict(c.execute("select * from claude_tasks where id=?", (tid,)).fetchone()))
    cmd = seen["cmd"]
    assert cmd[cmd.index("--allowedTools") + 1].split(",")[:3] == ["Read", "Grep", "Glob"] and "Bash" not in cmd[cmd.index("--allowedTools") + 1]
    assert "Edit" in cmd[cmd.index("--disallowedTools") + 1] and "Write" in cmd[cmd.index("--disallowedTools") + 1]
    assert "-e" in cmd and "CLAUDE_CODE_OAUTH_TOKEN" in cmd and not any("sk-ant" in x for x in cmd)     # passed by name only
    row = c.execute("select status, answer, turns from claude_tasks where id=?", (tid,)).fetchone()
    assert row[:] == ("done", "It reverts the merge and redeploys.", 3)
    doc = json.loads((CT.OUT / f"{tid}.json").read_text())
    assert any(s["kind"] == "think" for s in doc["steps"]) and "context" not in doc
    assert not (CT.TMP / str(tid)).exists()                                                           # the copy is gone


def test_a_usage_limit_waits_for_the_reset(CT, monkeypatch):
    c = mem(CT)
    tid = CT.handle({"action": "claude_task", "question": "Explain the build pipeline to the owner.", "context": "x"}, c)["id"]
    limit = [{"type": "result", "is_error": True, "result": "Claude AI usage limit reached|1900000000"}]

    class FakeP:
        def __init__(self, cmd, **kw):
            self.stdout = io.StringIO(json.dumps(limit[0]) + "\n")
        def wait(self, timeout=None):
            return 1
        def kill(self):
            pass
    monkeypatch.setattr(CT.subprocess, "Popen", FakeP)
    CT.run(c, dict(c.execute("select * from claude_tasks where id=?", (tid,)).fetchone()))
    assert c.execute("select status from claude_tasks where id=?", (tid,)).fetchone()[0] == "waiting"



def test_evidence_is_validated_gathered_and_put_next_to_the_question(CT, monkeypatch):
    c = mem(CT)
    with pytest.raises(ValueError, match="evidence"):
        CT.handle({"action": "claude_task", "question": "Why did the RAM mission fail?", "evidence": "rm -rf /"}, c)
    tid = CT.handle({"action": "claude_task", "question": "Why did the RAM mission fail?", "evidence": "mission:ram, minutes:30"}, c)["id"]
    asked = {}
    monkeypatch.setattr(CT, "gather", lambda spec: asked.setdefault("spec", spec) and "## mission:ram\n10:01 error 429 usage_limit_reached")
    seen = {}

    class FakeP:
        def __init__(self, cmd, **kw):
            seen["cmd"] = cmd
            seen["ev"] = (CT.TMP / str(tid) / "evidence.md").read_text()
            self.stdout = io.StringIO("\n".join(json.dumps(e) for e in STREAM) + "\n")
        def wait(self, timeout=None):
            return 0
        def kill(self):
            pass
    monkeypatch.setattr(CT.subprocess, "Popen", FakeP)
    CT.run(c, dict(c.execute("select * from claude_tasks where id=?", (tid,)).fetchone()))
    assert asked["spec"] == "mission:ram, minutes:30" and "usage_limit_reached" in seen["ev"]
    assert "evidence.md" in seen["cmd"][seen["cmd"].index("-p") + 1]


def test_evidence_for_reads_each_ref_and_redacts(monkeypatch):
    import crew
    import doctor as D
    D.C = crew
    monkeypatch.setattr(D, "evidence", lambda i: f"## {i['id']} kind={i['kind']} slug={i['slug']} run={i['run']} token=abcdefgh12345")
    monkeypatch.setattr(D, "window_evidence", lambda m, b=0: f"## last {m} minutes")
    out = D.evidence_for("mission:ram, run:hermes:main:b3, minutes:15, crew:nobody, what")
    assert "kind=mission slug=ram" in out and "run=hermes:main:b3" in out and "last 15 minutes" in out
    assert "no crew agent 'nobody'" in out and "not understood" in out and "abcdefgh12345" not in out


def test_a_task_s_copy_is_one_commit_with_the_release_tags_before_it(tmp_path):
    """Overnight exercise, 8 Nov 2026: sympy imports only from a git checkout whose `git describe` names a release; a Claude
    task's plain copy made the scribe write a version shim. The copy is one commit, tagged, with no history."""
    import claude_tasks as CT
    src = tmp_path / "src"
    src.mkdir()
    g = lambda *a: subprocess.run(["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    g("init", "-q")
    (src / "a.py").write_text("x = 1" + chr(10))
    g("add", "a.py")
    g("commit", "-q", "-m", "one")
    g("tag", "proj-1.0")
    g("tag", "1.0")
    (src / "a.py").write_text("x = 2" + chr(10))
    g("commit", "-qam", "two")
    dest = tmp_path / "copy"
    dest.mkdir()
    (dest / "a.py").write_text("x = 2" + chr(10))
    CT.one_commit(dest, src, "HEAD")
    tags = subprocess.run(["git", "-C", str(dest), "tag"], capture_output=True, text=True).stdout.split()
    assert sorted(tags) == ["1.0", "proj-1.0"]
    assert subprocess.run(["git", "-C", str(dest), "rev-list", "--count", "HEAD"], capture_output=True, text=True).stdout.strip() == "1"


def test_a_cancelled_task_cancels_the_claude_tasks_its_steps_started(tmp_path):
    """Overnight exercise, 8 Nov 2026: a cancelled exam change's Claude task was asked again after a restart and ran on."""
    import sqlite3
    import claude_tasks as CT
    c = sqlite3.connect(tmp_path / "m.sqlite")
    c.row_factory = sqlite3.Row
    CT.table(c)
    for i, (src, st) in enumerate((("task:243:step:1", "running"), ("task:243:step:4", "queued"), ("task:244:step:1", "running"),
                                   ("chat", "running"), ("task:243:step:2", "done")), 1):
        c.execute("insert into claude_tasks (id, question, status, source, created) values (?, 'q', ?, ?, '2026-11-08')", (i, st, src))
    c.commit()
    assert CT.cancel_for(c, 243) == 2
    got = {r["id"]: r["status"] for r in c.execute("select id, status from claude_tasks")}
    assert got == {1: "cancelled", 2: "cancelled", 3: "running", 4: "running", 5: "done"}
    src = Path(CT.__file__).read_text()
    assert "if M.stop.is_set() or cancelled:" in src                             # a running one stops at its next live update


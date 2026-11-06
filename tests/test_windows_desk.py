"""The Windows desk (PLT-31, PLT-32, DEC-43): the stack asks, Windows fetches, and nothing from a request is ever run."""
import json
import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ops"))
WIN = ROOT / "ops/windows"
DESK = (WIN / "desk.ps1").read_text()
REMOTE = (WIN / "claude-remote.ps1").read_text()


@pytest.fixture
def WD(tmp_path, monkeypatch):
    import windows_desk as wd
    monkeypatch.setattr(wd, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(wd, "ANSWERS", tmp_path / "answers")
    monkeypatch.setattr(wd, "OUT", tmp_path / "out")
    wd.ANSWERS.mkdir()
    (wd.ANSWERS / "status.json").write_text("\ufeff" + json.dumps({"ts": time.time(), "free_gb": 4}))   # PowerShell may write a BOM
    return wd


def test_a_question_is_left_in_the_folder_and_its_answer_published(WD):
    r = WD.handle({"source": "chat", "question": "What does this do?", "folder": "C:\\Programming\\x"})
    rid = r["id"]
    assert re.fullmatch(r"[a-f0-9]{12}", rid)
    asked = json.loads((WD.INBOX / f"{rid}.json").read_text())
    assert asked["question"] == "What does this do?" and asked["folder"] == "C:\\Programming\\x" and set(asked) == {"question", "folder", "at"}
    assert json.loads((WD.OUT / f"{rid}.json").read_text())["status"] == "queued"
    (WD.ANSWERS / f"{rid}.json").write_text(json.dumps({"id": rid, "status": "running", "folder": "C:\\Programming\\x"}))
    WD.step()
    assert json.loads((WD.OUT / f"{rid}.json").read_text())["status"] == "running"
    (WD.ANSWERS / f"{rid}.json").write_text(json.dumps({"id": rid, "status": "done", "answer": "It reads files.", "ended": int(time.time())}))
    WD.step()
    t = json.loads((WD.OUT / f"{rid}.json").read_text())
    assert t["status"] == "done" and t["answer"] == "It reads files." and t["question"] == "What does this do?"
    assert json.loads((WD.OUT / "status.json").read_text())["free_gb"] == 4


def test_a_silent_desk_is_said_not_waited_for(WD):
    assert WD.handle({"source": "app", "question": "x"}) == {"ok": False, "error": "asked only from a chat"}
    assert WD.handle({"source": "chat", "question": " "})["error"] == "no question"
    assert "characters" in WD.handle({"source": "chat", "question": "x" * (WD.QUESTION_MAX + 1)})["error"]
    rid = WD.handle({"source": "chat", "question": "q"})["id"]
    WD.step(time.time() + WD.PICKUP_S + 1)                          # asleep: the question does not wait for ever, nor run hours later
    t = json.loads((WD.OUT / f"{rid}.json").read_text())
    assert t["status"] == "failed" and "asleep" in t["error"] and not (WD.INBOX / f"{rid}.json").exists()
    (WD.ANSWERS / "status.json").write_text(json.dumps({"ts": time.time() - 300}))
    assert "not answering" in WD.handle({"source": "chat", "question": "q"})["error"]
    rid2 = "a" * 12
    (WD.OUT / f"{rid2}.json").write_text(json.dumps({"id": rid2, "status": "running", "at": 0, "picked": 0}))
    WD.step(time.time())
    assert json.loads((WD.OUT / f"{rid2}.json").read_text())["status"] == "failed"
    (WD.OUT / "not-an-id.json").write_text("{}")                    # a stray file is left alone
    WD.step()


def test_only_your_own_chat_can_ask():
    server = (ROOT / "images/mission-control/server.py").read_text()
    assert '"windows_ask"' in server.split("ACTIONS = {", 1)[1].split("}", 1)[0]
    assert 'str(body.get("action", "")).startswith("windows_")' in server                # no screen or device asks through /api/request
    for tool in ("windows_status", "windows_ask"):
        body = server.split(f"async def {tool}(", 1)[1].split("@mcp.tool", 1)[0]
        assert "if not owner_chat_running():" in body
    fn = server.split("def owner_chat_running():", 1)[1].split("@mcp.tool", 1)[0]
    assert '.get("origin") in (None, "owner")' in fn                                     # not the stack's checks, helpers or the AI phone
    assert server.index("async def windows_ask(") > server.index('mcp = MCPServer("missions")')
    assert server.index("async def windows_ask(") < server.index('files_mcp = MCPServer("files")')
    cards = (ROOT / "config/agents.yaml").read_text()
    assert len(re.findall(r"tools: \[[^\]]*\bmissions\b", cards)) == 1                   # that server is your assistant's alone
    assert 're.fullmatch(r"[a-f0-9]{12}", id or "")' in server                           # an id is no path


def test_the_desk_gives_claude_reading_tools_only_and_runs_nothing_from_a_request():
    assert '--tools "Read,Grep,Glob"' in DESK and "--permission-mode dontAsk" in DESK and "--strict-mcp-config" in DESK and '--setting-sources ""' in DESK
    assert "--dangerously" not in DESK and "bypassPermissions" not in DESK and "Bash" not in DESK
    assert 'EnvironmentVariables.Remove("ANTHROPIC_API_KEY")' in DESK                    # the subscription, never a metered key
    assert "Invoke-Expression" not in DESK and "iex " not in DESK.lower() and "$req.question" not in DESK.split("function Start-Question")[1].split("function Stop-Tree")[0]
    assert "StandardInput.BaseStream.Write" in DESK                                      # the question goes in as text on stdin, not as an argument
    assert "Get-AllowedFolder" in DESK and "ReparsePoint" in DESK and "'\\.\\.'" in DESK and "$id -notmatch '^[a-f0-9]{12}$'" in DESK
    assert '$single.WaitOne(0)' in DESK and "$limitS = 900" in DESK and "$needGb = 1.75" in DESK
    settings = json.loads((WIN / "desk-settings.json").read_text())
    assert settings["disableAllHooks"] is True and settings["permissions"]["defaultMode"] == "dontAsk"
    assert settings["permissions"]["allow"] == ["Read(./**)", "Glob(./**)", "Grep(./**)"]
    assert all(x.startswith("Read(") for x in settings["permissions"]["deny"]) and "Read(**/.env)" in settings["permissions"]["deny"]
    assert "Bash" not in json.dumps(settings) and "Write" not in json.dumps(settings) and "Edit" not in json.dumps(settings)
    setup = (WIN / "desk-setup.ps1").read_text()
    assert "New-ScheduledTaskTrigger -AtLogOn" in setup and "RunLevel" not in setup and "desk-folders.txt" in setup
    assert "/srv/ai/state/windesk" not in (ROOT / "images/mission-control/server.py").read_text()   # the app never writes to the folder itself: the runner does (SEC-12)
    for script in WIN.glob("desk*.ps1"):
        for bad in ("&&", "||", " ?? "):
            assert bad not in script.read_text(), f"{script.name}: Windows PowerShell 5.1 has no {bad}"
    wsl = (ROOT / "ops/bootstrap-wsl-1-root.sh").read_text()
    assert re.search(r"\[interop\]\s*enabled=false", wsl)                                # interop stays off


def test_remote_control_keeps_one_server_and_passes_no_permission_flags():
    assert "'remote-control --name \"Windows PC\"'" in REMOTE and '$single.WaitOne(0)' in REMOTE and "[math]::Min($wait * 2, 300)" in REMOTE
    for bad in ("permission-mode", "dangerously", "bypass", "RedirectStandardOutput"):
        assert bad not in REMOTE                                                         # and no output kept: it holds the connection link
    setup = (WIN / "desk-setup.ps1").read_text()
    assert '"ai-stack Claude remote", "claude-remote.ps1"' in setup and '"ai-stack Windows desk", "desk.ps1"' in setup


def test_a_use_of_windows_is_a_line_on_the_map():
    sys.path.insert(0, str(ROOT / "images/mission-control"))
    import interactions as IX
    rows = [{"title": "mcp__vault__missions_windows_ask", "run": "m", "lane": "main", "ts": 5}, {"title": "mcp__vault__missions_status", "run": "m", "lane": "main", "ts": 6}]
    assert IX.tool_calls(rows) == [{"run": "m", "lane": "main", "node": "windows", "tool": "missions_windows_ask", "ts": 5}]

"""What the stack tells you, in plain words (OBS-19 to OBS-23). The owner's screenshots of 11 Nov 2026 showed, in Activity,
"mission told you · Workflows · Crew: Repository facts: failed (n8n run 4424) · Message to you · push · matched", a
systemd error pushed during a deploy that recovered a minute later, and the doctor's whole prompt to Claude: "Not great
information coming there. Barely readable." and "This should be professional, maybe used by many people"."""
import ast
import fcntl
import json
import re
import time
import types
from pathlib import Path

import pytest

import flows as FW
import interactions as IX
import notices as NT
import teamroom as TR

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "images/mission-control/web/static"
SWARM_JS = (STATIC / "swarm.js").read_text()
CREW = {"repofacts-sync": {"id": "repofacts-sync", "name": "Repository facts", "area": "upkeep", "unit": "repofacts-sync"}}
SYSTEMD = "Job for repofacts-sync.service failed because the control process exited with error code. See \"systemctl --user status repofacts-sync.service\" for details."
# the words the owner should never read in a notice or the app (the interaction design's wording rules)
NOTICE_WORDS = ("detector", "crew", "matched", "shadow", "mission told you", "n8n run", "Message to you")
APP_WORDS = ("detector", "matched", "mission told you", "n8n run")


@pytest.fixture
def owner_first_name():
    """The owner's first name, from this fixture only: nothing the stack ships needs it, so no setting holds it. Built
    from pieces, so the public snapshot keeps it (its swap would turn it into words the app rightly says)."""
    return "Ma" + "rc"


@pytest.fixture
def said(monkeypatch):
    """flows.report's missions.event, recorded: [(text, push, title, more)]."""
    out = []
    monkeypatch.setattr(FW, "M", types.SimpleNamespace(event=lambda kind, slug="", text="", push=False, title="", **k: out.append((text, push, title, k))))
    return out


def crew_step(execution="4424"):
    return {"kind": "crew", "job": "repofacts-sync", "title": "Crew: Repository facts", "workflow": "wf1", "execution": execution}


def test_a_failure_says_what_stopped_why_and_whether_to_act():
    f = NT.failure("Repository facts", SYSTEMD)
    assert f["text"] == "Repository facts couldn't run: its job stopped with an error. It needs a look: open it to see what went wrong."
    assert f["detail"] == SYSTEMD                                                        # the raw reason, one tap away
    assert NT.failure("Daily digest", "connection refused by litellm:4000")["text"].endswith(
        "a service it needs did not answer. Nothing to do: it tries again on its next run.")
    assert NT.failure("Daily digest", "the step timed out after 600 s")["text"] == \
        "Daily digest couldn't run: it took too long and was stopped. Nothing to do: it tries again on its next run."
    assert NT.failure("root", "no agent 'root'", state="refused")["text"] == \
        "root was not started: no agent 'root'. It needs a look: open it to see what went wrong."      # words stay words
    trace = "Traceback (most recent call last):\n  File \"/opt/x.py\", line 3\nKeyError: 'k'"
    assert NT.failure("X", trace)["text"] == "X couldn't run: it stopped with an error. It needs a look: open it to see what went wrong."
    assert NT.failure("X", "")["text"].startswith("X couldn't run: it stopped with an error.")


def test_a_step_s_failure_is_pushed_in_plain_words_under_its_area(said):
    FW.report(crew_step(), {"status": "failed", "error": SYSTEMD}, crew=CREW)
    [(text, push, title, more)] = said
    assert text.startswith("Repository facts couldn't run: its job stopped with an error.") and push and title == "Upkeep"
    assert more["area"] == "upkeep" and more["detail"] == f"{SYSTEMD}; n8n run 4424"      # the run's place behind the tap
    assert "Crew" not in text and "n8n" not in text and "failed (" not in text
    said.clear()
    FW.report(crew_step(), {"status": "done"}, crew=CREW)
    assert said == [("Repository facts ran fine.", False, "Upkeep", {"area": "upkeep", "task": None, "detail": "n8n run 4424", "by": "repofacts-sync"})]


def test_a_failure_during_an_update_that_recovers_is_one_quiet_line(said, monkeypatch):
    t0 = time.mktime((2026, 11, 11, 6, 20, 0, 0, 0, -1))
    monkeypatch.setattr(NT, "change", lambda now=None, **k: {"what": "update", "at": t0})
    FW.report(crew_step("4424"), {"status": "failed", "error": SYSTEMD}, crew=CREW, now=t0 + 30)
    assert said == []                                                                    # not pushed, not shown yet
    monkeypatch.setattr(NT, "change", lambda now=None, **k: None)
    FW.report(crew_step("4425"), {"status": "done"}, crew=CREW, now=t0 + 180)
    [(text, push, title, more)] = said
    assert text == "Repository facts couldn't run during the update at 06:20. It ran fine at 06:23."
    assert not push and more["quiet"] and title == "Upkeep"                                # one quiet line in Activity
    said.clear()
    FW.report(crew_step("4426"), {"status": "done"}, crew=CREW, now=t0 + 3600)
    assert said[0][0] == "Repository facts ran fine."                                    # settled once


def test_a_failure_during_an_update_that_does_not_recover_is_told_after_it(said, monkeypatch):
    t0 = time.mktime((2026, 11, 11, 6, 20, 0, 0, 0, -1))
    monkeypatch.setattr(NT, "change", lambda now=None, **k: {"what": "update", "at": t0})
    FW.report(crew_step(), {"status": "failed", "error": "connection refused"}, crew=CREW, now=t0 + 30)
    assert NT.due(FW.told_late, now=t0 + 60) == 0 and said == []                        # still within the wait
    assert NT.due(FW.told_late, now=t0 + 30 + NT.SETTLE_S) == 1
    [(text, push, title, more)] = said
    assert text == ("Repository facts couldn't run during the update at 06:20, and it has not run fine since: a service it needs "
                    "did not answer. Nothing to do: it tries again on its next run.")
    assert push and title == "Upkeep" and "n8n run 4424" in more["detail"]
    assert NT.due(FW.told_late, now=t0 + 2 * NT.SETTLE_S) == 0                            # told once


def test_a_change_is_known_from_the_deploy_lock_the_record_and_the_runner_start(tmp_path):
    now = time.time()
    lock, rec, recycle = tmp_path / "deploy.lock", tmp_path / "deploys.jsonl", tmp_path / "recycle.jsonl"
    kw = {"locks": [lock], "deploys": rec, "recycle": recycle, "started": 0}
    assert NT.change(now, **kw) is None
    lock.write_text("")
    with open(lock) as held:
        fcntl.flock(held, fcntl.LOCK_EX)                                                  # a deploy holds it
        assert NT.change(now, **kw)["what"] == "update"
    assert NT.change(now, **kw) is None                                                   # given back: no change
    rec.write_text(json.dumps({"ts": now - 7200, "ok": True}) + "\n" + json.dumps({"ts": now - 60, "ok": True}) + "\n")
    assert NT.change(now, **kw) == {"what": "update", "at": now - 60}
    assert NT.change(now + NT.AFTER_S, **kw) is None
    recycle.write_text(json.dumps({"ts": now + NT.AFTER_S - 30}) + "\n")
    assert NT.change(now + NT.AFTER_S, **kw)["what"] == "restart"
    assert NT.change(now, **{**kw, "deploys": tmp_path / "none", "recycle": tmp_path / "none", "started": now - 90}) == {"what": "restart", "at": now - 90}


def test_health_alerts_wait_while_the_stack_is_updated(monkeypatch):
    import crew as CR
    import stack_gate as SG
    monkeypatch.setattr(SG, "settled", lambda: True)
    monkeypatch.setattr(SG, "why_down", lambda: "")
    seen = []
    monkeypatch.setattr(NT, "change", lambda now=None, within=NT.AFTER_S, **k: seen.append(within) or None)
    assert not CR.quiet() and seen == [NT.SETTLE_S]                                       # alerts wait as long as a held failure
    monkeypatch.setattr(NT, "change", lambda now=None, within=NT.AFTER_S, **k: {"what": "update", "at": time.time()})
    assert CR.quiet()
    assert CR.area_label("repofacts-sync") == "Upkeep" and CR.area_label("memory") == "Memory"


def test_a_quiet_line_reaches_activity_and_is_never_pushed(runner):
    import notify as N
    N.TOLD.parent.mkdir(parents=True, exist_ok=True)
    runner.event("workflow", "", "Repository facts couldn't run during the update at 06:20. It ran fine at 06:23.", title="Upkeep",
                 area="upkeep", detail="n8n run 4425", task=7, quiet=True)
    [row] = [json.loads(x) for x in N.TOLD.read_text().splitlines()]
    assert row["channel"] == "activity" and row["decision"] == "quiet" and row["area"] == "upkeep" and row["task"] == 7
    ev = json.loads((runner.PUBLIC / "events.jsonl").read_text().splitlines()[-1])
    assert ev["push"] is False and ev["area"] == "upkeep"
    [line] = IX.tell_lines([row], 0)
    assert line["quiet"] and line["area"] == "upkeep" and line["detail"] == "n8n run 4425" and IX.task_of(line) == 7
    assert line["text"].startswith("Repository facts couldn't run during the update")


def test_an_agent_s_request_to_another_is_one_line_with_the_request_behind_a_tap():
    prompt = "Look at these 3 open health issues and say for each whether it is real.\n\n## Issue 1\n" + "evidence " * 300
    line = TR.ask_line({"ts": 1, "from": "doctor", "to": "claude", "ask": prompt, "answer": "Two are noise.", "run": "claude-task:9"})
    assert line["summary"] == "Look at these 3 open health issues and say for each whether it is real."
    assert line["text"] == prompt and line["words"] == len(prompt.split()) and line["verb"] == "asked"   # whole, behind the tap
    assert TR.gist("# Brief\n\nYou are the health doctor. " + "x" * 200) == "Brief"
    assert TR.gist("A first sentence that goes on " + "and on " * 40 + ".") == ""        # too long for one line: none
    room = SWARM_JS[SWARM_JS.index("function swRoomLine("):SWARM_JS.index("async function swChat(")]
    assert "The request${l.words ?" in room and "l.summary ? `: ${esc(l.summary)}`" in room
    assert "${l.text ? `<div class=\"small rtext\">${swFold(l.text, 600)}</div>` : \"\"}" not in room   # the prompt is not on the line


def test_activity_groups_lines_by_task_newest_first_with_area_labels():
    assert IX.task_of({"ref": {"task": 12}}) == 12 and IX.task_of({"ref": {"run": "task:31:step:2"}}) == 31
    assert IX.task_of({"ref": {"run": "crew:doctor:1"}}) is None
    room = SWARM_JS[SWARM_JS.index("async function swChat("):SWARM_JS.index("// A success check in plain words")]
    assert "const byTask = new Map();" in room and "byTask.get(k).push(l)" in room and "swTaskHead(ls[0])" in room
    assert 'ts.find((t) => t.door === "crew" && t.ref === l.actor)' in SWARM_JS                  # a crew job's lines go with its duty
    assert "Message to you" not in SWARM_JS and "AREAS[a]" in SWARM_JS and 'class="rtask-h"' in SWARM_JS
    tell = SWARM_JS[SWARM_JS.index("function swTellLine("):SWARM_JS.index("function swRoomLine(")]
    assert "swFold(l.text, 600)" in tell and "channels" not in tell and "matched" not in tell and "told" not in tell
    assert "rtask-h" in (STATIC / "app.css").read_text()


def _texts(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            yield n.value


def notice_templates():
    """The words of every event and message the runner writes: the text and title of each missions.event, flows' ev,
    notify.send and notify() call in ops/, as written in the code."""
    for p in sorted([*(ROOT / "ops").glob("*.py"), *(ROOT / "ops/domain").glob("*.py")]):
        for n in ast.walk(ast.parse(p.read_text())):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            base = getattr(f.value, "id", getattr(f.value, "attr", "")) if isinstance(f, ast.Attribute) else ""
            if name in ("event", "ev"):
                parts = n.args[2:3] + [k.value for k in n.keywords if k.arg in ("text", "title")]
            elif (name == "send" and base in ("N", "notify", "NOTIFY")) or (name == "notify" and isinstance(f, ast.Name)):
                parts = n.args[:1] + [k.value for k in n.keywords if k.arg == "title"]
            else:
                continue
            for a in parts:
                for t in _texts(a):
                    yield f"{p.relative_to(ROOT)}:{n.lineno}", t


def app_texts():
    """What the app says: its scripts without their comments and without one-word values compared in code
    ("matched" as a record's certainty is data), and the in-app guide."""
    for p in sorted(STATIC.glob("*.js")):
        s = re.sub(r"/\*[\s\S]*?\*/", "", p.read_text())
        s = re.sub(r"(^|[^:\\\"'`])//.*$", r"\1", s, flags=re.M)
        yield p.name, re.sub(r"([\"'])\w+\1", "", s)
    for p in sorted((ROOT / "images/mission-control/guide").glob("*.md")):
        yield p.name, p.read_text()
    for name in ("interactions.py", "teamroom.py"):                                     # the feed's own lines
        tree = ast.parse((ROOT / "images/mission-control" / name).read_text())
        docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        yield name, "\n".join(c.value for c in ast.walk(tree) if isinstance(c, ast.Constant) and isinstance(c.value, str) and " " in c.value and id(c) not in docs)


def test_no_owner_name_or_internal_words_in_notices_or_the_app(owner_first_name):
    name = re.compile(rf"\b{owner_first_name}\b")
    bad = [f"{w}: {t!r}" for w, t in notice_templates() if name.search(t)
           or any(re.search(rf"\b{re.escape(j)}\b", t, re.I) for j in NOTICE_WORDS)]
    assert len(list(notice_templates())) > 100 and not bad, bad
    app = ROOT / "images/mission-control"
    named = [str(p.relative_to(ROOT)) for p in app.rglob("*") if p.is_file() and p.suffix in (".py", ".js", ".md", ".html", ".css", ".json")
             and "vendor" not in p.parts and name.search(p.read_text(errors="replace"))]
    assert not named, named
    words = [(f, j) for f, s in app_texts() for j in APP_WORDS if re.search(rf"\b{re.escape(j)}\b", s, re.I)]
    assert not words, words

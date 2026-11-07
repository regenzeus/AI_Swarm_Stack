"""Journey checks (TSK-32, ops/journeys.py): each journey fails on the fault it is for. A route that scrolls sideways at
375 px, a broken make target and a mangled e-mail headline each fail the check; a task given in a sentence is followed
through the real intake, Conductor, judge and board to its result; a failed journey is an alert on the health board."""
import json

import pytest
import shutil
import re
import subprocess
from pathlib import Path

import journeys as JY

ROOT = Path(__file__).resolve().parent.parent


def route(**k):
    return {"route": "#/tasks", "overflow": 0, "wide": [], "chain": [], "main": "Tasks", "graphic": False, "skeleton": False,
            "cards": [], "empties": [], "formats": [], "errors": [], "actions": 3, **k}


def test_a_route_that_scrolls_sideways_at_375_px_and_each_other_screen_fault_fail_the_check():
    assert JY.judge_routes({"live": {"results": [route()]}, "empty": {"results": [route()]}}) == []
    got = JY.judge_routes({"live": {"results": [
        route(route="#/live/run:58", overflow=129, wide=["div.tiny.muted (2229 px)"], chain=["div#view[375px block]", "div.tiny.muted[2546px block]"]),
        route(route="#/wiki", errors=["ReferenceError: watch is not defined"]), route(route="#/share", main="", graphic=False),
        route(route="#/missions", cards=["RAM upgrade → #/mission/ram"]), route(route="#/build", formats=["2026-10-28T19:31:46Z"])],
        "errors": [{"route": "", "msg": "the app reported: boom"}]},
        "empty": {"results": [route(route="#/share", empties=["This shared item is gone"], actions=0)]}})
    assert got[0] == "the app reported an error: the app reported: boom"
    assert got[1] == "#/live/run:58 scrolls sideways at 375 px by 129 px (div.tiny.muted (2229 px); from div.tiny.muted[2546px block])"
    assert "#/wiki: a script error: ReferenceError: watch is not defined" in got and "#/share shows nothing" in got
    assert "#/missions: the card “RAM upgrade → #/mission/ram” does not open its page on a tap" in got
    assert "#/build shows “2026-10-28T19:31:46Z”, not the app's date and number format" in got
    assert "#/share (with no data): an empty state that offers no action: “This shared item is gone”" in got and "#/share (with no data) offers no action" in got


@pytest.mark.skipif(not shutil.which("make"), reason="make is not installed here (CI's runner has none); the builder runs this")
def test_a_broken_make_target_fails_the_check_and_every_real_target_dry_runs(tmp_path):
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops/here.py").write_text("")
    (tmp_path / "Makefile").write_text("X := 1\ngood:  ## fine\n\tpython3 ops/here.py\nbroken:  ## its script is gone\n\tpython3 ops/gone.py\n"
                                       "worse:\n\t$(error a rule that stops make)\n.PHONY: good\n")
    assert JY.targets(tmp_path / "Makefile") == ["good", "broken", "worse"]
    got = JY.check_make(tmp_path)
    assert got["checked"] == 3 and got["failures"][0] == "make broken names ops/gone.py, which does not exist"
    assert got["failures"][1].startswith("make worse does not run: ") and "a rule that stops make" in got["failures"][1]
    real = JY.check_make(ROOT)
    assert real["checked"] >= 40 and real["failures"] == [] and "journeys" in JY.targets(ROOT / "Makefile")


def test_a_mangled_email_headline_fails_the_check_and_the_desk_s_email_passes_it(desk, monkeypatch, capsys):
    import sys
    import types
    monkeypatch.setitem(sys.modules, "markdown", types.SimpleNamespace(markdown=lambda t, extensions=(): "<p>" + t.replace("\n\n", "</p><p>") + "</p>"))
    report = ('---\ntopic: x\nheadline: "BYD & VW: exports up 12%"\n---\n\n# BYD & VW: exports up 12%\n\nIn 60 seconds: exports rose.\n')
    assert JY.headline_of(report) == "BYD & VW: exports up 12%"
    desk.email({"markdown": report, "kicker": "Weekly briefing · 31 Oct 2026", "url": "https://app/#/read"})
    page = json.loads(capsys.readouterr().out)["html"]
    assert JY.judge_email(page, JY.headline_of(report), "Weekly briefing · 31 Oct 2026") == []
    bad = JY.judge_email(JY.BAD_EMAIL, "China Weekly", "Daily · 1 Nov")
    assert bad == ["the headline “China Weekly” is in the e-mail 0 times, not once in its header", "a Markdown heading mark (#) shows in the e-mail",
                   "Markdown bold marks (**) show in the e-mail", "text escaped twice (like &amp;amp;) shows in the e-mail",
                   "the line “Daily · 1 Nov” shows 2 times in the e-mail, not once", "the e-mail has no phone viewport, so phone mail apps scale it"]
    twice = page.replace("</body>", "<div>BYD &amp; VW: exports up 12%</div></body>")
    assert JY.judge_email(twice, JY.headline_of(report), "Weekly briefing · 31 Oct 2026")[0].endswith("2 times, not once in its header")
    assert JY.judge_email_layout({"overflow": 0, "headline": True, "headline_top": 40, "headline_px": 18, "body_px": 15}) == []
    assert JY.judge_email_layout({"overflow": 60, "headline": False}) == ["the e-mail scrolls sideways at 375 px by 60 px",
                                                                          "the headline is not one element of the e-mail at phone width"]


def test_a_task_given_in_a_sentence_is_followed_to_its_result_and_a_broken_hand_over_fails_it(monkeypatch):
    import conductor as CD
    import notify as N
    before = (CD.M, CD.RESULTS, N.send)
    got = JY.check_task(JY.SAMPLE)
    assert got["failures"] == [] and got["steps"] == 2
    assert (CD.M, CD.RESULTS, N.send) == before                                          # the sandbox's doors are put back
    monkeypatch.setattr(CD, "prompt_of", lambda t, s, all_steps, agents: "no context")   # step 2 no longer sees step 1's answer
    assert JY.check_task(JY.SAMPLE)["failures"] == ["step 2 did not get the result of step 1, which it waits for"]


def test_the_replay_is_the_newest_finished_planned_task(tmp_path):
    import sqlite3
    import tasks as TK
    import conductor as CD
    c = sqlite3.connect(tmp_path / "m.sqlite")
    c.row_factory = sqlite3.Row
    CD.M = TK.M = __import__("types").SimpleNamespace(event=lambda *a, **k: None)
    TK.table(c)
    CD.table(c)
    spec = {"plan": JY.SAMPLE["answer"]["plan"], "judgement": JY.SAMPLE["judgement"]}
    for tid, rhythm, source, sp in ((1, "once", "app", spec), (2, "schedule", "app", spec), (3, "once", "trial:mustache", spec),
                                    (4, "once", "app", {**spec, "repo": "trial-x"})):
        c.execute("insert into tasks (id, text, title, goal, kind, door, done, effort, autonomy, rhythm, spec, questions, answers, status, source, created, updated) "
                  "values (?, 'x y z', 'T', 'G', 'research', 'plan', '[\"a b c\"]', 'light', 'auto', ?, ?, '[]', '[]', 'done', ?, 'x', 'x')",
                  (tid, json.dumps({"type": rhythm}), json.dumps(sp), source))
        for i in (1, 2):
            c.execute("insert into task_steps (task, idx, title, agent, harness, after, why, status, output, occ) values (?,?,?,?,?,?,?,?,?,1)",
                      (tid, i, "s", "scout", "hermes", "[]", "w", "done", f"answer {i}"))
    c.commit()
    rec = JY.recorded_task(tmp_path / "m.sqlite")
    assert rec["task"] == 1 and rec["outputs"] == {1: "answer 1", 2: "answer 2"} and rec["answer"]["plan"] == spec["plan"]   # a schedule's is not a once-task
    # 3 and 4, newer, are a trial's and one in a repository: the sandbox has no repositories to give them
    assert JY.recorded_task(tmp_path / "none.sqlite") is None


def test_a_failed_journey_is_an_alert_on_the_health_board_and_runs_nightly(tmp_path):
    import crew
    rep = {"at": 1.0, "journeys": [{"name": "routes", "failures": ["#/live/x scrolls sideways at 375 px by 129 px"]}, {"name": "make", "failures": []}]}
    (tmp_path / "j.json").write_text(json.dumps(rep))
    assert crew.journey_issues(tmp_path / "j.json", now=2.0) == [{"kind": "journey", "at": 1.0, "text": "1 journey check failed: routes: #/live/x scrolls "
                                                         "sideways at 375 px by 129 px (make journeys shows them all)"}]
    assert "journey" in crew.ALERTS
    rep["journeys"][0]["failures"] = []
    (tmp_path / "j.json").write_text(json.dumps(rep))
    assert crew.journey_issues(tmp_path / "j.json", now=2.0) == []                      # a good night clears it
    job = next(a for a in crew.CREW if a["id"] == "journeys")
    assert job["unit"] == "crew-journeys" and "python3 ops/crew.py journeys" in (ROOT / "ops/systemd/crew-journeys.service").read_text()
    assert re.search(r"OnCalendar=\*-\*-\* 04:10", (ROOT / "ops/systemd/crew-journeys.timer").read_text())
    assert "python3 ops/journeys.py all" in (ROOT / "Makefile").read_text()


def test_the_browser_half_measures_what_the_owner_sees():
    js = (ROOT / "ops/journeys.mjs").read_text()
    assert "measure, PHONE.viewport.width" in js and 'u.host !== base.host) return route.abort()' in js       # nothing outside the app
    assert 'req.method() !== "GET"' in js and "route.fulfill({ status: 200" in js                               # a write is never sent
    assert "for (const [k, v] of Object.entries(s)) if (Array.isArray(v)) s[k] = [];" in js                    # the emptied state
    subprocess.run(["node", "--check", str(ROOT / "ops/journeys.mjs")], check=True)


def test_a_tool_check_needs_two_timeouts_to_call_a_tool_broken(monkeypatch):
    import journeys as JY
    monkeypatch.setattr(JY, "tool_links", lambda tools=None: [("T", "Open", "https://t")])
    tries = iter(["TimeoutError: slow", 200])
    assert JY.check_tools(opener=lambda url: next(tries))["failures"] == []
    assert JY.check_tools(opener=lambda url: "TimeoutError: slow")["failures"]

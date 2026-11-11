"""Journey checks (TSK-32, ops/journeys.py): each journey fails on the fault it is for. A route that scrolls sideways at
375 px, a broken make target and a mangled e-mail headline each fail the check; a task given in a sentence is followed
through the real intake, Conductor, judge and board to its result; a test item decided through the real server, inbox
and runner proves deciding works, and the journey fails when it does not (GEN-03); a failed journey is an alert on the
health board."""
import json
import sqlite3
import threading
import time
import types

import pytest
import shutil
import re
import subprocess
from pathlib import Path

import journeys as JY

ROOT = Path(__file__).resolve().parent.parent
H = {"Tailscale-User-Login": "journeys@test"}


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


@pytest.fixture
def stack(tmp_path, monkeypatch):
    """The way a tap really goes, on temporary folders: the app's /api/state and /api/request (server.py), the inbox, the
    runner's process_inbox and respond (missions.py), the queue (decisions.py)."""
    import decisions as DQ
    import missions as MM
    import server as SV
    from starlette.testclient import TestClient
    m = tmp_path / "missions"
    for d in ("inbox", "public/results"):
        (m / d).mkdir(parents=True)
    monkeypatch.setattr(DQ, "LOG", tmp_path / "autonomy.jsonl")
    monkeypatch.setattr(DQ, "TEST_ITEM", m / "decision-test.json")
    DQ._seen.clear()
    DQ._loaded["t"] = 0

    def conn():
        c = sqlite3.connect(tmp_path / "m.sqlite")
        c.row_factory = sqlite3.Row
        return c
    for o, a, v in ((MM, "INBOX", m / "inbox"), (MM, "PUBLIC", m / "public"), (MM, "db", conn), (MM, "log", lambda *a: None),
                    (SV, "INBOX", m / "inbox"), (SV, "RESULTS", m / "public/results"), (SV, "STATE", m / "public/state.json"),
                    (SV, "PHONE", tmp_path / "phone"), (SV, "CONN", tmp_path / "conn")):
        monkeypatch.setattr(o, a, v)
    stop = threading.Event()

    def runner():
        while not stop.is_set():
            MM.process_inbox()
            tmp = m / "public/state.tmp"
            tmp.write_text(json.dumps(DQ.state({})))
            tmp.replace(m / "public/state.json")
            stop.wait(0.05)
    client = TestClient(SV.app)

    def tap(token, wait=10):      # limit: waits, a ceiling: under a loaded machine 1.5 s ran out; a good tap returns at once
        """Stands in for ops/journeys.mjs: what the page reads and sends, through the real server."""
        id, rep = f"test:{token}", {"started": True, "writes": [], "errors": [], "still_shown": []}

        def until(ok):
            end = time.time() + wait
            while True:
                s = client.get("/api/state", headers=H).json()
                if ok(s) or time.time() > end:
                    return s, ok(s)
                time.sleep(0.05)
        before, rep["listed"] = until(lambda s: any(d["id"] == id for d in s["decisions"]))
        if not rep["listed"]:
            return rep
        d, n = next(x for x in before["decisions"] if x["id"] == id), len(before["decisions"])
        rep.update(marked=d.get("test"), no_answer=[], home={"shown": True, "count": n, "list": n}, queue={"shown": True, "count": n, "list": n}, tapped=True)
        rep["answer"] = client.post("/api/request", headers=H, json=d["answers"][0]["act"]).json()
        after, gone = until(lambda s: not any(x["id"] == id for x in s["decisions"]))
        rep.update(still_listed=not gone, record=after.get("decision_test"))
        return rep
    t = threading.Thread(target=runner, daemon=True)
    t.start()
    yield types.SimpleNamespace(DQ=DQ, MM=MM, SV=SV, tap=tap, run=lambda: JY.check_decide(tap=tap, inbox=m / "inbox", results=m / "public/results", state=m / "public/state.json", wait=20))   # limit: waits, a ceiling: a busy test machine (6 workers) answered after 2 s; a good run returns at once
    stop.set()
    t.join(5)


def test_the_decide_journey_takes_a_test_item_through_the_queue_and_leaves_nothing_behind(stack):
    assert stack.run() == {"checked": 1, "failures": []}
    assert stack.DQ.test_record() is None and stack.DQ._records() == []   # gone, and never in the shadow or the queue's numbers
    assert "decide" in JY.JOURNEYS


def test_the_decide_journey_fails_when_deciding_stops_working(stack, monkeypatch):
    """GEN-03: each way the owner's tap can stop working fails the journey, and the test item is removed all the same."""
    def raises(req):
        raise ValueError("the action is broken")

    def forgets(req):
        stack.DQ.TEST_ITEM.unlink()
        return {}
    no_item = tuple(f for f in stack.DQ.SOURCES if f.__name__ != "_test_item")
    no_tap = stack.SV.ACTIONS - {"decision_test_answer"}
    cases = [(stack.DQ, "answer_test", raises, "the answer was refused: the action is broken"),
             (stack.DQ, "answer_test", lambda req: {}, "the test item is still in the list after its answer: deciding does not work"),
             (stack.DQ, "answer_test", forgets, "the answer was not recorded: the item is gone, answer None"),
             (stack.SV, "ACTIONS", no_tap, "the answer was refused: unknown action"),
             (stack.DQ, "SOURCES", no_item, "the test item did not reach the app's list")]
    for obj, attr, broken, want in cases:
        with monkeypatch.context() as m:
            m.setattr(obj, attr, broken)
            got = stack.run()["failures"]
        assert want in got, (attr, got)
        assert stack.DQ.test_record() is None, attr                    # removed, also when the journey failed
    assert stack.run()["failures"] == []                               # mended: it passes again


def test_the_decide_journey_says_so_when_the_runner_does_not_answer_or_the_browser_dies(tmp_path):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "results").mkdir()
    dead = JY.check_decide(tap=lambda t: {}, inbox=tmp_path / "inbox", results=tmp_path / "results", state=tmp_path / "s.json", wait=0.1)["failures"]
    assert dead == ["the test item could not be made: the runner did not answer in 0.1 s", "the test item could not be removed: the runner did not answer in 0.1 s"]


def test_the_decide_journey_judges_what_the_browser_saw():
    good = {"started": True, "listed": True, "marked": True, "home": {"shown": True, "count": 4, "list": 4}, "queue": {"shown": True, "count": 4, "list": 4}, "no_answer": [],
            "tapped": True, "answer": {"ok": True}, "still_listed": False, "record": {"state": "answered", "answer": "yes"}, "still_shown": [], "writes": [], "errors": []}
    assert JY.judge_decide(good) == []
    assert JY.judge_decide({"started": True}) == ["the test item did not reach the app's list"]
    assert JY.judge_decide({**good, "home": {"shown": False, "count": 3, "list": 4}}) == ["Home does not show the test item", "Home counts 3 waiting and the list holds 4"]
    assert JY.judge_decide({**good, "marked": False}) == ["the item in the app's list is not marked as a test"]
    assert JY.judge_decide({**good, "tapped": False}) == ["the tap on the test item's answer sent nothing"]
    assert JY.judge_decide({**good, "no_answer": ["idea:3"]}) == ["idea:3 in the queue has no answer and no link"]
    assert JY.judge_decide({**good, "still_shown": ["#/decide"], "writes": ["POST /api/request"], "errors": ["boom"]}) == [
        "#/decide still shows the test item after its answer", "the page tried another write, which was not sent: POST /api/request", "a script error: boom"]
    assert len(JY.judge_decide(JY.BAD_DECIDE)) >= 4
    js = (ROOT / "ops/journeys.mjs").read_text()
    decide = js[js.index("async function decide("):js.index("async function email(")]
    for key in ("started", "listed", "marked", "home", "queue", "no_answer", "tapped", "answer", "still_listed", "record", "still_shown", "writes", "errors"):
        assert re.search(rf"\bout\.{key}\b|\b{key}:", decide), key     # the report the judge reads is the report the browser writes
    assert 'body.action === "decision_test_answer" && body.token === token' in decide and decide.count("route.continue()") == 2   # the one write sent, and reads
    assert 'u.host !== base.host) return route.abort()' in decide
    subprocess.run(["node", "--check", str(ROOT / "ops/journeys.mjs")], check=True)


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
    import n8n_jobs as NJ                                                       # nightly at 04:10, from its n8n workflow (WFL-09)
    assert NJ.of("crew", "journeys", NJ.index(ROOT / "n8n/workflows", ROOT / "no-such-folder"))["cron"] == "10 4 * * *"
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


def test_the_app_is_checked_in_every_shape_of_window():
    """APP-60. The owner, 9 Nov 2026: "The requirement is the webside has to be looking good on Mobile and on desktop on
    any ratio ... Durable." The routes journey opens the main screens in ten windows, from a phone to a 4K screen, and
    every screen at a desktop, and names each fault with its window: sideways scrolling, text a box cuts off, the chat's
    box to write in outside the window, a chat page that scrolls, no way to the other pages."""
    mjs = (Path(JY.__file__).parent / "journeys.mjs").read_text()
    for shape in ("phone", "phone-landscape", "tablet", "tablet-landscape", "laptop", "desktop", "desktop-1080p", "ultrawide", "portrait-monitor", "4k"):
        assert f'"{shape}"' in mjs or f"{shape}:" in mjs, shape
    assert set(JY.SHAPES) >= {"desktop-1080p", "ultrawide", "portrait-monitor", "4k"} and "#/chat" in JY.MAIN
    rep = {"shapes": {"results": [
        {"route": "#/chat", "shape": "desktop-1080p", "size": "1920×1080", "overflow": 0, "clipped": [], "writebox": False, "pagescroll": 128, "nav": True, "main": "x"},
        {"route": "#/", "shape": "phone-landscape", "size": "812×375", "overflow": 14, "wide": ["div.card (14 px)"], "clipped": ["span.chip “Running a long”"], "writebox": True, "nav": False, "main": "x"}]}}
    out = JY.judge_shapes(rep)
    assert "#/chat in a desktop-1080p window (1920×1080): the box to write in is outside the window" in out
    assert "#/chat in a desktop-1080p window (1920×1080): the chat page scrolls by 128 px instead of holding the window" in out
    assert any("scrolls sideways by 14 px" in x for x in out) and any("cuts text off: span.chip" in x for x in out)
    assert any("neither the tab bar nor the sidebar shows" in x for x in out)


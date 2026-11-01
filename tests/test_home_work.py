"""Home (redesigned 28 Oct 2026): Needs you, Now, and the live feed of results. Runs the real rendering helpers in
node with fake state; no services or secrets."""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MC = ROOT / "images/mission-control"
APP_JS = (MC / "web/static/app.js").read_text()
GUIDE = (MC / "guide/01-welcome.md").read_text()
FUNCS = ("needsItems", "needsHtml", "nowHtml", "upkeepHtml", "feedItems", "feedHtml", "workBuildRow", "statusPill", "runningCard", "stepsHtml", "dayOf")
CONSTS = ("esc", "BSTATUS", "bcls", "VERDICT", "STATUS", "typeIcon", "toIso", "gbOf", "clockOf", "CREW_IC", "TRIG", "firstLine", "ctAsker", "ctTitle", "ideasWaiting")
FORMAT = re.search(r"// ---------- formatting \(TSK-31\).*?// ---------- end of formatting ----------", APP_JS, re.S)[0]   # the app's own helpers


def run(state, expr):
    functions = [m[0] for name in FUNCS if (m := re.search(rf"^function {name}\(.*?^\}}", APP_JS, re.M | re.S))]
    constants = [m[0] for name in CONSTS if (m := re.search(rf"^const {name} = .*?;$", APP_JS, re.M | re.S))]
    script = "\n".join([
        'const ic = new Proxy({}, {get: (_, key) => `<svg data-icon="${key}"></svg>`});',
        FORMAT, "const SHOP_STATE = {watching: ['paused', 'Watching'], proposed: ['ok', 'Proposed']};",
        "let homeFilter = 'all', homeShow = 40; const homeEx = new Map();",
        f"let S = {json.dumps({'missions': [], **state})};",
        "const shopProposals = () => (S.shopping || {}).proposals || [];",
        *constants, *functions, f"process.stdout.write(String({expr}));"])
    return subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True).stdout


def test_home_is_needs_now_and_a_live_feed_with_an_ask_bar():
    home = re.search(r"^function vHome\(\).*?^\}", APP_JS, re.M | re.S)[0]
    for part in ("${needsHtml()}", "${nowHtml()}", "${feedHtml()}", 'id="askbar"', "#/new", "#/wiki?new=1"):
        assert part in home
    assert "fab" not in home                                       # the floating New mission button is gone
    on_state = re.search(r"^function onState\(.*?^\}", APP_JS, re.M | re.S)[0]
    assert on_state.index('route.name === "home" && !first && $("#homefeed")') < on_state.index("render();")
    update = re.search(r"^function homeUpdate\(.*?^\}", APP_JS, re.M | re.S)[0]
    assert "homeLast[id] === html" in update                       # unchanged parts are not touched: no twitch
    assert "## Home" in GUIDE and "Latest from your agents" in GUIDE and "Needs you" in GUIDE


def test_needs_you_lists_only_decisions_and_says_so_when_there_are_none():
    calm = run({}, "needsHtml()")
    assert "Nothing needs you" in calm
    html = run({"builds": [{"id": 1, "status": "review", "title": "Review <me>", "checks_ok": True, "checks": "x", "ci": "success"},
                           {"id": 2, "status": "working", "title": "Busy"}],
                "shopping": {"proposals": [{"id": "p-1", "slug": "ram", "status": "proposed", "item": "RAM kit", "total_eur": 99},
                                           {"id": "p-2", "slug": "ram", "status": "watching", "item": "Other", "total_eur": 189}]},
                "crew": [{"id": "phone-cleanup", "actions": [{"status": "open", "size": 2e9}, {"status": "done", "size": 1e9}]}],
                "phone": {"pending": 2}, "health": {"alerts": 1}, "proposals": [{"status": "proposed", "title": "Fix the watchdog"}]},
               "needsHtml()")
    for want in ('href="#/build/1"', "Review &lt;me&gt;", "#/mission/ram?shop=p-1", "1 AI phone cleanup step to approve", "2.0 GB",
                 "2 approvals", '<span class="hcount">4</span>'):
        assert want in html, want
    assert "#/build/2" not in html and "p-2" not in html           # working builds are Now, a watched price is not a decision
    assert "health alert" not in html and "improvement" not in html  # the stack's own upkeep is not the owner's decision


def test_stack_upkeep_sits_under_now_not_needs_you():
    html = run({"health": {"alerts": 2}, "swarm": {"board": {"open": [{"id": 3, "title": "Fix the watchdog", "state": "open"}],
                                                          "recent": [{"id": 1, "state": "declined"}]}},
                "crew": [{"name": "Backup", "state": "failed"}]}, "nowHtml()")
    assert "Stack upkeep" in html and "2 health alerts" in html and "Backup" in html and "1 improvement idea" in html


def test_now_shows_work_in_progress_and_whats_next():
    html = run({"builds": [{"id": 2, "status": "working", "title": "Busy"}], "queue": [{"slug": "q", "status": "queued"}],
                "missions": [{"slug": "q", "title": "Queued one", "type": "task", "status": "active", "next_run": "2026-10-29T06:30:00+01:00"}],
                "claude_tasks": [{"id": 7, "status": "running", "question": "Why?\nmore"}]}, "nowHtml()")
    for want in ('href="#/build/2"', "Queued one", "waits for the run slot", "Claude task #7", "Up next", "working"):
        assert want in html, want
    assert "all quiet" in run({}, "nowHtml()")


def test_the_feed_has_results_first_class_and_leaves_out_noise():
    state = {"missions": [{"slug": "uranium", "title": "Uranium", "type": "briefing", "runs": [
                {"status": "ok", "summary": "Boss reports 359,000 lb", "output": "topics/uranium/reports/2026/10/2026-10-28.md",
                 "started": "2026-10-28T06:33:34+01:00", "ended": "2026-10-28T06:37:54+01:00", "seconds": 260, "calls": 3, "trigger": "schedule"},
                {"status": "failed", "summary": "no answer", "started": "2026-10-27T06:30:00+01:00"}]}],
             "crew": [{"id": "inbox", "name": "Inbox digest", "area": "memory", "last": 1793219000, "result": "Filed 2 of 37", "schedule": "daily 07:15", "state": "ok"},
                      {"id": "memory-review", "name": "Memory gatekeeper", "area": "memory", "last": 1793219100, "result": "ok", "schedule": "every 10min", "state": "ok"},
                      {"id": "phone-check", "name": "Phone check", "area": "phone", "last": 1793219200, "result": "failed: RuntimeError: battery at 19 %", "schedule": "weekly", "state": "failed"}],
             "builds": [{"id": 4, "status": "deployed", "title": "Work section", "updated": "2026-10-28T13:50:00+01:00"}, {"id": 5, "status": "working", "title": "x", "updated": 1}],
             "activity": [{"ts": "2026-10-28T20:00:00+01:00", "kind": "run_started", "title": "Uranium", "text": "Run started"},
                          {"ts": "2026-10-28T19:00:00+01:00", "kind": "triggered", "title": "ASPI", "text": "New SEC filing", "slug": "aspi"}]}
    items = json.loads(run(state, "JSON.stringify(feedItems())"))
    heads = [x["head"] for x in items]
    assert "Boss reports 359,000 lb" in heads and "Run failed: no answer" in heads and "Filed 2 of 37" in heads
    assert "Failed: battery at 19 %" in heads and "Deployed: Work section" in heads and "New SEC filing" in heads
    assert "ok" not in heads and "Run started" not in heads and not any("x" == h.split(": ")[-1] for h in heads)
    when = json.loads(run(state, "JSON.stringify(feedItems().map((x) => +new Date(toIso(x.ts))))"))
    assert when == sorted(when, reverse=True)                      # newest first, across ISO times and epoch seconds
    html = run(state, "feedHtml()")
    assert 'href="#/read?path=topics%2Furanium%2Freports%2F2026%2F10%2F2026-10-28.md&amp;m=uranium"' in html or \
           'href="#/read?path=topics%2Furanium%2Freports%2F2026%2F10%2F2026-10-28.md&m=uranium"' in html
    assert 'data-ex="topics/uranium/reports/2026/10/2026-10-28.md"' in html and "scheduled · 4 min · 3 model calls" in html
    assert 'data-hf="housekeeping"' in html and 'data-hf="code"' in html
    only = run(state, "(homeFilter = 'housekeeping', feedHtml())")
    assert "Filed 2 of 37" in only and "Boss reports" not in only


def test_chats_from_tests_and_agents_are_kept_apart_from_yours():
    server = (MC / "server.py").read_text()
    fn = re.search(r"^def origin_of\(.*?(?=^\S)", server, re.M | re.S)[0]
    assert '"owner" if ip and request.headers.get("tailscale-user-login") else "automation"' in fn
    assert '"origin": origin_of(request)' in server and '"origin")' in server
    assert "From tests and agents" in APP_JS


def test_list_row_chevrons_have_a_size():
    from pathlib import Path
    css = (Path(__file__).resolve().parent.parent / "images/mission-control/web/static/app.css").read_text()
    assert ".list > a > svg {" in css and "width: 16px" in css.split(".list > a > svg {")[1].split("}")[0]   # unsized, one filled the card


def test_the_swarm_and_session_deploys_are_on_the_home_timeline():
    html = run({"activity": [{"ts": "2026-10-29T18:48:49+01:00", "kind": "swarm", "title": "Swarm", "text": "doctor proposed idea #28 Make swarm-sync tolerate a restart"},
                             {"ts": "2026-10-29T18:47:09+01:00", "kind": "deploy", "title": "Session deploy", "text": "deployed: Swarm switch-over (2cea212c..d6e62a00)"}]},
               "feedHtml()")
    assert "doctor proposed idea #28" in html and 'href="#/swarm?tab=improve"' in html and "Session deploy" in html


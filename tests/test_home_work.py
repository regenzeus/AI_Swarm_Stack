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
FUNCS = ("needsItems", "needsHtml", "nowHtml", "upkeepHtml", "healthAlerts", "feedItems", "feedHtml", "workBuildRow", "statusPill", "runningCard", "stepsHtml", "dayOf")
CONSTS = ("RKIND", "NOT_YOURS", "esc", "BSTATUS", "bcls", "VERDICT", "STATUS", "typeIcon", "toIso", "gbOf", "clockOf", "CREW_IC", "TRIG", "firstLine", "ctAsker", "ctTitle", "ideasWaiting")
FORMAT = re.search(r"// ---------- formatting \(TSK-31\).*?// ---------- end of formatting ----------", APP_JS, re.S)[0]   # the app's own helpers


def run(state, expr):
    functions = [m[0] for name in FUNCS if (m := re.search(rf"^function {name}\(.*?^\}}", APP_JS, re.M | re.S))]
    constants = [m[0] for name in CONSTS if (m := re.search(rf"^const {name} = .*?;$", APP_JS, re.M | re.S))]
    script = "\n".join([
        'const ic = new Proxy({}, {get: (_, key) => `<svg data-icon="${key}"></svg>`}); const taskWho = (a) => a;',
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
    assert "## Home" in GUIDE and "**Results**" in GUIDE and "Needs you" in GUIDE


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
    html = run({"health": {"alerts": 2, "items": [{"kind": "crew", "id": "backup", "issues": [{"severity": "alert", "text": "failed 2 times"}]},
                                                  {"kind": "crew", "id": "doctor", "issues": [{"severity": "note", "text": "slow"}]}]},
                "swarm": {"board": {"open": [{"id": 3, "title": "Fix the watchdog", "state": "open"}], "recent": [{"id": 1, "state": "declined"}]}},
                "crew": [{"id": "backup", "name": "Backup", "state": "failed"}]}, "nowHtml()")
    assert "Stack upkeep" in html and "2 health alerts" in html and "Backup: failed 2 times" in html and "1 improvement idea" in html
    assert 'href="#/crew/backup"' in html                       # one agent with an alert: its page, not the Agents overview
    two = run({"health": {"alerts": 2, "items": [{"kind": "crew", "id": "a", "issues": [{"severity": "alert", "text": "x"}]},
                                                 {"kind": "mission", "slug": "m", "issues": [{"severity": "alert", "text": "y"}]}]},
               "crew": [{"id": "a", "name": "A"}], "missions": [{"slug": "m", "title": "M"}]}, "upkeepHtml()")
    assert 'href="#/missions?f=problems"' in two and "A: x · M: y" in two   # several: the Agents list, only those with problems


def test_now_shows_work_in_progress_and_whats_next():
    html = run({"builds": [{"id": 2, "status": "working", "title": "Busy"}], "queue": [{"slug": "q", "status": "queued"}],
                "missions": [{"slug": "q", "title": "Queued one", "type": "task", "status": "active", "next_run": "2026-10-29T06:30:00+01:00"}],
                "claude_tasks": [{"id": 7, "status": "running", "question": "Why?\nmore"}]}, "nowHtml()")
    for want in ('href="#/build/2"', "Queued one", "waits for the run slot", "Claude task #7", "Up next", "working"):
        assert want in html, want
    assert "all quiet" in run({}, "nowHtml()")


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


def test_home_s_results_are_one_card_per_outcome_named_by_what_it_is_about():
    """APP-38 (the owner's review of 2 Nov: "Tasks", "Triggers" and "Agent health" cards, two cards for one outcome, what
    is what hard to tell): one card per outcome you asked for or your rules started, with its kind, its headline and its
    page; a running task is on Now; the stack's own machinery (health, deploys, the Ledger, crew jobs, trials, probes)
    is not among your results."""
    ts = "2026-11-02T13:25:00+01:00"
    state = {"missions": [{"slug": "uranium", "title": "Uranium", "type": "briefing", "runs": [
                {"status": "ok", "summary": "Boss reports 359,000 lb", "output": "topics/uranium/reports/2026/10/2026-10-28.md",
                 "started": "2026-10-28T06:33:34+01:00", "ended": "2026-10-28T06:37:54+01:00", "seconds": 260, "calls": 3, "trigger": "schedule"},
                {"status": "failed", "summary": "no answer", "started": "2026-10-27T06:30:00+01:00"}]}],
             "tasks": [{"id": 113, "status": "done", "door": "plan", "source": "rule:2", "kind": "research", "title": "Macusani brief", "result": "tasks/113-macusani.md", "updated": ts, "runs": [{"occ": 1, "ended": ts, "status": "done"}]},
                       {"id": 120, "status": "done", "door": "plan", "source": "app", "kind": "analysis", "title": "Compare two NAS", "result": "tasks/120-nas.md", "updated": ts, "runs": [{"occ": 1, "ended": ts, "status": "done"}]},
                       {"id": 121, "status": "failed", "door": "plan", "source": "app", "kind": "research", "title": "Broken one", "error": "step 1 failed", "updated": ts, "runs": [{"occ": 1, "ended": ts, "status": "failed"}]},
                       {"id": 79, "status": "scheduled", "door": "plan", "source": "app", "kind": "briefing", "title": "China weekly", "result": "tasks/79-china-1.md", "updated": ts, "runs": [{"occ": 1, "ended": ts, "status": "done"}]},
                       {"id": 115, "status": "done", "door": "plan", "source": "probe:p4", "title": "Hermes version", "updated": ts},
                       {"id": 109, "status": "done", "door": "plan", "source": "trial:mustache", "title": "Mustache", "updated": ts},
                       {"id": 12, "status": "done", "door": "mission", "source": "app", "title": "Uranium mission", "updated": ts},
                       {"id": 130, "status": "running", "door": "plan", "source": "app", "title": "Busy one", "updated": "2099-01-01T00:00:00+00:00",
                        "steps": [{"status": "done", "agent": "scout"}, {"status": "running", "agent": "main"}]}],
             "crew": [{"id": "inbox", "name": "Inbox digest", "last": 1793219000, "result": "Filed 2 of 37", "schedule": "daily 07:15", "state": "ok"}],
             "builds": [{"id": 4, "status": "deployed", "title": "Work section", "updated": ts}],
             "activity": [{"ts": ts, "kind": "triggered", "title": "Triggers", "text": "Rule fired on Macusani: task #113"},
                          {"ts": ts, "kind": "health", "push": True, "title": "Agent health", "text": "Journey checks: 4 failed"},
                          {"ts": ts, "kind": "deploy", "title": "Session deploy", "text": "deployed: Memory"}]}
    items = json.loads(run(state, "JSON.stringify(feedItems().map((x) => [x.kind, x.head, x.href]))"))
    assert ["alert", "Macusani brief", "#/task/113"] in items                          # the rule's alert and its task: one card
    assert ["task", "Compare two NAS", "#/task/120"] in items and ["failed", "Broken one", "#/task/121"] in items
    assert ["briefing", "China weekly", "#/task/79"] in items                          # a scheduled task's last run
    assert ["briefing", "Boss reports 359,000 lb", "#/read?path=topics%2Furanium%2Freports%2F2026%2F10%2F2026-10-28.md&m=uranium"] in items
    assert ["failed", "Did not finish: no answer", "#/mission/uranium?tab=history"] in items
    heads = [h for _, h, _ in items]
    for gone in ("Hermes version", "Mustache", "Uranium mission", "Busy one", "Filed 2 of 37", "Deployed: Work section", "Journey checks: 4 failed", "Rule fired on Macusani: task #113"):
        assert not any(gone in h for h in heads), gone
    when = json.loads(run(state, "JSON.stringify(feedItems().map((x) => +new Date(toIso(x.ts))))"))
    assert when == sorted(when, reverse=True)
    html = run(state, "feedHtml()")
    assert '<span class="fkind k-alert">Alert</span>' in html and 'data-ex="tasks/113-macusani.md"' in html and "scheduled · 4 min · 3 model calls" in html
    assert 'data-hf="alert"' in html and 'data-hf="housekeeping"' not in html and "<h2>Results</h2>" in html
    assert "Compare two NAS" not in run(state, "(homeFilter = 'alert', feedHtml())")
    now = run(state, "nowHtml()")
    assert 'href="#/task/130"' in now and "1 of 2 steps done · main at work" in now   # a task at work is on Now


def test_home_holds_its_updates_while_you_scroll_or_touch():
    """APP-38: a card came in above the one tapped and the tap opened another; Home waits behind a button instead."""
    fn = re.search(r"^function homeUpdate\(.*?^\}", APP_JS, re.M | re.S)[0]
    assert "window.scrollY > 120 || Date.now() - homeTouch < 2500" in fn and 'id="homenew"' in fn and "homeUpdate(true)" in fn

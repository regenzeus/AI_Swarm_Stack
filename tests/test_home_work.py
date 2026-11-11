"""Home (redesigned 28 Oct 2026): Needs you, Now, and the live feed of results. Runs the real rendering helpers in
node with fake state; no services or secrets."""
import pysrc
import webjs
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MC = ROOT / "images/mission-control"
APP_JS = webjs.app_js()
GUIDE = (MC / "guide/01-welcome.md").read_text()
FUNCS = ("needsRows", "needsRow", "needsHtml", "nowHtml", "upkeepHtml", "healthAlerts", "feedItems", "feedHtml", "workBuildRow", "statusPill", "runningCard", "stepsHtml", "dayOf")
CONSTS = ("RKIND", "QUIET", "esc", "BSTATUS", "bcls", "VERDICT", "STATUS", "typeIcon", "toIso", "clockOf", "HOME_ICON", "homeMany", "CREW_IC", "TRIG", "firstLine", "firstSentence", "ctAsker", "ctTitle", "ideasWaiting",
          "IDEA_CLS", "yoursN", "ideasN")
FORMAT = re.search(r"// ---------- formatting \(TSK-31\).*?// ---------- end of formatting ----------", APP_JS, re.S)[0]   # the app's own helpers


def item(id, cls, what, href, why="", routine=False):
    return {"id": id, "cls": cls, "what": what, "why": why, "href": href, "answers": [{"label": "Look", "href": href}], "routine": routine}


def run(state, expr):
    functions = [m[0] for name in FUNCS if (m := re.search(rf"^function {name}\(.*?^\}}", APP_JS, re.M | re.S))]
    constants = [m[0] for name in CONSTS if (m := re.search(rf"^const {name} = .*?;$", APP_JS, re.M | re.S))]
    script = "\n".join([
        'const ic = new Proxy({}, {get: (_, key) => `<svg data-icon="${key}"></svg>`}); const taskWho = (a) => a;',
        FORMAT, "const SHOP_STATE = {watching: ['paused', 'Watching'], proposed: ['ok', 'Proposed']};",
        "let homeFilter = 'all', homeShow = 40; const homeEx = new Map();",
        f"let S = {json.dumps({'missions': [], **state})};",
        "const shopProposals = () => (S.shopping || {}).proposals || [];",
        "const notConnected = () => false;",
        *constants, *functions, f"process.stdout.write(String({expr}));"])
    return subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True).stdout


def test_home_is_needs_now_and_a_live_feed_with_an_ask_bar():
    home = re.search(r"^function vHome\(\).*?^\}", APP_JS, re.M | re.S)[0]
    for part in ("${needsHtml()}", "${nowHtml()}", "${feedHtml()}", 'id="askbar"', 'data-hp="today"', 'data-hp="results"', 'data-hp="overview"'):
        assert part in home
    for gone in ("#/wiki?new=1", 'href="#/chat"', 'href="#/missions"', "Task with details", "#/new", "hquick"):   # 8 Nov: they have their own tabs
        assert gone not in home
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
                "shopping": {"proposals": [{"id": "p-2", "slug": "ram", "status": "watching", "item": "Other", "total_eur": 189}]},
                "decisions": [item("build:1", "coding", "Deploy build #1: Review <me>", "#/build/1"), item("shop:p-1", "shopping-buy", "Buy RAM kit for EUR 99 at Alternate?", "#/mission/ram?shop=p-1"),
                              item("phone-step:a1", "phone-routine", "AI phone cleanup: caches", "#/crew/phone-cleanup", why="frees 2.0 GB"),
                              item("phone-ask", "phone", "The AI phone asks for 2 approvals", "#/phone")],
                "health": {"alerts": 1}, "proposals": [{"status": "proposed", "title": "Fix the watchdog"}]},
               "needsHtml()")
    for want in ('href="#/build/1"', "Review &lt;me&gt;", "#/mission/ram?shop=p-1", "AI phone cleanup: caches", "2.0 GB",
                 "2 approvals", '<span class="hcount">4</span>', 'href="#/decide"'):
        assert want in html, want
    assert "#/build/2" not in html and "p-2" not in html           # working builds are Now, a watched price is not a decision
    assert "health alert" not in html and "improvement" not in html  # the stack's own upkeep is not the owner's decision


def test_home_and_the_queue_draw_one_list_and_a_kind_with_many_items_is_a_count_row():
    """GEN-02: Home built its own list and left out ideas and agent changes. Now both read S.decisions; the rows add up to it."""
    assert "const n = yoursN(), ideas = ideasN()" in re.search(r"^function homeHeadHtml\(.*?^\}", APP_JS, re.M | re.S)[0]   # the stack's ideas counted apart (APP-54)
    for src in ("needsRows", "needsHtml"):
        body = re.search(rf"^function {src}\(.*?^\}}", APP_JS, re.M | re.S)[0]
        assert "S.decisions" in body and "S.builds || []).filter" not in body and "S.tasks" not in body and "S.swarm" not in body, src
    assert "S.decisions" in re.search(r"^function vDecide\(.*?^\}", APP_JS, re.M | re.S)[0]
    assert "needsItems" not in APP_JS and "ideasWaiting" not in re.search(r"^function upkeepHtml\(.*?^\}", APP_JS, re.M | re.S)[0]
    ideas = [item(f"idea:{n}", "ideas", f"Take this idea? {n}", "#/swarm?tab=improve") for n in range(22)]
    ds = [item("build:1", "coding", "Deploy build #1", "#/build/1"), item("phone-step:a", "phone-routine", "Cache a", "#/crew/phone-cleanup", routine=True),
          item("agent-1", "agent-change", "Take the change to scout?", "#/swarm?tab=improve"), item("phone-step:b", "phone-routine", "Cache b", "#/crew/phone-cleanup", routine=True),
          item("memory:1", "memory", "Remember this?", "#/system", routine=True), item("keeper:1", "memory", "Forget this?", "#/crew/memory", routine=True), *ideas,
          item("test:abc", "journey-test", "Test item", "#/decide")]
    state = {"decisions": ds, "decide": {"classes": {"ideas": {"title": "Ideas"}, "phone-routine": {"title": "Phone routine"}, "memory": {"title": "Memory"}}}}
    rows = json.loads(run(state, "JSON.stringify(needsRows().map((x) => [x.title, x.n, x.href]))"))
    assert rows == [["Deploy build #1", 1, "#/build/1"], ["Phone routine · 2 waiting", 2, "#/crew/phone-cleanup"], ["Take the change to scout?", 1, "#/swarm?tab=improve"],
                    ["Memory · 2 waiting", 2, "#/decide"], ["Ideas · 22 waiting", 22, "#/swarm?tab=improve"], ["Test item", 1, "#/decide"]]
    assert sum(r[1] for r in rows) == len(ds)                      # nothing is hidden: the rows add up to the queue
    html = run(state, "needsHtml()")
    yours = [d for d in ds if d["cls"] not in ("ideas", "agent-change")]         # the stack's ideas wait in the list, counted apart (APP-54)
    assert f'<span class="hcount">{len(yours)}</span>' in html and len(yours) < len(ds) and "first: Take this idea? 0" in html
    few = run({"decisions": ideas[:3]}, "JSON.stringify(needsRows().map((x) => x.title))")
    assert json.loads(few) == [d["what"] for d in ideas[:3]]       # three of a kind are still rows of their own


def test_what_the_owner_cannot_answer_stays_on_the_health_board_and_under_stack_upkeep():
    """GEN-02: the AI phone being down and health alerts are states: not in the queue, still one tap from Home."""
    state = {"health": {"alerts": 1, "items": [{"kind": "crew", "id": "phone-check", "issues": [{"severity": "alert", "kind": "phone-down", "text": "The AI phone: disconnected"}]}]},
             "crew": [{"id": "phone-check", "name": "Phone check"}], "decisions": []}
    assert "Nothing needs you" in run(state, "needsHtml()")
    html = run(state, "upkeepHtml()")
    assert "The AI phone is not connected" in html and 'href="#/phone"' in html and "1 health alert" in html


def test_stack_upkeep_sits_under_now_not_needs_you():
    html = run({"health": {"alerts": 2, "items": [{"kind": "crew", "id": "backup", "issues": [{"severity": "alert", "text": "failed 2 times"}]},
                                                  {"kind": "crew", "id": "doctor", "issues": [{"severity": "note", "text": "slow"}]}]},
                "swarm": {"board": {"open": [{"id": 3, "title": "Fix the watchdog", "state": "open"}], "recent": [{"id": 1, "state": "declined"}]}},
                "crew": [{"id": "backup", "name": "Backup", "state": "failed"}]}, "nowHtml()")
    assert "Stack upkeep" in html and "2 health alerts" in html and "Backup: failed 2 times" in html
    assert "improvement idea" not in html                       # ideas wait for an answer: they are under Needs you (GEN-02)
    assert 'href="#/crew/backup"' in html                       # one agent with an alert: its page, not the Agents overview
    two = run({"health": {"alerts": 2, "items": [{"kind": "crew", "id": "a", "issues": [{"severity": "alert", "text": "x"}]},
                                                 {"kind": "mission", "slug": "m", "issues": [{"severity": "alert", "text": "y"}]}]},
               "crew": [{"id": "a", "name": "A"}], "missions": [{"slug": "m", "title": "M"}]}, "upkeepHtml()")
    assert 'href="#/tasks?v=team&p=crew"' in two and "A: x · M: y" in two   # several: Team → Crew, with their health


def test_now_shows_work_in_progress_and_whats_next():
    html = run({"builds": [{"id": 2, "status": "working", "title": "Busy"}], "queue": [{"slug": "q", "status": "queued"}],
                "missions": [{"slug": "q", "title": "Queued one", "type": "task", "status": "active", "next_run": "2026-10-29T06:30:00+01:00"}],
                "claude_tasks": [{"id": 7, "status": "running", "question": "Why?\nmore"}]}, "nowHtml()")
    for want in ('href="#/build/2"', "Queued one", "waits for the run slot", "Claude task #7", "Up next", "working"):
        assert want in html, want
    assert "all quiet" in run({}, "nowHtml()")


def test_chats_from_tests_and_agents_are_kept_apart_from_yours():
    server = pysrc.server()
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
    state = {"missions": [{"slug": "copper", "title": "Copper", "type": "briefing", "runs": [
                {"status": "ok", "summary": "Boss reports 359,000 lb", "output": "topics/copper/reports/2026/10/2026-10-28.md",
                 "started": "2026-10-28T06:33:34+01:00", "ended": "2026-10-28T06:37:54+01:00", "seconds": 260, "calls": 3, "trigger": "schedule"},
                {"status": "failed", "summary": "no answer", "started": "2026-10-27T06:30:00+01:00"}]}],
             "tasks": [{"id": 113, "status": "done", "door": "plan", "source": "rule:2", "kind": "research", "title": "Macusani brief", "result": "tasks/113-macusani.md", "updated": ts, "runs": [{"occ": 1, "ended": ts, "status": "done"}]},
                       {"id": 120, "status": "done", "door": "plan", "source": "app", "kind": "analysis", "title": "Compare two NAS", "result": "tasks/120-nas.md", "updated": ts, "runs": [{"occ": 1, "ended": ts, "status": "done"}]},
                       {"id": 121, "status": "failed", "door": "plan", "source": "app", "kind": "research", "title": "Broken one", "error": "step 1 failed", "updated": ts, "runs": [{"occ": 1, "ended": ts, "status": "failed"}]},
                       {"id": 79, "status": "scheduled", "door": "plan", "source": "app", "kind": "briefing", "title": "China weekly", "result": "tasks/79-china-1.md", "updated": ts, "runs": [{"occ": 1, "ended": ts, "status": "done"}]},
                       {"id": 115, "status": "done", "door": "plan", "source": "probe:p4", "area": "upkeep", "title": "Hermes version", "updated": ts},
                       {"id": 109, "status": "done", "door": "plan", "source": "trial:mustache", "area": "code", "title": "Mustache", "updated": ts},
                       {"id": 12, "status": "done", "door": "mission", "source": "app", "title": "Copper mission", "updated": ts},
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
    assert ["briefing", "Boss reports 359,000 lb", "#/read?path=topics%2Fcopper%2Freports%2F2026%2F10%2F2026-10-28.md&m=copper"] in items
    assert ["failed", "Did not finish: no answer", "#/mission/copper?tab=history"] in items
    heads = [h for _, h, _ in items]
    assert ["task", "Mustache", "#/task/109"] in items                                 # TSK-55: every area but upkeep, which shows when it fails
    for gone in ("Hermes version", "Copper mission", "Busy one", "Filed 2 of 37", "Deployed: Work section", "Journey checks: 4 failed", "Rule fired on Macusani: task #113"):
        assert not any(gone in h for h in heads), gone
    when = json.loads(run(state, "JSON.stringify(feedItems().map((x) => +new Date(toIso(x.ts))))"))
    assert when == sorted(when, reverse=True)
    html = run(state, "feedHtml()")
    assert '<span class="fkind k-alert">Alert</span>' in html and 'data-ex="tasks/113-macusani.md"' in html and "scheduled · 4 min · 3 model calls" in html
    assert 'data-hf="alert"' in html and 'data-hf="housekeeping"' not in html and "<h2>Results</h2>" in html
    assert "Compare two NAS" not in run(state, "(homeFilter = 'alert', feedHtml())")
    now = run(state, "nowHtml()")
    assert 'href="#/task/130"' not in now and "working" in now                    # a task at work is under In the stack (TSK-55)


def test_home_holds_its_updates_while_you_scroll_or_touch():
    """APP-38: a card came in above the one tapped and the tap opened another; what arrives waits, silently, and comes in at the top."""
    fn = re.search(r"^function homeUpdate\(.*?^\}", APP_JS, re.M | re.S)[0]
    assert "window.scrollY > 120 || Date.now() - homeTouch < 2500" in fn and "homeHeld = held" in fn
    assert "homenew" not in APP_JS and "New on Home" not in APP_JS.replace('"New on Home" button', "")

"""DEC-53: the app after n8n. The Temporal era's screens are gone and their old links land where the work is now; packs
and trackers are one section of the Stack page."""
import json
import re
import subprocess
from pathlib import Path

import webjs

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "images/mission-control"
STATIC = APP / "web/static"


def moved(*calls):
    """MOVED (app-base.js) evaluated in node: [route, args, query] -> the address an old link lands on."""
    src = re.search(r"^const MOVED = \{.*?^\};", webjs.app_js(), re.M | re.S)[0]
    js = f"{src}\nprocess.stdout.write(JSON.stringify({json.dumps(calls)}.map(([r, a, q]) => MOVED[r](a, new URLSearchParams(q)))));"
    return json.loads(subprocess.run(["node", "-e", js], check=True, capture_output=True, text=True).stdout)


def views():
    return {k.split(":")[0].strip() for k in re.search(r"const fn = \{(.*?)\}\[route\.name\]", webjs.app_js(), re.S)[1].split(",")}


def test_the_engine_runs_and_templates_screens_are_gone_and_their_links_land_on_workflows():
    html = (APP / "web/index.html").read_text()
    for f in ("app-engine.js", "app-templates.js", "app-packs.js", "app-trackers.js"):
        assert not (STATIC / f).exists() and f not in html, f
    assert not (APP / "server.engine.py").exists()
    server = (APP / "server.py").read_text()
    for gone in ("engine_view", "engine_decide", "template_save", "template_test", "template_describe", "runs_proxy", "api_codec_decode", '"/runs"'):
        assert gone not in server, gone
    assert not {"engine", "runs", "templates", "packs", "trackers"} & views()
    assert "S?.engine" not in webjs.app_js() and "taskEngineLink" not in (STATIC / "task.js").read_text()
    assert moved(["engine", ["task:3:1"], ""], ["runs", [], ""], ["templates", ["x"], ""]) == [
        "#/workflows?open=executions", "#/workflows?open=executions", "#/workflows"]
    assert "const moved = MOVED[route.name]?.(route.args, route.q);\n  if (moved) { location.replace(moved); return; }" in webjs.app_js()


def test_packs_and_trackers_are_one_section_of_the_stack_page_and_their_old_links_open_it():
    js = (STATIC / "app.js").read_text()
    assert '<div id="packsbox">${packsHtml()}</div>' in js and "bindPacks();" in js
    assert "const L = S?.packs ||" in js and "T = S?.trackers ||" in js           # published by the runner (ops/missions.py domain_state)
    assert 'n(p.workflows, "workflow", "workflows")' in js and "t.workflow" in js    # n8n workflows, not templates
    to = moved(["packs", ["toy"], ""], ["packs", [], ""], ["trackers", [], ""])
    assert all(x.startswith("#/system?tab=") and "at=packs" in x for x in to) and "pack=toy" in to[0]
    assert "if (packSig() !== PK_SIG && !typing())" in js                           # redrawn only when they change


def fn(name, src=None):
    return re.search(rf"^(async )?function {name}\(.*?^\}}$", src or webjs.app_js(), re.M | re.S)[0]


def test_the_stack_page_holds_the_stack_and_the_rest_is_where_it_belongs_two_taps_from_the_menu():
    js = webjs.app_js()
    v = fn("vSystem")
    assert 'href="#/guide">${ic.doc}Guide</a>' in v and 'href="#/files"' in v               # the title row: one tap
    for gone in ("engineBanner", "#/telemetry", "#/house", "pending_memory", "memoryHtml", "librarianHtml", "learnHtml", "data-mem="):
        assert gone not in v, gone
    assert "telInto($(\"#telbox\"))" in v and 'id="telbox"' in fn("stackCostsHtml") and 'id="subs"' in fn("stackCostsHtml")
    assert "a2aCardHtml()" in v and "packsHtml()" in v and 'id="conncard"' in v      # Connections: Gmail, outside agents, packs
    assert moved(["telemetry", [], ""]) == ["#/system?tab=costs"] and "telemetry" not in views()
    assert 'if (route.q.get("tab") === "guide") { location.replace("#/guide"); return; }' in v
    home = fn("vHome")                                                              # Home → Overview: the House beside the AI phone
    assert "${devicesHtml()}${houseCardHtml()}" in home and '["homehouse", houseCardHtml]' in js and 'href="#/house"' in js
    memory = fn("vMemory")                                                          # Memory: each store's figures and the weekly tidy
    assert "${memUpkeepHtml()}" in memory and "librarianHtml(S.memory.librarian)" in js
    guide = (STATIC / "guide.js").read_text()
    assert "return route.args[0] ? vGuideChapter(route.args[0]) : vGuideIndex();" in guide and "scrollToLearn" not in js + guide
    assert '"Remember this?", m.get("text") or "", "#/decide"' in (ROOT / "ops/decisions.py").read_text()   # a memory to approve is in Needs you
    pages = {p[1] for p in json.loads((STATIC / "tools.json").read_text())["pages"]}
    assert {"#/system?tab=costs", "#/system?tab=connections", "#/system?tab=settings", "#/memory", "#/guide"} <= pages and "#/telemetry" not in pages


def test_a_run_is_followed_on_its_task_page_and_the_old_run_screens_land_there():
    """One place for a run: its task's page (Where it runs, its steps and each step's log, Sources: from what it read to
    the answer) and Workflows. The task map folded into Sources; old links to it, to Telemetry and a bare #/live land
    where the work is now; a step's log (#/live/<run>) stays, the one view of what an agent did."""
    js, task = webjs.app_js(), (STATIC / "task.js").read_text()
    assert not {"taskmap", "telemetry"} & views() and "live" in views()
    for gone in ("vTaskMap", "tmapTimeline", "tmapMode", "#/taskmap", "vTelemetry"):
        assert gone not in js + task, gone
    assert moved(["taskmap", [], "t=7&o=2"], ["taskmap", [], "t=7"], ["live", [], ""], ["live", ["task:7:step:1"], ""]) == [
        "#/task/7?tab=sources&o=2", "#/task/7?tab=sources", "#/tasks?v=activity", ""]
    src = fn("taskSources", task)
    assert 'taskFlowInto($("#tflow", box), t);' in src and "tmapFlow(el, d, tmapGraph(d));" in fn("taskFlowInto", task)
    assert 'href="#/task/${t.id}?tab=sources&o=${r.occ}"' in task and "The run's log" in task and "how it ran" in task
    assert "wfWhereInto($(\"#wfwhere\")" in task                                     # Where it runs, at the top
    assert "taskSrc, wfWhereOf(d)]);" in task and '"files", "file", "task"].includes(route.name)) return render(true);' in js   # opened cold: Where it runs comes with the state
    decisions = (ROOT / "ops/decisions.py").read_text()
    assert "#/swarm?tab=" not in decisions and '"#/tasks?v=ideas"' in decisions and 'f"#/tasks?v=activity&ctx=' in decisions
    seeds = (ROOT / "ops/journeys.py").read_text()
    assert "#/taskmap" not in seeds and "#/telemetry" not in seeds and 'f"#/task/{tid}?tab=sources"' in seeds


def test_the_menu_names_the_seven_parts_and_every_part_is_reachable():
    """Home, Tasks, Workflows (the desk's), Memory, Code, Chat, Stack; the phone's bar the six without Workflows, in the
    same order. Home has its own address (#/ is whatever the app opens on); the start page offers the same names and
    reads a choice made under the old ones; what the phone shared has a list, one tap from Home's Overview."""
    js = webjs.app_js()
    nav = re.search(r"^const NAV = \[(.*?)\];", js, re.M | re.S)[1]
    assert re.findall(r'\["\w+", "(#/\w+)", "(\w+)"', nav) == [("#/home", "Home"), ("#/tasks", "Tasks"), ("#/workflows", "Workflows"),
        ("#/memory", "Memory"), ("#/build", "Code"), ("#/chat", "Chat"), ("#/system", "Stack")]
    assert 'if (k === "workflows" && bottom) return "";' in js and 'href="#/workflows">${ic.flow}Workflows</a>' in js   # the phone: from Tasks
    assert 'k === "home" && needs ?' in js and "pending_memory" not in fn("navHtml")
    starts = re.search(r"^const START_PAGES = \[(.*?)\];", js, re.M)[1]
    assert "Agents" not in starts and "Wiki" not in starts and '["#/tasks", "Tasks"]' in starts and '["#/memory", "Memory"]' in starts
    html = (APP / "web/index.html").read_text()
    assert '"#/missions": "#/tasks", "#/wiki": "#/memory"' in html and 'class="brand" href="#/home"' in html
    assert "if (!route.args[0]) return shareList();" in (STATIC / "app-devices.js").read_text() and "${sharedCardHtml()}" in fn("vHome")
    assert 'Route("/api/shares", api_shares)' in (APP / "server.py").read_text()


def test_the_app_says_what_is_true_when_the_runner_s_state_is_old():
    """APP-65: "Not connected" only when this device gets no answer from the app; otherwise the stack is starting (with
    the runner's time to come up from the last boot), the runner stopped and since when, or it did not start."""
    js = webjs.app_js()
    src = "\n".join([re.search(rf"^const {n} = [^\n]*", js, re.M)[0] for n in ("linkUp", "liveState", "notConnected", "LIVE_DOT")]
                    + [re.search(r"^function linkWords\(.*?^\}$", js, re.M | re.S)[0]])
    run = src + """
const dur = (s) => (!s ? "–" : s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`);
let S = { running: null }, LINK = null, lastAlive = Date.now(); const noLink = () => false; const out = [];
for (const l of [{ state: "ok" }, { state: "starting", up_s: 60, ready_s: 240 }, { state: "starting", up_s: 200, ready_s: 240 }, { state: "starting", up_s: 60 },
  { state: "stopped", age_s: 720 }, { state: "not_started", up_s: 3600 }]) { LINK = l; out.push([liveState(), linkWords()]); }
lastAlive = Date.now() - 60000; out.push([liveState(), linkWords()]); S = null; out.push([liveState(), linkWords()]);
process.stdout.write(JSON.stringify(out));"""
    got = json.loads(subprocess.run(["node", "-e", run], check=True, capture_output=True, text=True).stdout)
    assert got == [["ok", "Ready"], ["wait", "The stack is starting (runner up in about 3 min)"], ["wait", "The stack is starting (runner up in about a minute)"],
                   ["wait", "The stack is starting"], ["wait", "The runner stopped 12 min ago"], ["wait", "The runner did not start: the PC started 60 min ago"],
                   ["off", "Not connected"], ["off", "Connecting…"]]
    assert 'es.addEventListener("alive"' in js


def test_one_visual_system_every_font_size_is_on_the_type_scale_and_docs_ux_names_the_tokens():
    """APP-67, docs/UX.md: one type scale (no size between two steps), one spacing rhythm, the colour tokens defined for
    both themes, and the components the doc names exist in the stylesheet."""
    css = (STATIC / "app.css").read_text() + (STATIC / "guide.css").read_text()
    sizes = re.findall(r"font-size:\s*([^;}\n]+)", css)
    assert sizes and all(s.strip().startswith(("var(--fs-", "clamp(")) or s.strip().endswith(("em", "rem", "%")) or s.strip() == "inherit" for s in sizes), \
        sorted({s for s in sizes if not s.strip().startswith("var(--fs-")})
    root = css[css.index(":root {"):css.index("}", css.index(":root {"))]
    for k in ("--fs-1:", "--fs-5:", "--fs-9:", "--s-1:", "--s-4:", "--accent:", "--surface:", "--ok:", "--warn:", "--err:", "--run:"):
        assert k in root, k
    light = css[css.index(':root[data-theme="light"]'):]
    assert all(k in light[:light.index("}")] for k in ("--bg:", "--surface:", "--text:", "--accent:", "--ok:", "--err:"))
    doc = (ROOT / "docs/UX.md").read_text()
    for cls in (".hero", ".section-h", ".card", ".btn", ".pill", ".tag", ".seg", ".banner", ".tool-frame", ".kpi"):
        assert f"`{cls}" in doc and any(cls + c in css for c in " {.:,"), cls
    for tok in re.findall(r"`(--fs-\d+|--s-\d+)`", doc):
        assert tok + ":" in root, tok
    assert "toolPage(" in doc and "function toolPage(" in (STATIC / "app-workflows.js").read_text()
    for step, undo in (("1.12", "0.892857"), ("1.3", "0.769231"), ("1.6", "0.625")):       # a wide screen's zoom, undone on a tool's frame
        assert f"zoom: {step}; --z: {step};" in css and f".tool-frame {{ zoom: {undo};" in css
    assert "body[data-page=\"workflows\"] .pagehelp, body[data-page=\"traces\"] .pagehelp { display: none; }" in css


def test_a_schedule_held_by_a_workflow_is_shown_read_only_with_the_way_to_its_workflow():
    """WFL-09: every schedule is a workflow's. A crew job's Settings and a mission's form show it in plain words with a
    link that opens its workflow inside the app; the old schedule form, its presets and the crew_schedule action are
    gone from the app, the server's allow-list and the runner; the event bus has no time trigger any more; a run n8n
    started says so; the Stack page names the three timers that run without n8n."""
    js, wf = webjs.app_js(), (STATIC / "app-workflows.js").read_text()
    for gone in ("CREW_PRESETS", '" (yours)"', "crew_schedule", 'schedule: ["When"'):
        assert gone not in js, gone
    for f in ("images/mission-control/server.py", "ops/crew.py", "ops/missions.requests.py"):
        assert "crew_schedule" not in (ROOT / f).read_text(), f
    settings = fn("agentSettings")
    assert "c.workflow ? wfScheduleHtml(" in settings and "Run now works any time" in settings
    src = re.search(r"^function wfScheduleHtml\(.*?^\}$", wf, re.M | re.S)[0]
    run = "const esc = (s) => String(s); const ic = { flow: '' }; const when = (x) => 'in 2 h'; const explain = () => '';\n" + src + \
        "\nprocess.stdout.write(JSON.stringify([wfScheduleHtml('daily 04:30', 1, 'w1'), wfScheduleHtml('switched off', null, 'w 2')]));"
    a, b = json.loads(subprocess.run(["node", "-e", run], check=True, capture_output=True, text=True).stdout)
    assert 'href="#/workflows?open=w1"' in a and "daily 04:30" in a and "next in 2 h" in a
    assert 'href="#/workflows?open=w%202"' in b and "it does not run until it is switched on" in b
    form = (STATIC / "app-runs.js").read_text()
    assert "m.workflow ? `<div class=\"field\"><span>Schedule</span>${wfScheduleHtml(m.schedule_text" in form
    assert "...(sched ? { schedule: sched } : {})" in form                      # the form leaves a workflow's schedule alone
    assert 'workflow=wf["id"] if wf else None' in (ROOT / "ops/missions.py").read_text()
    assert 'n8n: "by its workflow" };' in js and js.count('n8n: "by its workflow"') == 2
    health = fn("stackHealthHtml")
    assert "<h2>Timers without n8n</h2>" in health and 'href="#/workflows">Every other schedule: Workflows</a>' in health


def test_the_runner_lists_the_stack_s_services_with_three_fields_not_docker_s_slow_json():
    """The live state reported no service on 10 Nov 2026: `docker ps -a --format "{{json .}}"` makes Docker work out
    every container's volumes and mounts (3 s quiet, past the runner's 60 s timeout when busy). Three fields take 0.1 s."""
    import missions as MS
    seen = []

    def run(*cmd, **k):
        seen.append(cmd)
        return "aistack-n8n-1\trunning\tUp 3 minutes (healthy)\naistack-backup-1\texited\tExited (0) 2 hours ago\n\nnot a row\n"
    assert MS.stack_services(run) == [{"name": "n8n", "state": "running", "status": "Up 3 minutes (healthy)"},
                                      {"name": "backup", "state": "exited", "status": "Exited (0) 2 hours ago"}]
    assert seen[0][-1] == "{{.Names}}\t{{.State}}\t{{.Status}}" and not any("json" in x for x in seen[0])
    assert "services = stack_services()" in (ROOT / "ops/missions.py").read_text()

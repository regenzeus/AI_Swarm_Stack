"""Every zoomable chart moves, zooms and names its dots the same way (APP-22, the owner's review of 2026-10-30: one chart
moved with one finger, another only with two, and dots carried no name)."""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "images/mission-control/web/static/app.js").read_text()
SWARM = (ROOT / "images/mission-control/web/static/swarm.js").read_text()


def fn(src, name):
    return re.search(rf"^function {name}\(.*?^\}}$", src, re.M | re.S)[0]


def test_every_chart_moves_and_zooms_through_one_helper_and_one_finger_scrolls_the_page():
    assert len(re.findall(r"d3\.zoom\(\)", APP + SWARM)) == 1                          # only chartZoom makes one
    cz = fn(APP, "chartZoom")
    assert 'style("touch-action", "pan-y")' in cz                                 # one finger scrolls the page (the map swallowed it)
    assert 'e.type === "wheel" ? e.ctrlKey || e.metaKey : e.type.startsWith("touch") ? e.touches.length > 1 : !e.button' in cz
    assert 'data-z="in"' in cz and 'data-z="out"' in cz and 'data-z="fit"' in cz
    assert "d3.drag()" not in APP + SWARM                                              # a finger on a dot moves the view, not the dot
    assert APP.count("chartZoom(") >= 2 and "chartZoom(el, svg, root" in SWARM


def test_names_never_cover_each_other_and_the_busiest_keep_theirs():
    js = "\n".join([fn(APP, "placeLabels"),
        "const el = () => ({ style: {}, setAttribute() {} });",
        "const a = { x: 0, y: 0, r: 5, text: 'agent', prio: 1000, el: el() }, b = { x: 4, y: 2, r: 3, text: '#12 an idea', prio: 1, el: el() },",
        "  c = { x: 400, y: 0, r: 3, text: '#13 far away', prio: 1, el: el() };",
        "placeLabels([a, b, c], 1); const at1 = [a, b, c].map((i) => i.el.style.display);",
        "placeLabels([a, b, c], 8); const at8 = [a, b, c].map((i) => i.el.style.display);",
        "process.stdout.write(JSON.stringify([at1, at8, a.el.style.fontSize]));"])
    at1, at8, size = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert at1 == ["", "none", ""]                                                     # the agent keeps its name, the crowded idea waits
    assert at8 == ["", "", ""] and size == "1.375px"                                   # zoomed in, every dot is named, names stay 11 px on screen


def test_the_map_names_every_dot_and_shows_open_ideas_when_asked():
    g = re.search(r"^function swMapCard\(.*?^\}$", SWARM, re.M | re.S)[0]                # who works on what is the map's "Ideas too"
    assert "swIdeaLabel(x)" in g and "placeLabels(items, t.k)" in g and "swMapIdeas ? (g.artifacts || []).filter((x) => !closed(x.state))" in g
    assert 'root.append("g").selectAll("text")' in g                                    # names drawn above every dot
    assert "#/swarm/artifact/${d.aid}" in g                                             # a tap opens the idea
    js = "\n".join([re.search(r"^const swIdeaLabel = .*$", SWARM, re.M)[0],
        "process.stdout.write(JSON.stringify([swIdeaLabel({id: 4, title: 'Refresh the desk feeds every hour'}), swIdeaLabel({id: 9, title: 'PC disk cleanup'})]));"])
    assert json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout) == ["#4 Refresh the desk feeds …", "#9 PC disk cleanup"]
    assert "groupName(c)" in APP and "`around ${top.title}`" in APP                        # the code graph's groups by name, not number


def test_a_redraw_keeps_the_map_s_dots_and_zoom():
    """APP-22: the map redraws with live data; its dots stay put (new ones settle around them) and so does the zoom."""
    m = fn(SWARM, "swMapCard")
    assert "fx: was[n.id].x, fy: was[n.id].y" in m and "settled ? 0" in m
    assert "swOv.pos = Object.fromEntries" in m and "svg.call(zoom.transform, swOv.zoom || d3.zoomIdentity)" in m


def test_explanations_fold_and_stay_open_through_redraws():
    """APP-31"""
    g = (ROOT / "images/mission-control/web/static/guide.js").read_text()
    assert 'const explain = (key, html, label = "About this") => `<details class="explain"' in g and "EXPLAIN_OPEN.has(key)" in g
    assert APP.count("${explain(") >= 17 and SWARM.count("${explain(") >= 9 and "fab" not in APP


def test_a_live_update_redraws_the_agents_page_only_when_its_list_changed():
    """APP-32: the overview's live parts update in place; the page itself is redrawn only when what it lists changed."""
    r = fn(APP, "render")
    assert 'route.name === "missions" && missionsSig() === missionsSig.last) return swOverview();' in r
    assert "missionsSig.last = missionsSig();" in fn(APP, "vMissions")


def test_back_returns_to_where_you_were_and_a_new_page_starts_at_the_top():
    """APP-33: run the app's own navigation logic in node with a fake history."""
    import subprocess
    nav = re.search(r"const scrollAt = \{\};.*?\nfunction restoreScroll", APP, re.S)[0].rsplit("\n", 1)[0]
    js = "\n".join([
        "const listeners = {}; const window = { scrollY: 0, addEventListener: (k, f) => (listeners[k] = f) };",
        "let entries = [{ state: null }], at = 0; const history = { get state() { return entries[at].state; },",
        "  replaceState(s) { entries[at].state = s; } }; const location = { hash: '#/' };",
        nav.replace("const scrollAt", "var scrollAt"),
        "const go = (h) => { entries = entries.slice(0, at + 1); entries.push({ state: null }); at++; location.hash = h; return navStep(); };",
        "const back = (h) => { at--; location.hash = h; return navStep(); };",
        "window.scrollY = 900; listeners.scroll();",           # read down Agents
        "const a = go('#/swarm/agent/scout');",                # open an agent: a new page
        "const b = back('#/');",                               # back
        "process.stdout.write(JSON.stringify([a, b, scrollAt['#/']]));"])
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == ["new", "history", 900]


def test_the_theme_is_calm():
    """APP-34: graphite and opaque surfaces, no glow behind the pages, section titles in sentence case, grey counts."""
    css = (ROOT / "images/mission-control/web/static/app.css").read_text()
    html = (ROOT / "images/mission-control/web/index.html").read_text()
    assert "--bg: #111317;" in css and "--glow-1: transparent;" in css and ".bg-glow { display: none; }" in css
    assert "h2 { font-size: 15px; font-weight: 650; text-transform: none;" in css and ".hcount { background: var(--surface-3)" in css
    assert "bg-glow" not in html and ".btn.primary { background: var(--accent); box-shadow: none; }" in css


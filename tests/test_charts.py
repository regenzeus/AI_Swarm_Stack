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


def test_every_chart_moves_and_zooms_through_one_helper_with_one_finger():
    assert len(re.findall(r"d3\.zoom\(\)", APP + SWARM)) == 1                          # only chartZoom makes one
    cz = fn(APP, "chartZoom")
    assert 'style("touch-action", "none")' in cz and 'e.type === "wheel" ? e.ctrlKey || e.metaKey : !e.button' in cz
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


def test_who_works_on_what_names_every_dot_and_hides_closed_ideas_until_asked():
    g = re.search(r"^async function swGraph\(.*?^\}$", SWARM, re.M | re.S)[0]
    assert "swIdeaLabel(x)" in g and "placeLabels(items, t.k)" in g and "Closed ideas · ${nClosed}" in g
    assert 'root.append("g").selectAll("text")' in g                                    # names drawn above every dot
    assert "info.innerHTML" in g and "#/swarm/artifact/${d.aid}" in g                   # a tap says what the dot is
    js = "\n".join([re.search(r"^const swIdeaLabel = .*$", SWARM, re.M)[0],
        "process.stdout.write(JSON.stringify([swIdeaLabel({id: 4, title: 'Refresh the desk feeds every hour'}), swIdeaLabel({id: 9, title: 'PC disk cleanup'})]));"])
    assert json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout) == ["#4 Refresh the desk feeds …", "#9 PC disk cleanup"]
    assert "groupName(c)" in APP and "`around ${top.title}`" in APP                        # the code graph's groups by name, not number

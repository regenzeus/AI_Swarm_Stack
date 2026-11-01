"""images/mission-control/web/static/app.js: every screen gets drawn when opened cold (e.g. from a notification)."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "images/mission-control/web/static"
APP_JS = (STATIC / "app.js").read_text()


def names(pattern):
    return set(re.findall(r'"(\w+)"', re.search(pattern, APP_JS, re.S)[1]))


def test_every_screen_is_drawn_when_opened_cold():
    routes = {k.split(":")[0].strip() for k in re.search(r"const fn = \{(.*?)\}\[route\.name\]", APP_JS, re.S)[1].split(",")}
    no_state = names(r'if \(!S && !\[(.*?)\]\.includes\(route\.name\)\)')        # drawn without waiting for the state
    on_first = names(r'if \(first && \[(.*?)\]\.includes\(route\.name\)\) return render\(true\)')
    live = names(r'const LIVE = new Set\(\[(.*?)\]\)')                           # redrawn on every state update
    stuck = routes - no_state - on_first - live
    assert not stuck, f"screens that stay on the loading skeleton when opened cold: {stuck}"


def test_an_open_timeline_is_not_redrawn_away():
    assert '!$(".tl:not([hidden])")' in APP_JS          # the live Runs tab keeps an open timeline open


def test_the_connections_card_is_started_by_render():
    assert 'if (route.name === "system") { clearInterval(connTimer); drawConnections();' in APP_JS



def test_live_redraws_do_not_replay_the_entrance_animation():
    css = (Path(__file__).resolve().parent.parent / "images/mission-control/web/static/app.css").read_text()
    assert "body.anim .fadein" in css and "\n.fadein {" not in css        # pages twitched every 15-20 s



def test_the_interactive_code_map_is_inside_the_repo_page():
    js = (Path(__file__).resolve().parent.parent / "images/mission-control/web/static/app.js").read_text()
    assert '<iframe src="${HOSTURL}:8446/"' in js and 'id="rstudy2"' in js     # the owner asked for it in Code -> repo, twice



def test_the_tab_bar_spreads_however_many_tabs_there_are():
    css = (Path(__file__).resolve().parent.parent / "images/mission-control/web/static/app.css").read_text()
    assert "grid-auto-flow: column; grid-auto-columns: 1fr;" in css and "repeat(6, 1fr)" not in css


def test_view_scripts_load_before_app_js_and_take_no_arguments():
    """app.js draws the first screen as it loads, and render() calls each screen's view without arguments."""
    web = Path(__file__).resolve().parent.parent / "images/mission-control/web"
    html = (web / "index.html").read_text()
    for js in ("guide.js", "shop.js", "swarm.js"):
        assert html.index(js) < html.index("/static/app.js"), js
    views = {k.split(":")[1].strip() for k in re.search(r"const fn = \{(.*?)\}\[route\.name\]", APP_JS, re.S)[1].split(",")}
    code = "".join(f.read_text() for f in (web / "static").glob("*.js"))
    for v in views:
        assert re.search(rf"^(async )?function {v}\(\)", code, re.M), f"{v} is missing or takes arguments"


def test_a_page_that_loads_draws_only_while_you_are_still_on_it():
    """FND-95: the wiki's index loaded slowly and was drawn over the Agents page you had moved to (the Agents tab lit,
    the Wiki on screen). Every page that waits for data checks, after its first wait, that it is still the page."""
    for f in ("app.js", "swarm.js", "guide.js", "task.js"):
        src = (STATIC / f).read_text()
        for m in re.finditer(r"^async function (v[A-Z]\w*)\(\) \{\n(.*?)^\}", src, re.S | re.M):
            body = m.group(2)
            first = body.find("await ")
            draw = body.find("view.innerHTML", first) if first >= 0 else -1
            if draw < 0:
                continue
            assert re.search(r"route\.(name|args|q)|mountRun|swAgents|swActivity|loadGuide", body[first:draw]), \
                f"{f}: {m.group(1)} draws after a wait without checking it is still the page"


def test_a_live_redraw_never_scrolls_the_page():
    """FND-96: the Agents page jumped up while you read it: a redraw centred its view tabs with scrollIntoView, which
    scrolled the whole page to the row. Code that runs on every redraw moves only its own row (scrollLeft)."""
    i = APP_JS.index("function agentViews(")
    body = APP_JS[i:APP_JS.index("\n}\n", i)]
    assert "scrollIntoView" not in body and "scrollLeft" in body


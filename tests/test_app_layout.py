"""The app's frame (APP-01): no app top bar, every section in the tab bar with the live state as a dot on Stack, the
swarm's views under Agents, the chat's own bar and buttons, and a page's main action on its title row on one line."""
import webjs
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "images/mission-control/web/static"
CSS, JS = (STATIC / "app.css").read_text(), webjs.app_js()
SWARM = (STATIC / "swarm.js").read_text()
HTML = (STATIC.parent / "index.html").read_text()


def test_the_chat_has_one_top_bar_on_a_phone_with_the_live_state_in_it():
    phone = re.search(r"@media \(max-width: 959px\) \{\s*/\* on a phone the chat's own bar is the only top bar.*?\n\}", CSS, re.S)[0]
    assert "position: sticky" in phone and "body.chatmode .chathead .chatchip { display: inline-flex;" in phone
    head = re.search(r'<div class="chathead">.*?</div>', JS, re.S)[0]
    assert 'id="chatchip"' in head and "function mirrorChip()" in JS and "mirrorChip();" in JS


def test_an_icon_in_text_is_one_line_high_and_no_page_has_an_app_top_bar():
    assert 'const I = (d) => `<svg class="ico"' in JS                                  # every icon has a default size
    assert ".ico { width: 1.15em; height: 1.15em;" in CSS                               # (the run page's tune icon filled the card)
    assert '<header class="top">' not in HTML and 'class="top-r"' not in HTML and "stackbtn" not in HTML
    assert '<div id="livebar" class="livebar" hidden><div id="live-chip" class="chip"></div></div>' in HTML
    assert "if (bar) bar.hidden = !updateReady && liveState() !== \"off\";" in JS          # only while offline or an update waits
    nav = re.search(r"^const NAV = .*?;$", JS, re.M | re.S)[0]
    assert '["system", "#/system", "Stack", ic.layers]' in nav and "NAV.map(" in JS and "k === \"swarm\"))" not in JS
    assert '`<span class="tab-dot ${liveState()}"' in JS and ".tab-dot.run" in CSS     # the live state is the dot on Stack
    assert '<div id="pagehelp" class="pagehelp"><a href="#/guide">How this page works</a></div>' in HTML and "helpbtn" not in HTML
    assert 'help.querySelector("a").href = helpHref()' in JS and "body.chatmode .pagehelp { display: none; }" in CSS
    assert "!/^##\\s*Your memory/.test(V.title)" in JS                                  # a run's prompt preamble is no subtitle


def test_the_swarm_s_views_are_under_agents_on_every_screen():
    """Since 8 Nov 2026 (DEC-46) the agents' views are views of the Tasks tab, which lights up on every page of a task,
    a mission, a crew duty, an agent and the old addresses."""
    assert '["swarm", "#/swarm"' not in JS                                              # no section of its own, hidden on a phone
    assert '(k === "tasks" && ["task", "taskmap", "mission", "crew", "new", "swarm", "missions", "telemetry", "trials"].includes(route.name))' in JS
    assert '(k === "home" && route.name === "decide")' in JS                             # decided on Home (AUT-05)
    assert '"read", "swarm"' not in JS                    # a result opened from the Wiki or Home is no Agents page (FND-95)
    views = re.search(r"^const TVIEWS = .*?;$", JS, re.M | re.S)[0]
    for label in ("Tasks", "Activity", "Team", "Network", "Ideas"):
        assert f'"{label}"]' in views
    assert "async function swRender(body, tab" in SWARM and "<h1>Agents</h1>" not in SWARM and "<h1>Tasks</h1>" in JS


def test_new_chat_starts_afresh_and_attaching_is_a_clip():
    head = re.search(r'<div class="chathead">.*?\n      </div>', JS, re.S)[0]
    assert "data-newchat" not in head and "${ic.plus}" not in head                     # not in the header: first in the list of chats (APP-46)
    assert 'aria-label="Attach pictures or documents">${ic.clip}<input type="file" id="cfile"' in JS
    assert '<a class="btn primary cnew" href="#/chat?new=1" data-newchat>' in JS and '!route.q.get("new")' in JS


def test_the_wiki_s_new_button_is_one_line_on_the_title_row():
    assert 'class="btn sm" id="wnewb"' in JS                                             # beside Add to the vault, under the tab's frame (APP-50)
    assert ".btn.sm { white-space: nowrap; flex: none; }" in CSS and ".hero.heading { display: block; }" in CSS


def test_the_section_headings_keep_their_gap_and_stay_on_one_line():
    assert ".section-h.section { margin-top: 26px; }" in CSS                            # (the Code page's headings sat on the card above)
    assert ".section-h > h2 { white-space: nowrap; }" in CSS


def test_the_wiki_tab_opens_on_every_wiki_and_a_wiki_on_its_pages():
    assert 'if (!route.q.get("root")) return wikiIndex();' in JS and "function wikiIndex()" in JS
    assert "wikiRoots.find((r) => r.mission)" not in JS                                 # no wiki is picked for the owner
    v = re.search(r"async function vWiki\(\) \{.*?\n\}\n", JS, re.S)[0]
    assert '[["pages", "Pages"], ["graph", "Graph"], ["about", "About"]]' in v and 'id="wq"' in v
    assert v.index("if (pageId)") < v.index('id="wq"')                                  # an open page has the screen to itself
    assert 'if (root !== wikiLast) { wikiMode = "pages"; wikiLast = root; }' in v
    assert ".wside" not in CSS                                                          # no list scrolls inside the page


def test_a_crew_agent_s_claude_task_is_named_after_it_and_keeps_its_whole_question():
    assert "`Asked by the ${ctAsker(t)}`" in JS and "esc(ctTitle(t))" in JS
    row = re.search(r"function ctRow\(t\) \{.*?\n\}\n", JS, re.S)[0]
    assert "The whole question" in row and "${esc(t.question)}</div></details>" in row   # nothing of it is cut
    assert "function ctAnswer(a)" in JS and "${T.answer ? ctAnswer(T.answer)" in JS     # the doctor's JSON reads as findings


def test_every_idea_is_in_one_list_under_agents():
    assert '["ideas", "Ideas"]' in JS and 'swRender(b, "improve"' in JS and "function proposalsHtml" not in JS and "The stack suggests" not in JS
    ideas = SWARM[SWARM.index("function swIdeas(body, quiet) {"):SWARM.index("// the numbers behind the improvement loop")]
    assert "stackIdeaCard(p, n)" in ideas and "change(a)" in ideas and "ideaRulesHtml()" in ideas and "Decided lately" in ideas
    assert '[["all", "All"], ["stack", "The stack"], ["agent", "The agents"]]' in ideas
    assert ideas.index("changesOpen.filter(passed)") < ideas.index("(b.open || []).map((p, n)") < ideas.index("changesOpen.filter((a) => !passed(a))")
    assert "function swImprove" not in SWARM and "${swLoopNumbers()}" in SWARM                   # its numbers are under Flow
    assert JS.count('href="#/tasks?v=ideas"') >= 2 and "ideasWaiting()" in JS   # Code only links to it; Home's count row comes from the queue (GEN-02)


def test_the_phone_chat_is_pinned_to_the_screen_and_the_title_has_its_own_width():
    phone = re.search(r"@media \(max-width: 959px\) \{\s*/\* on a phone the chat's own bar is the only top bar.*?\n\}", CSS, re.S)[0]
    assert "body.chatmode .chatwrap { position: fixed; top: 0;" in phone and "bottom: calc(65px + env(safe-area-inset-bottom))" in phone
    assert "100dvh" not in phone.split("body.chatmode .chatwrap", 1)[1].split("}", 1)[0]    # went stale when the keyboard closed
    assert "body.chatmode { overflow: hidden;" in phone
    assert "interactive-widget=resizes-content" in HTML                                     # the keyboard resizes the layout
    assert re.search(r"max-height: 560px\) \{[^}]*\n  body.chatmode .tabbar \{ display: none; \}", CSS)
    head = re.search(r'<div class="chathead">.*?\n      </div>', JS, re.S)[0]
    assert head.index('id="ctitle"') < head.index('class="chatstat"') < head.index('id="chatchip"')
    assert "new ResizeObserver(() => { if (atEnd) pane.scrollTop = pane.scrollHeight; }).observe(pane);" in JS


def test_the_look_is_opaque_and_exact_with_its_type_vendored():
    """APP-46, from photos of a fresh install on a light screen: washed-out see-through surfaces and faint small print."""
    light = CSS[CSS.index(':root[data-theme="light"]'):]
    light = light[:light.index("}")]
    assert "--surface: #ffffff" in light and "rgba(255,255,255" not in light          # surfaces are solid
    assert "--faint: #66737e" in light                                                 # small print stays readable on white
    assert "--rail:" in CSS[:CSS.index(':root[data-theme="light"]')] and "--rail:" in light
    assert "bg-glow" not in CSS or "transparent" in CSS
    docker = (STATIC.parent.parent / "Dockerfile").read_text()
    sw = (STATIC.parent / "sw.js").read_text()
    for font in ("archivo.woff2", "jetbrains-mono.woff2"):
        assert f"/static/vendor/{font}" in CSS and f"/app/web/static/vendor/{font}" in docker and f"/static/vendor/{font}" in sw
    assert ":focus-visible" in CSS and "prefers-reduced-motion" in CSS


def test_a_screen_without_a_connection_claims_nothing():
    """QA-23 in the app: the same photos said Offline beside Ready, all services running and all quiet."""
    assert "function footState()" in JS and "footState();" in JS
    assert "Ready\"} · updated" not in JS and "Offline ·" not in JS
    for where in ("function homeHeadHtml", "function needsHtml", "function vSystem"):
        body = JS[JS.index(where):]
        assert "notConnected()" in body[:body.index("\n}")], where
    assert "<b class=\"err-t\">Not connected</b>" in JS


def test_a_fresh_install_sees_no_one_else_s_topics():
    for private in ("copper", "Gamma Metals", "Watch ASPI"):
        assert private not in JS[JS.index("What are my agents doing?") - 40:JS.index("What are my agents doing?") + 300]
    assert 'live.length === 1 ? "" : "s"' in JS                                         # "1 wikis"


def test_a_page_that_loads_shows_it_is_coming_and_a_tool_without_an_address_has_no_tile():
    body = JS[JS.index("function render("):]
    assert "render.nav" in body[:body.index("\n}")] and 'class=\"skeleton\"' in body[:body.index("\n}")]
    assert "toolsHere(JSON.parse(" in JS and '!("host" in x) || (x.host &&' in JS and "https?:" in JS


def test_an_app_no_runner_ever_wrote_to_is_not_connected():
    """Seen by running the image alone with empty data: it said Ready and all quiet while Stack said not connected."""
    assert "!S || !S.generated ||" in JS and "the runner has written nothing here" in JS
    assert 'notConnected() ? "not known" : "all quiet"' in JS



def test_the_desk_uses_the_width_it_has():
    """APP-56: above 1,100 px the pages stop being a phone column in the middle: the view is as wide as the window with
    gutters in proportion, Home's three parts stand as columns (its tabs go), a repository's graph has the node panel beside
    it, the chat list and the repository cards widen, a wiki page or the guide keeps a reading measure, and a very wide
    window scales the whole app up in steps. The stylesheet knows the page."""
    import webjs
    css = (STATIC / "app.css").read_text()
    assert "document.body.dataset.page = route.name;" in webjs.app_js()
    desk = css.rsplit("@media (min-width: 1100px) {", 1)[1].split(chr(10) + "}" + chr(10), 1)[0]     # the desk block is the last one
    assert ".view, .pagehelp { max-width: none; }" in desk and ".view { padding: 28px clamp(24px, 3vw, 72px) 16px; }" in desk   # fluid, gutters in proportion
    assert 'body[data-page="home"] .home { max-width: none; display: grid;' in desk
    assert 'body[data-page="home"] .homeseg { display: none; }' in desk and 'body[data-page="home"] .home-pane[hidden] { display: flex !important; }' in desk
    assert ".rgwrap { grid-template-columns: minmax(0, 1.6fr) minmax(320px, 1fr);" in desk and ".chatwrap { grid-template-columns: 320px minmax(0, 1fr); }" in desk
    assert ".repos { grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); }" in desk
    assert 'body[data-page="read"] .view, body[data-page="guide"] .view' in desk and "max-width: 980px" in desk
    assert "@media (min-width: 1900px) { .shell { zoom: 1.12; --z: 1.12; } }" in css and "@media (min-width: 3200px) { .shell { zoom: 1.6; --z: 1.6; } }" in css   # a 4K screen scales the app, not a corner of it
    assert "max-width: 1440px" not in css and "max-width: 1680px" not in css
    assert ".chatpane .msgs { padding-left: max(0px, calc((100% - 960px) / 2));" in desk and ".chatpane .composer2 { margin-left:" in desk   # a chat keeps a reading measure


def test_an_agent_s_own_sentence_shows_dates_the_app_s_way_and_quotes_as_quotes():
    """Overnight journeys, 8 Nov 2026: agents' sentences (an idea's signal, a crew finding, a feed line, a decision's reason)
    showed raw "2026-11-02T15:19" and a quoted error's "undefined" as if the app said it; a reader page that failed after you
    left it threw; a task's run picker scrolled the phone sideways."""
    app = webjs.app_js() + (STATIC / "task.js").read_text()
    assert "const prose = (text) => esc(String(text ?? \"\")).replace(ISO_IN_TEXT" in app and '<q class="quote">$1</q>' in app
    for spot in ('<div class="tiny faint psig">${ic.radar}${prose(p.signal || "")}', '<div class="sub wrap">${prose(d.why)}</div>',
                 '<div class="fi-x small muted wrap">${prose(x.sub)}</div>', '<div class="sub">${prose(r.text || "")}</div>',
                 '<div class="small muted agwhat">${prose(t.goal)}</div>', '${prose(i.text)}</div>'):
        assert spot in app, spot
    assert 'const d = $("#doc"); if (d) d.textContent = "Not readable.";' in app
    assert 'id="tocc" style="width:auto;max-width:100%;min-width:0;flex:1 1 auto"' in app


def test_chat_on_a_desktop_holds_the_window_and_no_height_overshoots_the_zoom():
    """APP-59. The owner, 9 Nov 2026: "Chat still looks ugly in desktop. You open it and then scroll down to see chat
    window." From 1,900 px the app is zoomed, and every height taken from the window came out 12 % too tall: the input
    box fell below the fold and every page scrolled. Each such height divides by the zoom; on a desktop the chat's list
    and conversation scroll in their own columns; Home's left column fills its width."""
    css = (Path(__file__).resolve().parents[1] / "images/mission-control/web/static/app.css").read_text()
    for z in ("1.12", "1.3", "1.6"):
        assert f"zoom: {z}; --z: {z};" in css
    inside = [ln for ln in css.splitlines() if re.search(r"100d?vh", ln) and not ln.lstrip().startswith(("-webkit-font-smoothing", "/*"))
              and "zoom: 0." not in ln]   # GEN-34: the editor undoes the zoom itself (its React Flow measures page pixels), so its own height is the window's
    assert inside and all("var(--z, 1)" in ln for ln in inside), [ln for ln in inside if "var(--z, 1)" not in ln]
    assert "body.chatmode .view { height: calc(100dvh / var(--z, 1));" in css and "body.chatmode .chatpane .msgs { flex: 1 1 0; min-height: 0; overflow-y: auto; }" in css
    assert 'body[data-page="home"] .home-today { grid-area: today; display: flex; align-items: stretch; }' in css


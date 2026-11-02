"""The app's frame (APP-01): no app top bar, every section in the tab bar with the live state as a dot on Stack, the
swarm's views under Agents, the chat's own bar and buttons, and a page's main action on its title row on one line."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "images/mission-control/web/static"
CSS, JS = (STATIC / "app.css").read_text(), (STATIC / "app.js").read_text()
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
    assert '["swarm", "#/swarm"' not in JS                                              # no section of its own, hidden on a phone
    assert '(k === "missions" && ["mission", "crew", "new", "swarm"].includes(route.name))' in JS   # Agents lights up on them
    assert '(k === "home" && ["tasks", "task", "taskmap", "decide"].includes(route.name))' in JS   # tasks are given on Home (APP-37), and decided there (AUT-05)
    assert '"read", "swarm"' not in JS                    # a result opened from the Wiki or Home is no Agents page (FND-95)
    views = re.search(r"^const AGENT_VIEWS = .*?;$", JS, re.M | re.S)[0]
    for label in ("Overview", "Activity", "Team", "Ideas"):                          # four views (1 Nov 2026)
        assert f'"{label}"]' in views
    assert '${agentViews("list")}' in JS and "${agentViews(swTab)}" in SWARM and "<h1>Agents</h1>" in SWARM


def test_new_chat_starts_afresh_and_attaching_is_a_clip():
    head = re.search(r'<div class="chathead">.*?\n      </div>', JS, re.S)[0]
    assert 'title="New chat" aria-label="New chat" data-newchat>${ic.compose}' in head and "${ic.plus}" not in head
    assert 'aria-label="Attach pictures or documents">${ic.clip}<input type="file" id="cfile"' in JS
    assert 'if (location.hash !== "#/chat") return;' in JS and '$$("[data-newchat]")' in JS   # (on #/chat the link changed nothing)


def test_the_wiki_s_new_button_is_one_line_on_the_title_row():
    hero = re.search(r'<div class="hero heading"[^>]*><div class="row between"[^>]*><h1>Wiki</h1>.*?</div><p>', JS, re.S)[0]
    assert "<h1>Wiki</h1>" in hero and 'class="btn sm" id="wnewb"' in hero
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
    assert '["improve", "Ideas"]' in JS and "function proposalsHtml" not in JS and "The stack suggests" not in JS
    ideas = SWARM[SWARM.index("function swIdeas(body, quiet) {"):SWARM.index("// the numbers behind the improvement loop")]
    assert "stackIdeaCard(p, n)" in ideas and "change(a)" in ideas and "ideaRulesHtml()" in ideas and "Decided lately" in ideas
    assert '[["all", "All"], ["stack", "The stack"], ["agent", "The agents"]]' in ideas
    assert ideas.index("changesOpen.filter(passed)") < ideas.index("(b.open || []).map((p, n)") < ideas.index("changesOpen.filter((a) => !passed(a))")
    assert "function swImprove" not in SWARM and "${swLoopNumbers()}" in SWARM                   # its numbers are under Flow
    assert JS.count('href="#/swarm?tab=improve"') >= 2 and "const props = ideasWaiting()" in JS   # Code and Home only link to it

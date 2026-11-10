"""The repo page's tabs (APP-51): one question each, a link per tab, data loaded when a tab opens, and the facts in plain
words: the most telling rows first, nothing cut, and a plain sentence with Re-analyse when there are none."""
import webjs
import json
import re
import shutil
import subprocess
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "images/mission-control/web/static"
APP = webjs.app_js()
CSS = (STATIC / "app.css").read_text()
FORMAT_BLOCK = re.compile(r"// ---------- formatting \(TSK-31\).*?// ---------- end of formatting ----------", re.S)
DRAW_BLOCK = re.compile(r"// ---------- the repo page's tabs that only draw.*?// ---------- end of the repo page's tabs that only draw ----------", re.S)
STUBS = """
const ONB_LIVE = ["queued", "running", "waiting"];
const ic = new Proxy({}, { get: () => "" });
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const explain = (key, html, label) => `<details class="explain" data-x="${key}"><summary aria-label="${label}"></summary><div>${html}</div></details>`;
const emptyState = (text, action, cls = "") => `<div class="empty ${cls}"><div>${text}</div><div class="empty-a">${action}</div></div>`;
const fcolor = () => "red";
const firstSentence = (s) => s;
"""
# the shape of /api/repo/{name}/facts, from what CodeLore and repowise wrote for click on 7 Nov 2026
HOTSPOTS = [{"path": "src/click/testing.py", "revisions": 73, "cognitive": 25.0, "cognitive_health": 82.7, "hotspot_score": 2.98, "mi": -46.0},
            {"path": "src/click/core.py", "revisions": 431, "cognitive": 45.0, "cognitive_health": 68.9, "hotspot_score": 7.58, "mi": -235.5},
            {"path": "tests/test_arguments.py", "revisions": 66, "cognitive": 9.0, "cognitive_health": 93.7, "hotspot_score": 0.75, "mi": -123.1}] \
    + [{"path": f"src/click/f{i}.py", "revisions": 10 + i, "cognitive": 16.0, "cognitive_health": 88.9, "hotspot_score": 1.0 + i / 10, "mi": -9.0} for i in range(9)]
FACTS = {
    "at": "2026-11-07T08:44:54+00:00", "commit": "ac0e297ec2d7d78455a7d18ce306996e668c4a85", "commits": 2412, "errors": [],
    "hotspots": HOTSPOTS,
    "coupling": [{"entity_a": "examples/colors/setup.py", "entity_b": "examples/termui/setup.py", "shared": 5, "revs_a": 6, "revs_b": 6, "degree": 83.3, "fisher_p": 9.1e-14},
                 {"entity_a": "requirements/dev.txt", "entity_b": "requirements/docs.txt", "shared": 51, "revs_a": 110, "revs_b": 51, "degree": 63.35, "fisher_p": 1.6e-72}],
    "ownership": [{"path": "docs/bashcomplete.rst", "main_author": "test@example.com", "total_revs": 25, "fractal_value": 0.9152},
                  {"path": "CHANGES.rst", "main_author": "a@example.com", "total_revs": 639, "fractal_value": 0.9078},
                  {"path": "src/one.py", "main_author": "friend@example.org", "total_revs": 40, "fractal_value": 0.05}],
    "code_age": [{"path": "CHANGES.md", "age_months": 1, "age_days": 45, "last_modified": "2026-09-23"},
                 {"path": "docs/arguments.md", "age_months": 1, "age_days": 59, "last_modified": "2026-09-09"}],
    "health": {"sections": [
        {"id": "components", "title": "Component map and posture", "summary": "", "checks": [
            {"name": "component-map", "score": None, "reason": "1 component(s): 0 declared, 1 derived; 138 file(s) belong to none", "details": [], "basis": "inferred", "data": {"declared": 0, "derived": 1, "unassigned_files": 138}},
            {"name": "components", "score": None, "reason": "1 component(s); no declared owner: 1", "details": ["no declared owner: click"], "basis": "measured", "data": {"components": {"click": {
                "file_count": 17, "health": {"average": 3.8, "worst_path": "src/click/core.py", "worst_score": 1.0},
                "ownership": {"files_with_declared_owner": 0, "recent": {"commits": 37, "contributors": 3, "window_days": 90, "as_of": "2026-10-05"}}}}}}]},
        {"id": "dead-code", "title": "Dead code", "summary": "", "checks": [
            {"name": "dead-code", "score": None, "reason": "10 open finding(s), 1070 line(s) where counted", "details": ["unreachable_file: 10"], "basis": "inferred", "data": {"by_kind": {"unreachable_file": 10}, "lines": 1070}},
            {"name": "dead-code:high", "score": None, "reason": "5 finding(s) at high confidence", "details": [], "basis": "inferred", "data": {"count": 5}},
            {"name": "dead-code:low", "score": None, "reason": "0 finding(s) at low confidence", "details": [], "basis": "inferred", "data": {"count": 0}}]},
        {"id": "bus-factor", "title": "Bus-factor exposure", "summary": "", "checks": [
            {"name": "bus-factor", "score": None, "reason": "1 component(s); bus factor 2: 1", "details": [], "basis": "measured", "data": {"components": {"click": {"value": 2, "owned_files": 17, "file_count": 17, "single_owner_files": 0}}}}]},
        {"id": "test-reach", "title": "Test reach", "summary": "", "checks": [
            {"name": "test-reach", "score": 6.1, "reason": "20 of 33 production file(s) reached by a test", "details": [], "basis": "inferred", "data": {"reached_files": 20, "production_files": 33, "share": 0.61}},
            {"name": "line-coverage", "score": -1, "reason": "no coverage report is ingested; `repowise coverage add` ingests one", "details": [], "basis": "unresolved"},
            {"name": "brand-new-check", "score": 4.0, "reason": "3 widget(s) out of order", "details": ["left_over: 3"], "basis": "measured"}]},
        {"id": "provenance", "title": "Provenance", "summary": "", "checks": [{"name": "provenance:agents", "score": None, "reason": "no commit in the window names an agent", "details": [], "basis": "declared"}]},
    ]},
}


def draw(fn, *args):
    """Run one of the repo page's drawing functions in node, as the page would, on data."""
    js = FORMAT_BLOCK.search(APP)[0] + STUBS + DRAW_BLOCK.search(APP)[0] + f"\nprocess.stdout.write({fn}(...{json.dumps(args)}));"
    return subprocess.run([shutil.which("node") or "node", "-e", js], capture_output=True, text=True, check=True).stdout


def body_of(start):
    i = APP.index(start)
    return APP[i:APP.index("\n}\n", i)]


def text_of(html):
    return re.sub(r"\s+", " ", re.sub(r"<details.*?</details>", " ", re.sub(r"<[^>]+>", lambda m: m[0] if m[0].startswith(("<details", "</details")) else " ", html), flags=re.S))


def test_the_repo_page_has_seven_tabs_one_question_each():
    tabs = re.search(r"const REPO_TABS = (\[.*?\]);\n", APP)[1]
    assert re.findall(r'"([A-Z]\w+)"', tabs) == ["Overview", "Map", "Card", "History", "Health", "Analysis", "Wiki"]   # DEC-49: the Card
    assert '<nav class="seg repotabs"' in APP and 'route.q.get("tab")' in body_of("function repoTabNow(")
    assert '`#/repo/${encodeURIComponent(name)}?tab=${tab}`' in APP               # a link per tab


def test_six_labels_fit_a_phone_and_nothing_is_ellipsed():
    assert re.search(r"@media \(max-width: 480px\) \{[^}]*\}? *\.repotabs a \{ padding: 8px 3px; font-size: var\(--fs-2\); \}", CSS)
    assert ".rflist:not(.all)" not in CSS                                            # every row shows from the start (APP-57)
    assert not re.search(r"text-overflow:\s*ellipsis|line-clamp", CSS)


def test_a_tab_change_touches_no_page_and_a_live_redraw_keeps_the_tab_and_the_place():
    assert "if (route.name + route.args[0] !== prev || !repoTabSwitch()) render(true);" in APP
    switch = body_of("function repoTabSwitch(")
    assert "render(" not in switch and "innerHTML" not in switch
    show = body_of("function showRepoTab(")
    assert "sessionStorage.setItem" in show and "scrollIntoView" not in show and "scrollLeft" in show
    assert "repoRedraw()" in body_of("function repoLive(") and "render(true)" not in body_of("function repoLive(")
    redraw = body_of("function repoRedraw(")
    assert "window.scrollY" in redraw and "window.scrollTo(0, y)" in redraw and "f.text.value" in redraw
    assert 'route.name === "repo") return repoLive()' in APP


def test_a_tab_loads_its_data_only_when_it_opens():
    first_draw = body_of("function vRepo(") + body_of("function repoOverviewHtml(")
    for heavy in ("<iframe", "/graph", "/map", "/facts", "/overview", "/api/wiki", "repoSwitchMap"):
        assert heavy not in first_draw, heavy
    assert 'rp.loaded.has(t)' in body_of("function showRepoTab(")
    load_map = body_of("function repoLoadMap(")
    assert all(x in load_map for x in ("<iframe", "/graph", "/map", "repoSwitchMap(name)"))
    assert "/facts" in re.search(r"const rpFacts = .*", APP)[0]


def test_every_feature_of_the_old_page_is_still_reachable():
    over = body_of("function repoOverviewHtml(")
    for it in ('id="rchange"', "Request a change", "New build", 'id="rstudy"', "Re-analyse", "Ask about it", 'id="ronboard"', "Waiting for you", "What it is", "Builds", 'id="rmap"', 'id="rbuildable"', 'id="rremove"'):
        assert it in over, it
    assert "showNode(name, n.id)" in body_of("function repoLoadMap(") and 'id="rnode"' in body_of("function repoLoadMap(")
    assert '[data-rstudy]' in body_of("function bindOnboard(")


def test_history_says_what_a_row_means_in_plain_words_most_telling_first():
    html = draw("repoHistoryHtml", "click", {}, FACTS)
    text = text_of(html)
    assert "changed 431 times, hard to read" in text
    assert "changed together 51 times, 63 % of their changes" in text
    assert "changed 639 times by many people, most often a@example.com" in text    # a high value: many people
    assert "changed 40 times, almost all by friend@example.org" in text                    # a low value: one person
    assert "last changed 59 days ago" in text
    assert text.index("src/click/core.py") < text.index("src/click/testing.py") < text.index("tests/test_arguments.py")   # by the risk
    assert text.index("requirements/dev.txt") < text.index("examples/colors/setup.py")   # 51 together before 5
    assert text.index("CHANGES.rst") < text.index("docs/bashcomplete.rst")               # the busy file before the quiet one
    assert text.index("docs/arguments.md") < text.index("CHANGES.md")                    # the oldest first
    assert 'href="#/chat?prompt=' in html and "src%2Fclick%2Fcore.py" in html            # a path opens a question about it
    for metric in ("fractal", "fisher", "hotspot_score", "cognitive", "degree", "revisions", "coupling", "bus factor"):
        assert metric not in html.lower(), metric


def test_nothing_is_cut_every_row_shows_from_the_start():
    """The owner, 9 Nov 2026: "Need All here and all should start as default." Every row, no "Show all"."""
    html = draw("repoHistoryHtml", "click", {}, FACTS)
    for h in HOTSPOTS:
        assert h["path"] in html, h["path"]
    assert "Show all" not in html and "data-rfall" not in html


def test_health_says_each_finding_and_its_reason_in_plain_words():
    html = draw("repoHealthHtml", "click", {}, FACTS)
    text = text_of(html)
    for it in ("click: health 3.8 of 10", "weakest src/click/core.py at 1.0 of 10", "37 commits by 3 people in the 90 days to", "138 files in none of them",
               "10 files nothing refers to", "1,070 lines where counted", "5 clear to remove", "click: 2 people hold over half of its files", "none with a single owner",
               "20 of 33 files reached by a test", "61 %", "Lines the tests really run: not measured", "3 widgets out of order (4.0 of 10)", "left over: 3"):
        assert it in text, it
    assert "possibly used" not in text                                                  # a tier with nothing in it
    assert "provenance" not in html.lower()
    for raw in ("(s)", "repowise coverage add", "unreachable_file", "bus-factor", "Bus factor"):
        assert raw not in text, raw
    for kept in ("inferred", "measured", "not known"):
        assert kept in text
    assert text.index("Parts of the code") < text.index("Dead code") < text.index("Who it depends on") < text.index("What the tests reach")


def test_a_repository_without_facts_says_so_and_offers_re_analyse():
    for fn, words in (("repoHistoryHtml", "has not got its history facts yet"), ("repoHealthHtml", "has not got its health findings yet")):
        for answer in (None, "Not Found", {"error": "no facts yet"}):
            html = draw(fn, "click", {"onboard": {"status": "done"}}, answer)
            assert words in html and "data-rstudy" in html and "Re-analyse" in html, (fn, answer)
    running = draw("repoHistoryHtml", "click", {"onboard": {"status": "running"}}, None)
    assert "See the onboarding" in running and "#/repo/click?tab=overview" in running and "data-rstudy" not in running
    one = draw("repoHistoryHtml", "click", {}, {"at": "2026-11-07T08:44:54+00:00", "commits": 1, "hotspots": [], "coupling": [], "ownership": [], "code_age": [], "errors": []})
    assert "holds one commit" in one and "data-rstudy" in one


def test_a_repository_whose_facts_failed_says_what_failed_where_it_failed():
    failed = {**FACTS, "hotspots": HOTSPOTS[:1], "coupling": [], "health": {}, "errors": ["repowise index: exit 1, out of memory", "codelore coupling: no result in 300 s", {"step": "clone", "error": "no history"}, "something <else>"]}
    hist, health = draw("repoHistoryHtml", "click", {}, failed), draw("repoHealthHtml", "click", {}, failed)
    assert "What failed" in hist and "codelore coupling: no result in 300 s" in hist and "clone: no history" in hist and "repowise" not in hist
    assert "What failed" in health and "repowise index: exit 1, out of memory" in health and "codelore" not in health
    assert "something &lt;else&gt;" in hist and "something &lt;else&gt;" in health      # it names no tool: both tabs say it
    assert "data-rstudy" in hist and "data-rstudy" in health
    assert "src/click/testing.py" in hist and "change together often" not in hist          # beside a failure an empty part is no finding


def test_the_wiki_tab_lists_the_pages_and_opens_them_in_the_wiki_viewer():
    g = {"nodes": [{"id": "guide/commands", "title": "How commands work", "summary": "Parsing.", "folder": "guide"}, {"id": "where", "title": "Where it breaks", "summary": "", "folder": ""}], "links": [{"source": "guide/commands", "target": "where"}]}
    html = draw("repoWikiHtml", "click", {}, g)
    assert "#/wiki?root=repos%2Fclick%2Fwiki" in html and "&amp;page=" not in html and "&page=guide%2Fcommands" in html
    assert "back=%23%2Frepo%2Fclick%3Ftab%3Dwiki" in html and re.match(r"^#/[\w/%?=&.:-]*$", "#/repo/click?tab=wiki")
    assert "How commands work" in html and "2 pages" in html and "1 link" in html
    empty = draw("repoWikiHtml", "click", {}, {"error": "unknown wiki"})
    assert "has no wiki pages yet" in empty and "data-rstudy" in empty


def test_the_overview_says_what_it_is_and_the_map_folds_its_files():
    """On a phone the Overview ran 129,555 pixels: the code map's whole digest, every file and function, sat under What it is."""
    app = webjs.app_js()
    assert "repoIntro(o.markdown" in app and "md(o.markdown)" not in app
    assert app.count('<details class="cm-more">') == 2


def test_health_opens_with_a_glance_and_every_part_even_one_without_a_score():
    """APP-58. The owner, 9 Nov 2026: "did I not request well designed health visualisations from you for code?" A
    repository whose parts carried no health score (a work site's Java code) got no chart at all. Health opens with
    figures at a glance, then every part with each measure it has; a part without a score keeps its row."""
    import copy
    html = draw("repoHealthHtml", "click", {}, FACTS)
    assert "At a glance" in html and "5.6" not in html and "3.8" in html and "61 %" in html and "Each part" in html
    assert "2 people hold it" in html and "pieces of code nothing uses" in html
    unscored = copy.deepcopy(FACTS)
    comps = unscored["health"]["sections"][0]["checks"][1]["data"]["components"]
    comps["click"].pop("health")
    comps["other"] = {"file_count": 4}
    html = draw("repoHealthHtml", "click", {}, unscored)
    assert html.count('class="hpart"') == 2 and "not scored" in html and "<b>other</b>" in html


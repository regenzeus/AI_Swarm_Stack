"""UX polish from the wide review of 2026-10-30 (APP-26; U1 to U4): the Stack page links its sections, Home's feed
opens short, the greeting never shows an e-mail address, scheduled jobs carry their names, and the Code tab never
shows an empty "No repository called ."."""
import datetime
import re
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "images/mission-control/web/static/app.js").read_text()


def test_the_greeting_uses_a_display_name_and_never_an_e_mail_address():
    import server as S
    assert S.display_name("Alex Example", "owner@example.com") == "Alex Example"
    assert S.display_name("", "owner@example.com") == ""                     # no name: just "Good evening"
    assert S.display_name("owner@example.com", "owner@example.com") == ""
    assert S.display_name("owner", "owner@example.com") == ""
    assert "${S.viewer_name ? \", \" + esc(String(S.viewer_name).split(\" \")[0]) : \"\"}" in APP


def test_the_stack_page_shows_one_part_at_a_time_and_jobs_carry_their_names():
    v = re.search(r"^function vSystem\(\).*?^\}$", APP, re.M | re.S)[0]
    for part in ("tools", "health", "guide", "settings"):
        assert f'data-sp="{part}"' in v
    assert '(S.crew || []).find((c) => c.unit === t.unit)?.name || t.unit' in v
    for moved in ("Notifications", "Scheduled jobs", "Connections", "How it fits together", "Health and costs", "Appearance"):
        assert f"<h2>{moved}</h2>" in v                       # nothing left the page


def test_the_agents_and_wiki_pages_lead_with_their_lists():
    """APP-47: the map stood 1,300 pixels above the missions and 900 above the wikis."""
    missions = re.search(r"^function vMissions\(\).*?^\}$", APP, re.M | re.S)[0]
    assert "ovmap" not in missions and '["map", "Map"]' in APP
    swarm = (ROOT / "images/mission-control/web/static/swarm.js").read_text()
    assert 'swTab === "map"' in swarm and '<div id="ovmap">' in swarm
    wiki = re.search(r"^function wikiIndex\(\).*?^\}$", APP, re.M | re.S)[0]
    assert wiki.index('class="card list wikis"') < wiki.index('class="card pad-l wmap"')


def test_the_code_tab_keeps_the_repositories_apart_from_the_work():
    """APP-47: they were 2,100 pixels down, after 15 questions to Claude, in the same cards as everything else."""
    v = re.search(r"^function vBuild\(\).*?^\}$", APP, re.M | re.S)[0]
    assert v.index("repoDir(repos)") < v.index("Waiting for you") < v.index("Earlier builds") < v.index("Questions to Claude Code")
    css = (ROOT / "images/mission-control/web/static/app.css").read_text()
    assert re.search(r"\.repodir \{ position: sticky", css) and re.search(r'\.codegrid\[data-pane="work"\] \.repodir', css)
    assert '<details class="section codehist" data-keep="questions">' in v     # the agents' questions stay folded


def test_home_opens_short_and_the_code_tab_never_shows_an_empty_name():
    assert re.search(r"let homeFilter = \"all\", homeShow = 12;", APP) and "homeShow = 12; const el" in APP
    assert 'if (!name) { location.hash = "#/build"; return; }' in APP


def test_the_crew_rows_carry_their_unit_so_the_app_can_name_a_job(monkeypatch):
    import crew                                          # the app's lookups ran on a field state.json did not have
    monkeypatch.setattr(crew, "_cache", {"t": 0, "data": []})
    monkeypatch.setattr(crew, "sh", lambda *a, **k: "")
    monkeypatch.setattr(crew, "unit_status", lambda a, units: {"installed": True, "state": "ok"})
    monkeypatch.setattr(crew, "journal_tail", lambda unit: [])
    monkeypatch.setattr(crew, "agent_file", lambda cid: {})
    monkeypatch.setattr(crew, "I", types.SimpleNamespace(last_scan=lambda: {}, EVERY=datetime.timedelta(days=7)))   # the self-review
    rows = crew.status()
    tests = next(r for r in rows if r["id"] == "tests")
    assert tests["unit"] == "crew-tests" and tests["name"] == "Test agent"


def test_the_theme_is_a_choice_and_is_applied_before_the_first_paint():
    """APP-49: the app followed each device's system theme, with no way to choose."""
    html = (ROOT / "images/mission-control/web/index.html").read_text()
    css = (ROOT / "images/mission-control/web/static/app.css").read_text()
    assert html.index("window.applyTheme") < html.index('rel="stylesheet"')
    assert "prefers-color-scheme" not in css and ':root[data-theme="light"]' in css
    assert 'data-theme-pick="${k}"' in APP and 'id="startpick"' in APP

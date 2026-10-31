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


def test_the_stack_page_links_each_section_and_jobs_carry_their_names():
    assert '<nav class="jump" id="stackjump"' in APP and re.search(r"function fillJump\(\) \{.*?scrollIntoView", APP, re.S)
    v = re.search(r"^function vSystem\(\).*?^\}$", APP, re.M | re.S)[0]
    assert "fillJump();" in v and '(S.crew || []).find((c) => c.unit === t.unit)?.name || t.unit' in v


def test_home_opens_short_and_the_code_tab_never_shows_an_empty_name():
    assert re.search(r"let homeFilter = \"mine\", homeShow = 12;", APP) and "homeShow = 12; const el" in APP
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

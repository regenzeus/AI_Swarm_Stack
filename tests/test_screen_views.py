"""PLT-26: the app counts which screens are opened (route name and tab, per day, nothing else), so a monthly report can
name the screens nobody opens; the nightly route check and the AI phone are not counted."""
import webjs
import asyncio
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_views_are_counted_per_day_by_name_and_tab_and_old_days_roll_off(tmp_path, monkeypatch):
    import server as S
    f = tmp_path / "views.json"
    S.count_view("task", path=f, day="2026-11-01")
    S.count_view("task", path=f, day="2026-11-02")
    S.count_view("swarm", "activity", path=f, day="2026-11-02")
    d = S.count_view("task", path=f, day="2026-11-02")
    assert d == {"2026-11-01": {"task": 1}, "2026-11-02": {"task": 2, "swarm:activity": 1}}
    assert S.screen_views(1, path=f, today=dt.date(2026, 11, 2)) == {"task": 2, "swarm:activity": 1}
    assert S.screen_views(30, path=f, today=dt.date(2026, 11, 2)) == {"task": 3, "swarm:activity": 1}
    monkeypatch.setattr(S, "VIEWS_DAYS", 2)
    S.count_view("home", path=f, day="2026-11-03")
    assert sorted(json.loads(f.read_text())) == ["2026-11-02", "2026-11-03"]


class Req:
    def __init__(self, body, phone=False):
        self.body_, self.phone = body, phone

    async def body(self):
        return self.body_


def test_the_endpoint_takes_a_screen_s_name_only_and_skips_the_ai_phone(tmp_path, monkeypatch):
    import server as S
    monkeypatch.setattr(S, "SCREEN_VIEWS", tmp_path / "views.json")
    monkeypatch.setattr(S, "from_ai_phone", lambda r: r.phone)
    call = lambda b, phone=False: asyncio.run(S.api_view(Req(json.dumps(b).encode(), phone)))
    assert call({"name": "task", "tab": "agents"}).status_code == 200
    assert call({"name": "../etc", "tab": ""}).status_code == 400                     # not a route name
    assert call({"name": "task", "tab": "x" * 30}).status_code == 400
    assert asyncio.run(S.api_view(Req(b"{" + b" " * 300 + b"}"))).status_code == 413  # refused, not cut
    call({"name": "home"}, phone=True)
    assert S.screen_views(1) == {"task:agents": 1}
    app = webjs.app_js()
    assert "if (navigator.webdriver) return;" in app and app.count("countView();") == 2   # the route check's browser is not counted

"""The app's own errors are kept, raised on the health board and checked for before they ship (APP-24, FND-52, FND-53:
a broken Start mission threw for days, its error went only to a container log that every deploy wiped)."""
import webjs
import json
import time
from pathlib import Path

import crew

ROOT = Path(__file__).resolve().parent.parent


def test_errors_the_app_hit_are_kept_and_become_one_alert_on_the_health_board(tmp_path):
    f = tmp_path / "client-errors.jsonl"
    now = time.time()
    rows = [{"ts": now - 60, "msg": "watch is not defined", "url": "#/new"}] * 3 + [{"ts": now - 30, "msg": "x is null", "url": "#/wiki"},
                                                                                    {"ts": now - 2 * 86400, "msg": "old", "url": "#/"}]
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    items = crew.app_errors(now, f)
    assert len(items) == 1 and items[0]["name"] == "AI Stack (the app)" and items[0]["kind"] == "engine"
    i = items[0]["issues"][0]
    assert i["kind"] == "app-error" and "app-error" in crew.ALERTS                       # an alert: it reaches the owner once
    assert i["text"] == "4 errors in the app in 24 h; most often “watch is not defined” (3×, on #/new) and 1 other kind"
    assert crew.app_errors(now, tmp_path / "none.jsonl") == []
    f.write_text(json.dumps({"ts": now - 3 * 86400, "msg": "old"}) + "\n")
    assert crew.app_errors(now, f) == []                                               # older than a day: nothing to raise
    assert "items += app_errors()" in (ROOT / "ops/crew.py").read_text()


def test_the_server_keeps_each_error_and_the_checks_lint_the_app_s_scripts(tmp_path, monkeypatch):
    import server as S
    monkeypatch.setattr(S, "CLIENT_ERRORS", tmp_path / "e.jsonl")
    for i in range(S.CLIENT_ERRORS_KEEP + 3):
        S.keep_client_error({"ts": i, "msg": f"m{i}"})
    rows = (tmp_path / "e.jsonl").read_text().splitlines()
    assert len(rows) == S.CLIENT_ERRORS_KEEP and json.loads(rows[-1])["msg"] == f"m{S.CLIENT_ERRORS_KEEP + 2}"
    check = (ROOT / "ops/check.sh").read_text()
    assert "python3 ops/app_lint.py" in check
    import app_lint
    assert [p.name for p in app_lint.scripts()] == ["guide.js", "shop.js", "swarm.js", "task.js", *webjs.APP_PARTS]   # the load order of index.html
    assert app_lint.RULES["no-undef"] == "error"
    for img in ("images/builder/Dockerfile", "images/ci-runner/Dockerfile"):
        assert "eslint@9.39.1 globals@16.5.0" in (ROOT / img).read_text(), img

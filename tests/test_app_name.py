"""APP-61: the app's name is the deployment's (the owner, 9 Nov 2026: "rename the Webside from Mission Control to AI
Stack ... have it be Configuration how the Webside is named"). Its pages, its installed name, its guide and the stack's
messages say it; nothing the owner sees says the old name."""
import re
from pathlib import Path

from starlette.testclient import TestClient

import deployment as DEPLOY
import server as S

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "images/mission-control/web"


def test_the_name_comes_from_the_deployment_and_defaults_to_ai_stack(monkeypatch):
    assert DEPLOY.app_name({}) == "AI Stack" and DEPLOY.app_name({"APP_NAME": "  Lab Bench "}) == "Lab Bench"
    for dep in ("home", "example-work"):
        assert DEPLOY.load(ROOT / f"deployments/{dep}/deployment.env", env={})["APP_NAME"] == "AI Stack"
    monkeypatch.setitem(S.DEPLOY, "APP_NAME", "Lab <Bench>")
    c = TestClient(S.app)
    page = c.get("/").text
    assert "<title>Lab &lt;Bench&gt;</title>" in page and "<span>Lab &lt;Bench&gt;</span>" in page
    m = c.get("/manifest.webmanifest").json()
    assert m["name"] == m["short_name"] == "Lab <Bench>"
    monkeypatch.setitem(S.DEPLOY, "APP_NAME", "")
    assert "<title>AI Stack</title>" in c.get("/").text


def test_nothing_the_owner_sees_says_the_old_name():
    for f in sorted((WEB / "static").glob("*.js")):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            code = line.split("//")[0] if not re.search(r"[`\"'][^`\"']*//", line) else line
            if n > 1 and "Mission Control" in code and not line.lstrip().startswith(("//", "/*", "*")):
                raise AssertionError(f"{f.name}:{n} shows the old name")
    for f in sorted((ROOT / "images/mission-control/guide").glob("*.md")):
        if f.name != "AGENTS.md":
            assert "Mission Control" not in f.read_text(), f.name
    assert "Mission Control" not in (WEB / "index.html").read_text() and "Mission Control" not in (WEB / "manifest.webmanifest").read_text()
    for rel in ("ops/builds.py", "ops/crew.py", "ops/memory_review.py", "ops/journal.py", "ops/house.py"):
        for line in (ROOT / rel).read_text().splitlines():
            if re.search(r"f?\"[^\"]*Mission Control[^\"]*\"", line) and not line.lstrip().startswith(("#", '"""')):
                raise AssertionError(f"{rel}: {line.strip()[:80]}")

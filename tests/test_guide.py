"""The in-app guide (images/mission-control/guide/*.md) must cover the stack: every assistant tool, app screen and
make target is explained somewhere, and every example and live block points at something that exists."""
import asyncio
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
MC = ROOT / "images" / "mission-control"
APP_JS = (MC / "web" / "static" / "app.js").read_text()
GUIDE_JS = (MC / "web" / "static" / "guide.js").read_text()


def chapters():
    out = []
    for f in sorted((MC / "guide").glob("[0-9][0-9]-*.md")):
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", f.read_text(), re.S)
        assert m, f"{f.name}: no front matter"
        out.append((f, yaml.safe_load(m[1]), m[2]))
    return out


ALL = chapters()
TEXT = "\n".join(body for _, _, body in ALL)
ROUTES = {k.split(":")[0].strip() for k in re.search(r"const fn = \{(.*?)\}\[route\.name\]", APP_JS, re.S)[1].split(",")}
ICONS = set(re.findall(r"^  (\w+): I\(", APP_JS, re.M))
PARTS = re.findall(r'"([^"]+)"', re.search(r"const GPARTS = \[(.*?)\]", GUIDE_JS)[1])
LIVE = set(re.findall(r"^  (\w+): ", re.search(r"const LIVEB = \{(.*?)\n\};", GUIDE_JS, re.S)[1], re.M))


def test_chapters_are_well_formed():
    ids = [f.stem.split("-", 1)[1] for f, _, _ in ALL]
    assert len(ids) == len(set(ids)) and all(re.match(r"^\d\d-[a-z0-9-]+\.md$", f.name) for f, _, _ in ALL)
    for f, meta, body in ALL:
        assert {"title", "kicker", "part", "icon", "minutes", "summary", "views"} <= set(meta), f.name
        assert meta["part"] in PARTS, f"{f.name}: part {meta['part']!r} not in {PARTS}"
        assert meta["icon"] in ICONS, f"{f.name}: no icon {meta['icon']!r}"
        assert set(meta["views"]) <= ROUTES, f"{f.name}: unknown views {set(meta['views']) - ROUTES}"


def test_every_app_screen_has_a_chapter():
    nav = set(re.findall(r'\["(\w+)", "#/', APP_JS)) - {"guide"}
    covered = {v for _, meta, _ in ALL for v in meta["views"]}
    assert nav <= covered, f"screens without a guide chapter (add them to a chapter's views): {nav - covered}"


def test_every_assistant_tool_is_explained():
    import server
    tools = {t.name for t in asyncio.run(server.mcp.list_tools())} | {t.name for t in asyncio.run(server.claude_mcp.list_tools())} \
        | {t.name for t in asyncio.run(server.house_mcp.list_tools())}
    missing = {t for t in tools if t not in TEXT}
    assert not missing, f"Mission Control tools not mentioned in the guide: {missing}"
    helped = set(re.findall(r"^  (\w+): \"", re.search(r"const TOOL_HELP = \{(.*?)\n\};", GUIDE_JS, re.S)[1], re.M))
    assert tools <= helped, f"tools without a plain-language line in guide.js TOOL_HELP: {tools - helped}"


def test_every_make_target_is_explained():
    targets = re.findall(r"^([a-z][a-z-]*):.*##", (ROOT / "Makefile").read_text(), re.M)
    missing = [t for t in targets if not re.search(rf"make {re.escape(t)}\b", TEXT)]
    assert not missing, f"make targets missing from the guide (Operations chapter): {missing}"


@pytest.mark.parametrize("f,meta,body", ALL, ids=[f.stem for f, _, _ in ALL])
def test_examples_and_live_blocks_point_at_real_things(f, meta, body):
    for name in re.findall(r"^```live\n\s*([\w-]+)\s*\n```$", body, re.M):
        assert name in LIVE, f"{f.name}: unknown live block {name!r}"
    for src in re.findall(r"^```try\n(.*?)\n```$", body, re.M | re.S):
        t = dict(re.findall(r"^(\w+):\s*(.*)$", src, re.M))
        assert t.get("label") and t.get("note"), f"{f.name}: example without label or note"
        kinds = [k for k in ("chat", "open", "app") if k in t]
        assert len(kinds) == 1, f"{f.name}: example {t['label']!r} needs exactly one of chat/open/app"
        if "open" in t:
            route = t["open"].strip('"')
            assert route.startswith("#/") and (route[2:].split("/")[0].split("?")[0] or "home") in ROUTES, f"{f.name}: bad route {route}"
        if "app" in t:
            assert t["app"].strip('"') in {"443", "8443", "8445", "8446", "8448"}, f"{f.name}: unknown app port"
    assert body.count("```") % 2 == 0, f"{f.name}: unclosed code fence"


def test_guide_api(tmp_path, monkeypatch):
    import server as S
    from starlette.testclient import TestClient
    c = TestClient(S.app)
    H = {"Tailscale-User-Login": "owner@test"}
    lst = c.get("/api/guide", headers=H).json()
    assert [x["id"] for x in lst][:2] == ["welcome", "first-ten-minutes"] and "body" not in lst[0]
    assert sum(x["tries"] for x in lst) >= 30
    one = c.get("/api/guide/chat", headers=H).json()
    assert one["title"] == "Chat with Hermes" and "```live\ntools\n```" in one["body"]
    assert c.get("/api/guide/nope", headers=H).status_code == 404
    live = c.get("/api/guide/live", headers=H).json()
    assert {t["name"] for t in live["tools"]} >= {"mission_create", "build_assign"} and live["models"]


def test_activity_feed_links_build_events_to_their_build():
    """Build events open #/build/<n>, ideas open Agents → Ideas (the feed's only link rules besides missions)."""
    feed = APP_JS.split("function activityList", 1)[1].split("\nfunction ", 1)[0]
    assert "`#/build/${bn[1]}`" in feed and '"#/swarm?tab=improve"' in feed


def test_live_map_boxes_point_at_real_sections():
    """Each box of the Stack page's live map links to a section of a chapter; that heading must exist."""
    rows = re.findall(r'^\s*\["([^"]+)", "[^"]*", (?:null|"[^"]*"), "([\w-]+)", "([^"]+)"', GUIDE_JS, re.M)
    assert len(rows) >= 18
    for name, chapter, section in rows:
        f = next((MC / "guide").glob(f"[0-9][0-9]-{chapter}.md"), None)
        assert f, f"map box {name}: no chapter {chapter}"
        assert re.search(rf"^## {re.escape(section)}$", f.read_text(), re.M), f"map box {name}: no section '{section}' in {f.name}"


def test_every_screen_s_how_this_page_works_opens_the_chapter_about_it():
    """The owner's review of 2 Nov: the Agents tab opened the Missions chapter and a task page the Stack page. Every
    screen a person reaches is in some chapter's views; one with none opens the guide's contents."""
    js = (Path(__file__).resolve().parent.parent / "images/mission-control/web/static/app.js").read_text()
    screens = {k.split(":")[0].strip() for k in re.search(r"const fn = \{(.*?)\}\[route\.name\]", js, re.S)[1].split(",")}
    covered = {v for _, meta, _ in ALL for v in meta["views"]}
    assert screens - covered <= {"guide", "share"}, f"screens without a chapter: {screens - covered - {'guide', 'share'}}"
    first = {}
    for _, meta, _ in ALL:
        for v in meta["views"]:
            first.setdefault(v, meta["title"])
    assert first["missions"].startswith("The swarm") and first["task"].startswith("Tasks") and first["mission"].startswith("Missions")
    gjs = (Path(__file__).resolve().parent.parent / "images/mission-control/web/static/guide.js").read_text()
    assert ': "#/guide";' in gjs and '"#/system";' not in re.search(r"function helpHref\(\).*?\n\}", gjs, re.S)[0]

"""images/mission-control/server.py: tailnet auth, requests to the runner, wiki link resolution, chat on Hermes sessions."""
import asyncio
import json
import subprocess
from pathlib import Path

import pytest
from starlette.testclient import TestClient

H = {"Tailscale-User-Login": "owner@test"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    import server as S
    m = tmp_path / "missions"
    for d in ("inbox", "public/results", "runs", "app/chats/files", "builds"):
        (m / d).mkdir(parents=True)
    vault = tmp_path / "vault"
    (vault / "wiki" / "entities").mkdir(parents=True)
    (vault / "wiki" / "entities" / "acme-mining.md").write_text("---\ntitle: Acme Mining\naliases: [ACME]\n---\nProducer. See [[entities/kazatomprom]] "
                                                           "and [[Missing Page]] and [[topics/u/reports/r|report]].")
    (vault / "wiki" / "entities" / "kazatomprom.md").write_text("---\ntitle: Kazatomprom\n---\nPartner of [[ACME]].")
    (vault / "topics" / "u" / "reports").mkdir(parents=True)
    (vault / "topics" / "u" / "reports" / "r.md").write_text("# report")
    state = {"missions": [{"slug": "u", "title": "Copper", "type": "briefing", "wiki": "topics/u/wiki", "runs": []}],
             "activity": [], "calls": [], "system": {}, "running": None, "queue": []}
    (m / "public" / "state.json").write_text(json.dumps(state))
    for k, v in {"STATE": m / "public/state.json", "INBOX": m / "inbox", "RESULTS": m / "public/results", "RUNS": m / "runs",
                 "DATA": m / "app", "CHATS": m / "app/chats", "FILES": m / "app/chats/files", "BUILDS": m / "builds",
                 "VAULT": vault}.items():
        monkeypatch.setattr(S, k, v)
    S._wiki_cache.clear()
    orig = S.submit
    monkeypatch.setattr(S, "submit", lambda req, wait=8.0: orig(req, wait=0.3))
    return S


def test_api_needs_the_tailscale_identity(app):
    c = TestClient(app.app)
    assert c.get("/api/state").status_code == 403
    assert c.get("/api/state", headers=H).json()["viewer"] == "owner@test"
    assert c.get("/healthz").status_code == 200


def test_requests_go_to_the_inbox_and_unknown_actions_are_refused(app):
    c = TestClient(app.app)
    r = c.post("/api/request", headers=H, json={"action": "run", "slug": "u"}).json()
    assert r["pending"] is True
    req = json.loads((app.INBOX / f"{r['id']}.json").read_text())
    assert req == {"action": "run", "slug": "u", "source": "app"}
    assert c.post("/api/request", headers=H, json={"action": "rm -rf"}).json()["ok"] is False


def test_vault_files_stay_inside_the_vault(app):
    c = TestClient(app.app)
    assert c.get("/api/file", headers=H, params={"path": "topics/u/reports/r.md"}).text == "# report"
    assert c.get("/api/file", headers=H, params={"path": "../etc/passwd"}).status_code == 404
    assert c.get("/api/file", headers=H, params={"path": "topics/../../x.md"}).status_code == 404


def test_wiki_links_backlinks_and_aliases(app):
    c = TestClient(app.app)
    g = c.get("/api/wiki/graph", headers=H, params={"root": "wiki"}).json()
    assert {(e["source"], e["target"]) for e in g["links"]} == {("entities/acme-mining", "entities/kazatomprom"),
                                                                ("entities/kazatomprom", "entities/acme-mining")}
    p = c.get("/api/wiki/page", headers=H, params={"root": "wiki", "id": "entities/acme-mining"}).json()
    assert p["links"]["entities/kazatomprom"] == {"kind": "page", "ref": "entities/kazatomprom"}
    assert p["links"]["Missing Page"] == {"kind": None, "ref": None}
    assert p["links"]["topics/u/reports/r"] == {"kind": "file", "ref": "topics/u/reports/r.md"}
    assert p["backlinks"] == [{"id": "entities/kazatomprom", "title": "Kazatomprom"}]
    assert c.get("/api/wiki/graph", headers=H, params={"root": "../.."}).status_code == 404


@pytest.mark.parametrize("root", ["wiki", "topics/u/wiki"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_wiki_copy_source_preserves_original_markdown(app, root, newline):
    markdown = ('---\ntitle: Test page\ntype: concept\nsources: [raw/source]\n---\n'
                '# Test page\n\n**Bold** & <tags> [[other|Alias]]\n\n'
                '```js\nconst x = "<copy>";\n```\n\n').replace("\n", newline)
    folder = app.VAULT / root / "concepts"
    folder.mkdir(parents=True)
    (folder / "test.md").write_bytes(markdown.encode("utf-8"))
    c = TestClient(app.app)
    for _ in range(2):                     # also exercise the cached page
        response = c.get("/api/wiki/page", headers=H, params={"root": root, "id": "concepts/test"})
        assert response.status_code == 200
        page = response.json()
        assert page["markdown"] == markdown
        assert page["body"] == markdown.replace("\r\n", "\n").split("---\n", 2)[2]
        assert page["title"] == "Test page"
        assert page["meta"]["sources"] == ["raw/source"]
        assert page["path"] == f"{root}/concepts/test.md"


@pytest.mark.parametrize("markdown", ["# Plain\n\nNo frontmatter.\n", ""])
def test_wiki_copy_source_preserves_plain_and_empty_pages(app, markdown):
    (app.VAULT / "wiki/plain.md").write_text(markdown)
    page = TestClient(app.app).get("/api/wiki/page", headers=H, params={"root": "wiki", "id": "plain"}).json()
    assert page["markdown"] == page["body"] == markdown


@pytest.mark.parametrize("root, pid", [("wiki", "missing"), ("raw", "private")])
def test_wiki_missing_or_unapproved_pages_do_not_expose_markdown(app, root, pid):
    response = TestClient(app.app).get("/api/wiki/page", headers=H, params={"root": root, "id": pid})
    assert response.status_code == 404
    assert "markdown" not in response.json()


def test_wiki_copy_button_interactions():
    result = subprocess.run(["node", "--test", str(Path(__file__).with_name("wiki.test.cjs"))],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_chat_sends_only_the_new_turn_with_a_hermes_session(app):
    (app.FILES / "abc0000000000001.txt").write_text("PDF TEXT")
    c = {"id": "chat000001", "messages": [
        {"role": "user", "content": "first question"}, {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "about this file", "attachments": [{"id": "abc0000000000001", "name": "r.pdf", "kind": "doc"}]}]}
    payload, headers = app.build_request(c, "gpt-sub-fast", "low")
    assert headers == {"X-Hermes-Session-Id": "mc-chat000001-0"}
    assert [m["role"] for m in payload["messages"]] == ["system", "user"]          # one new turn, no history re-sent
    assert "PDF TEXT" in payload["messages"][1]["content"]
    assert "first answer" in payload["messages"][0]["content"]                       # older chat: seeded once
    assert payload["model_options"] == {"reasoning_effort": "low"} and payload["provider"] == "custom"
    c["messages"] += [{"role": "assistant", "content": "ok"}, {"role": "user", "content": "next"}]
    payload2, headers2 = app.build_request(c, "gpt-sub", "high")
    assert headers2 == headers and "first answer" not in payload2["messages"][0]["content"]
    assert payload2["messages"][1]["content"] == "next"


def test_edit_starts_a_new_session(app, monkeypatch):
    sent = []
    async def fake_run(c, payload, headers=None):
        sent.append((payload, headers))
    monkeypatch.setattr(app, "run_chat", fake_run)
    cl = TestClient(app.app)
    r = cl.post("/api/chat", headers=H, json={"message": "hello", "model": "gpt-sub", "effort": "medium"}).json()
    chat = json.loads((app.CHATS / f"{r['chat']}.json").read_text())
    chat["messages"].append({"role": "assistant", "content": "hi"}); chat["pending"] = False
    (app.CHATS / f"{r['chat']}.json").write_text(json.dumps(chat))
    cl.post("/api/chat", headers=H, json={"chat": r["chat"], "message": "hello again", "truncate": 0})
    assert [h["X-Hermes-Session-Id"] for _, h in sent] == [f"mc-{r['chat']}-0", f"mc-{r['chat']}-1"]


def test_tool_progress_labels(app):
    assert app.tool_label({"tool": "mcp__vault__qmd_query", "status": "running", "preview": "copper"}) == \
        {"name": "qmd_query", "status": "running", "detail": "copper"}


def test_interrupted_chats_are_closed_on_start(app):
    (app.CHATS / "chat000002.json").write_text(json.dumps({"id": "chat000002", "pending": True, "messages": [{"role": "user", "content": "q"}]}))
    app.close_interrupted_chats()
    c = json.loads((app.CHATS / "chat000002.json").read_text())
    assert c["pending"] is False and "interrupted" in c["messages"][-1]["content"]


def test_mcp_tools_are_registered(app):
    names = {t.name for t in asyncio.run(app.mcp.list_tools())}
    assert {"missions_overview", "mission_create", "mission_update", "mission_set_triggers", "build_assign", "send_email"} <= names


def test_phone_share_is_kept_and_opened_in_the_app(app, monkeypatch, tmp_path):
    monkeypatch.setattr(app, "SHARES", tmp_path / "shares")
    monkeypatch.setattr(app, "UPLOADS", tmp_path / "uploads")
    c = TestClient(app.app)
    assert c.post("/share", data={"text": "x"}, follow_redirects=False).status_code == 403     # tailnet only
    r = c.post("/share", headers=H, follow_redirects=False,
               data={"title": "RAM deal", "text": "Look at this https://example.com/ram?id=1."},
               files=[("files", ("notes.txt", b"DDR4 3200 CL16", "text/plain")), ("files", ("evil.exe", b"MZ", "application/octet-stream"))])
    assert r.status_code == 303 and r.headers["location"].startswith("/#/share/")
    sid = r.headers["location"].rsplit("/", 1)[1]
    s = c.get(f"/api/share/{sid}", headers=H).json()
    assert s["url"] == "https://example.com/ram?id=1"                  # the link is pulled out of the text
    assert [f["name"] for f in s["files"]] == ["notes.txt"] and "evil.exe" in s["errors"][0]
    assert c.get("/api/share/../../etc", headers=H).status_code == 404
    out = c.post(f"/api/share/{sid}/save", headers=H).json()
    assert out["of"] == 2                                              # the link's page and the text file
    reqs = [json.loads(p.read_text()) for p in app.INBOX.glob("*.json")]
    assert {r.get("url") for r in reqs} >= {"https://example.com/ram?id=1"} and any(r.get("upload", "").endswith("notes.txt") for r in reqs)
    m = json.loads((app.WEB / "manifest.webmanifest").read_text())
    assert m["share_target"]["action"] == "/share" and m["share_target"]["method"] == "POST"


def test_the_ai_phone_cannot_approve_its_own_actions(app, monkeypatch, tmp_path):
    monkeypatch.setattr(app, "PHONE", tmp_path)
    (tmp_path / "pending").mkdir()
    (tmp_path / "pending" / "abcdefabcdefabcd.json").write_text('{"id": "abcdefabcdefabcd"}')
    c = TestClient(app.app)
    s22 = {**H, "X-Forwarded-For": app.AI_PHONE_IP}
    assert c.post("/api/phone/decide", headers=s22, json={"id": "abcdefabcdefabcd", "allow": True}).status_code == 403
    assert c.post("/api/phone/control", headers=s22, json={"do": "trust", "minutes": 10}).status_code == 403
    assert c.post("/api/phone/control", headers=s22, json={"do": "stop"}).json()["ok"]            # switching off is fine
    main = {**H, "X-Forwarded-For": "100.64.0.11"}
    monkeypatch.setattr(app, "DECIDE_WAIT", 0.5)
    r = c.post("/api/phone/decide", headers=main, json={"id": "abcdefabcdefabcd", "allow": True}).json()
    assert r["ok"] and r["taken"] is False                 # nobody took the answer: the card says so instead of nothing


def test_hermes_can_review_and_request_changes_but_never_approve(app):
    names = {t.name for t in asyncio.run(app.mcp.list_tools())}
    assert {"build_details", "build_request_changes", "build_recheck"} <= names
    assert not any("approve" in n for n in names)                       # approving stays the owner's tap
    out = asyncio.run(app.build_details(99))
    assert "No build #99" in out


def test_forgejo_token_goes_to_the_runner_only(app, monkeypatch):
    c = TestClient(app.app)
    assert c.post("/api/forgejo/connect", headers=H, json={"token": "nope"}).status_code == 400
    s22 = {**H, "X-Forwarded-For": app.AI_PHONE_IP}
    assert c.post("/api/forgejo/connect", headers=s22, json={"token": "a" * 40}).status_code == 403
    r = c.post("/api/forgejo/connect", headers=H, json={"token": "a" * 40}).json()
    reqs = [json.loads(p.read_text()) for p in app.INBOX.glob("*.json")]
    assert reqs == [{"action": "forgejo_connect", "token": "a" * 40}] and r.get("pending")
    tools = {t.name for t in asyncio.run(app.mcp.list_tools())}
    assert not any("forgejo" in t for t in tools)                          # no AI can relay a token



def test_the_live_stream_carries_the_ai_phone(app):
    import inspect
    assert "'phone': ph" in inspect.getsource(app.api_stream)          # Home's AI phone card needs it live


def test_connection_grants_and_the_ai_phone(app, monkeypatch, tmp_path):
    monkeypatch.setattr(app, "CONN", tmp_path)
    (tmp_path / "status.json").write_text('{"gmail": {"ok": true}}')
    c = TestClient(app.app)
    assert c.post("/api/connections/grant", headers=H, json={"conn": "gmail", "scope": "delete", "minutes": 60}).status_code == 400
    s22 = {**H, "X-Forwarded-For": app.AI_PHONE_IP}
    assert c.post("/api/connections/grant", headers=s22, json={"conn": "gmail", "scope": "read", "minutes": 60}).status_code == 403
    assert c.post("/api/connections/grant", headers=H, json={"conn": "gmail", "scope": "read", "minutes": 60}).json()["ok"]
    assert "read" in c.get("/api/connections", headers=H).json()["connections"][0]["grants"]
    assert app.conn_summary()["gmail"]["grants"]["read"] > 0
    c.post("/api/connections/grant", headers=H, json={"conn": "gmail", "scope": "read", "minutes": 0})
    assert app.conn_summary()["gmail"]["grants"] == {}



def test_api_answers_are_never_cached(app):
    c = TestClient(app.app)
    assert c.get("/api/state", headers=H).headers.get("cache-control") == "no-cache"



def test_purchases_are_decided_only_by_the_owner(app):
    c = TestClient(app.app)
    s22 = {**H, "X-Forwarded-For": app.AI_PHONE_IP}
    assert c.post("/api/shop/decide", headers=s22, json={"id": "p-0000abcd", "decision": "approve"}).status_code == 403
    assert c.post("/api/shop/limits", headers=s22, json={"per_purchase_eur": 5000}).status_code == 403
    assert c.post("/api/request", headers=H, json={"action": "shop_decide", "id": "p-0000abcd", "decision": "approve"}).status_code == 403
    assert c.post("/api/shop/decide", headers=H, json={"id": "../x", "decision": "approve"}).status_code == 400
    r = c.post("/api/shop/decide", headers={**H, "X-Forwarded-For": "100.64.0.9"}, json={"id": "p-0000abcd", "decision": "approve"}).json()
    req = json.loads((app.INBOX / f"{r['id']}.json").read_text())
    assert req["source"] == "owner" and req["by"] == "owner@test" and req["action"] == "shop_decide"


def test_phoenix_picks_the_litellm_span_of_a_model_call():
    import server as S
    spans = [
        {"name": "auth", "start_time": "2026-10-28T19:00:00+00:00", "end_time": "2026-10-28T19:00:01+00:00", "context": {"trace_id": "x"}},
        {"name": "litellm_request", "start_time": "2026-10-28T19:00:00+00:00", "end_time": "2026-10-28T19:00:04+00:00",
         "context": {"trace_id": "a"}, "attributes": {"litellm.model_group": "gpt-sub"}},
        {"name": "litellm_request", "start_time": "2026-10-28T19:00:02+00:00", "end_time": "2026-10-28T19:00:05+00:00",
         "context": {"trace_id": "b"}, "attributes": {"litellm.model_group": "gpt-sub-fast"}},
    ]
    from datetime import datetime
    end = datetime.fromisoformat("2026-10-28T19:00:04+00:00").timestamp()
    assert S.phoenix_pick(spans, end, 4000, "gpt-sub")["context"]["trace_id"] == "a"          # Hermes: seen at the end
    start = datetime.fromisoformat("2026-10-28T19:00:02+00:00").timestamp()
    assert S.phoenix_pick(spans, start, 3000, "gpt-sub-fast")["context"]["trace_id"] == "b"   # spend logs: the start
    assert S.phoenix_pick(spans, end + 600) is None                                           # nothing near: none


def test_house_owner_taps_ai_phone_and_hermes(app):
    c = TestClient(app.app)
    s22 = {**H, "X-Forwarded-For": app.AI_PHONE_IP}
    assert c.post("/api/request", headers=H, json={"action": "house_switch", "entity": "fridge", "op": "off", "by": "owner"}).status_code == 403
    assert c.post("/api/house", headers=s22, json={"do": "settings", "voice": False}).status_code == 403
    c.post("/api/house", headers=H, json={"do": "switch", "entity": "Fridge", "op": "off", "by": "ai"})
    c.post("/api/house", headers=s22, json={"do": "switch", "entity": "Fridge", "op": "off"})
    asyncio.run(app.house_switch("Fridge", "off"))
    reqs = sorted((json.loads(p.read_text()) for p in app.INBOX.glob("*.json")), key=lambda r: r["by"])
    assert [r["by"] for r in reqs] == ["ai", "ai-phone", "owner"]          # the app sets who it is; a body can't claim it
    assert {t.name for t in asyncio.run(app.house_mcp.list_tools())} == {"house_status", "house_switch", "house_alexa", "house_say"}


def test_house_connect_sends_owner_to_home_assistant_and_back(app):
    c = TestClient(app.app, base_url="https://pc.example.ts.net:8447")
    r = c.get("/api/house/connect", headers=H, follow_redirects=False)
    loc = r.headers["location"]
    assert r.status_code in (302, 307) and loc.startswith(app.HA_BROWSER + "/auth/authorize?")
    q = dict(x.split("=", 1) for x in loc.split("?", 1)[1].split("&"))
    assert q["client_id"] == "https%3A%2F%2Fpc.example.ts.net%3A8447%2F" and q["redirect_uri"].endswith("%2Fapi%2Fhouse%2Fcallback")
    assert c.get("/api/house/callback?state=forged&code=abc", headers=H, follow_redirects=False).headers["location"].startswith("/#/house?err=")
    c.get(f"/api/house/callback?state={q['state']}&code=" + "a" * 32, headers=H, follow_redirects=False)
    reqs = [json.loads(p.read_text()) for p in app.INBOX.glob("*.json")]
    assert reqs == [{"action": "house_connect", "code": "a" * 32, "client_id": "https://pc.example.ts.net:8447/"}]


def test_a_task_run_s_map_is_served_as_the_runner_wrote_it_and_the_newest_run_without_a_number(app, monkeypatch):
    """TSK-24: /api/task/map serves public/maps/<task>.<occ>.json; a run without a map says so; no path tricks."""
    d = app.STATE.parent / "maps"
    d.mkdir()
    monkeypatch.setattr(app, "MAPS", d)
    (d / "7.1.json").write_text(json.dumps({"task": 7, "occ": 1}))
    (d / "7.10.json").write_text(json.dumps({"task": 7, "occ": 10}))
    c = TestClient(app.app)
    assert c.get("/api/task/map", headers=H, params={"t": 7, "o": 1}).json()["occ"] == 1
    assert c.get("/api/task/map", headers=H, params={"t": 7}).json()["occ"] == 10          # the newest run (10 after 9, not after 1)
    assert c.get("/api/task/map", headers=H, params={"t": 8}).status_code == 404
    assert c.get("/api/task/map", headers=H, params={"t": "../x"}).status_code == 400
    assert c.get("/api/task/map", params={"t": 7}).status_code == 403


def test_the_telemetry_history_is_served_and_says_when_there_is_none_yet(app, monkeypatch, tmp_path):
    """TSK-25: /api/telemetry serves public/telemetry.json as the runner wrote it."""
    f = tmp_path / "telemetry.json"
    monkeypatch.setattr(app, "TELEMETRY", f)
    c = TestClient(app.app)
    assert c.get("/api/telemetry", headers=H).json()["rows"] == [] and "within the hour" in c.get("/api/telemetry", headers=H).json()["error"]
    f.write_text(json.dumps({"rows": [{"day": "2026-11-01", "agent": "scout", "runs": 3}], "prices": {}}))
    assert c.get("/api/telemetry", headers=H).json()["rows"][0]["runs"] == 3


def test_the_owner_keeps_the_phone_screen_on_for_an_hour_at_most(app, monkeypatch, tmp_path):
    """PHN-17"""
    monkeypatch.setattr(app, "PHONE", tmp_path)
    c = TestClient(app.app)
    assert c.post("/api/phone/control", headers=H, json={"do": "screen", "minutes": 500}).json() == {"ok": True}
    assert json.loads(next((tmp_path / "control").glob("*.json")).read_text()) == {"do": "screen", "minutes": 60}


def test_every_action_a_button_sends_is_one_the_app_lets_through(app):
    """Delete wiki answered "unknown action" (1 Nov): the runner knew wiki_delete, the app's list did not."""
    import re
    js = "".join((Path(app.__file__).parent / "web/static" / f).read_text() for f in ("app.js", "swarm.js", "guide.js", "shop.js"))
    assert sorted(set(re.findall(r'action: "([a-z0-9_]+)"', js)) - app.ACTIONS) == []


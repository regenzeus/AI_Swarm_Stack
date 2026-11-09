"""APP-39 (docs/CHAT-MADE.md): what a chat made is reachable from the chat (a card under the answer, the Made here sheet,
icons in the chat list), leads back to it ("From a chat"), and a one-off item says in the chat when it ends."""
import asyncio
import json
import time

import pytest
from starlette.testclient import TestClient

H = {"Tailscale-User-Login": "owner@test"}
CID = "abc123abc123"


@pytest.fixture
def app(tmp_path, monkeypatch):
    import runrecord as RT
    import server as S
    monkeypatch.setattr(RT, "DB", tmp_path / "runtime.db")
    monkeypatch.setattr(RT, "_db", None)
    m = tmp_path / "missions"
    for d in ("inbox", "public/results", "app/chats/files"):
        (m / d).mkdir(parents=True)
    for k, v in {"STATE": m / "public/state.json", "INBOX": m / "inbox", "RESULTS": m / "public/results", "DATA": m / "app",
                 "CHATS": m / "app/chats", "FILES": m / "app/chats/files"}.items():
        monkeypatch.setattr(S, k, v)
    S.MADE_IDX.update(t=0, v={})
    S.RT = RT
    return S


def set_state(S, missions=(), builds=(), running=None, queue=()):
    S.STATE.write_text(json.dumps({"missions": list(missions), "builds": list(builds), "claude_tasks": [], "running": running,
                                   "queue": list(queue), "activity": [], "calls": [], "system": {}}))


def mission(slug, title, runs=(), schedule="manual"):
    return {"slug": slug, "title": title, "type": "task", "status": "active", "schedule": schedule, "triggers": [], "runs": list(runs)}


def turn(S, t0, tool, args, result, n=0):
    """One chat turn in the run record: Hermes calls a tool and gets its answer; and the chat file around it."""
    run = f"hermes:main:c-{CID}-0:{n}"
    S.RT.ingest([{"run": run, "ref": f"chat:{CID}", "agent": "main", "kind": "run", "ts": t0},
                 {"run": run, "kind": "call", "ts": t0 + 1, "title": f"mcp__vault__missions_{tool}", "detail": json.dumps(args),
                  "data": {"call_id": f"c{n}"}},
                 {"run": run, "kind": "result", "ts": t0 + 2, "title": f"mcp__vault__missions_{tool}",
                  "detail": json.dumps({"result": result}), "data": {"call_id": f"c{n}", "status": "success"}}])


def chat(S, *turns):
    msgs = []
    for t0 in turns:
        msgs += [{"role": "user", "content": "please", "ts": t0}, {"role": "assistant", "content": "done", "ts": t0 + 5}]
    c = {"id": CID, "title": "Lithium chat", "created": turns[0], "updated": turns[-1] + 5, "messages": msgs}
    S.CHATS.joinpath(f"{CID}.json").write_text(json.dumps(c))
    return c


def test_the_answer_that_made_a_mission_shows_it_with_its_live_state(app):
    S, t0 = app, time.time() - 600
    set_state(S, [mission("lith", "Lithium market", [{"status": "ok", "summary": "Prices fell 4 %."}])])
    turn(S, t0, "mission_create", {"kind": "task", "title": "Lithium market"}, "Created: [lith] long-term task created\nmade: mission:lith")
    chat(S, t0)
    got = TestClient(S.app).get(f"/api/chats/{CID}", headers=H).json()
    x = got["made"][0]
    assert (x["kind"], x["id"], x["verb"], x["name"], x["href"], x["state"], x["line"]) == \
        ("mission", "lith", "made", "Lithium market", "#/mission/lith", "done", "Prices fell 4 %.")
    kept = json.loads(S.CHATS.joinpath(f"{CID}.json").read_text())
    assert kept["made"][0]["id"] == "lith" and kept["updated"] == t0 + 5          # kept in the chat, not moved up the list
    assert S.chat_summary(kept)["made"] == {"mission": 1}                         # the chat list's icon


def test_older_answers_are_read_by_their_wording_and_a_pending_one_by_its_title(app):
    """The owner's case of 2 Nov: mission_create answered "Creating '…' now" (the runner took over 6 s): no id at all."""
    S, t0 = app, time.time() - 600
    set_state(S, [mission("bullet", "Bullet Heaven Design Primer", [{"status": "ok"}]), mission("ram", "RAM upgrade")],
              running={"slug": "ram"})
    turn(S, t0, "mission_create", {"title": "Bullet Heaven Design Primer"}, "Creating 'Bullet Heaven Design Primer' now. It appears …", 0)
    turn(S, t0 + 10, "mission_create", {"title": "RAM"}, "Already exists: [ram] already exists as 'RAM upgrade'", 1)
    turn(S, t0 + 20, "mission_control", {"slug": "ram", "action": "pause"}, "OK", 2)
    turn(S, t0 + 30, "build_assign", {"repo": "ai-stack", "title": "x"}, "Error: no repo 'ai-stack'", 3)
    chat(S, t0, t0 + 10, t0 + 20, t0 + 30)
    made = TestClient(S.app).get(f"/api/chats/{CID}", headers=H).json()["made"]
    assert [(x["id"], x["verb"], x["state"]) for x in made] == [("bullet", "made", "done"), ("ram", "exists", "running"),
                                                               ("ram", "changed", "changed"), (None, "failed", "failed")]
    assert made[2]["what"] == "paused" and made[3]["line"].startswith("Error")


def test_a_pending_request_resolves_through_the_runner_s_answer(app):
    S, t0 = app, time.time() - 600
    set_state(S, builds=[{"id": 9, "title": "Fix it", "status": "review", "summary": "Ready"}])
    turn(S, t0, "build_assign", {"repo": "TestRepo", "title": "Something else"}, "Queuing the build now …\nmade: build:request-0123456789abcdef")
    chat(S, t0)
    assert TestClient(S.app).get(f"/api/chats/{CID}", headers=H).json()["made"][0]["state"] == "creating"
    S.RESULTS.joinpath("0123456789abcdef.json").write_text(json.dumps({"ok": True, "id": 9}))
    x = TestClient(S.app).get(f"/api/chats/{CID}", headers=H).json()["made"][0]
    assert (x["id"], x["name"], x["href"], x["state"]) == ("9", "Build #9: Fix it", "#/build/9", "waits")


def test_the_item_leads_back_and_a_one_off_says_in_the_chat_when_it_ends(app):
    S, t0 = app, time.time() - 600
    set_state(S, [mission("lith", "Lithium market"), mission("daily", "Daily copper", schedule="daily 06:30"),
                  mission("old", "Old one", [{"status": "ok"}])], queue=[{"slug": "lith"}, {"slug": "daily"}])
    turn(S, t0, "mission_create", {"title": "Lithium market"}, "Created: [lith] x\nmade: mission:lith", 0)
    turn(S, t0 + 10, "mission_create", {"title": "Daily copper"}, "Created: [daily] x\nmade: mission:daily", 1)
    turn(S, t0 + 20, "mission_create", {"title": "Old one"}, "Created: [old] x\nmade: mission:old", 2)
    chat(S, t0, t0 + 10, t0 + 20)
    idx = S.made_pass()
    assert idx["mission:lith"]["chat"] == CID and idx["mission:lith"]["title"] == "Lithium chat"
    assert len(json.loads(S.CHATS.joinpath(f"{CID}.json").read_text())["messages"]) == 6     # nothing ended yet
    set_state(S, [mission("lith", "Lithium market", [{"status": "ok", "summary": "Albemarle leads."}]),
                  mission("daily", "Daily copper", [{"status": "ok"}], schedule="daily 06:30"), mission("old", "Old one", [{"status": "ok"}])])
    S.made_pass()
    S.made_pass()                                                                 # told once
    msgs = json.loads(S.CHATS.joinpath(f"{CID}.json").read_text())["messages"]
    notes = [m for m in msgs if m.get("note")]
    assert len(notes) == 1 and notes[0]["content"] == "**Lithium market** finished: [open it](#/mission/lith)\n\nAlbemarle leads."
    st = TestClient(S.app).get("/api/state", headers=H).json()
    assert st["from_chat"]["mission:old"]["chat"] == CID                          # the "From a chat" link on its page


def test_maker_tools_end_with_the_line_the_app_reads(app, monkeypatch):
    S = app

    async def answer(req, wait=8.0):
        return {"ok": True, "pending": True, "id": "fedcba9876543210"} if req["action"] == "build_assign" else {"ok": True, "slug": "lith"}
    monkeypatch.setattr(S, "submit", answer)
    assert asyncio.run(S.mission_create("task", "Lithium market", "watch it")).endswith("\nmade: mission:lith")
    b = asyncio.run(S.build_assign("TestRepo", "Fix", "fix it"))
    assert b.endswith("\nmade: build:request-fedcba9876543210") and "Build #" not in b      # not the request id as a build number
    assert asyncio.run(S.mission_set_triggers("lith", [])).endswith("\nchanged: mission:lith")


def test_a_change_request_from_the_chat_says_where_it_went(app, monkeypatch):
    S, sent = app, []

    async def answer(req, wait=8.0):
        sent.append(req)
        return {"ok": True, "task": 12}                  # the runner's own shape: {"ok": true, **result}
    monkeypatch.setattr(S, "submit", answer)
    assert "task #12" in asyncio.run(S.change_request("TestRepo", "Add a version flag"))
    assert sent == [{"action": "change_request", "repo": "TestRepo", "text": "Add a version flag", "source": "chat"}]

    async def later(req, wait=8.0):
        return {"ok": True, "pending": True, "id": "x"}
    monkeypatch.setattr(S, "submit", later)
    assert "Do not call change_request again" in asyncio.run(S.change_request("TestRepo", "Add a version flag"))

    async def no(req, wait=8.0):
        return {"ok": False, "error": "that repository is not one the builder may change"}
    monkeypatch.setattr(S, "submit", no)
    assert asyncio.run(S.change_request("x", "Add a version flag")).startswith("Error: that repository")


def test_a_chat_s_first_title_ends_on_a_whole_word_with_the_cut_marked():
    import server as S
    assert S.chat_title("short  and\nplain") == "short and plain"
    long = "Make a mission to research the nulletheaven game brotato. Find everything about it"
    assert S.chat_title(long) == "Make a mission to research the nulletheaven game brotato…"      # it used to end "brotato. Fi"
    assert S.chat_title("x" * 80) == "x" * 60 + "…"                  # one long word: still marked

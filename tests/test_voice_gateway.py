"""The voice gateway (images/mission-control/server.py, docs/HOME-VOICE.md): Home Assistant's Ollama integration talks
to Hermes through it."""
import asyncio
import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
KEY = {"Authorization": "Bearer k3y"}


@pytest.fixture
def gw(tmp_path, monkeypatch):
    import server as S
    chats = tmp_path / "chats"
    (chats / "files").mkdir(parents=True)
    for k, v in {"CHATS": chats, "FILES": chats / "files", "VOICE_KEY": "k3y", "PROMPTS": ROOT / "prompts"}.items():
        monkeypatch.setattr(S, k, v)
    S.LIVE.pop(S.VOICE_CHAT, None)
    sent = []

    async def fake_run(c, payload, headers=None, retry=False):
        """Hermes: a tool first when the question needs one, then the answer in two pieces."""
        sent.append((payload, headers))
        live = S.LIVE[c["id"]] = {"text": "", "reasoning": "", "tools": [], "done": False, "stopped": False, "status": 200}
        await asyncio.sleep(0.05)
        if "missions" in payload["messages"][-1]["content"]:
            live["tools"].append({"name": "missions_overview", "status": "running", "detail": ""})
            await asyncio.sleep(0.1)
        live["text"] += "You have nine missions. "
        await asyncio.sleep(0.05)
        live["text"] += "Shall I read them out?"
        c = S.load_chat(c["id"])
        c["messages"].append({"role": "assistant", "content": live["text"]})
        c["pending"] = False
        S.save_chat(c)
        live["done"] = True
    monkeypatch.setattr(S, "run_chat", fake_run)
    S.sent = sent
    return S


def lines(r):
    return [json.loads(x) for x in r.text.splitlines() if x.strip()]


def test_the_gateway_needs_its_key_and_offers_one_model_per_room(gw):
    """VOI-03"""
    c = TestClient(gw.voice_app)
    assert c.get("/api/tags").status_code == 401 and c.get("/api/tags", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.post("/api/chat", json={"model": "hermes:kitchen", "messages": [{"role": "user", "content": "hi"}]}).status_code == 401
    names = [m["name"] for m in c.get("/api/tags", headers=KEY).json()["models"]]
    assert "hermes:kitchen" in names and "hermes:home" in names and len(names) == len(gw.VOICE_ROOMS)
    assert gw.room_of("hermes:office") == "office" and gw.room_of("hermes:garage") == gw.room_of(None) == "home"
    assert c.post("/api/show", headers=KEY, json={"model": "hermes:home"}).json()["capabilities"] == ["completion"]
    gw.VOICE_KEY = ""
    assert c.get("/api/tags", headers={"Authorization": "Bearer "}).status_code == 401      # no key set: closed


def test_a_spoken_turn_joins_the_voice_chat_and_streams_back_as_ollama_does(gw):
    """VOI-03, VOI-04: Home Assistant's history is not used; the newest words go to the one Voice chat, framed by the
    voice prompt with the room; the answer streams back in pieces and ends with done."""
    c = TestClient(gw.voice_app)
    r = c.post("/api/chat", headers=KEY, json={"model": "hermes:kitchen", "stream": True, "messages": [
        {"role": "system", "content": "Home Assistant's own prompt"}, {"role": "user", "content": "an old turn"},
        {"role": "assistant", "content": "old"}, {"role": "user", "content": "how long does an egg take"}]})
    out = lines(r)
    assert r.headers["content-type"].startswith("application/x-ndjson") and out[-1]["done"] is True
    assert "".join(x["message"]["content"] for x in out) == "You have nine missions. Shall I read them out?"
    payload, headers = gw.sent[0]
    assert headers == {"X-Hermes-Session-Id": f"mc-{gw.VOICE_CHAT}-0"} and payload["model"] == gw.VOICE_MODEL
    framed = payload["messages"][-1]["content"]
    assert framed.startswith("[Voice: this turn was spoken to you through the speaker in the kitchen")
    assert framed.endswith("how long does an egg take") and "Home Assistant's own prompt" not in json.dumps(payload)
    chat = gw.load_chat(gw.VOICE_CHAT)
    first = chat["messages"][0]
    assert chat["title"] == "Voice" and (first["role"], first["content"], first["room"]) == ("user", "how long does an egg take", "kitchen")
    voice = chat["messages"][-1]["voice"]
    assert chat["prompt"].startswith("main/VOICE@") and voice["room"] == "kitchen" and voice["first_ms"] is not None and voice["checked"] is False
    r2 = c.post("/api/chat", headers=KEY, json={"model": "hermes:office", "stream": False, "messages": [{"role": "user", "content": "and a soft one"}]})
    assert r2.json()["done"] is True and r2.json()["message"]["content"].startswith("You have nine")
    assert gw.sent[1][1] == headers                    # the same Hermes session in every room


def test_let_me_check_while_a_tool_runs_and_new_topic_starts_a_fresh_session(gw):
    """VOI-05: a tool before any word is bridged at once; "new topic" starts a new Hermes session, the chat stays."""
    c = TestClient(gw.voice_app)
    out = lines(c.post("/api/chat", headers=KEY, json={"model": "hermes:office", "messages": [{"role": "user", "content": "which missions run"}]}))
    assert out[0]["message"]["content"] == gw.VOICE_CHECK and gw.load_chat(gw.VOICE_CHAT)["messages"][-1]["voice"]["checked"] is True
    out = lines(c.post("/api/chat", headers=KEY, json={"model": "hermes:office", "messages": [{"role": "user", "content": "New topic."}]}))
    assert out[0]["message"]["content"] == "Sure. What's on your mind?" and len(gw.sent) == 1   # no Hermes call
    chat = gw.load_chat(gw.VOICE_CHAT)
    assert chat["hrev"] == 1 and "hsid" not in chat and len(chat["messages"]) == 4
    c.post("/api/chat", headers=KEY, json={"model": "hermes:office", "messages": [{"role": "user", "content": "hello"}]})
    assert gw.sent[-1][1] == {"X-Hermes-Session-Id": f"mc-{gw.VOICE_CHAT}-1"}

"""Chat through a usage limit (AST-12): the message is kept, the chat says when it is tried again (ChatGPT's own
reset time), it is answered by itself after the reset with a notification through the one path, and a normal answer
that talks about rate limits is not mistaken for one."""
import asyncio
import json
import time

import pytest
from starlette.testclient import TestClient

H = {"Tailscale-User-Login": "owner@test"}


def limit_error(reset):
    return ('RateLimitError: ChatgptException - {"error":{"type":"usage_limit_reached","message":"The usage limit has been '
            f'reached","plan_type":"plus","resets_at":{reset},"eligible_promo":null,"limit_window_minutes":300}}}}')


@pytest.fixture
def chat(tmp_path, monkeypatch):
    import server as S
    (tmp_path / "chats").mkdir()
    monkeypatch.setattr(S, "CHATS", tmp_path / "chats")
    S.LIMITED.clear()
    told = []

    async def submit(req, wait=8.0):
        told.append(req)
        return {"ok": True}
    monkeypatch.setattr(S, "submit", submit)

    async def nap(s):
        return None
    monkeypatch.setattr(S.asyncio, "sleep", nap)
    reply = {}

    class Resp:
        status_code = 200

        def __init__(self):
            self.status_code = reply["status"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aread(self):
            return reply["text"].encode()

        async def aiter_lines(self):
            yield "data: " + json.dumps({"choices": [{"delta": {"content": reply["text"]}}]})
            yield "data: [DONE]"

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, *a, **k):
            return Resp()
    monkeypatch.setattr(S.httpx, "AsyncClient", Client)
    c = {"id": "abc123def", "created": time.time(), "title": "RAM prices", "messages": [], "pending": True}
    c["messages"].append({"role": "user", "content": "What does 32 GB DDR4 cost now?", "ts": time.time()})
    S.save_chat(c)
    return S, c, reply, told


def test_a_usage_limit_keeps_the_message_and_says_when_the_limit_resets(chat):
    S, c, reply, told = chat
    reset = int(time.time()) + 3600
    reply.update(status=200, text=limit_error(reset))
    payload, headers = S.build_request(c, "gpt-sub", "medium")
    asyncio.run(S.run_chat(c, payload, headers))
    saved = S.load_chat(c["id"])
    last = saved["messages"][-1]
    assert last["limit"]["reset_known"] is True and abs(last["limit"]["retry_at"] - (reset + 60)) < 5
    assert "usage limit is reached" in last["content"] and "answered here by itself when the limit resets" in last["content"]
    assert last["detail"] == limit_error(reset) and saved["limit"]["tries"] == 1 and S.LIMITED[c["id"]] == last["limit"]["retry_at"]
    assert not saved["pending"] and told == []


def test_after_the_reset_the_message_is_answered_by_itself_and_the_owner_is_told(chat):
    S, c, reply, told = chat
    reply.update(status=200, text=limit_error(int(time.time()) + 5))
    asyncio.run(S.run_chat(c, *S.build_request(c, "gpt-sub", "medium")))
    S.LIMITED[c["id"]] = 0                                       # its time has come
    reply.update(status=200, text="32 GB DDR4-3200 costs about 60 € now.")

    async def due():
        S.retry_due()
        await S.RUNNING[c["id"]]
    asyncio.run(due())
    saved = S.load_chat(c["id"])
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant"]          # the waiting notice gave way
    assert saved["messages"][-1]["content"] == "32 GB DDR4-3200 costs about 60 € now." and "limit" not in saved
    assert told == [{"action": "chat_ready", "chat": c["id"], "title": "RAM prices"}] and c["id"] not in S.LIMITED


def test_a_limit_that_lasts_a_day_stops_and_try_now_moves_the_retry(chat):
    S, c, reply, told = chat
    reply.update(status=429, text="Too Many Requests")
    asyncio.run(S.run_chat(c, *S.build_request(c, "gpt-sub", "medium")))
    saved = S.load_chat(c["id"])
    assert saved["limit"]["reset_known"] is False and "tries every 15 minutes" in saved["messages"][-1]["content"]
    r = TestClient(S.app).post(f"/api/chats/{c['id']}/retry", headers=H).json()
    assert r["ok"] and S.LIMITED[c["id"]] <= time.time()
    saved["limit"]["since"] = time.time() - 25 * 3600
    S.save_chat(saved)

    async def due():
        S.retry_due()
    asyncio.run(due())
    saved = S.load_chat(c["id"])
    assert "limit" not in saved and "did not end within a day" in saved["messages"][-1]["content"] and c["id"] not in S.RUNNING


def test_a_normal_answer_about_rate_limits_is_not_a_usage_limit():
    import server as S
    assert S.limit_of(200, "A 429 means too many requests: the API's rate limit was hit, so back off.") == (False, None)
    assert S.limit_of(200, limit_error(int(time.time()) + 600), tools=[{"name": "web_search"}]) == (False, None)
    assert S.limit_of(429, "")[0] and S.limit_of(500, "upstream: usage limit reached")[0]
    assert S.reset_in("Please try again in 5 minutes.") == 300 and S.reset_in("resets_in_seconds: 90") == 90
    assert S.reset_in("no time given") is None

"""images/swarm/swarm.py: who the caller is, what the runner may do, the tool surface, snapshots (SWM-23, SWM-62, SWM-89)."""
import asyncio
import json
import sqlite3

import pytest

import swarm
from ledger import Refused

CARDS = [{"id": "scout", "harness": "hermes", "key": "vk-scout", "tools": ["fetch"]},
         {"id": "doctor", "harness": "claude-code", "key": "none", "tools": []},
         {"id": "self-review", "harness": "python", "key": "vk-review", "tools": []}]


@pytest.fixture
def svc(tmp_path):
    tokens = {"agents": {"scout": swarm.sha("tok-scout")}, "runner": swarm.sha("tok-runner")}
    return swarm.Service(tmp_path, CARDS, tokens)


def test_identity_comes_only_from_the_stored_credential(svc):
    assert svc.agent_from_headers({"x-api-key": "tok-scout"})["id"] == "scout"
    with pytest.raises(Refused, match="SWM-89"):          # a client header would replace the stored credential
        svc.agent_from_headers({"x-api-key": "tok-scout", "authorization": "Bearer tok-scout"})
    with pytest.raises(Refused, match="unknown caller"):
        svc.agent_from_headers({"x-api-key": "guess"})
    r = svc.answer(lambda: svc.agent_from_headers({"x-api-key": "tok-scout"}), "upsert",
                   {"idem": "i1", "kind": "report", "key": "r1", "title": "Uranium miners note", "body": "text"})
    assert r["ok"]
    assert svc.ledger.get(None, r["result"]["id"])["owner"] == "scout"      # the sender is the token's agent, not an argument


def test_the_runner_acts_only_for_host_agents_and_relays_the_owner(svc):
    h = {"authorization": "Bearer tok-runner"}
    assert svc.actor_for_runner({**h, "x-swarm-actor": "doctor"}) == {"id": "doctor", "cls": "agent", "via": "runner", "run": ""}
    assert svc.actor_for_runner({**h, "x-swarm-actor": "self-review"})["id"] == "self-review"
    assert svc.actor_for_runner({**h, "x-swarm-actor": "owner", "x-swarm-by": "owner"})["id"] == "owner:owner"
    with pytest.raises(Refused, match="through the gateway"):
        svc.actor_for_runner({**h, "x-swarm-actor": "scout"})
    with pytest.raises(Refused, match="unknown caller"):
        svc.actor_for_runner({"authorization": "Bearer nope", "x-swarm-actor": "doctor"})
    r = svc.answer(lambda: svc.actor_for_runner({**h, "x-swarm-actor": "doctor"}), "transition", {"idem": "t", "id": 99, "to": "open", "reason": "x"})
    assert r == {"ok": False, "refused": "no artifact 99"}


def test_the_tool_surface_is_small(svc):
    tools = asyncio.run(swarm.mcp_app(svc).list_tools())
    tools = getattr(tools, "tools", tools)
    assert len(tools) <= 12
    assert sum(len(t.description or "") for t in tools) <= 6000
    assert {t.name for t in tools} >= {"swarm_context", "ledger_find", "ledger_get", "ledger_upsert", "ledger_transition"}


def test_the_snapshot_is_a_consistent_copy(svc, tmp_path):
    svc.answer(lambda: svc.actor_for_runner({"authorization": "Bearer tok-runner", "x-swarm-actor": "doctor"}), "upsert",
               {"idem": "s", "kind": "finding", "key": "f", "title": "A finding to back up", "body": "b"})
    svc.snapshot()
    c = sqlite3.connect(tmp_path / "swarm.snapshot.db")
    assert c.execute("select title from artifacts").fetchone()[0] == "A finding to back up"
    assert json.loads(json.dumps(svc.op({"id": "x", "cls": "owner"}, "who", {})))[0]["id"] == "scout"
    restored = tmp_path / "restored"
    restored.mkdir()
    (restored / "swarm.snapshot.db").write_bytes((tmp_path / "swarm.snapshot.db").read_bytes())
    assert swarm.restore_if_missing(restored) and not swarm.restore_if_missing(restored)     # only when the database is missing
    assert swarm.Service(restored, CARDS, {}).ledger.find(None, kind="finding")[0]["title"] == "A finding to back up"

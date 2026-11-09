"""The memory tool (MEM-28 to MEM-30) and its views (MEM-45, MEM-46): one MCP server per access class with four tools, granted in place
of qmd, graphify and agent_note; the scout and the coders get the one without the owner's facts; the app shows the catalogue, the
lessons and each run's memory."""
import pysrc
import webjs
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SERVER = pysrc.server()
APP = webjs.app_js()


def test_the_memory_server_has_four_tools():
    body = SERVER.split("def memory_server(name, access):")[1].split("memory_mcp = memory_server")[0]
    assert re.findall(r'@srv\.tool\(name="(\w+)"', body) == ["search", "open", "subscribe", "note"]
    assert 'memory_mcp = memory_server("memory", "all")' in SERVER and 'memory_public_mcp = memory_server("memorypublic", "public")' in SERVER
    assert 'allowed_hosts=["mission-control:8097"]' in SERVER and 'allowed_hosts=["mission-control:8098"]' in SERVER
    assert '{**req, "access": access}' in body                                             # the server decides the access, never the caller
    lite = yaml.safe_load((ROOT / "config/litellm/config.yaml").read_text())["mcp_servers"]
    assert lite["memory"]["url"] == "http://mission-control:8097/mcp" and lite["memorypublic"]["url"] == "http://mission-control:8098/mcp"
    import memstack as MS
    assert {"mem_search", "mem_open", "mem_subscribe", "mem_note"} <= MS.ACTIONS
    assert "elif req.get(\"action\") in MS.ACTIONS:" in pysrc.missions()   # its own thread


def test_memory_public_never_reads_owner_facts_private_wikis_or_journals(monkeypatch):
    import memstack as MS
    monkeypatch.setattr(MS, "private_roots", lambda: {"missions/mail/wiki"})
    pub = MS.access_check("public", "scout")
    for coll in ("owner:facts", "owner:profile", "agent:scout", "agent:mission-ram", "world:missions/mail/wiki", "world:sources", "work:ledger"):
        assert not pub(coll), coll
    for coll in ("world:topics/copper/wiki", "code:click", "howto:lessons/research", "howto:skills"):
        assert pub(coll), coll
    out = MS.handle({"action": "mem_note", "access": "public", "kind": "owner", "text": "The owner likes tea.", "evidence": "x"})
    assert out["text"].startswith("Not kept: the owner's facts are not yours")


def test_memory_replaces_qmd_graphify_and_agent_note_in_every_grant():
    keys = (ROOT / "ops/keys.sh").read_text()
    grants = dict(re.findall(r'"(vk-[a-z-]+)\|[^|]+\|[0-9.]+\|([^"]*)"', keys))
    for k, g in grants.items():
        assert not {"qmd", "graphify"} & set(g.split(",")), k
    assert "memory" in grants["vk-main"] and "memory" in grants["vk-mission"] and "memory" in grants["vk-curator"]
    assert grants["vk-builder"] == "memorypublic" and grants["vk-code"] == "memorypublic" and "memorypublic" in grants["vk-scout"]   # MEM-30
    cards = yaml.safe_load((ROOT / "config/agents.yaml").read_text())["agents"]
    for c in cards:
        if c.get("harness") in ("hermes", "opencode") or c["id"] == "builder":
            assert {"memory", "memorypublic"} & set(c.get("tools") or []) or c["id"] == "desk", c["id"]
    assert "async def agent_note" not in SERVER
    assert "graphify" not in (ROOT / "config/hermes/configure-builder.sh").read_text().split("mcp_servers.memory")[0].split("hermes config unset")[1]


def test_the_memory_tab_shows_the_catalogue_by_sector():
    assert 'const MEM_TABS = [["memory", "#/memory", "All"]' in APP and '["howto", "#/howto", "How-to"]' in APP
    assert '["wiki", "#/memory", "Memory", ic.wiki]' in APP and "memory: vMemory, howto: vHowto" in APP
    v = APP.split("async function vMemory()")[1].split("async function vHowto()")[0]
    assert '"/api/memory/catalogue"' in v and "c.answers" in v and "TRUST_WORD[c.trust]" in v and "given to ${nf(g.runs)} run" in v and "emptyState(" in v
    assert 'Route("/api/memory/catalogue", api_memory_catalogue)' in SERVER and 'Route("/api/memory/lessons", api_memory_lessons)' in SERVER


def test_the_memory_tab_opens_on_a_map_of_its_sectors():
    v = APP.split("async function vMemory()")[1].split("async function vHowto()")[0]
    m = APP.split("function memMapHtml(cs, sectors)")[1].split("async function vMemory()")[0]
    assert v.index("memMapHtml(cs, sectors)") < v.index('id="memsec-${k}"')            # the map first, every collection below it
    assert "memStatusHtml(st)" in v.split("<details")[1]                              # the usage figures folded away under the map
    assert "given_7d" in m and "MEM_TOP" in m and "cap: top" in m and 'href="#memsec-${k}"' in m
    assert 'id="memprobs"' in m and "m.problems" in APP.split("const memProbsHtml")[1][:300]
    assert 'route.name === "memory" && $("#memprobs")' in APP                          # the problems fill in when the state arrives
    css = (ROOT / "images/mission-control/web/static/app.css").read_text()
    assert ".memmap {" in css and ".memprobs:empty { display: none; }" in css


def test_a_run_s_page_shows_its_memory():
    assert 'data-memrun="${esc(V.run)}"' in APP and "function memRunHtml(r, chat)" in APP and "/api/memory/run?run=" in APP
    assert 'act({ action: "mem_chat"' in APP and 'act({ action: "mem_undo"' in APP
    assert 'Route("/api/memory/run", api_memory_run)' in SERVER

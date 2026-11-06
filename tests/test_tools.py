"""The Stack tab's tools (APP-30): one list of every tool the stack runs on with its menus, the Go-to search over it,
and a nightly check that every link opens."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "images/mission-control/web/static"


def test_every_tool_has_its_menus_and_every_page_exists():
    j = json.loads((STATIC / "tools.json").read_text())
    ids = [t["id"] for t in j["tools"]]
    assert len(ids) == len(set(ids)) and {"homeassistant", "nas", "fritzbox", "forgejo", "hermes", "phoenix"} <= set(ids)
    for t in j["tools"]:
        assert t["name"] and t["what"] and t["menus"] and (t["host"].startswith(("tailnet", "http://", "https://"))), t["id"]
        assert all(m["name"] and m["path"].startswith("/") for m in t["menus"]), t["id"]
    ha = next(t for t in j["tools"] if t["id"] == "homeassistant")
    assert {"Settings", "Integrations", "Voice assistants", "People"} <= {m["name"] for m in ha["menus"]}
    js = (STATIC / "app.js").read_text()
    views = set(re.findall(r"(\w+): v[A-Z]\w+", re.search(r"const fn = \{(.*?)\}\[route\.name\]", js).group(1)))
    for name, href, _ in j["pages"]:
        assert href.startswith("#/") and (href[2:].split("?")[0].split("/")[0] or "home") in views | {"home"}, name
    assert "const APPS" not in js and "toolsLoad()" in (STATIC / "guide.js").read_text()     # one list for the Stack tab and the guide


def test_go_to_finds_menus_and_pages_by_their_words():
    """The search ranks Mission Control's own pages first, then every tool menu whose name or words match all words."""
    js = (STATIC / "app.js").read_text()
    body = js[js.index("function toolHits(q) {"):js.index("function bindStackTools() {")]
    assert "words.every((w) => s.toLowerCase().includes(w))" in body and "return [...pages, ...menus];" in body
    j = json.loads((STATIC / "tools.json").read_text())

    def hits(q):                                         # the same rule, on the real list
        w = q.lower().split()
        ok = lambda s: all(x in s.lower() for x in w)
        return [n for n, _, words in j["pages"] if ok(f"{n} {words}")] + \
            [f"{t['name']} → {m['name']}" for t in j["tools"] for m in t["menus"] if ok(f"{t['name']} {m['name']} {m.get('words', '')} {t['what']}")]
    assert "Home Assistant → People" in hits("people") and "Home Assistant → Voice assistants" in hits("voice pipeline")
    assert hits("wifi")[:1] == ["Router → Overview"] and "Forgejo → Access tokens" in hits("tokens") and hits("house")[0] == "House"


def test_a_tool_link_that_does_not_open_is_a_journey_failure():
    import journeys as J
    tools = {"tools": [{"name": "HA", "host": "http://192.168.1.10:8123", "menus": [{"name": "People", "path": "/config/person"}, {"name": "Gone", "path": "/x"}]},
                       {"name": "Hermes", "host": "tailnet:8448", "menus": [{"name": "Open", "path": "/"}]},
                       {"name": "Tailscale", "host": "https://login.tailscale.com", "menus": [{"name": "Machines", "path": "/admin"}]}]}
    seen = []
    status = {"/config/person": 200, "/x": 404, "/": 302}
    r = J.check_tools(tools, opener=lambda url: seen.append(url) or status[url[url.index("/", 8):]])
    assert r["checked"] == 3 and r["failures"] == ["HA → Gone does not open (404): http://192.168.1.10:8123/x"]
    assert f"{J.TAILNET}:8448/" in seen and not any("tailscale.com" in u for u in seen)          # outside the house: not called
    assert J.check_tools(tools, opener=lambda url: "URLError: timed out")["failures"][0].startswith("HA → People does not open")

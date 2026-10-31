"""ops/house.py: the House (Home Assistant on the NAS). A fake Home Assistant: REST calls are recorded, the websocket
client talks to a tiny local websocket server. Nothing reaches the NAS, Amazon or Hermes."""
import base64
import hashlib
import json
import socket
import struct
import threading
import types

import pytest


@pytest.fixture
def H(tmp_path, monkeypatch):
    import house
    calls, events = [], []
    monkeypatch.setattr(house, "HOME", tmp_path)
    monkeypatch.setattr(house, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(house, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(house, "TOKEN", "t0ken")
    monkeypatch.setattr(house.RTM, "emit", lambda *a, **k: None)
    monkeypatch.setattr(house, "rest", lambda method, path, body=None, **k: calls.append((method, path, body)) or {})
    house.M = types.SimpleNamespace(event=lambda *a, **k: events.append(a), log=lambda *a: None)
    things = [
        {"entity_id": "light.sofa", "name": "Sofa lamp", "domain": "light", "area": "Living room", "state": "off", "protected": False},
        {"entity_id": "switch.fridge", "name": "Fridge", "domain": "switch", "area": "Kitchen", "state": "on", "protected": True},
        {"entity_id": "cover.bedroom", "name": "Shutter", "domain": "cover", "area": "Bedroom", "state": "open", "protected": False},
    ]
    echos = [{"id": "dev1", "name": "Echo Kitchen", "area": "Kitchen", "speak": "notify.echo_kitchen_speak",
              "announce": "notify.echo_kitchen_announce", "event": "event.echo_kitchen_voice"},
             {"id": "dev2", "name": "Echo Bedroom", "area": "Bedroom", "speak": "notify.echo_bedroom_speak",
              "announce": "notify.echo_bedroom_announce", "event": "event.echo_bedroom_voice"}]
    house._status.update(t=10**12, data={"connected": True, "things": things, "echos": echos})
    house.real_snapshot = house.__dict__.get("real_snapshot", house.snapshot)
    monkeypatch.setattr(house, "snapshot", lambda: house._status["data"])        # a refresh after a switch reads the same fake
    house._voice.update(last={}, times=[], busy=False)
    house.calls, house.events = calls, events
    return house


@pytest.mark.parametrize("said,question", [
    ("hermes what is the weather", "what is the weather"), ("Alexa, Hermes, wie spät ist es", "wie spät ist es"),
    ("frag hermes ob es morgen regnet", "ob es morgen regnet"), ("ask Hermes: who won", "who won"),
    ("turn on the light", None), ("hermesbrücke", None), ("hermes", "")])
def test_trigger(H, said, question):
    m = H.TRIGGER.match(said)
    assert (m.group(1).strip() if m else None) == question


def test_switch_light_dim_and_cover(H):
    assert H.switch({"entity": "sofa lamp", "op": "dim", "value": 30})["done"] == "Sofa lamp: dim 30"
    assert H.calls[-1] == ("POST", "/api/services/light/turn_on", {"entity_id": "light.sofa", "brightness_pct": 30})
    H.switch({"entity": "bedroom", "op": "position", "value": 140})
    assert H.calls[-1] == ("POST", "/api/services/cover/set_cover_position", {"entity_id": "cover.bedroom", "position": 100})
    with pytest.raises(ValueError, match="only lights"):
        H.switch({"entity": "fridge", "op": "dim", "value": 5, "by": "owner"})
    with pytest.raises(ValueError, match="unknown action"):
        H.switch({"entity": "shutter", "op": "dim", "value": 5})


def test_protected_things_only_by_the_owner(H):
    with pytest.raises(ValueError, match="protected"):
        H.switch({"entity": "Fridge", "op": "off"})
    assert not H.calls
    H.switch({"entity": "Fridge", "op": "off", "by": "owner"})
    assert H.calls[-1][1] == "/api/services/switch/turn_off"
    log = [json.loads(x) for x in H.LOG.read_text().splitlines()]
    assert log[-1]["by"] == "owner" and "Fridge" in log[-1]["text"]


def test_unknown_or_ambiguous_names(H):
    with pytest.raises(ValueError, match="no light"):
        H.switch({"entity": "garage", "op": "on"})
    H._status["data"]["things"].append({**H._status["data"]["things"][0], "entity_id": "light.sofa2", "name": "Sofa lamp 2"})
    with pytest.raises(ValueError, match="matches 2"):
        H.switch({"entity": "sofa", "op": "on"})


def test_alexa_command_and_refusals(H):
    H.alexa({"command": "schalte das Licht im Wohnzimmer aus", "echo": "bedroom"})
    assert H.calls[-1] == ("POST", "/api/services/alexa_devices/send_text_command",
                           {"device_id": "dev2", "text_command": "schalte das Licht im Wohnzimmer aus"})
    for bad, why in (("schalte den Kühlschrank aus", "protected"), ("turn off the router", "protected"), ("bestelle Milch", "shopping")):
        with pytest.raises(ValueError, match=why):
            H.alexa({"command": bad})
    with pytest.raises(ValueError, match="no Echo called"):
        H.alexa({"command": "licht an", "echo": "garage"})


def test_say_everywhere_with_chime(H):
    H.say({"message": "Dinner is ready", "echo": "all", "announce": True})
    assert H.calls[-1] == ("POST", "/api/services/notify/send_message",
                           {"entity_id": ["notify.echo_kitchen_announce", "notify.echo_bedroom_announce"], "message": "Dinner is ready"})


def test_not_connected(H, monkeypatch):
    monkeypatch.setattr(H, "TOKEN", "")
    with pytest.raises(ValueError, match="not connected"):
        H.switch({"entity": "sofa", "op": "on"})


def test_settings_only_by_the_owner(H):
    with pytest.raises(ValueError, match="only the owner"):
        H.handle({"action": "house_settings", "voice": False, "by": "ai"})
    assert H.handle({"action": "house_settings", "voice": False, "by": "owner"})["settings"] == {"voice": False}


def test_connect_rejects_odd_codes(H):
    with pytest.raises(ValueError, match="sign-in code"):
        H.connect({"code": "x; rm -rf /", "client_id": "https://pc.ts.net:8447/"})
    with pytest.raises(ValueError, match="sign-in code"):
        H.connect({"code": "a" * 32, "client_id": "http://evil/"})


def test_voice_bridge_only_hermes_requests(H, monkeypatch):
    states = {"event.echo_kitchen_voice": {"state": "t1", "attributes": {"voice_command": "hermes how old is the moon"}},
              "event.echo_bedroom_voice": {"state": "t1", "attributes": {"voice_command": "licht an"}}}
    monkeypatch.setattr(H, "rest", lambda m, path, body=None, **k: states[path.rsplit("/", 1)[1]])
    started = []
    monkeypatch.setattr(H.threading, "Thread", lambda target, args, **k: types.SimpleNamespace(start=lambda: started.append(args)))
    H.voice_once()
    assert not started                           # what was said before the runner started is not a new question
    states["event.echo_kitchen_voice"] = {"state": "t2", "attributes": {"voice_command": "Alexa, frag Hermes wie alt ist der Mond"}}
    states["event.echo_bedroom_voice"] = {"state": "t2", "attributes": {"voice_command": "licht aus"}}
    H.voice_once()
    assert [(q, e["name"]) for q, e in started] == [("wie alt ist der Mond", "Echo Kitchen")]
    H._voice["busy"] = False
    H.handle({"action": "house_settings", "voice": False, "by": "owner"})
    states["event.echo_kitchen_voice"] = {"state": "t3", "attributes": {"voice_command": "hermes again"}}
    H.voice_once()
    assert len(started) == 1                     # switched off on the House page


def test_spoken_answer_is_plain(H, monkeypatch):
    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"choices": [{"message": {"content": "**Sunny**, see [here](https://x.example) `ok`"}}]}).encode()
    seen = {}
    monkeypatch.setattr(H.urllib.request, "urlopen", lambda req, timeout: seen.update(body=json.loads(req.data), headers=req.headers) or R())
    out = H.ask_hermes("weather?", H._status["data"]["echos"][0])
    assert out == "Sunny, see here ok"
    assert "Echo Kitchen" in seen["body"]["messages"][0]["content"] and seen["headers"]["X-hermes-session-id"].startswith("alexa-dev1-")


# ---------- the websocket client against a tiny fake Home Assistant ----------
def _frame(obj):
    data = json.dumps(obj).encode()
    n = len(data)
    return bytes([0x81]) + (bytes([n]) if n < 126 else bytes([126]) + struct.pack(">H", n) if n < 65536 else bytes([127]) + struct.pack(">Q", n)) + data


def _read_frame(conn):
    b0, b1 = conn.recv(2, socket.MSG_WAITALL)
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack(">H", conn.recv(2, socket.MSG_WAITALL))[0]
    mask = conn.recv(4, socket.MSG_WAITALL)
    data = conn.recv(n, socket.MSG_WAITALL) if n else b""
    return json.loads(bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def fake_ha(results, token="good"):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        head = b""
        while b"\r\n\r\n" not in head:
            head += conn.recv(1024)
        key = [ln.split(b": ")[1] for ln in head.split(b"\r\n") if ln.lower().startswith(b"sec-websocket-key")][0]
        acc = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
        conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + acc + b"\r\n\r\n"
                     + _frame({"type": "auth_required"}))
        auth = _read_frame(conn)
        conn.sendall(_frame({"type": "auth_ok" if auth.get("access_token") == token else "auth_invalid"}))
        try:
            while True:
                msg = _read_frame(conn)
                conn.sendall(_frame({"type": "event", "id": 999}) + _frame({"id": msg["id"], "type": "result", "success": True,
                                                                            "result": results[msg["type"]]}))
        except (ValueError, OSError, KeyError):
            conn.close()
    threading.Thread(target=serve, daemon=True).start()
    return f"http://127.0.0.1:{srv.getsockname()[1]}"


def test_snapshot_over_websocket(H, monkeypatch):
    results = {
        "config/entity_registry/list": [
            {"entity_id": "notify.echo_kitchen_speak", "platform": "alexa_devices", "device_id": "d1"},
            {"entity_id": "notify.echo_kitchen_announce", "platform": "alexa_devices", "device_id": "d1"},
            {"entity_id": "event.echo_kitchen_last_called", "platform": "alexa_devices", "device_id": "d1"},
            {"entity_id": "switch.echo_kitchen_do_not_disturb", "platform": "alexa_devices", "device_id": "d1"},
            {"entity_id": "switch.plug_fridge", "platform": "tplink", "device_id": "d2"},
            {"entity_id": "switch.plug_fridge_led", "platform": "tplink", "device_id": "d2", "entity_category": "config"},
            {"entity_id": "light.desk", "platform": "hue", "device_id": "d3", "name": "Desk lamp"}],
        "config/device_registry/list": [{"id": "d1", "name": "Echo Dot", "name_by_user": "Kitchen Echo", "area_id": "kitchen", "model": "Echo Dot (5th Gen)"},
                                        {"id": "d2", "name": "Kühlschrank", "area_id": "kitchen"}, {"id": "d3", "name": "Hue", "area_id": None}],
        "config/area_registry/list": [{"area_id": "kitchen", "name": "Kitchen"}],
        "get_states": [{"entity_id": "switch.plug_fridge", "state": "on", "attributes": {"friendly_name": "Plug", "current_power_w": 61.5}},
                       {"entity_id": "light.desk", "state": "on", "attributes": {"brightness": 128}}],
        "config_entries/get": [{"domain": "alexa_devices", "title": "Amazon", "state": "loaded", "source": "user"},
                               {"domain": "sun", "title": "Sun", "state": "loaded", "source": "system"}],
    }
    monkeypatch.setattr(H, "HA", fake_ha(results, token="t0ken"))
    monkeypatch.setattr(H, "_onboarded", lambda: True)
    s = H.real_snapshot()
    assert s["connected"] and s["integrations"] == [{"domain": "alexa_devices", "title": "Amazon", "state": "loaded"}]
    assert s["echos"] == [{"id": "d1", "name": "Kitchen Echo", "area": "Kitchen", "speak": "notify.echo_kitchen_speak",
                           "announce": "notify.echo_kitchen_announce", "event": "event.echo_kitchen_last_called", "model": "Echo Dot (5th Gen)"}]
    plug, desk = sorted(s["things"], key=lambda t: t["entity_id"], reverse=True)
    assert plug == {"entity_id": "switch.plug_fridge", "name": "Plug", "domain": "switch", "area": "Kitchen", "state": "on",
                    "platform": "tplink", "protected": True, "power_w": 61.5}      # protected by its id and device name (Kühlschrank)
    assert desk["name"] == "Desk lamp" and desk["brightness"] == 50 and desk["area"] == "" and not desk["protected"]


def test_snapshot_bad_token(H, monkeypatch):
    monkeypatch.setattr(H, "HA", fake_ha({}, token="other"))
    monkeypatch.setattr(H, "_onboarded", lambda: True)
    s = H.real_snapshot()
    assert not s["connected"] and "connect again" in s["error"]

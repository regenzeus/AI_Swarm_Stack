"""Hermes' voice in Home Assistant (docs/HOME-VOICE.md, VOI-06): connect the speech services, the voice gateway and the
English pipeline, through Home Assistant's own setup flows with the stack's token. Safe to run again: what exists is
kept, only what is missing is added; nothing is removed.

  sops exec-env secrets/secrets.enc.yaml "python3 ops/voice_setup.py [speech|gateway|pipeline|all] [GATEWAY_URL]"

speech    Wyoming: speech to text (127.0.0.1:10300) and Piper (127.0.0.1:10200), both on the NAS (nas/voice)
gateway   Home Assistant's Ollama integration to the app's voice gateway (GATEWAY_URL, default the PC's LAN address, key
          VOICE_KEY), and one conversation agent per room (hermes:kitchen …), Home Assistant's own control left off
pipeline  the Assist pipeline "Hermes" in English: speech to text → Hermes (home) → Piper, no wake word on the server
          (the satellite listens for it itself); it is Home Assistant's preferred one, so the phone's app uses it
"""
import json
import textcap as TC                              # visible caps (AGENTS.md, truncation)
import deployment as DEPLOY                        # this deployment's hosts and paths (deployments/<name>/deployment.env)
import os
import sys
import urllib.error
import urllib.request

HA = DEPLOY.HA_URL
GATEWAY = f"http://{DEPLOY.PC_LAN_HOST}:11434"    # the PC on the LAN; Windows passes 11434 to the gateway (11435), from the NAS only
SPEECH = {"stt": ("127.0.0.1", 10300), "tts": ("127.0.0.1", 10200)}
ROOMS = ("home", "living-room", "kitchen", "office", "bedroom", "bathroom", "hallway", "guest-bath")   # = server.py VOICE_ROOMS
PIPELINE = "Hermes"
VOICE = "en_GB-alba-medium"                       # V0: the first audio in 0.82 s
VOICE_LANG = VOICE.split("-")[0]                  # Piper takes its voices' locale (en_GB), not "en": with "en" every spoken
                                                  # turn failed before it began ("Oops, an error has occurred", 1 Nov)


def call(method, path, body=None, token=None):
    req = urllib.request.Request(HA + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token or os.environ['HA_TOKEN']}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Home Assistant {method} {path}: HTTP {e.code} {TC.cut(e.read().decode(errors='replace'), 300)}") from e   # cap: preview


def entries(domain, call=call):
    return [e for e in call("GET", "/api/config/config_entries/entry") if e["domain"] == domain]


def flow(handler, data, call=call):
    """Run a one-step config flow. -> its result (create_entry, or abort with a reason such as already_configured)."""
    f = call("POST", "/api/config/config_entries/flow", {"handler": handler})
    if f.get("type") != "form":
        return f
    return call("POST", f"/api/config/config_entries/flow/{f['flow_id']}", data)


def speech(call=call):
    """The two Wyoming services. -> what happened to each. Home Assistant accepts the same address twice (no unique
    id for a host added by hand), so an existing entry is recognised by its title (the service's name)."""
    out, titles = {}, " ".join(e["title"] for e in entries("wyoming", call))
    for kind, (host, port) in SPEECH.items():
        if {"stt": "whisper", "tts": "piper"}[kind] in titles:
            out[kind] = "kept"
            continue
        r = flow("wyoming", {"host": host, "port": port}, call)
        out[kind] = r.get("type") == "create_entry" and "added" or r.get("reason") or r.get("type")
    return out


def gateway(url=GATEWAY, call=call):
    """The Ollama integration to the voice gateway. -> 'added', 'kept' or the reason it failed."""
    if any(e["title"] for e in entries("ollama", call)):
        return "kept"
    r = flow("ollama", {"url": url, "api_key": os.environ["VOICE_KEY"]}, call)
    if r.get("type") == "create_entry":
        return "added"
    raise RuntimeError(f"the gateway at {url} was not accepted: {r.get('errors') or r.get('reason') or r}")


def agents(ws, call=call):
    """One conversation agent per room on the gateway's Ollama entry (model hermes:<room>). Home Assistant's own control
    of the house stays off and it sends no history: Hermes has its own tools and keeps the conversation. -> added rooms"""
    entry = next(e for e in entries("ollama", call))
    have = {s["title"] for s in ws.call(type="config_entries/subentries/list", entry_id=entry["entry_id"])}   # titles only, no data
    added = []
    for room in ROOMS:
        if f"Hermes {room.replace('-', ' ')}" in have:
            continue
        f = call("POST", "/api/config/config_entries/subentries/flow", {"handler": [entry["entry_id"], "conversation"]})
        if f.get("type") != "form":
            raise RuntimeError(f"no agent form for {room}: {f.get('reason') or f}")
        r = call("POST", f"/api/config/config_entries/subentries/flow/{f['flow_id']}",
                 {"name": f"Hermes {room.replace('-', ' ')}", "model": f"hermes:{room}", "llm_hass_api": [], "max_history": 0,
                  "prompt": "Hermes answers with its own instructions (the voice gateway); this text is not used.", "think": False})
        if r.get("type") != "create_entry":
            raise RuntimeError(f"the agent for {room} was not added: {r.get('errors') or r.get('reason') or r}")
        added.append(room)
        loaded(entry["entry_id"], call)                   # a new agent reloads the entry; the next one waits for it
    return added


def loaded(entry_id, call=call, wait=30, sleep=None):
    """Wait until a config entry is loaded again (Home Assistant reloads it after a change)."""
    import time
    for _ in range(wait * 2):
        if next((e["state"] for e in call("GET", "/api/config/config_entries/entry") if e["entry_id"] == entry_id), "") == "loaded":
            return
        (sleep or time.sleep)(0.5)
    raise RuntimeError(f"Home Assistant did not load {entry_id} again within {wait} s")


def engines(call=call):
    """-> entity ids of speech to text, Piper and each room's agent (conversation.hermes_kitchen …)."""
    states = [s["entity_id"] for s in call("GET", "/api/states")]
    stt = next(s for s in states if s.startswith("stt.") and "whisper" in s)
    tts = next(s for s in states if s.startswith("tts.") and "piper" in s)
    rooms = {r: next((s for s in states if s == f"conversation.hermes_{r.replace('-', '_')}"), None) for r in ROOMS}
    return stt, tts, rooms


def pipelines(ws, call=call):
    """The English pipeline "Hermes" (home), and "Hermes <room>" per room: speech to text → Hermes → Piper, no wake word
    on the server (the satellite listens for it), no local intents (every sentence goes to Hermes). -> added names"""
    stt, tts, rooms = engines(call)
    have = {p["name"]: p for p in ws.call(type="assist_pipeline/pipeline/list")["pipelines"]}
    added = []
    for room, agent in rooms.items():
        name = PIPELINE if room == "home" else f"{PIPELINE} {room.replace('-', ' ')}"
        if not agent:
            continue
        fields = dict(name=name, language="en", conversation_engine=agent, conversation_language="en", stt_engine=stt,
                      stt_language="en", tts_engine=tts, tts_language=VOICE_LANG, tts_voice=VOICE, wake_word_entity=None,
                      wake_word_id=None, prefer_local_intents=False)
        if name not in have:
            ws.call(type="assist_pipeline/pipeline/create", **fields)
            added.append(name)
        elif have[name].get("tts_language") != VOICE_LANG:      # made with "en" before: repaired in place
            ws.call(type="assist_pipeline/pipeline/update", pipeline_id=have[name]["id"], **fields)
            added.append(name + " (repaired)")
    r = ws.call(type="assist_pipeline/pipeline/list")
    home = next((p["id"] for p in r["pipelines"] if p["name"] == PIPELINE), None)
    if home and r.get("preferred_pipeline") != home:          # the Home Assistant app has no pipeline choice of its own
        ws.call(type="assist_pipeline/pipeline/set_preferred", pipeline_id=home)
    return added


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("speech", "all"):
        print("speech:", speech())
    if step in ("gateway", "all"):
        print("gateway:", gateway(sys.argv[2] if len(sys.argv) > 2 else GATEWAY))
    if step in ("pipeline", "all"):
        import house as H                                 # its Home Assistant websocket client
        ws = H.WS(os.environ["HA_TOKEN"])
        try:
            print("agents:", agents(ws))
            print("pipelines:", pipelines(ws))
        finally:
            ws.close()

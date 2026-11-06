"""Hermes' voice in Home Assistant (ops/voice_setup.py) and the AI phone as its satellite (docs/HOME-VOICE.md)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FakeHA:
    """Home Assistant's config flows, subentries, states and pipelines, enough for the setup."""
    def __init__(self):
        self.entries, self.subs, self.pipes, self.flows, self.preferred = [], [], [], {}, None

    def call(self, method, path, body=None):
        if path == "/api/config/config_entries/entry":
            return self.entries
        if path == "/api/states":
            return [{"entity_id": e} for e in ["stt.faster_whisper", "tts.piper", "light.x"] +
                    [f"conversation.{s['title'].lower().replace(' ', '_')}" for s in self.subs]]
        if path.endswith("/flow") and method == "POST":
            fid = f"f{len(self.flows)}"
            self.flows[fid] = body["handler"]
            return {"type": "form", "flow_id": fid}
        fid = path.rsplit("/", 1)[1]
        handler = self.flows.pop(fid)
        if isinstance(handler, list):                     # a subentry: one room's agent
            self.subs.append({"title": body["name"], "data": body})
            return {"type": "create_entry"}
        if handler == "ollama" and any(e["domain"] == "ollama" and e["data"]["url"] == body["url"] for e in self.entries):
            return {"type": "abort", "reason": "already_configured"}
        title = {10300: "faster-whisper", 10200: "piper"}.get(body.get("port"), body.get("url") or handler)
        self.entries.append({"domain": handler, "title": title, "entry_id": f"e{len(self.entries)}", "data": body})
        return {"type": "create_entry"}         # Wyoming takes the same address twice, as Home Assistant does

    def ws(self):
        ha = self

        class WS:
            def call(self, type, **kw):
                if type == "config_entries/subentries/list":    # as Home Assistant lists them: no data, only the title
                    return [{"subentry_id": f"s{i}", "subentry_type": "conversation", "title": s["title"], "unique_id": None}
                            for i, s in enumerate(ha.subs)]
                if type == "assist_pipeline/pipeline/list":
                    return {"pipelines": ha.pipes, "preferred_pipeline": ha.preferred}
                if type == "assist_pipeline/pipeline/create":
                    ha.pipes.append({**kw, "id": f"p{len(ha.pipes)}"})
                    return kw
                if type == "assist_pipeline/pipeline/update":
                    p = next(p for p in ha.pipes if p["id"] == kw["pipeline_id"])
                    p.update({k: v for k, v in kw.items() if k != "pipeline_id"})
                    return p
                if type == "assist_pipeline/pipeline/set_preferred":
                    ha.preferred = kw["pipeline_id"]
                    return None
                raise AssertionError(type)
        return WS()


def test_the_setup_adds_what_is_missing_and_keeps_what_is_there(monkeypatch):
    """VOI-06"""
    import voice_setup as VS
    monkeypatch.setenv("VOICE_KEY", "k3y")
    ha = FakeHA()
    assert VS.speech(ha.call) == {"stt": "added", "tts": "added"} and VS.speech(ha.call) == {"stt": "kept", "tts": "kept"}
    assert [e["title"] for e in ha.entries] == ["faster-whisper", "piper"]           # no second copy
    assert VS.gateway("http://pc:11434", ha.call) == "added" and VS.gateway("http://pc:11434", ha.call) == "kept"
    assert ha.entries[-1]["data"] == {"url": "http://pc:11434", "api_key": "k3y"}
    ws = ha.ws()
    monkeypatch.setattr(VS, "loaded", lambda entry_id, call=None: None)
    assert VS.agents(ws, ha.call) == list(VS.ROOMS) and VS.agents(ws, ha.call) == [] and len(ha.subs) == len(VS.ROOMS)
    kitchen = next(s["data"] for s in ha.subs if s["data"]["model"] == "hermes:kitchen")
    assert kitchen["llm_hass_api"] == [] and kitchen["max_history"] == 0 and kitchen["think"] is False
    added = VS.pipelines(ws, ha.call)
    assert added[0] == "Hermes" and "Hermes guest bath" in added and VS.pipelines(ws, ha.call) == []
    home = ha.pipes[0]
    assert (home["conversation_engine"], home["stt_engine"], home["tts_engine"]) == ("conversation.hermes_home", "stt.faster_whisper", "tts.piper")
    assert home["language"] == home["stt_language"] == "en" and home["tts_language"] == "en_GB" and home["prefer_local_intents"] is False
    assert home["wake_word_entity"] is None and home["tts_voice"] == VS.VOICE and ha.preferred == home["id"]   # the app's choice
    home["tts_language"] = "en"                                # as the first setup made it: Piper refused every turn
    assert VS.pipelines(ws, ha.call) == ["Hermes (repaired)"] and home["tts_language"] == "en_GB"
    import server as S
    assert VS.ROOMS == S.VOICE_ROOMS                     # the agents' models are the gateway's rooms


def test_the_agents_never_open_the_home_assistant_app_on_the_ai_phone():
    """VOI-07: the satellite's sign-in reaches the house, the router and the NAS."""
    src = (ROOT / "images/phone/phone.py").read_text()
    block = re.search(r'DEFAULT_BLOCK = """(.*?)"""', src, re.S).group(1)
    words = [ln.strip() for ln in block.splitlines() if ln.strip() and not ln.startswith("#")]
    assert "task:homeassistant" in words                     # only a task the owner approved that names it opens it


def test_the_house_page_sets_up_the_ai_phone_step_by_step_and_ticks_what_it_sees():
    """VOI-08: the steps tick themselves where the stack can see them in Home Assistant (the pipeline, the person, the
    signed-in app); the app's own settings are said plainly; the buttons open the exact screen."""
    js = (ROOT / "images/mission-control/web/static/app.js").read_text()
    body = js[js.index("function phoneVoiceSteps(h, ha) {"):js.index("function phoneVoiceHtml(h, ha) {")]
    for seen in ('(h.pipelines || []).includes("Hermes")', '(h.people || []).find((n) => /ai.?phone/i.test(n))', "data-phvoice",
                 '!!(S.phone?.voice?.assistant && S.phone?.voice?.mic && S.phone?.voice?.awake)',
                 '(h.integrations || []).filter((x) => x.domain === "mobile_app")', 'link("People", "Open People")',
                 "play.google.com/store/apps/details?id=io.homeassistant.companion.android", "#/chat?c=voicechat"):
        assert seen in body or seen in js, seen
    assert '${h.connected ? phoneVoiceHtml(h, ha) : ""}' in js


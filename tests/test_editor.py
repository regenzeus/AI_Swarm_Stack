"""ops/editor.py: the Editor sorts the stack's open ideas (DEC-47, AI change requests step 2, ACR-02). It changes nothing:
its sorting is saved on its card and shown on each idea and the Ideas view."""
import pysrc
import json
import types
from pathlib import Path

import crew as CR
import editor as ED

ROOT = Path(__file__).resolve().parent.parent
IDEAS = [{"id": 16, "owner": "doctor", "state": "open", "title": "Exempt no-argument tools", "body": "obs_core.py:301", "evidence": 8},
         {"id": 626, "owner": "doctor", "state": "open", "title": "A floor for the token spike", "body": "judge()", "evidence": 1},
         {"id": 1, "owner": "self-review", "state": "open", "title": "Tests for builder states", "body": "builds.py", "evidence": 1},
         {"id": 30, "owner": "tests", "state": "open", "title": "Tests for missions.py", "body": "missions.py", "evidence": 2}]
ANSWER = {"ideas": [{"id": 16, "verdict": "in", "request": "Health alerts you can trust", "reason": "obs_core.py:301 still has the tuple"},
                    {"id": 626, "verdict": "in", "request": "Health alerts you can trust", "reason": "judge() has no floor"},
                    {"id": 1, "verdict": "held", "reason": "waits for the split of missions.py (PLT-25)"},
                    {"id": 99, "verdict": "in", "request": "Not an open idea", "reason": "x"},                # no such open idea
                    {"id": 30, "verdict": "maybe", "reason": "not one of the four"}],                          # refused
          "requests": [{"title": "Health alerts you can trust", "why": "false alarms cost runs and questions"}]}


def test_the_editor_keeps_only_verdicts_it_can_check_and_groups_requests():
    v, reqs, missing = ED.verdicts_of(ANSWER, IDEAS)
    assert sorted(v) == ["1", "16", "626"] and v["16"]["request"] == "Health alerts you can trust" and v["1"]["verdict"] == "held"
    assert reqs == [{"title": "Health alerts you can trust", "why": "false alarms cost runs and questions", "ideas": [16, 626]}]
    assert missing == [30]                                             # an idea left out or wrongly sorted is listed, not guessed
    assert ED.verdicts_of({"ideas": [{"id": 16, "verdict": "in", "reason": "r"}]}, IDEAS)[0] == {}          # "in" needs its request's title


def test_the_editor_s_context_holds_the_ideas_the_owner_s_reasons_and_planned_work(tmp_path):
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements/platform.yaml").write_text("area: Platform\nprefix: PLT\nitems:\n  - {id: PLT-25, title: No source file over 1500 lines, status: partial, gap: server.py waits}\n"
                                                          "  - {id: PLT-01, title: Done thing, status: implemented}\n")
    (tmp_path / "requirements/decisions.yaml").write_text("area: Decisions\nprefix: DEC\nitems:\n  - {id: DEC-47, title: Ideas become AI change requests}\n")
    recent = [{"id": 11, "state": "declined", "title": "Tests for missions.py handle_stack", "decision": {"reason": "not now"}}]
    ctx = ED.context(IDEAS, recent, tmp_path)
    assert "## Idea #16 · by doctor · open · seen 8 time(s)" in ctx and "- #11 declined: not now: Tests for missions.py handle_stack" in ctx
    assert "- PLT-25 (partial): No source file over 1500 lines. Still open: server.py waits" in ctx and "PLT-01" not in ctx
    assert "- DEC-47: Ideas become AI change requests" in ctx


def test_a_pass_saves_its_sorting_and_changes_nothing(tmp_path, monkeypatch):
    saved = {}
    ED.C = types.SimpleNamespace(save=lambda aid, **kw: saved.update(kw), agent_file=lambda aid: {}, json_in=CR.json_in, STACK=tmp_path)
    (tmp_path / "requirements").mkdir()
    monkeypatch.setattr(ED, "board", lambda send=None: (IDEAS, []))
    asked = []
    monkeypatch.setattr(ED, "ask", lambda ideas, ctx: asked.append(ctx) or (5, "done", json.dumps(ANSWER), ideas))
    assert ED.run(None) == 3
    assert saved["result"] == "4 ideas: 2 into 1 request, 1 held, 0 covered, 0 dropped, 1 not sorted (Claude task #5)"
    assert saved["verdicts"]["626"]["request"] == "Health alerts you can trust" and saved["missing"] == [30] and asked
    monkeypatch.setattr(ED, "ask", lambda ideas, ctx: (6, "waiting", "2026-11-09T07:40:00", ideas))
    assert ED.run(None) == 0 and "waits for the Claude usage limit (until 07:40)" in saved["result"]   # the next run reads it


def test_the_editor_is_a_crew_duty_with_its_card_units_and_prompt():
    assert any(c["id"] == "editor" and c["unit"] == "crew-editor" for c in CR.CREW)
    assert "editor\": ED.run" in (ROOT / "ops/crew.py").read_text()
    assert "python3 ops/crew.py editor" in (ROOT / "ops/systemd/crew-editor.service").read_text()
    import n8n_jobs as NJ                                                       # n8n starts it each morning (WFL-09)
    assert NJ.schedule("crew", "editor", NJ.index(ROOT / "n8n/workflows", ROOT / "no-such-folder")) == "daily 07:15"
    cards = {c["id"]: c for c in __import__("yaml").safe_load((ROOT / "config/agents.yaml").read_text())["agents"]}
    assert cards["editor"]["jobs"] == ["crew-editor"] and cards["editor"]["prompts"] == "prompts/editor.md"
    assert any(r.get("baseline") for r in json.loads((ROOT / "prompts/replays.json").read_text())["editor/SORT"])


def test_each_idea_and_the_ideas_view_show_the_editor_s_sorting():
    import webjs
    app, sw = webjs.app_js(), (ROOT / "images/mission-control/web/static/swarm.js").read_text()
    server = pysrc.server()
    assert '(M / "crew" / "editor.json")' in server and '"editor": verdicts.get(str(r["id"]))' in server
    assert "function editorHtml(v)" in app and "[ideaFromHtml(o), editorHtml(o?.editor)]" in app
    assert '<div id="ieditor"></div>' in sw and "The Editor's sorting" in app and "It changes nothing yet" in app
    assert "${editorHtml(o.editor)}" in sw

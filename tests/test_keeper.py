"""The Memory Keeper (MEM-17, MEM-18, MEM-20, MEM-21): its judgement checked before it counts, its automatic changes
only behind its trial and its budget, every change logged and undone, contradictions of the owner's facts settled by
date (DEC-44: the newer holds), wiki disputes worked to an end through the Ledger and a refinement task. Hindsight, the Ledger, the
task intake and the model are fakes; the vault is a temporary folder."""
import json
import time
import types

import pytest

import keeper as K


def F(i, text, date="2026-10-20", end="", type_="world"):
    return {"id": i, "type": type_, "date": date, "end": end, "text": text}


FACTS = [F("a1", "The owner prefers short voice answers without lists."),
         F("a2", "The owner wants the morning briefing at 06:30."),
         F("a3", "The owner wants the morning briefing at 07:15.", "2026-10-21"),
         F("a4", "The owner prefers short voice answers without lists.", "2026-10-22"),
         F("a5", "Der Nutzer kauft zuerst bei Amazon.de.", "2026-10-22"),
         F("a6", "The Health doctor run failed with a RuntimeError.", "2026-10-23", type_="experience"),
         F("a7", "The sale runs now and ends on October 5, 2026.", "2026-10-24", type_="experience"),
         F("a8", "For spoken replies the user wants short answers and no lists.", "2026-10-25"),
         F("a9", "The owner is called the owner.", "2026-10-25")]


def ask_model(findings):
    return lambda prompt: {"findings": findings}


@pytest.fixture
def keeper(tmp_path, monkeypatch):
    monkeypatch.setattr(K, "LOG", tmp_path / "keeper.jsonl")
    monkeypatch.setattr(K, "TRIAL", tmp_path / "trial.json")
    return K


def test_the_judgement_is_checked_before_it_counts_and_the_older_fact_stays(keeper):
    found = keeper.classify(FACTS, ask_model([
        {"id": "a1", "class": "duplicate", "of": "a8", "why": "same preference"},            # the newer one goes, not a1
        {"id": "a3", "class": "contradiction", "of": "a2", "why": "two times"},
        {"id": "a5", "class": "not_english", "text": "The user shops at Amazon.de first.", "why": "German"},
        {"id": "a6", "class": "agent_run", "why": "an agent's run"},
        {"id": "a7", "class": "passing_state", "end": "2026-10-05", "why": "the sale ended"},  # it may end before it was stored
        {"id": "a9", "class": "not_english", "text": "Der Besitzer heißt the owner.", "why": "x"},   # a "translation" not in English
        {"id": "zz", "class": "test_noise", "why": "no such fact"},
        {"id": "a2", "class": "passing_state", "end": "2099-01-01", "why": "in the future"}]))
    by = {x["id"]: x for x in found}
    assert by["a4"] == {"id": "a4", "class": "duplicate", "of": "a1", "why": "the same words as an older fact"}   # no model needed
    assert by["a8"]["class"] == "duplicate" and by["a8"]["of"] == "a1"     # swapped: the older a1 stays (KNW-08)
    assert by["a2"]["class"] == "superseded" and by["a2"]["end"] == "2026-10-21" and by["a2"]["of"] == "a3"   # DEC-44: the newer holds
    assert "a3" not in by and by["a5"]["text"] == "The user shops at Amazon.de first."
    assert by["a7"]["end"] == "2026-10-05" and "a9" not in by and "zz" not in by
    # "at 06:30" and "at 07:15" are two facts: numbers are words too (the trial caught this on 2 Nov)
    assert not any(x["id"] in ("a2", "a3") and x["class"] == "duplicate" for x in found)


def test_nothing_is_changed_while_the_trial_has_not_passed_three_times_on_the_current_prompt(keeper):
    assert keeper.gate() == (False, "the memory trial has 0 of 3 runs on the current " + K.KEEPER.ref + ": every finding is a suggestion")
    run = {"at": "2026-11-02T08:00", "prompt": K.KEEPER.ref, "precision": 1.0, "recall": 0.9}
    keeper.TRIAL.write_text(json.dumps({"runs": [run, run]}))
    assert not keeper.gate()[0]
    keeper.TRIAL.write_text(json.dumps({"runs": [run, run, {**run, "precision": 0.9}]}))
    assert "worst of 3 runs scored precision 0.9" in keeper.gate()[1]          # one true fact touched closes it
    keeper.TRIAL.write_text(json.dumps({"runs": [run, run, run]}))
    assert keeper.gate()[0]
    keeper.TRIAL.write_text(json.dumps({"runs": [{**run, "prompt": "memory/KEEPER_FACTS@old"}] * 3}))
    assert not keeper.gate()[0]                                               # a changed prompt runs the trial again
    found = [{"id": "a6", "class": "agent_run", "why": "x"}, {"id": "a3", "class": "contradiction", "of": "a2", "why": "y"},
             {"id": "a5", "class": "not_english", "text": "t", "why": "z"}]
    assert keeper.plan(found, False) == ([], found)                           # gate closed: all suggestions
    auto, sug = keeper.plan(found, True, budget=1)
    assert [x["id"] for x in auto] == ["a6"] and [x["id"] for x in sug] == ["a3", "a5"]   # a raw "contradiction" is not a change: classify() dates it


def test_each_change_is_logged_with_what_was_there_and_undone(keeper):
    sent = []
    send = lambda ops: sent.append(ops) or [True] * len(ops)                  # noqa: E731
    auto = [{"id": "a6", "class": "agent_run", "why": "an agent's run"},
            {"id": "a5", "class": "not_english", "text": "The user shops at Amazon.de first.", "why": "German"},
            {"id": "a7", "class": "passing_state", "end": "2026-10-05", "why": "ended"}]
    done = keeper.apply(auto, FACTS, send=send)
    assert sent[0] == [("a6", {"state": "invalidated", "reason": "Memory Keeper: agent run: an agent's run"}),
                       ("a5", {"text": "The user shops at Amazon.de first."}), ("a7", {"occurred_end": "2026-10-05"})]
    log = keeper.changes()
    assert [e["target"] for e in log] == ["a6", "a5", "a7"] and log[1]["before"] == {"text": "Der Nutzer kauft zuerst bei Amazon.de."}
    keeper.undo(done[1]["id"], send=send)
    keeper.undo(done[0]["id"], send=send)
    assert sent[1] == [("a5", {"text": "Der Nutzer kauft zuerst bei Amazon.de."})] and sent[2] == [("a6", {"state": "valid"})]
    assert [e["undone"] for e in keeper.changes()] == [True, True, False]
    with pytest.raises(ValueError, match="already undone"):
        keeper.undo(done[0]["id"], send=send)
    assert keeper.apply(auto, FACTS, send=send, dry=True) and len(keeper.changes()) == 3   # a dry pass changes and logs nothing


def test_the_trial_scores_the_automatic_changes_against_the_answer_key(keeper, tmp_path):
    import yaml
    fx = tmp_path / "memory.yaml"
    fx.write_text(yaml.safe_dump({"facts": [
        {"id": "t1", "date": "2026-10-20", "label": "keep", "text": "The owner likes tea."},
        {"id": "t2", "date": "2026-10-21", "label": "duplicate:t1", "text": "The owner enjoys drinking tea."},
        {"id": "t3", "date": "2026-10-21", "label": "test_noise", "text": "test 123 please ignore"},
        {"id": "t4", "date": "2026-10-22", "label": "contradiction:t5", "text": "The owner wants the briefing at 06:30."},
        {"id": "t5", "date": "2026-10-22", "label": "keep", "text": "The owner wants the briefing at 07:00."}]}))
    good = ask_model([{"id": "t2", "class": "duplicate", "of": "t1", "why": "tea"}, {"id": "t3", "class": "test_noise", "why": "a test"},
                      {"id": "t4", "class": "contradiction", "of": "t5", "why": "two times"}])
    r = keeper.trial(good, fixture=fx, out=keeper.TRIAL)
    assert (r["precision"], r["recall"], r["contradictions_settled"]) == (1.0, 1.0, ["t4"])
    bad = ask_model([{"id": "t5", "class": "test_noise", "why": "looks odd"}, {"id": "t3", "class": "test_noise", "why": "a test"}])
    r = keeper.trial(bad, fixture=fx, out=keeper.TRIAL)
    assert r["precision"] == 0.5 and r["wrong"][0]["id"] == "t5" and r["missed"] == ["t2"]
    assert len(json.loads(keeper.TRIAL.read_text())["runs"]) == 2 and not keeper.gate()[0]


def test_a_contradiction_on_a_wiki_becomes_a_dispute_a_task_researches_and_its_settling_closes(keeper, tmp_path, monkeypatch):
    import mission_extras as X
    page = {"path": "entities/smartdomo", "title": "SmartDomo", "body": "## Contradictions\n> [!contradiction] EUR 69 ([[a]]); EUR 79 ([[b]])"}
    pages = {"missions/hv/wiki": [page]}
    monkeypatch.setattr(X, "wiki_pages", lambda root: pages[root])
    ledger, calls = {}, []

    def send(op, args, actor):
        calls.append((op, args))
        if op == "find":
            return {"ok": True, "result": [dict(a) for a in ledger.values()]}
        if op == "upsert":
            ledger[args["key"]] = {"id": len(ledger) + 1, "key": args["key"], "state": "draft", "body": args["body"],     # as the Ledger does
                                   "created": NOW - 15 * 86400, "updated": NOW - 15 * 86400}
            return {"ok": True, "result": {"id": len(ledger)}}
        if op == "get":
            return {"ok": True, "result": next(a for a in ledger.values() if a["id"] == args["id"])}
        if op == "transition":
            a = next(a for a in ledger.values() if a["id"] == args["id"])
            a["state"], a["updated"] = args["to"], NOW
            return {"ok": True}
    NOW = time.time()
    made = []
    create = lambda req, c: made.append(req) or 41                            # noqa: E731
    roots = [("missions/hv/wiki", "Voice speaker")]
    first = keeper.disputes(None, roots, send, create, today=NOW - 15 * 86400)   # seen for the first time 15 days ago
    assert first["new"] == 1 and not made
    a = next(iter(ledger.values()))
    assert a["key"].startswith("dispute:missions/hv/wiki:entities/smartdomo:") and a["state"] == "open"
    up = next(x for op, x in calls if op == "upsert")
    assert up["owner"] == "mission" and up["kind"] == "memory_issue"         # the wiki's one writer owns it (MEM-03)
    out = keeper.disputes(None, roots, send, create, today=NOW)
    assert out["tasks"] == [41] and made[0]["wiki"] == {"root": "missions/hv/wiki", "page": "entities/smartdomo"}
    assert "EUR 69 ([[a]]); EUR 79 ([[b]])" in made[0]["text"] and made[0]["source"] == "keeper" and a["state"] == "active"
    assert keeper.disputes(None, roots, send, create, today=NOW)["tasks"] == []   # once
    page["body"] = "## Superseded\n- until 2026-11-02: EUR 79 [[b]]"           # the refinement settled it
    assert keeper.disputes(None, roots, send, create, today=NOW)["settled"] == 1 and a["state"] == "done"


def test_a_dispute_its_research_could_not_settle_stays_marked_on_both_pages(keeper, monkeypatch):
    import mission_extras as X
    page = {"path": "p", "title": "P", "body": "> [!contradiction] x ([[a]]); y ([[b]])"}
    monkeypatch.setattr(X, "wiki_pages", lambda root: [page])
    NOW = time.time()
    key = keeper.dispute_key("missions/m/wiki", "p", page["body"])
    a = {"id": 1, "key": key, "state": "active", "created": NOW - 40 * 86400, "updated": NOW - 15 * 86400}
    moved = []
    send = lambda op, args, actor: ({"ok": True, "result": [a]} if op == "find" else moved.append(args) or {"ok": True})  # noqa: E731
    out = keeper.disputes(None, [("missions/m/wiki", "M")], send, lambda r, c: 1, today=NOW)
    assert out["asked"] == 1 and moved[0]["to"] == "blocked" and "both claims stay marked" in moved[0]["reason"]   # DEC-44: nobody is asked


def test_the_compile_is_told_of_the_disputes_on_the_pages_it_rewrites(tmp_path, monkeypatch):
    import mission_extras as X
    import swarm_client as SW
    monkeypatch.setattr(SW, "wiki_helps", lambda root, title="", send=None: [])
    body = "## Key facts\n- EUR 69 [[a]]\n\n## Contradictions\n> [!contradiction] EUR 69 ([[a]]); EUR 79 ([[b]])"
    monkeypatch.setattr(X, "wiki_pages", lambda root: [{"path": "entities/shop", "title": "Shop", "summary": "", "aliases": [], "body": body, "meta": {}}])
    monkeypatch.setattr(X, "write_index", lambda root, title: None)
    asked = []
    monkeypatch.setattr(X, "M", types.SimpleNamespace(ask_json=lambda p, key, timeout=0: asked.append(p) or {"pages": []}))
    X.compile_into("missions/m/wiki", "M", "missions/m/log/c.md", "Shop: a result", "k")
    assert "open dispute on entities/shop (the Memory Keeper): > [!contradiction] EUR 69" in asked[0]
    assert "moving the claim that no longer holds under Superseded" in asked[0]


def test_the_crew_saves_the_keeper_s_report_and_undoes_a_change_on_the_owner_s_tap(keeper, monkeypatch):
    import crew
    import journal as J
    import librarian as LIB
    saved = {"suggestions": [{"id": "a3", "text": "x", "why": "contradiction of a2: two times", "note": ""},
                             {"id": "a6", "text": "y", "why": "agent run", "note": ""}]}     # Wednesday's judgement
    monkeypatch.setattr(crew, "save", lambda aid, **kw: saved.update(kw))
    monkeypatch.setattr(crew, "agent_file", lambda aid: dict(saved))
    monkeypatch.setattr(J, "curate", lambda: 0)
    monkeypatch.setattr(LIB, "clean_index", lambda: {"before": {"orphaned": 0}, "after": {"orphaned": 0}})
    import memory as MEM
    monkeypatch.setattr(MEM, "measure", lambda sid, now: {"orphaned_share": 0.0})
    monkeypatch.setattr(K, "run_pass", lambda c: {"deep": False, "facts": 9, "gate": {"open": True, "why": "ok"}, "changed": [],
                                                  "suggestions": [], "disputes": {"open": 0, "tasks": [], "settled": 0}})
    crew.M = types.SimpleNamespace(event=lambda *a, **k: None, log=lambda *a: None)
    monkeypatch.setattr(crew, "move_list", lambda: {"moved": 0})
    import memwrite as MW
    monkeypatch.setattr(MW, "LOG", keeper.LOG.with_name("writes.jsonl"))
    keeper.log({"id": "c0", "at": "2026-11-02T08:00:00+01:00", "store": "hindsight", "target": "a6", "class": "agent_run", "fact": "y",
                "before": {"state": "valid"}, "after": {"state": "invalidated"}, "why": "x"})
    crew.memory(None)                                                          # a night without judgement keeps Wednesday's list
    assert [s["id"] for s in saved["suggestions"]] == ["a3"] and saved["keeper"]["gate"]["open"]   # less what it changed since
    saved.clear()
    monkeypatch.setattr(crew, "save", lambda aid, **kw: saved.update(kw))
    monkeypatch.setattr(crew, "agent_file", lambda aid: dict(saved))
    events = []
    crew.M = types.SimpleNamespace(event=lambda *a, **k: events.append(a[2]), log=lambda *a: None)
    sent = []
    monkeypatch.setattr(K, "hindsight", lambda ops: sent.append(ops) or [True] * len(ops))
    e = keeper.apply([{"id": "a6", "class": "agent_run", "why": "an agent's run"}], FACTS, send=K.hindsight)[0]
    saved["keeper"] = {"changes": keeper.changes()}
    r = crew.handle({"action": "crew_memory_undo", "change": e["id"]}, None)
    assert r == {"undone": e["id"], "fact": FACTS[5]["text"]} and sent[-1] == [("a6", {"state": "valid"})]
    assert saved["keeper"]["changes"][0]["undone"] is True and "undone, as you asked" in events[-1]
    crew.M = None


def test_two_owner_facts_that_disagree_the_newer_holds_and_it_can_be_undone(keeper):
    found = keeper.classify(FACTS, ask_model([{"id": "a2", "class": "contradiction", "of": "a3", "why": "two times"}]))
    x = next(f for f in found if f["class"] == "superseded")
    assert (x["id"], x["of"], x["end"]) == ("a2", "a3", "2026-10-21")                       # the older is dated, whichever the model named
    auto, sug = keeper.plan(found, True)
    assert x in auto and not [s for s in sug if s["class"] == "contradiction"]              # DEC-44: automatic, nothing waits for the owner
    sent = []
    send = lambda ops: sent.append(ops) or [True] * len(ops)                  # noqa: E731
    e = keeper.apply([x], FACTS, send=send)[0]
    assert sent[0] == [("a2", {"occurred_end": "2026-10-21"})] and e["before"] == {"occurred_end": ""}
    keeper.undo(e["id"], send=send)
    assert sent[1] == [("a2", {"occurred_end": ""})]


def test_the_move_list_is_applied_by_the_keeper_without_a_tap(tmp_path, monkeypatch):
    import crew
    import memtrials as MT
    moved = []
    lst = tmp_path / "move.json"
    lst.write_text(json.dumps([{"id": "f1", "topic": "Copper"}, {"id": "f2", "topic": "RAM", "kept": True}, {"id": "f3", "topic": "RAM"}]))
    crew.M = types.SimpleNamespace(MOVE_LIST=lst, memory_move=lambda ids, keep: moved.append((ids, keep)) or {"moved": len(ids)})
    monkeypatch.setattr(MT, "gate", lambda now=None: (False, "the coverage trial failed"))
    assert crew.move_list() == {"moved": 0, "waits": "the coverage trial failed"} and not moved
    monkeypatch.setattr(MT, "gate", lambda now=None: (True, "ok"))
    assert crew.move_list() == {"moved": 2} and moved == [(["f1", "f3"], [])]               # what the owner kept stays
    crew.M = None


def test_a_duplicate_that_adds_a_detail_is_merged_into_the_older_and_both_steps_undo(keeper):
    """MEM-50: the owner's voice preference was kept six times, each adding one detail; the older now holds them, the copy goes."""
    fs = [F("v1", "The owner prefers voice answers in two or three short sentences without lists."),
          F("v2", "For the bedroom Echo the owner wants voice answers in 2 or 3 short sentences without Markdown.", "2026-10-23"),
          F("v3", "Voice answers for the owner: two or three short sentences, in English.", "2026-10-24")]
    merged = "For voice, including the bedroom Echo, the owner prefers 2 or 3 short sentences without lists or Markdown."
    found = keeper.classify(fs, ask_model([
        {"id": "v2", "class": "duplicate", "of": "v1", "text": merged, "why": "same preference, adds the Echo"},
        {"id": "v3", "class": "duplicate", "of": "v1", "text": "The owner prefers two or three short English sentences.", "why": "adds English"},
        {"id": "v1", "class": "duplicate", "of": "v2", "text": "Short answers.", "why": "loses the numbers"}]))
    assert found == [{"id": "v2", "class": "duplicate", "why": "same preference, adds the Echo", "merge": merged, "of": "v1"}]   # one merge into v1 a pass
    sent = []
    send = lambda ops: sent.append(ops) or [True] * len(ops)                  # noqa: E731
    done = keeper.apply(found, fs, send=send)
    assert sent[0][0][0] == "v2" and sent[0][0][1]["state"] == "invalidated" and sent[0][1] == ("v1", {"text": merged})
    assert [(e["target"], e["class"]) for e in done] == [("v2", "duplicate"), ("v1", "merged")]
    keeper.undo(done[1]["id"], send=send)
    assert sent[-1] == [("v1", {"text": fs[0]["text"]})]                       # the older's own words come back
    assert not keeper.merge_ok("Short answers.", fs[0]["text"], fs[1]["text"]) and keeper.merge_ok(merged, fs[0]["text"], fs[1]["text"])

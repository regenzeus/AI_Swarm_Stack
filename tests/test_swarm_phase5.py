"""Swarm phase 5, the improvement loop (requirements/swarm.yaml SWM-18, SWM-20, SWM-70, SWM-82, SWM-83, SWM-84):
replay sets from real runs, failure classes, agent changes that ship only after an experiment on the agent's past runs,
a 14-day watch with a one-step revert, the Coach, and the requirements as Ledger artifacts."""
import webjs
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
import yaml

import swarm_client as SW
from ledger import Ledger, Refused, card_hash, classify, gate

ROOT = Path(__file__).resolve().parent.parent
CARDS = [{"id": "doctor", "tools": [], "roles": ["health"], "rooms": ["all", "health"], "contact": ["*"], "model": "claude-subscription",
          "purpose": "The Health doctor.", "responsibilities": ["diagnose health issues"], "owns": {"finding": "resolved"},
          "instructions": ["Cite the log line you saw."]},
         {"id": "coach", "tools": [], "roles": ["reviewers"], "rooms": ["all"], "contact": ["*"], "model": "claude-subscription"}]
DOC, COACH = {"id": "doctor", "cls": "agent"}, {"id": "coach", "cls": "agent"}
OWNER, SYS = {"id": "owner:owner", "cls": "owner"}, {"id": "system", "cls": "system"}
BODY = "The owner declined four of the doctor's ten ideas: detector changes from one sighting. Two sightings first."
CHANGE = {"agent": "doctor", "change": {"instructions": {"add": ["Propose a detector change only after two sightings."]}},
          "target": {"score": "avoids_declined"}, "experiment": {"examples": 10}}


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        self.t += 1
        return self.t


@pytest.fixture
def L(tmp_path):
    return Ledger(str(tmp_path / "s.db"), CARDS, now=Clock(), registry={"rooms": ["all", "health"]})


def change(L, key="coach:doctor:avoids_declined"):
    aid = L.upsert(COACH, f"c:{key}", "agent_change", key, "Coach: doctor, avoids declined", BODY, plan=CHANGE,
                   evidence=[{"text": "scorecard: 4 of 10 ideas declined"}])["id"]
    for to in ("open", "ready"):
        L.transition(COACH, f"c:{key}:{to}", aid, to, "the Coach's claim")
    return aid


# ---------------------------------------------------------------- SWM-70 no agent rewrites itself
def test_no_agent_writes_or_moves_an_agent_change_about_itself(L):
    with pytest.raises(Refused, match="SWM-70"):
        L.upsert(DOC, "self", "agent_change", "doctor:self", "Doctor: more tools", BODY,
                 plan={"agent": "doctor", "change": {"tools": ["fetch"]}, "target": {"score": "valid"}}, evidence=[{"text": "x"}])
    aid = change(L)                                                       # the Coach may write one about the doctor
    with pytest.raises(Refused, match="SWM-70"):
        L.transition(DOC, "dmove", aid, "open", "I disagree")
    with pytest.raises(Refused, match="SWM-70"):
        L.upsert(DOC, "dedit", "agent_change", "coach:doctor:avoids_declined", "Coach: doctor", BODY + " Or not.")
    with pytest.raises(Refused, match="may change only"):
        L.upsert(COACH, "bad", "agent_change", "x", "Coach: doctor's key", BODY, plan={"agent": "doctor", "change": {"key": "vk-main"}})
    with pytest.raises(Refused, match="names the agent"):
        L.upsert(COACH, "ghost", "agent_change", "y", "Coach: nobody", BODY, plan={"agent": "ghost", "change": {}})
    with pytest.raises(Refused, match="SWM-20"):
        L.upsert(DOC, "rq", "requirement", "SWM-01", "One registry", "Every agent has one card.")


def test_a_build_that_changes_an_agent_is_blocked_without_a_passed_agent_change(runner, monkeypatch):
    import builds as B
    assert B.agent_gate({"idea": None}, ["ops/wikis.py"]) is None
    assert "SWM-70" in B.agent_gate({"idea": None}, ["config/agents.yaml", "ops/wikis.py"], send=lambda op, a: None)
    art = {"kind": "agent_change", "state": "active", "version": 3}
    passed = lambda v: (lambda op, a: art if op == "get" else [{"passed": 1, "version": v}])
    assert B.agent_gate({"idea": 7}, ["config/agents.yaml"], send=passed(3)) is None
    assert "no passed experiment for its version 3" in B.agent_gate({"idea": 7}, ["config/agents.yaml"], send=passed(2))
    idea = lambda op, a: {"kind": "idea", "state": "active", "version": 1} if op == "get" else []
    for f in ("ops/keys.sh", "config/hermes/configure-scout.sh", "ops/builds.py"):     # grants, a profile, the builder itself
        assert "SWM-70" in B.agent_gate({"idea": 7}, [f], send=idea)
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    B.table(c)
    c.execute("insert into builds (id, repo, title, description, status, created, updated, attempts, engine) values "
              "(1, 'ai-stack', 'Give the scout a model', 'd', 'review', 't', 't', 0, 'claude')")
    monkeypatch.setattr(B, "one_review", lambda engine, b, path, diff, ok, lens, *a: {"lens": lens, "engine": "hermes", "verdict": "approve",
                                                                                       "summary": "fine", "findings": [], "at": "t"})
    row = c.execute("select * from builds where id=1").fetchone()
    rv = B.ai_review(c, row, Path("."), "diff", True, files=["config/agents.yaml"])
    assert rv["verdict"] == "block" and [r["lens"] for r in rv["reviews"]] == ["requirements", "security", "agents"]
    assert B.ai_review(c, row, Path("."), "diff", True, files=["ops/wikis.py"])["verdict"] == "approve"


# ---------------------------------------------------------------- SWM-18 the gate
def test_an_agent_change_leaves_ready_only_after_a_passed_experiment_and_a_drop_sends_it_back(L):
    aid = change(L)
    with pytest.raises(Refused, match="none has run yet"):
        L.transition(OWNER, "go0", aid, "active", "Build it")
    base = {"valid": 1.0, "keeps_proven": 1.0, "avoids_declined": 0.25}
    r = L.experiment(SYS, "e1", aid, {"version": 1, "examples": 8, "baseline": base,
                                      "candidate": {**base, "avoids_declined": 0.75, "keeps_proven": 0.5}})
    assert not r["passed"] and "keeps_proven 1.00 -> 0.50" in r["why"]
    a = L.get(None, aid)
    assert a["state"] == "open" and any("not passed" in e["text"] and "avoids_declined 0.25 -> 0.75" in e["text"] for e in a["evidence"])
    with pytest.raises(Refused, match="experiments are the runner's"):
        L.experiment(COACH, "e1x", aid, {})
    v = L.upsert(COACH, "c2", "agent_change", "coach:doctor:avoids_declined", "Coach: doctor, avoids declined", BODY + " Keep the accepted.")["version"]
    L.transition(COACH, "c2r", aid, "ready", "refined")
    with pytest.raises(Refused, match="changed since its experiment"):
        L.transition(OWNER, "go1", aid, "active", "Build it")
    r = L.experiment(SYS, "e2", aid, {"version": v, "examples": 3, "baseline": base, "candidate": {**base, "avoids_declined": 1.0}})
    assert not r["passed"] and "only 3 settled" in r["why"] and L.get(None, aid)["state"] == "open"
    L.transition(COACH, "c3r", aid, "ready", "again")
    r = L.experiment(SYS, "e3", aid, {"version": v, "examples": 8, "baseline": base, "candidate": {**base, "avoids_declined": 0.75}})
    assert r["passed"] and L.get(None, aid)["state"] == "ready"
    with pytest.raises(Refused, match="is for owner"):
        L.transition(COACH, "go2", aid, "active", "me")                      # only the owner's Build it ships it
    L.transition(OWNER, "go3", aid, "active", "Build it")
    assert [e["passed"] for e in L.experiments_of(aid)] == [1, 0, 0]
    assert gate({"valid": 1.0}, {"valid": 1.0}, "avoids_declined")[1].startswith("the target score avoids_declined has no replay")
    assert not gate(base, base, "avoids_declined")[0]                        # a target that does not rise is not enough


REFACTORS = {"Refactor the notification helpers into one module": "The notification helpers repeat the same retry loop in three places.",
             "Refactor the build page renderer into small functions": "The build page renderer is one long function mixing markup and state.",
             "Refactor the journal writer for readability": "The journal writer nests five levels of conditionals around file handling."}
FIXES = {"Fix the wiki summary crash on broken front matter": "Pages with broken YAML front matter crash the summary job; later pages are skipped.",
         "Fix the backup retention that removes the newest archive": "Backup retention sorts archives by name, not date, so the newest goes first."}
NO_REFACTOR = "Propose a refactor only when a bug or a measured cost stands behind it."


def history(L, agent="maintainability"):
    """Five ideas of an agent before runs were recorded: the owner declined the three refactors and the two fixes were proved."""
    me = {"id": agent, "cls": "agent"}
    ids = {}
    for n, (t, body) in enumerate({**REFACTORS, **FIXES}.items()):
        ids[t] = L.upsert(me, f"h{n}", "idea", f"{agent}:{n}", t, body, evidence=[{"text": f"signal for: {t}"}])["id"]
        L.transition(me, f"h{n}o", ids[t], "open", "stated")
    for t in REFACTORS:
        L.transition(OWNER, f"d{ids[t]}", ids[t], "declined", "refactor of working, rarely broken code: no bug or real cost behind it")
    for t in FIXES:
        for to, who in (("ready", OWNER), ("active", OWNER), ("checking", SYS), ("done", {"id": "checker", "cls": "checker"})):
            L.transition(who, f"p{ids[t]}{to}", ids[t], to, "built and proved")
    return ids


def replayer(card, text):
    """A stand-in model: it proposes again whatever the replayed input shows, except refactors when its card says not to."""
    import re
    t = re.search(r"signal for: ([^\n\"]+)", text)[1].strip()
    if NO_REFACTOR in text and t.startswith("Refactor"):
        return json.dumps({"ops": [], "summary": "nothing worth it"})
    body = {**REFACTORS, **FIXES}[t]
    return json.dumps({"ops": [{"op": "upsert", "kind": "idea", "key": "k", "title": t, "body": body, "evidence": [{"text": "seen"}]}]})


def test_an_experiment_replays_both_arms_on_the_same_examples_and_ships_only_through_build_it(ledger, runner, monkeypatch, tmp_path):
    import builds as B
    import evals as E
    import improve
    L = ledger.ledger
    monkeypatch.setattr(SW, "limited", lambda engine, now=None: False)
    ids = history(L)
    newest = L.replays("maintainability")[0]                       # its input lists the agent's open work at that time
    assert newest["id"] == f"hist-{max(ids.values())}" and len(newest["inputs"]["pack"]["own_artifacts"]) == 4
    plan = {"agent": "maintainability", "change": {"instructions": {"add": [NO_REFACTOR]}}, "target": {"score": "avoids_declined"}}
    aid = L.upsert(COACH, "mc", "agent_change", "coach:maintainability:avoids_declined", "Coach: maintainability, avoids declined",
                   "The owner declined three of its five ideas: refactors of working code without a bug or a cost.", plan=plan,
                   evidence=[{"text": "scorecard: 3 of 5 declined"}])["id"]
    for to in ("open", "ready"):
        L.transition(COACH, f"mc{to}", aid, to, "claim")
    logged = []
    res = E.run(aid, ask_fn=replayer, phoenix=lambda *a: logged.append(a) or {"dataset": "D1"})
    assert res["passed"] and res["examples"] == 5 and len(logged[0][2]) == 5
    assert res["baseline"]["avoids_declined"] == 0.0 and res["candidate"]["avoids_declined"] == 1.0
    assert res["baseline"]["keeps_proven"] == res["candidate"]["keeps_proven"] == 1.0 and res["candidate"]["valid"] == 1.0
    ex = L.experiments_of(aid)[0]
    assert ex["passed"] == 1 and ex["phoenix"] == {"dataset": "D1"} and L.get(None, aid)["state"] == "ready"
    assert E.due(start=lambda i: pytest.fail("its version has an experiment"), active=lambda: False) is None
    # a candidate that also drops what the owner accepted does not pass
    cand = E.apply_change({"id": "maintainability", "model": "gpt-sub"}, {"instructions": {"add": [NO_REFACTOR]}, "model": "gpt-sub-fast"})
    assert cand["instructions"] == [NO_REFACTOR] and cand["model"] == "gpt-sub-fast"
    b, c, _ = E.evaluate({"id": "m", "arm": "b"}, {"id": "m", "arm": "c"}, E.pick(L.replays("maintainability"), 10), SW.call,
                         ask_fn=lambda card, t: replayer(card, t) if card["arm"] == "b" else '{"ops": []}')      # it proposes nothing at all
    assert c["avoids_declined"] == 1.0 and c["keeps_proven"] == 0.0
    assert gate(b, c, "avoids_declined") == (False, "a score dropped: keeps_proven 1.00 -> 0.00")
    # Build it: a build that edits the card, linked to the change; the change is active
    improve.M, improve.B, B.M = runner, B, runner
    monkeypatch.setattr(B, "repos", lambda: ["ai-stack"])
    db = runner.db()
    B.table(db)
    r = improve.handle({"action": "proposal_accept", "id": aid, "by": "owner"}, db)
    row = db.execute("select * from builds where id=?", (r["build"],)).fetchone()
    assert row["idea"] == aid and json.loads(row["files_plan"]) == ["config/agents.yaml"] and NO_REFACTOR in row["description"]
    assert L.get(None, aid)["state"] == "active" and B.agent_gate(dict(row), ["config/agents.yaml"], send=lambda op, a: SW.call(op, a, "system")["result"]) is None


def test_a_ready_change_without_an_experiment_starts_one_and_an_agent_without_a_model_cannot_be_replayed(ledger, monkeypatch):
    import evals as E
    L = ledger.ledger
    monkeypatch.setattr(SW, "limited", lambda engine, now=None: False)
    aid = L.upsert(COACH, "tc", "agent_change", "coach:tests:valid", "Coach: tests, valid", "The tests agent's proposals keep being refused for "
                   "missing evidence.", plan={"agent": "tests", "change": {"instructions": {"add": ["Cite the test run."]}}, "target": {"score": "valid"}},
                   evidence=[{"text": "3 refused writes"}])["id"]
    for to in ("open", "ready"):
        L.transition(COACH, f"tc{to}", aid, to, "claim")
    started = []
    assert E.due(start=started.append, active=lambda: True) is None and not started        # one experiment at a time
    assert E.due(start=started.append, active=lambda: False) == aid and started == [aid]
    res = E.run(aid, ask_fn=lambda *a: pytest.fail("nothing to replay"))
    assert not res["passed"] and "no model" in res["why"] and L.get(None, aid)["state"] == "open"


# ---------------------------------------------------------------- SWM-82 replay sets
def test_a_finished_run_adds_one_replay_example_with_its_label_and_a_later_decline_updates_it(L, monkeypatch):
    import evals as E
    L.run_start(SYS, "doctor", "crew:doctor:1")
    assert L.context("doctor")["instructions"] == ["Cite the log line you saw."]       # the card's instructions come first
    L.finish({"id": "doctor", "cls": "agent", "via": "runner"}, "f1", "proposed one idea",
             ops=[{"op": "upsert", "kind": "idea", "key": "k1", "title": "Wiki summaries stop at broken front matter", "body": BODY,
                   "evidence": [{"text": "log: yaml error in one page"}]}], run="crew:doctor:1", inputs={"signal": "health issue: wiki-summary failing"})
    assert L.label_runs() == ["crew:doctor:1"]
    ex = L.replays("doctor")
    assert len(ex) == 1 and ex[0]["source"] == "run" and ex[0]["label"] == "pending" and ex[0]["card"] == card_hash(CARDS[0])
    assert ex[0]["inputs"]["signal"].startswith("health issue") and ex[0]["inputs"]["pack"]["instructions"] and ex[0]["inputs"]["tools"] == []
    assert ex[0]["output"]["ops"][0]["title"].startswith("Wiki")
    L.transition(OWNER, "dec", ex[0]["artifacts"][0], "declined", "no evidence: one log line is a guess")
    assert L.label_runs() == ["crew:doctor:1"] and L.label_runs() == []                 # relabelled once, then stable
    ex = L.replays("doctor")[0]
    assert ex["label"] == "declined" and ex["label_reason"].startswith("no evidence") and ex["failure"]["mode"] == "FM-3.2"
    L.run_start(SYS, "doctor", "crew:doctor:2")
    L.now.t += 3 * 3600
    L.label_runs()
    assert {x["id"]: x["label_reason"] for x in L.replays("doctor")}["crew:doctor:2"].startswith("never finished")
    sc = L.scorecard("doctor")
    assert sc["replays"]["labels"] == {"declined": 1, "failed": 1} and sc["failures"]["FC3"] == 1 and sc["failures"]["FC1"] == 1
    sent = []
    monkeypatch.setattr(E, "_px", lambda method, path, body=None: sent.append(body) or {"data": {"dataset_id": "D"}})
    assert E.upload("doctor", L.replays("doctor")) == "D"
    assert sent[0]["action"] == "update" and sent[0]["name"] == "replay-doctor"
    assert sorted(sent[0]["example_ids"]) == ["crew-doctor-1", "crew-doctor-2"] and {m["label"] for m in sent[0]["metadata"]} == {"declined", "failed"}


def test_the_replay_set_is_mirrored_to_phoenix_only_when_it_changed(ledger, monkeypatch):
    import evals as E
    history(ledger.ledger)
    up = []
    monkeypatch.setattr(E, "upload", lambda agent, ex: up.append((agent, len(ex))))
    assert E.sync(every=0) == ["maintainability"] and up == [("maintainability", 5)]
    assert E.sync(every=0) == []                                                         # nothing changed
    assert E.sync(every=600) == []                                                       # and not more often than every 10 minutes


# ---------------------------------------------------------------- SWM-84 failure classes
FIXTURES = [   # (label, the reason its label carries, the MAST failure mode a reader assigns; reasons from the live Ledger where there are any)
    ("declined", "refactor of working, rarely broken code: no bug or real cost behind it", "FM-1.1"),
    ("declined", "low value: notifications work; the duplication costs nothing today", "FM-1.1"),
    ("duplicate", "merged into #17 (same partial-read detector fix)", "FM-1.3"),
    ("declined", "already proposed last week in other words", "FM-1.3"),
    ("failed", "reopened after it shipped: still broken: the alert came back the next day", "FM-3.3"),
    ("declined", "no evidence: one log line is a guess", "FM-3.2"),
    ("declined", "untested: the plan names no test that would show it works", "FM-3.2"),
    ("failed", "never finished (no swarm_finish)", "FM-1.5"),
    ("failed", "left a request unanswered until it expired: can you check the backup log?", "FM-2.5"),
    ("failed", "said it proposed something but wrote nothing", "FM-2.6"),
    ("declined", "too vague: which job, which file?", "FM-2.2"),
    ("declined", "out of scope: the phone is not the doctor's area", "FM-1.2"),
    ("failed", "never finished (no swarm_finish); refused: op 1 (upsert idea k): evidence is empty; a new artifact needs at least one evidence entry", "FM-1.1"),
    ("failed", "Claude usage limit: the answers wait for the next run", "harness"),
    ("failed", "failed: RuntimeError: docker exec timed out", "harness"),
    ("declined", "not needed: nobody uses that page", "FM-2.3"),
    ("declined", "it stops half-done: the migration has no step for the old rows", "FM-3.1"),
    ("failed", "reopened after it shipped: the check failed: CI is red on the same test", "FM-3.3"),
    ("failed", "never finished (no swarm_finish); refused: doctor may not message phone-cleanup (its contact policy, SWM-51)", "FM-1.2"),
    ("declined", "test idea from 'no test mentions this name' only; the tests agent now asks for tests of recently changed code", "FM-1.1"),
    ("declined", "wrong fix: the timeout is in the proxy, not the client", "FM-3.3"),
    ("duplicate", "refused as a copy: similar open artifacts exist: update, merge or link them", "FM-1.3"),
]


def test_labelled_fixture_runs_are_classified_with_at_least_80_percent_agreement():
    got = [(classify(lab, why) or {}).get("mode") for lab, why, _ in FIXTURES]
    agree = sum(g == want for g, (_, _, want) in zip(got, FIXTURES)) / len(FIXTURES)
    assert agree >= 0.8, [(w, g) for g, (_, w, want) in zip(got, FIXTURES) if g != want]
    assert classify("proven", "") is None and classify("declined", "for no reason we know")["category"] == "unclassified"


# ---------------------------------------------------------------- SWM-83 the Coach
def test_a_scorecard_with_40_percent_declined_ideas_yields_one_agent_change_naming_its_target(ledger):
    import coach as CO
    import registry
    cards = {c["id"]: c for c in registry.load()["agents"]}
    sc = {"maintainability": {"ideas": 10, "declined": 4, "decline_reasons": [["refactor of working code", 3]],
                              "failures": {"modes": [["FM-1.1 disobey task specification", 4]], "refused_fc1": 0}},   # declines, not refusals
          "tests": {"ideas": 10, "declined": 6},                  # no model: nothing to replay
          "coach": {"ideas": 10, "declined": 9},                  # never itself (SWM-70)
          "doctor": {"ideas": 10, "declined": 1}}
    f = CO.findings(cards, sc)
    assert [(x["agent"], x["target"]) for x in f] == [("maintainability", "avoids_declined")] and "40%" in f[0]["problem"]
    sc["doctor"]["failures"] = {"refused_fc1": 3}               # three runs whose own writes were refused (FND-34)
    assert [(x["agent"], x["target"]) for x in CO.findings(cards, sc)] == [("doctor", "valid"), ("maintainability", "avoids_declined")]
    L = ledger.ledger
    me = {"id": "maintainability", "cls": "agent"}
    for n, (t, body) in enumerate({**REFACTORS, **FIXES}.items()):
        aid = L.upsert(me, f"i{n}", "idea", f"m:{n}", t, body, evidence=[{"text": "churn"}])["id"]
        L.transition(me, f"i{n}o", aid, "open", "stated")
        if n < 2:
            L.transition(OWNER, f"i{n}d", aid, "declined", "refactor of working, rarely broken code: no bug or real cost behind it")
    asked = []
    draft = lambda p: asked.append(p) or json.dumps({"instructions": [NO_REFACTOR], "why": "the owner declines refactors without a cost"})
    made = CO.coach(ask=draft, run="crew:coach:1")
    assert len(made) == 1 and "refactor of working, rarely broken code" in asked[0]
    a = SW.get(made[0])
    assert (a["kind"], a["state"], a["owner"]) == ("agent_change", "ready", "coach")
    assert a["plan"]["agent"] == "maintainability" and a["plan"]["target"]["score"] == "avoids_declined"
    assert a["plan"]["change"] == {"instructions": {"add": [NO_REFACTOR]}} and a["evidence"][0]["text"].startswith("scorecard: 2 of 5")
    assert CO.coach(ask=draft, run="crew:coach:2") == made                       # next month: the same change, refreshed
    L.transition(OWNER, "no", made[0], "declined", "not now")
    assert CO.coach(ask=draft, run="crew:coach:3") == []                         # the owner's no stands


# ---------------------------------------------------------------- SWM-18 the watch and the revert
def test_a_shipped_agent_change_is_watched_and_a_drop_reopens_it_with_the_revert():
    import checker as CK
    now = 1_800_000_000
    ship = now - 5 * 86400
    ch = {"id": 9, "version": 2, "state": "checking", "state_since": ship, "builds": ["41"],
          "plan": {"agent": "doctor", "target": {"score": "avoids_declined"}}}
    runs = ([{"source": "run", "ts": ship - d * 86400, "label": "proven"} for d in (1, 2, 3, 4)]
            + [{"source": "run", "ts": ship + d * 3600, "label": "declined"} for d in (1, 2, 3)])
    calls = []

    def send(op, args, actor, **k):
        calls.append((op, args, actor))
        return {"ok": True, "result": {"agent_changes": [ch], "replays": runs}.get(op, {})}
    out = CK.watch_changes(send, now)
    assert len(out) == 1 and "revert build #41 in one tap" in out[0] and "1.00 -> 0.00" in out[0]
    assert [(a["to"], who) for op, a, who in calls if op == "transition"] == [("open", "checker")]
    calls.clear()
    runs[4:] = [{**r, "label": "proven"} for r in runs[4:]]
    assert CK.watch_changes(send, now) == [] and not [c for c in calls if c[0] == "transition"]      # holding, still watched
    ch["state_since"] = now - 15 * 86400
    assert CK.watch_changes(send, now) == [] and [a["to"] for op, a, _ in calls if op == "transition"] == ["done"]


def test_a_deployed_build_is_reverted_in_one_step_through_the_merge_queue(runner, monkeypatch):
    import builds as B
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    B.table(c)
    for bid, st in ((1, "deployed"), (2, "review")):
        c.execute("insert into builds (id, repo, title, description, status, created, updated, attempts, engine, merged, idea) values "
                  "(?, 'ai-stack', 't', 'd', ?, 't', 't', 0, 'claude', 'abc123', 5)", (bid, st))
    assert B.handle({"action": "build_revert", "id": 1}, c) == {"reverting": True}
    with pytest.raises(ValueError, match="only a deployed"):
        B.handle({"action": "build_revert", "id": 2}, c)
    spawned = []
    monkeypatch.setattr(B, "spawn", lambda b, slot, kind: spawned.append((b["id"], kind)))
    monkeypatch.setattr(B, "promote", lambda c: None)
    B.dispatch(c)
    assert spawned[0] == (1, "deploy") and "reverted" in B.ENDED


# ---------------------------------------------------------------- SWM-20 requirements in the Ledger
def write_reqs(root, status2="planned", finding=None):
    (root / "requirements").mkdir(exist_ok=True)
    (root / "requirements" / "t.yaml").write_text(yaml.safe_dump({"area": "Test", "prefix": "TST", "items": [
        {"id": "TST-01", "title": "One", "statement": "The one thing shall work.", "status": "implemented", "trace": ["ops/one.py"]},
        {"id": "TST-02", "title": "Two", "statement": "The second thing shall work.", "status": status2}]}))
    (root / "requirements" / "findings.yaml").write_text(yaml.safe_dump({"area": "Findings", "prefix": "FND", "items": [finding] if finding else []}))


def test_a_requirement_file_change_creates_or_updates_its_artifact_and_a_violated_one_is_open(ledger, tmp_path):
    write_reqs(tmp_path)
    assert SW.sync_requirements(root=tmp_path) == {"items": 2, "created": 2, "updated": 0, "moved": 2}
    L = ledger.ledger
    state = lambda: {x["key"]: x["state"] for x in L.find(None, kind="requirement")}
    assert state() == {"TST-01": "done", "TST-02": "ready"}
    assert SW.sync_requirements(root=tmp_path) is None                                  # unchanged files: nothing to do
    write_reqs(tmp_path, "partial", {"id": "FND-01", "title": "One breaks", "status": "open", "affects": ["TST-01"]})
    assert SW.sync_requirements(root=tmp_path) == {"items": 2, "created": 0, "updated": 2, "moved": 2}
    assert state() == {"TST-01": "open", "TST-02": "open"}
    (tmp_path / "requirements" / "t.yaml").write_text((tmp_path / "requirements" / "t.yaml").read_text().replace("title: Two", "title: Two again"))
    assert SW.sync_requirements(root=tmp_path) == {"items": 2, "created": 0, "updated": 1, "moved": 0}     # FND-35: the unchanged one is no news
    one = L.get(None, L.find(None, kind="requirement", key="TST-01")[0]["id"])
    assert one["evidence"][-1]["text"] == "violated by FND-01 (open finding)"
    evs = L.events_since(0, 1000)
    lines = [SW.line_of(e) for e in evs if e.get("akind") == "requirement"]
    assert [x for x in lines if x] and all("reopened" in x or "opened" in x for x in lines if x)     # only a violation is news
    assert SW.requirements_of(["ops/one.py"], root=tmp_path) == ["TST-01"]
    # once requirements are in the Ledger, an agent's idea names the ones it serves before it is ready
    me = {"id": "doctor", "cls": "agent"}
    aid = L.upsert(me, "r1", "idea", "rq:1", "Make the one thing work again", "The one thing fails since Tuesday: the parser drops the last line.",
                   plan={"files": ["ops/one.py"], "test": "tests/test_one.py"}, evidence=[{"text": "a"}, {"text": "b"}], confidence="high",
                   check={"type": "ci_green", "repo": "ai-stack"})["id"]
    L.transition(me, "r1o", aid, "open", "stated")
    with pytest.raises(Refused, match="the requirements it serves"):
        L.transition(me, "r1r", aid, "ready", "claim")
    L.upsert(me, "r2", "idea", "rq:1", "Make the one thing work again", plan={"files": ["ops/one.py"], "test": "tests/test_one.py",
                                                                              "requirements": ["TST-01"]})
    assert L.transition(me, "r2r", aid, "ready", "claim")["to"] == "ready"


def test_the_swarm_tabs_that_read_the_state_draw_again_when_it_first_arrives():
    js = webjs.app_js()
    body = js[js.index("function onState(s)"):][:1500]
    assert 'if (first && ["ideas", "agents"].includes(route.name)) return render(true);' in body   # FND-36: Ideas and Agents read S
    sw = (ROOT / "images/mission-control/web/static/swarm.js").read_text()
    assert 'swIdeas($("#swideas"));' in sw and "let swTab" in sw


def test_standing_instructions_reach_every_harness_and_the_registry_checks_them(tmp_path):
    send = lambda op, a, actor: {"ok": True, "result": {"instructions": ["Cite the log line you saw."]}}
    assert "Your standing instructions (from your card; follow them):\n- Cite the log line you saw." in SW.lessons_text("doctor", send=send)
    import registry
    (tmp_path / "config").mkdir()
    (tmp_path / "ops").mkdir()
    shutil.copy(ROOT / "ops/keys.sh", tmp_path / "ops/keys.sh")
    shutil.copytree(ROOT / "ops/systemd", tmp_path / "ops/systemd")
    reg = yaml.safe_load((ROOT / "config/agents.yaml").read_text())
    next(c for c in reg["agents"] if c["id"] == "doctor")["instructions"] = ["ok", 3]
    (tmp_path / "config/agents.yaml").write_text(yaml.safe_dump(reg))
    assert any("instructions must be a list" in p for p in registry.check(tmp_path))
    assert registry.check(ROOT) == []                                                     # the repo's cards, the Coach's too

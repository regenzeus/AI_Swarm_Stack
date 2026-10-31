"""ops/swarm_client.py: the one-way migration of the old ideas table, the app's view, Pause, the activity feed and the outbox
(SWM-35, SWM-26, SWM-72, SWM-78)."""
import json
import sqlite3

import swarm
import swarm_client as SC

CARDS = [{"id": i, "harness": "python", "key": "none", "tools": []} for i in ("self-review", "doctor", "maintainability", "tests")]
ROWS = [  # id, status, source, reason, build_id, title, description
    (1, "accepted", "self-review", None, 2, "Complete the new-PC setup documentation", "Write the missing steps for a new PC setup."),
    (2, "dismissed", "maintainability", "refactor of working code: no bug behind it", None, "Split handle() into functions", "handle() is long."),
    (3, "dismissed", "doctor", "merged into #5 (same partial-read detector fix)", None, "Stop flagging partial-read on fetch pagination notices",
     "The partial-read detector flags fetch pagination notices although the next page was read."),
    (4, "dismissed", "doctor", "already done by hand on 29 Oct: the backup skips phone/home", None, "Exclude phone/home from the backup rsync",
     "The nightly backup rsync fails on the unreadable phone home folder."),
    (5, "proposed", "doctor", None, None, "Make partial-read fire only on real, unfollowed fetch pagination cut-offs",
     "The partial-read detector flags fetch pagination notices and cut-offs that the agent followed."),
    (6, "dismissed", "self-review", "stale: not built within 30 days", None, "Refresh the digest lock", "Pinned digests are old; refresh the lock."),
    (7, "dismissed", "doctor", "the health issue it was for is gone (fixed or cleared)", None, "Close usage-limit runs as limit", "Runs stalled at the usage limit."),
]


def missions_db(tmp_path):
    p = tmp_path / "missions.sqlite"
    c = sqlite3.connect(p)
    c.execute("create table proposals (id integer primary key, created text, title text, why text, signal text, area text, size text, "
              "description text, status text, build_id integer, reason text, updated text, source text, covers text)")
    for i, st, src, reason, build, title, desc in ROWS:
        c.execute("insert into proposals values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (i, "2026-10-29", title, "why " + title, "signal " + title, "ops", "small", desc, st, build, reason, "2026-10-29", src, None))
    c.commit()
    return p


def wire(tmp_path, monkeypatch):
    (tmp_path / "swarm").mkdir()
    svc = swarm.Service(tmp_path / "swarm", CARDS, {"agents": {}, "runner": swarm.sha("tok")})
    monkeypatch.setattr(SC, "STATE", tmp_path / "state")
    monkeypatch.setattr(SC, "REPORT", tmp_path / "public/swarm.json")
    monkeypatch.setattr(SC, "EVENTS", tmp_path / "events.jsonl")

    def send(op, args, actor, by="", run=""):
        h = {"authorization": "Bearer tok", "x-swarm-actor": actor, "x-swarm-by": by}
        return svc.answer(lambda: svc.actor_for_runner(h), op, args)
    return svc, send


def test_the_migration_imports_ideas_and_the_owners_decisions(tmp_path, monkeypatch):
    svc, send = wire(tmp_path, monkeypatch)
    db = missions_db(tmp_path)
    rep = SC.migrate(db, send)
    L = svc.ledger
    st = {r["key"]: (r["state"], r["owner"]) for r in L.db.execute("select key, state, owner from artifacts")}
    # proposal 1 was accepted with build 2: active (this test DB has no builds table, so it stays there)
    assert st == {"proposal:1": ("active", "self-review"), "proposal:2": ("declined", "maintainability"), "proposal:3": ("merged", "doctor"),
                  "proposal:4": ("gone", "doctor"), "proposal:5": ("open", "doctor"), "proposal:6": ("open", "self-review"),
                  "proposal:7": ("gone", "doctor")}
    lessons = L.context("maintainability")["lessons"]
    assert lessons[0]["reason"] == "refactor of working code: no bug behind it"          # the owner's reason reaches the agent
    a5 = L.get(None, L.db.execute("select id from artifacts where key='proposal:5'").fetchone()[0])
    assert any("signal Stop flagging" in e["text"] for e in a5["evidence"])                  # merged evidence moved along
    events = L.db.execute("select count(*) from events").fetchone()[0]
    SC.migrate(db, send)
    assert L.db.execute("select count(*) from events").fetchone()[0] == events               # a second run changes nothing
    assert rep["mirrored"] == 7 and rep["stale_closures_kept_open"] == ["6"]
    pub = json.loads((tmp_path / "public/swarm.json").read_text())                          # the app's view (S.swarm)
    assert pub["paused"] == [] and sorted(x["key"] for x in pub["board"]["open"]) == ["proposal:5", "proposal:6"]
    top = next(x for x in pub["board"]["open"] if x["key"] == "proposal:5")
    assert top["merged_from"] == 1 and top["priority"] > next(x for x in pub["board"]["open"] if x["key"] == "proposal:6")["priority"]
    assert {x["key"] for x in pub["board"]["recent"]} >= {"proposal:2", "proposal:3"} and pub["stats"]["by_owner"]["doctor"]["gone"] == 2
    assert pub["stats"]["by_state"]["merged"] == 1 and SC.state()["swarm"]["stats"]["artifacts"] == 7
    assert set(pub["cards"]) == {"self-review", "doctor", "maintainability", "tests"}       # the agents Pause applies to


def test_the_owner_pauses_and_resumes_agents_from_the_app(tmp_path, monkeypatch):
    svc, send = wire(tmp_path, monkeypatch)
    monkeypatch.setattr(SC, "call", send)
    assert SC.handle({"action": "swarm_pause", "agent": "doctor", "on": True, "by": "owner"}) == {"agent": "doctor", "paused": True}
    assert SC.paused("doctor") and not SC.paused("tests")
    assert svc.answer(lambda: svc.actor_for_runner({"authorization": "Bearer tok", "x-swarm-actor": "doctor"}), "upsert",
                      {"idem": "x", "kind": "idea", "key": "k", "title": "A new idea title"})["refused"].startswith("agent doctor is paused")
    SC.handle({"action": "swarm_pause", "agent": "*", "on": True})
    assert SC.paused("tests")                                  # pause all
    SC.handle({"action": "swarm_pause", "agent": "*", "on": False})
    SC.handle({"action": "swarm_pause", "agent": "doctor", "on": False})
    assert not SC.paused("doctor")
    try:
        SC.handle({"action": "swarm_pause", "agent": "nobody"})
        raise AssertionError("an unknown agent must be refused")
    except ValueError as e:
        assert "no such agent" in str(e)


def test_the_migration_report_names_what_the_guard_would_have_refused(tmp_path, monkeypatch):
    svc, send = wire(tmp_path, monkeypatch)
    rep = SC.migrate(missions_db(tmp_path), send)
    assert rep["guard_would_refuse"]["5"] == ["3"]             # #5 restates #3: the guard would have sent it to update #3
    assert rep["owner_merges"] == ["3->5"] and rep["duplicates_caught"] == ["3->5"] and rep["duplicates_missed"] == []


def test_writes_wait_in_the_outbox_while_the_service_is_down(tmp_path, monkeypatch):
    monkeypatch.setattr(SC, "STATE", tmp_path / "state")
    monkeypatch.setattr(SC, "SOCK", tmp_path / "no.sock")
    r = SC.call("upsert", {"idem": "a", "kind": "idea", "key": "k", "title": "t"}, "doctor")
    SC.call("transition", {"idem": "b", "id": 1, "to": "open", "reason": "r"}, "doctor")
    assert r == {"ok": False, "queued": True}
    assert len((tmp_path / "state/outbox.jsonl").read_text().splitlines()) == 2
    try:
        SC.call("find", {"text": "x"}, "doctor")              # a read is not queued: it fails
        raise AssertionError("a read must not be queued")
    except SC.Down:
        pass
    sent = []
    monkeypatch.setattr(SC, "_post", lambda op, args, actor, by="", run="": sent.append((op, args["idem"])) or {"ok": True})
    assert SC.flush() == 2 and sent == [("upsert", "a"), ("transition", "b")]                 # in order
    assert (tmp_path / "state/outbox.jsonl").read_text() == ""


def test_ledger_changes_reach_the_activity_feed_once(tmp_path, monkeypatch):
    svc, send = wire(tmp_path, monkeypatch)
    monkeypatch.setattr(SC, "call", send)
    SC.migrate(missions_db(tmp_path), send)
    assert SC.feed() == 0                                        # the first run starts at the end: the import is not news
    new, _ = SC.propose("doctor", [{"title": "Retry a timed-out fetch once in the scout", "covers": ["runtime:Scout:tool-error"],
                                    "description": "The scout swallows fetch timeouts; retry once, with a test."}], "health doctor")
    aid = svc.ledger.db.execute("select id from artifacts where key='health:runtime:Scout:tool-error'").fetchone()[0]
    SC.dismiss(aid, "fetch timeouts are the site's problem", by="owner")
    assert new == 1 and SC.feed() == 2                           # proposed (with its evidence and opening), declined
    lines = [json.loads(x) for x in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [x["kind"] for x in lines] == ["swarm"] * 2 and lines[0]["text"].startswith("doctor proposed idea #")
    assert lines[-1]["text"].endswith("declined idea #%d Retry a timed-out fetch once in the scout: fetch timeouts are the site's problem" % aid)
    assert lines[-1]["text"].startswith("you declined")          # the owner is "you" in his own feed
    assert SC.feed() == 0                                        # each event once
    private = svc.ledger.upsert({"id": "system", "cls": "system"}, "p", "finding", "vault:x", "Insurance letter", "private details", label="private")["id"]
    SC.feed()
    assert "(private)" in (tmp_path / "events.jsonl").read_text().splitlines()[-1] and str(private) in (tmp_path / "events.jsonl").read_text()


def test_the_sync_survives_a_restarting_service(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(SC, "STATE", tmp_path / "state")
    monkeypatch.setattr(SC, "SOCK", tmp_path / "no.sock")
    monkeypatch.setattr(SC, "REPORT", tmp_path / "swarm.json")
    assert SC.main(["swarm_client.py", "feed"]) == 0 and "not reachable" in capsys.readouterr().out


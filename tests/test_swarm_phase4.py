"""Swarm phase 4 (requirements/swarm.yaml SWM-91 to SWM-99 and the gaps closed with them): the task graph, file leases,
the merge queue, the code-graph context, two reviewers, proven requirements, who works now, requests in Needs you,
flow metrics, proposals that become operations, the run contract, A2A cards, wakes through the Hermes adapter."""
import webjs
import datetime as dt
import json
import sqlite3
import subprocess
import types
from pathlib import Path

import pytest

import swarm_client as SW
from ledger import Ledger, Refused

ROOMS = {"rooms": ["all", "health", "code"]}
CARDS = [{"id": "doctor", "tools": [], "roles": ["health"], "rooms": ["all", "health"], "contact": ["*"], "purpose": "The Health doctor.",
          "owns": {"finding": "resolved"}, "responsibilities": ["diagnose health issues"]},
         {"id": "planner", "tools": [], "roles": ["code"], "rooms": ["all", "code"], "contact": ["*"]},
         {"id": "builder", "tools": ["graphify"], "roles": ["code"], "rooms": ["all", "code"], "contact": ["*"]},
         {"id": "scout", "tools": ["fetch", "browser"], "roles": ["research"], "rooms": ["all"], "contact": ["*"]}]
DOC, PLANNER, SCOUT = ({"id": i, "cls": "agent"} for i in ("doctor", "planner", "scout"))
OWNER, SYS = {"id": "owner:owner", "cls": "owner"}, {"id": "system", "cls": "system"}
BODY = "The wiki summaries stop when one page has broken front matter, so every summary after it is missing."


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        self.t += 1
        return self.t


@pytest.fixture
def L(tmp_path):
    return Ledger(str(tmp_path / "s.db"), CARDS, now=Clock(), registry=ROOMS)


def active_idea(L, key="k", files=("ops/a.py",)):
    aid = L.upsert(DOC, f"i{key}", "idea", key, f"Idea {key}: wiki summaries", BODY, plan={"files": list(files), "test": "t"},
                   evidence=[{"text": "seen twice"}, {"text": "and again"}], confidence="high",
                   check={"type": "ci_green", "repo": "ai-stack"})["id"]
    for to in ("open", "ready", "active"):
        L.transition(OWNER if to == "active" else DOC, f"{key}{to}", aid, to, "go")
    return aid


THREE = [{"title": "Parser", "body": "split the front matter safely", "files": ["ops/a.py"]},
         {"title": "App", "body": "show the summary", "files": ["images/mission-control/web/static/app.js"]},
         {"title": "Wire them", "body": "use the new parser in the page", "files": ["ops/b.py"], "depends_on": [0, 1]}]


def finish_task(L, tid, n):
    L.transition(SYS, f"a{tid}{n}", tid, "active", "build works")
    L.transition(SYS, f"d{tid}{n}", tid, "done", "build merged")


# ---------------------------------------------------------------- SWM-91 the task graph
def test_an_idea_split_into_three_tasks_offers_two_at_once_and_the_third_after_both(L):
    aid = active_idea(L)
    with pytest.raises(Refused, match="earlier tasks"):
        L.plan(PLANNER, "bad", aid, [{"title": "x", "body": "y", "depends_on": [0]}])
    t1, t2, t3 = L.plan(PLANNER, "p", aid, THREE)["tasks"]
    assert L.plan(PLANNER, "p", aid, THREE)["tasks"] == [t1, t2, t3]               # a retried plan is the same plan
    with pytest.raises(Refused, match="planned already"):
        L.plan(PLANNER, "p2", aid, THREE)
    assert [t["id"] for t in L.offer(SYS)] == [t1, t2]                            # two at once
    assert {x["dst"] for x in L.get(None, t3)["links"] if x["rel"] == "depends_on"} == {t1, t2}
    finish_task(L, t1, 1)
    assert t3 not in [t["id"] for t in L.offer(SYS)]                               # one dependency still open
    finish_task(L, t2, 1)
    assert t3 in [t["id"] for t in L.offer(SYS)]                                   # both merged: offered
    with pytest.raises(Refused, match="only an approved idea"):
        L.plan(PLANNER, "p3", L.upsert(DOC, "j", "idea", "j", "Disks fill up", "The NAS share runs out of space every month: old backups are kept.")["id"], THREE)


def test_the_planner_splits_only_across_areas_and_falls_back_to_one_task():
    import planner as PL
    idea = {"id": 7, "title": "Fix the summaries", "body": "see SWM-90", "plan": {"files": ["ops/wikis.py", "tests/test_wikis.py"]}}
    tasks, how = PL.split(idea, ask=lambda p: pytest.fail("one area needs no model"))
    assert how == "one area" and len(tasks) == 1 and tasks[0]["files"] == ["ops/wikis.py", "tests/test_wikis.py"] and tasks[0]["requirements"] == ["SWM-90"]
    two = {**idea, "plan": {"files": ["ops/wikis.py", "images/mission-control/web/static/app.js"]}}
    answer = json.dumps({"tasks": [{"title": "Runner", "body": "b", "files": ["ops/wikis.py"]},
                                   {"title": "Page", "body": "b", "files": ["images/mission-control/web/static/app.js", "ops/wikis.py"]}]})
    tasks, how = PL.split(two, ask=lambda p: answer)
    assert how == "model" and tasks[1]["depends_on"] == [0]                       # the same file: the later task waits
    assert PL.split(two, ask=lambda p: '{"tasks": [{"title": "x", "files": []}]}')[1].startswith("fallback")
    assert PL.split(two, ask=lambda p: 1 / 0)[1].startswith("fallback: ZeroDivisionError")


# ---------------------------------------------------------------- SWM-92 file leases
def test_leases_keep_tasks_on_the_same_file_apart_and_a_stale_one_expires(L):
    with pytest.raises(Refused, match="runner"):
        L.lease(DOC, "ai-stack", ["ops/a.py"], "build:1")
    assert L.lease(SYS, "ai-stack", ["ops/a.py"], "build:1")["granted"]
    r = L.lease(SYS, "ai-stack", ["ops/a.py"], "build:2")
    assert not r["granted"] and r["held_by"] == [{"holder": "build:1", "path": "ops/a.py"}]
    assert not L.lease(SYS, "ai-stack", ["ops"], "build:2")["granted"]                      # a folder covers its files
    assert not L.lease(SYS, "ai-stack", ["*"], "build:2")["granted"]                        # no files named: the whole repo
    assert L.lease(SYS, "ai-stack", ["images/x/y.py"], "build:3")["granted"]                # disjoint: together
    assert L.lease(SYS, "TestRepo", ["ops/a.py"], "build:4")["granted"]                     # another repo
    assert L.lease(SYS, "ai-stack", ["ops/a.py"], "build:1")["granted"]                     # its own lease is refreshed
    L.now.t += 4 * 3600 + 5
    assert L.lease(SYS, "ai-stack", ["ops/a.py"], "build:2")["granted"]                     # nobody refreshed it: expired
    L.release(SYS, "build:2")
    assert {x["holder"] for x in L.leases()} == set()                                       # build:3's expired too


def test_builds_run_together_only_when_their_files_do_not_overlap(runner, ledger, monkeypatch, tmp_path):
    import builds as B
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    B.table(c)
    t = "2026-10-30T10:00:00+01:00"
    for bid, files, eng in ((1, ["ops/a.py"], "claude"), (2, ["ops/a.py"], "claude"), (3, ["images/x.py"], "claude")):
        c.execute("insert into builds (id, repo, title, description, status, created, updated, attempts, engine, files_plan) values (?,?,?,?,?,?,?,0,?,?)",
                  (bid, "ai-stack", f"b{bid}", "d", "queued", t, t, eng, json.dumps(files)))
    c.commit()
    started = []
    monkeypatch.setattr(B, "_busy", {})
    monkeypatch.setattr(B, "spawn", lambda b, slot, kind: (started.append((b["id"], slot, kind)), B._busy.__setitem__(b["id"], (None, slot, kind))))
    monkeypatch.setattr(B, "SLOTS", 3)
    B.dispatch(c)
    assert [(i, k) for i, _, k in started] == [(1, "run"), (3, "run")]                        # 2 waits for 1's file
    assert "held by build #1" in c.execute("select note from builds where id=2").fetchone()["note"]
    B.put(c, 1, status="deployed")                                                           # build 1 ended: its lease is released
    B._busy.pop(1)
    B.dispatch(c)
    assert started[-1][:1] == (2,) and started[-1][2] == "run"


# ---------------------------------------------------------------- SWM-93 the merge queue
def sh(*a, cwd=None):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_three_approved_builds_land_in_order_and_a_failing_one_is_sent_back(runner, monkeypatch, tmp_path):
    import builds as B
    origin = tmp_path / "origin.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    sh("git", "clone", "-q", str(origin), str(seed))
    (seed / "app.txt").write_text("v1\n")
    sh("git", "add", "-A", cwd=seed); sh("git", "commit", "-qm", "v1", cwd=seed); sh("git", "push", "-q", "origin", "main", cwd=seed)
    base = sh("git", "rev-parse", "HEAD", cwd=seed)
    for n, content in ((1, "ok"), (2, "bad"), (3, "ok")):
        sh("git", "checkout", "-q", "-b", f"builder/{n}-x", base, cwd=seed)
        (seed / f"f{n}.txt").write_text(content + "\n")
        sh("git", "add", "-A", cwd=seed); sh("git", "commit", "-qm", f"build {n}", cwd=seed); sh("git", "push", "-q", "origin", f"builder/{n}-x", cwd=seed)
    live = tmp_path / "live"
    sh("git", "clone", "-q", str(origin), str(live))
    monkeypatch.setattr(B, "WB", tmp_path / "wb")
    monkeypatch.setattr(B, "STACK", live)
    monkeypatch.setattr(B, "origin", lambda repo: str(origin))
    monkeypatch.setattr(B, "run_deploy", lambda old, new: (True, "deployed", False))
    monkeypatch.setattr(B.M, "now", lambda: dt.datetime.now().astimezone())
    monkeypatch.setattr(B.M, "X", types.SimpleNamespace(telegram=lambda *a, **k: None, APP="x"))
    checked = []

    def checks(repo, slot=None, timeout=1800):                   # the combined code: fails when build 2's "bad" file is in it
        tree = B.WB / B.place(repo, slot)
        checked.append(sorted(p.name for p in tree.glob("f*.txt")))
        return "SOME CHECKS FAILED" if any(p.read_text().strip() == "bad" for p in tree.glob("f*.txt")) else "ALL CHECKS PASSED"
    monkeypatch.setattr(B, "sandbox_checks", checks)
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    B.table(c)
    for n in (1, 2, 3):
        c.execute("insert into builds (id, repo, title, status, branch, base, approved_at) values (?, 'ai-stack', ?, 'approved', ?, ?, ?)",
                  (n, f"build {n}", f"builder/{n}-x", base, f"2026-10-30T10:0{4 - n}:00"))  # approved 3, 2, 1 (newest first)
    c.execute("update builds set approved_at='2026-10-30T10:00:00' where id=1")
    c.execute("update builds set approved_at='2026-10-30T10:01:00' where id=2")
    c.execute("update builds set approved_at='2026-10-30T10:02:00' where id=3")
    c.commit()
    order = []
    monkeypatch.setattr(B, "_busy", {})
    monkeypatch.setattr(B, "spawn", lambda b, slot, kind: order.append(b["id"]) if kind == "deploy" else None)
    while True:
        order.clear()
        B.dispatch(c)
        if not order:
            break
        B.deploy(c, c.execute("select * from builds where id=?", (order[0],)).fetchone())
    st = {r["id"]: r for r in c.execute("select * from builds")}
    assert st[1]["status"] == "deployed" and st[3]["status"] == "deployed"
    assert st[2]["status"] == "queued" and "merge queue" in st[2]["feedback"]                # sent back to the builder
    log = sh("git", "log", "--format=%s", "main", cwd=origin).splitlines()
    assert [x for x in log if x.startswith("Merge build")] == ["Merge build #3: build 3", "Merge build #1: build 1"]
    assert checked == [["f1.txt", "f2.txt"], ["f1.txt", "f3.txt"]]                         # 1 landed on its own base; 2 and 3 re-checked


# ---------------------------------------------------------------- SWM-94 the code-graph context
def repo_for_graph(tmp_path):
    root = tmp_path / "repo"
    (root / "ops").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "requirements").mkdir()
    (root / "ops/wikis.py").write_text("def summary():\n    return 1\n")
    (root / "ops/missions.py").write_text("import wikis\n")
    (root / "tests/test_wikis.py").write_text("import wikis\n\ndef test_summary():\n    assert wikis.summary() == 1\n")
    (root / "tests/test_other.py").write_text("def test_nothing():\n    pass\n")
    (root / "requirements/x.yaml").write_text(
        "area: X\nprefix: XX\nitems:\n  - id: XX-01\n    title: summaries\n    statement: The wiki summaries shall be written.\n"
        "    type: functional\n    priority: must\n    status: implemented\n    verify: {method: test, by: ['tests/test_wikis.py::test_summary']}\n"
        "  - id: XX-02\n    title: other\n    statement: Another thing shall hold.\n    type: functional\n    priority: must\n"
        "    status: implemented\n    verify: {method: test, by: ['tests/test_other.py::test_nothing']}\n")
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"nodes": [{"id": "r::w", "repo": "repo", "source_file": "ops/wikis.py"},
                                           {"id": "r::m", "repo": "repo", "source_file": "ops/missions.py"},
                                           {"id": "r::t", "repo": "repo", "source_file": "tests/test_wikis.py"}],
                                 "links": [{"source": "r::m", "target": "r::w", "relation": "calls"},
                                           {"source": "r::t", "target": "r::w", "relation": "imports_from"},
                                           {"source": "r::w", "target": "r::w", "relation": "calls"}]}))
    return root, graph


def test_a_builds_context_pack_lists_callers_tests_and_requirements(tmp_path):
    import codegraph as CG
    root, graph = repo_for_graph(tmp_path)
    p = CG.pack(root, "repo", ["ops/wikis.py"], graph=graph)
    f = p["files"]["ops/wikis.py"]
    assert f["callers"] == ["ops/missions.py", "tests/test_wikis.py"] and f["tests"] == ["tests/test_wikis.py"] and f["requirements"] == ["XX-01"]
    text = CG.text(p)
    assert "used by ops/missions.py" in text and "requirements: XX-01" in text
    js = webjs.app_js()
    assert "/api/build/${b.id}/context" in js and "function blastHtml" in js                 # the review page shows it


# ---------------------------------------------------------------- SWM-96 proven requirements
def test_a_build_naming_a_requirement_without_a_test_it_runs_fails_its_checks(tmp_path):
    import req as R
    root, _ = repo_for_graph(tmp_path)
    for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "base")):
        sh("git", *args, cwd=root)
    base = sh("git", "rev-parse", "HEAD", cwd=root)
    (root / "ops/wikis.py").write_text("def summary():\n    return 2 - 1\n")
    sh("git", "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qam", "Change the summary\n\nRequirements: XX-01", cwd=root)
    assert R.prove(root, base)[2] == []                                                       # XX-01's test imports wikis
    assert any("XX-02" in p and "none of its tests" in p for p in R.prove(root, base, ids=["XX-02"])[2])
    assert any("no such requirement" in p for p in R.prove(root, base, ids=["XX-99"])[2])
    assert any("names no requirement" in p for p in R.prove(root, base, ids=[])[2])


# ---------------------------------------------------------------- SWM-95 two reviewers
def test_a_build_gets_two_lenses_and_one_block_stops_the_deploy(runner, ledger, monkeypatch, tmp_path):
    import builds as B
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    B.table(c)
    aid = ledger.ledger.upsert({"id": "system", "cls": "system"}, "x", "idea", "x", "Fix the summaries", BODY, owner="doctor", guard=False)["id"]
    t = "2026-10-30T10:00:00+01:00"
    c.execute("insert into builds (id, repo, title, description, status, created, updated, attempts, engine, idea, checks, ci) "
              "values (1,'ai-stack','x','something long enough','review',?,?,1,'claude',?,'ALL CHECKS PASSED','success')", (t, t, aid))
    c.commit()
    monkeypatch.setattr(B.M, "now", lambda: dt.datetime.now().astimezone())
    seen = []

    def fake(engine, b, path, diff, ok, lens="requirements", slot=None, context="", reqs=()):
        seen.append((engine, lens))
        return {"engine": engine, "verdict": "block" if lens == "security" else "approve", "summary": f"{lens} look", "findings": [],
                "at": "2026-10-30T10:00:00+01:00"}
    monkeypatch.setattr(B, "review_with", fake)
    r = B.ai_review(c, c.execute("select * from builds").fetchone(), tmp_path, "diff", True, reqs=["SWM-90"])
    assert sorted(seen) == [("hermes", "requirements"), ("hermes", "security")]               # the other engine, two lenses
    assert r["verdict"] == "block" and {x["lens"] for x in r["reviews"]} == {"requirements", "security"}
    with pytest.raises(ValueError, match="reviewer blocked"):
        B.handle({"action": "build_approve", "id": 1}, c)
    B.handle({"action": "build_approve", "id": 1, "override": "the block is about a test fixture, not real code"}, c)
    assert c.execute("select status from builds").fetchone()["status"] == "approved"
    ev = [e["text"] for e in ledger.ledger.get(None, aid)["evidence"]]
    assert any("security lens" in x and "block" in x for x in ev) and any("requirements lens" in x for x in ev)
    assert any("overrode the reviewers' block" in x for x in ev)


# ---------------------------------------------------------------- SWM-91/SWM-93: tasks follow their builds
def test_an_idea_with_tasks_is_shipped_only_when_every_task_is_merged(ledger):
    L = ledger.ledger
    aid = L.upsert({"id": "system", "cls": "system"}, "x", "idea", "x", "Fix the summaries", BODY, owner="doctor", guard=False)["id"]
    for to in ("open", "ready", "active"):
        L.transition({"id": "owner:owner", "cls": "owner"}, f"x{to}", aid, to, "go")
    t1, t2 = L.plan({"id": "planner", "cls": "agent"}, "p", aid, THREE[:2])["tasks"]
    for bid in (11, 12):
        L.add_ref({"id": "owner:owner", "cls": "owner"}, f"r{bid}", aid, "build", str(bid))
    for tid, bid in ((t1, 11), (t2, 12)):
        L.transition({"id": "system", "cls": "system"}, f"act{tid}", tid, "active", "works")
    SW.build_done(11, "deployed", task=t1)
    assert L.get(None, aid)["state"] == "active" and L.get(None, t1)["state"] == "done"
    SW.build_done(12, "deployed", task=t2)
    assert L.get(None, aid)["state"] == "checking"


# ---------------------------------------------------------------- SWM-97 who is working right now
def test_a_running_crew_job_and_a_running_build_show_until_they_end(tmp_path, monkeypatch):
    import runrecord as RR
    monkeypatch.setattr(RR, "DB", tmp_path / "rt.db", raising=False)
    monkeypatch.setattr(RR, "_db", None, raising=False)
    RR.ingest([{"run": "crew:doctor:1", "agent": "crew:doctor", "kind": "start", "title": "Crew · Health doctor", "ts": 1.9e9},
               {"run": "build:7:0:queued", "agent": "builder", "kind": "start", "title": "Build #7: fix", "ts": 1.9e9 + 5},
               {"run": "build:7:0:queued", "agent": "builder", "kind": "llm", "title": "gpt", "ts": 1.9e9 + 9, "tokens": {"in": 1200, "out": 300}}])
    now = {r["run"]: r for r in RR.live_now()}
    assert set(now) == {"crew:doctor:1", "build:7:0:queued"} and now["build:7:0:queued"]["tokens"] == 1500
    assert now["crew:doctor:1"]["started"] == 1.9e9
    RR.ingest([{"run": "crew:doctor:1", "agent": "crew:doctor", "kind": "end", "title": "done", "ts": 1.9e9 + 60, "status": "done"}])
    assert [r["run"] for r in RR.live_now()] == ["build:7:0:queued"]
    js = (Path(__file__).resolve().parent.parent / "images/mission-control/web/static/swarm.js").read_text()
    assert "/api/swarm/now" in js and "async function swNow" in js
    import re
    assert not re.search(r"[^?.\w]S\.(builds|swarm)", js)          # the page draws before the state loads (cold open): S may be null


# ---------------------------------------------------------------- SWM-98 requests to the owner in Needs you
def test_an_agents_request_to_the_owner_waits_in_needs_you_until_he_answers(ledger, monkeypatch):
    L = ledger.ledger
    m = L.send({"id": "doctor", "cls": "agent"}, "q", ["owner"], "request", "May I lower the disk alert to 90 %?")
    assert [x["mid"] for x in SW.publish()["owner_requests"]] == [m["mid"]]
    monkeypatch.setattr(SW, "publish", lambda *a, **k: None)
    SW.handle({"action": "swarm_post", "to": [], "text": "Yes, 90 % is fine.", "reply_to": m["mid"], "by": "owner"})
    monkeypatch.undo()
    assert SW.publish()["owner_requests"] == []
    assert L.db.execute("select state, state_reason from messages where mid=?", (m["mid"],)).fetchone()[0] == "completed"
    root = Path(__file__).resolve().parent.parent
    assert '"owner_requests"' in (root / "ops/decisions.py").read_text()     # the one queue (GEN-02) carries it to Home


# ---------------------------------------------------------------- SWM-99 flow metrics
def test_a_week_of_ledger_events_yields_counts_lead_time_and_tokens_per_proved_idea(tmp_path, monkeypatch):
    clock = Clock(1_799_020_800.0)                     # a Monday 00:00 UTC
    L = Ledger(str(tmp_path / "f.db"), CARDS, now=clock, registry=ROOMS)
    ids = []
    for n in range(3):
        ids.append(L.upsert(SYS, f"c{n}", "idea", f"k{n}", f"Idea {n} about the backup of disks", f"{BODY} {n}" * 2, owner="doctor", guard=False)["id"])
    for n, aid in enumerate(ids[:2]):
        for to in ("open", "ready", "active", "checking"):
            L.transition(SYS if to == "checking" else OWNER, f"{aid}{to}", aid, to, "go")
        clock.t += (n + 1) * 86400                     # proved after one day, then after two more
        L.transition({"id": "checker", "cls": "checker"}, f"{aid}done", aid, "done", "proved")
    w = L.flow(weeks=2)[-1]
    assert (w["proposed"], w["accepted"], w["proved"], w["wip"]) == (3, 2, 2, 0) and w["proved_ids"] == ids[:2]
    assert w["median_days"] == 2.0                      # 1 day and 3 days after the proposal
    db = tmp_path / "m.sqlite"
    c = sqlite3.connect(db)
    c.execute("create table builds (id integer primary key, tokens integer)")
    c.executemany("insert into builds values (?, ?)", [(1, 100_000), (2, 50_000), (3, 70_000)])
    c.commit()
    monkeypatch.setattr(SW, "MISSIONS", db)
    refs = {ids[0]: ["1", "2"], ids[1]: ["3"]}
    got = SW.flow_tokens([w], send=lambda op, a, actor: {"ok": True, "result": {"refs": [{"system": "build", "ref": r} for r in refs[a["id"]]]}})
    assert got[0]["tokens"] == 220_000 and got[0]["tokens_per_proved"] == 110_000


# ---------------------------------------------------------------- SWM-49 a propose becomes an operation when accepted
def test_a_proposal_is_applied_only_when_the_artifacts_owner_accepts(L):
    aid = L.upsert(DOC, "f", "finding", "f1", "Front matter breaks summaries", BODY)["id"]
    with pytest.raises(Refused, match="names its artifact"):
        L.send(SCOUT, "p0", ["agent:doctor"], "propose", "add this", proposal={"op": "evidence", "args": {"text": "x"}})
    m = L.send(SCOUT, "p1", ["agent:doctor"], "propose", "a source for it", artifact_id=aid,
               proposal={"op": "evidence", "args": {"text": "the YAML spec says a colon needs quoting"}})
    with pytest.raises(Refused, match="only its receivers"):
        L.reply_state(PLANNER, "a0", m["mid"], "completed")
    n = len(L.get(None, aid)["evidence"])
    L.reply_state(SCOUT, "a1", m["mid"], "canceled")                                  # an ack or a cancel applies nothing
    assert len(L.get(None, aid)["evidence"]) == n
    m = L.send(SCOUT, "p2", ["agent:doctor"], "propose", "here is the source once more, please take it", artifact_id=aid,
               proposal={"op": "evidence", "args": {"text": "the YAML spec says a colon needs quoting"}})
    L.reply_state(DOC, "a2", m["mid"], "completed", "right")
    ev = L.get(None, aid)["evidence"][-1]
    assert ev["actor"] == "doctor" and "proposed by scout" in ev["text"]
    assert "accepted: evidence applied" in L.db.execute("select state_reason from messages where mid=?", (m["mid"],)).fetchone()[0]


# ---------------------------------------------------------------- SWM-64 the run contract
def test_a_finish_is_checked_first_and_a_run_without_one_is_a_health_note(L, tmp_path):
    L.run_start(SYS, "doctor", "crew:doctor:1")
    with pytest.raises(Refused, match=r"op 1 \(upsert finding f9\): evidence is empty"):
        L.finish(DOC, "f1", "found one", [{"op": "upsert", "kind": "finding", "key": "f9", "title": "A new finding", "body": BODY}])
    assert L.unfinished(older_h=0) and L.db.execute("select count(*) from artifacts").fetchone()[0] == 0   # nothing applied
    L.finish(DOC, "f2", "found one", [{"op": "upsert", "kind": "finding", "key": "f9", "title": "A new finding", "body": BODY,
                                       "evidence": [{"text": "log line 12"}]}])
    assert L.unfinished(older_h=0) == []
    L.run_start(SYS, "scout", "wake:scout:1")
    L.now.t += 7200
    left = L.unfinished()
    assert [u["run"] for u in left] == ["wake:scout:1"]
    import crew as CR
    report = tmp_path / "swarm.json"
    report.write_text(json.dumps({"unfinished": left}))
    items = CR.unfinished_notes([{"kind": "crew", "id": "doctor", "name": "Health doctor", "issues": []}], report=report)
    assert any(i["kind"] == "no-finish" and "wake:scout:1" in i["text"] for it in items for i in it["issues"])


def test_a_finish_is_whole_or_nothing_and_keeps_every_field(L):
    """Review SWM-R6: with op 2 refused, op 1's artifact stayed and the run stayed unfinished; a retry with a new key
    applied op 1 again. finish also dropped send's proposal and label, and more than 20 ops were dropped silently."""
    L.run_start(SYS, "doctor", "crew:doctor:2")
    ok_op = {"op": "upsert", "kind": "finding", "key": "f20", "title": "Backup slow", "body": BODY, "evidence": [{"text": "log line 3"}]}
    with pytest.raises(Refused, match=r"op 2 \(transition\).*nothing of this finish was applied"):
        L.finish(DOC, "w1", "found one", [ok_op, {"op": "transition", "id": 999999, "to": "open", "reason": "x"}])
    assert L.db.execute("select count(*) from artifacts where key='f20'").fetchone()[0] == 0 and L.unfinished(older_h=0)
    L.finish(DOC, "w2", "found one", [ok_op, {"op": "send", "to": ["agent:builder"], "act": "inform", "text": "see the finding",
                                              "label": "private"}])
    assert L.db.execute("select label from messages order by id desc limit 1").fetchone()[0] == "private"
    with pytest.raises(ValueError, match="operations in one finish"):
        L.finish(DOC, "w3", "too much", [ok_op] * 21)


# ---------------------------------------------------------------- SWM-27 A2A agent cards
def test_each_card_is_an_a2a_agent_card_on_the_internal_network(ledger):
    import registry
    for card in registry.load()["agents"]:
        a = ledger.ledger.agent_card(card["id"])
        for k in ("protocolVersion", "name", "description", "version", "url", "capabilities", "defaultInputModes", "defaultOutputModes", "skills"):
            assert a.get(k) not in (None, "", []), (card["id"], k)
        assert a["supportedInterfaces"][0]["url"].startswith("http://swarm:8096/") and all({"id", "name", "description", "tags"} <= set(s) for s in a["skills"])
    compose = (Path(__file__).resolve().parent.parent / "compose/apps.yaml").read_text()
    swarm_block = compose.split("\n  swarm:\n", 1)[1].split("\n  ", 1)[0] + compose.split("\n  swarm:\n", 1)[1][:1500]
    assert "ports:" not in swarm_block.split("\n  # ")[0]                                    # no port published on the host


# ---------------------------------------------------------------- SWM-59 notifications through the one path
def test_a_mention_notifies_the_owner_once_through_the_shared_path(ledger, monkeypatch):
    L = ledger.ledger
    sent = []
    SW.notify_owner(notify=sent.append)                                                      # the first run starts at now
    L.send({"id": "doctor", "cls": "agent"}, "m1", ["owner"], "inform", "The backup failed twice tonight.")
    L.send({"id": "doctor", "cls": "agent"}, "m2", ["room:health"], "inform", "a room message is not a mention")
    assert SW.notify_owner(notify=sent.append) == 1 and "backup failed" in sent[0]
    assert SW.notify_owner(notify=sent.append) == 0                                           # once per item
    src = (Path(__file__).resolve().parent.parent / "ops/swarm_client.py").read_text()
    assert "notify.sh" in src and "api.telegram.org" not in src                              # no Telegram of its own


# ---------------------------------------------------------------- SWM-53, SWM-13, SWM-28: wakes through the adapters
def test_a_wake_waits_out_the_usage_limit_and_a_hermes_agent_gets_one_turn(ledger, monkeypatch):
    L = ledger.ledger
    L.send({"id": "doctor", "cls": "agent"}, "r1", ["agent:scout"], "request", "find the YAML rule for colons")
    turns = []
    assert SW.wake(hermes=lambda a, run: turns.append((a, run)), active=lambda u: False, now=1.9e9, limit=lambda e: e == "chatgpt") == []
    assert SW.wake(hermes=lambda a, run: turns.append((a, run)), active=lambda u: False, now=1.9e9 + 60, limit=lambda e: False) == ["scout"]
    assert turns == [("scout", "wake:scout:1900000060")]                                      # the limit lifted: started, not lost
    assert [r["run"] for r in L.runs_of()] == ["wake:scout:1900000060"]
    svc = ledger                                                                              # the agent finishes through its own door
    svc.tokens["agents"]["scout"] = __import__("swarm").sha("tok-scout")
    svc.by_sha = {v: k for k, v in svc.tokens["agents"].items()}
    r = svc.answer(lambda: svc.agent_from_headers({"x-api-key": "tok-scout"}), "finish", {"idem": "f", "summary": "answered the doctor"})
    assert r["ok"] and L.runs_of()[0]["state"] == "finished"


def test_the_usage_limit_is_read_from_the_runners_real_state(tmp_path, monkeypatch):
    monkeypatch.setattr(SW, "PUBLIC", tmp_path)
    later = (dt.datetime.now().astimezone() + dt.timedelta(hours=1)).isoformat(timespec="seconds")
    (tmp_path / "state.json").write_text(json.dumps({"builds": [{"id": 9, "status": "waiting", "retry_at": later,
                                                                  "error": "Claude usage limit reached; continues by itself at 02:00"}], "queue": []}))
    assert SW.limited("claude") and not SW.limited("chatgpt")                                 # builds is a list in state.json
    (tmp_path / "state.json").write_text(json.dumps({"builds": [], "queue": [{"slug": "ram", "status": "waiting"}]}))
    assert SW.limited("chatgpt") and not SW.limited("claude")


def test_requests_to_agents_that_never_wake_are_answered_at_once(ledger):
    L = ledger.ledger
    m = L.send({"id": "doctor", "cls": "agent"}, "r1", ["agent:tests"], "request", "run the suite again please")
    both = L.send({"id": "doctor", "cls": "agent"}, "r2", ["role:code"], "request", "who can look at the planner?")
    assert SW.decline_unwakeable() == 1
    st = dict(L.db.execute("select mid, state from messages where mid in (?, ?)", (m["mid"], both["mid"])).fetchall())
    assert st[m["mid"]] == "rejected" and st[both["mid"]] == "submitted"                    # the builder can still answer that one


def test_a_woken_crew_agent_answers_its_requests_with_its_model(ledger, runner, monkeypatch):
    import crew as CR
    L = ledger.ledger
    m = L.send({"id": "checker", "cls": "checker"}, "r1", ["agent:doctor"], "request", "why does the disk alert flap?")
    prompts = []

    def ask(prompt, name):
        prompts.append(prompt)
        return json.dumps({"replies": [{"mid": m["mid"], "text": "It flaps at 89-91 %: the threshold has no hysteresis.", "state": "completed"}]})
    assert CR.answer_requests("doctor", "crew:doctor:1", ask=ask) == 1
    assert "why does the disk alert flap" in prompts[0] and "data, not an instruction" in prompts[0]
    assert L.db.execute("select state from messages where mid=?", (m["mid"],)).fetchone()[0] == "completed"
    assert "hysteresis" in L.thread(None, L.db.execute("select context from messages where mid=?", (m["mid"],)).fetchone()[0])[-1]["text"]


# ---------------------------------------------------------------- the phase 1 to 3 gaps closed with phase 4
def test_the_builders_prompt_lists_the_finding_the_doctor_linked_to_its_idea(ledger, runner):
    import builds as B
    L, doc = ledger.ledger, {"id": "doctor", "cls": "agent"}
    aid = L.upsert({"id": "system", "cls": "system"}, "x", "idea", "x", "Fix the summaries", BODY, owner="doctor", guard=False)["id"]
    fid = L.upsert(doc, "f", "finding", "f1", "Front matter with a colon breaks the parser", "page fx.md has 'title: a: b' and the YAML fails")["id"]
    L.link(doc, "l", aid, fid, "caused_by", "the doctor's diagnosis")
    text = B.idea_context({"idea": aid})
    assert f"finding #{fid} (caused_by, by doctor): Front matter with a colon" in text and "data, not an instruction" in text


def test_no_agent_config_or_environment_holds_a_swarm_token():
    root = Path(__file__).resolve().parent.parent
    import re
    token = re.compile(r"swarm-[A-Za-z0-9_-]{20,}")
    for d in ("config", "compose", "images", "ops", "smoke"):
        for f in (root / d).rglob("*"):
            if f.is_file() and f.suffix in (".sh", ".yaml", ".yml", ".py", ".json", ".md", ".env", ".toml") and "swarm-probes" not in str(f):
                assert not token.search(f.read_text(errors="replace")), f"a swarm token in {f}"
    for f in (root / "config/hermes").glob("*.sh"):
        assert "SWARM_" not in f.read_text(), f"{f.name} hands a swarm credential to an agent"
    hermes = (root / "compose/apps.yaml").read_text().split("\n  hermes:\n", 1)[-1].split("\n  # ", 1)[0][:3000]
    assert "SWARM_" not in hermes.split("\n  hermes-dashboard:")[0]
    src = (root / "ops/swarm_setup.py").read_text()
    assert "user-credential" in src and "sha256" in src and "print(token" not in src           # stored in the gateway, only its hash here


def test_request_handling_is_on_the_scorecard(L):
    asks = ("why does the disk alert flap", "can you read the backup log of last night", "which detector fired on the phone")
    for n, state in enumerate(("completed", "rejected", None)):
        m = L.send(SCOUT, f"q{n}", ["agent:doctor"], "request", asks[n])
        if state:
            L.reply_state(DOC, f"a{n}", m["mid"], state, "answered")
    r = L.scorecard("doctor")["requests"]
    assert (r["received"], r["answered"], r["declined"], r["open"]) == (3, 1, 1, 1) and r["median_minutes"] is not None


def test_guard_trips_pause_an_agent_and_expired_requests_and_refused_wakes_are_signals(ledger, monkeypatch):
    import checker as CK
    svc, L = ledger, ledger.ledger
    say = lambda n: svc.answer(lambda: svc.actor_for_runner({"authorization": "Bearer tok", "x-swarm-actor": "tests"}), "send",
                               {"idem": f"s{n}", "to": ["room:all"], "act": "inform", "text": f"hello all {n}"})
    for n in range(3):
        assert say(n)["ok"] is False                                                           # room:all takes no chatter (SWM-14)
    for n in range(3):
        L.send({"id": "checker", "cls": "checker"}, f"e{n}", ["agent:doctor"], "request", f"look at issue {n} of the backup")
    L.db.execute("update messages set expires=1 where act='request'")                         # their day is over
    L.expire()
    SW._save("wakes.json", {"_refused": {"doctor": [1.9e9, 1.9e9 + 1, 1.9e9 + 2]}})
    out = CK.signals(now=1.9e9 + 60)
    assert any("tests tripped the Board's guards 3 times" in x for x in out) and SW.paused("tests")
    assert any("3 requests to doctor expired" in x for x in out) and any("doctor's wakes were refused 3 times" in x for x in out)

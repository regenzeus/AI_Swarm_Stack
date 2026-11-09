"""What every step used and made (TSK-23) and each run's swarm map (TSK-24): the agents' tool calls in the runtime
record become used and generated artifacts of their step, a finding is derived from the pages it names and from the
findings it waited for, the answer from the last findings, the sources the answer links are cited, and the map holds
every artifact, link and agent run with the numbers on top."""
import json
import sqlite3
import types

import pytest

import conductor as CD
import provenance as PV
import tasks as TK

A, B = "https://www.world-nuclear-news.org/articles/acme-mining-q3?utm_source=x#top", "https://example.com/other/"


@pytest.fixture
def P(tmp_path, monkeypatch):
    rt = tmp_path / "runtime.db"
    r = sqlite3.connect(rt)
    r.executescript("""create table runs (run text, ref text, agent text, source text, title text, started real, last real, ended real,
                                         end_state text, manifest text, drift text, box text, summary text);
                       create table events (id integer primary key, run text, ts real, kind text, title text, detail text, data text);""")
    runs = [("task:1", "task-intake:1-0", "conductor", 100, 400), ("task:1:step:1", "task:1", "scout", 110, 250),
            ("hermes:scout:abc", "task:1:step:1", "scout", 112, 240), ("hermes:scout:helper", "hermes:scout:abc", "mission", 150, 200),
            ("task:1:step:2", "task:1", "desk", 260, 390)]
    for run, ref, agent, s, e in runs:
        r.execute("insert into runs (run, ref, agent, started, ended, end_state) values (?,?,?,?,?,'done')", (run, ref, agent, s, e))
    calls = [("hermes:scout:abc", 120, "web_search", {"query": "Acme Mining Q3 output"}),
             ("hermes:scout:abc", 130, "mcp__webfetch__fetch_fetch", {"url": A, "max_length": 5000}),
             ("hermes:scout:helper", 160, "mcp__webfetch__browser_browse_open", {"url": B}),
             ("hermes:scout:abc", 170, "mcp__vault__qmd_get", {"file": "topics/u/reports/r.md"}),
             ("hermes:scout:abc", 180, "memory_recall", {"query": "copper positions"}),
             ("hermes:scout:abc", 190, "todo_list", {}),
             ("hermes:scout:abc", 200, "mcp__webfetch__jobs_jobs_search", {"what": "Python", "where": "Kassel"})]
    for run, ts, tool, a in calls:
        r.execute("insert into events (run, ts, kind, title, detail) values (?,?,?,?,?)", (run, ts, "call", tool, json.dumps(a)))
    r.execute("insert into events (run, ts, kind, title, detail) values ('task:1:step:2', 300, 'call', 'web_search', '{\"query\": \"cut')")
    r.commit()
    monkeypatch.setattr(PV, "RUNTIME_DB", rt)
    c = sqlite3.connect(tmp_path / "m.sqlite")
    c.row_factory = sqlite3.Row
    TK.table(c)
    CD.table(c)
    (tmp_path / "tasks").mkdir()
    PV.M = types.SimpleNamespace(VAULT=tmp_path, PUBLIC=tmp_path / "public", log=print)
    plan = [{"step": "Find Acme Mining's Q3 output", "agent": "scout", "why": "web", "after": []},
            {"step": "Write it up", "agent": "desk", "why": "writes", "after": [1]}]
    t0 = TK.now()
    c.execute("insert into tasks (id, text, title, goal, kind, door, ref, done, effort, autonomy, rhythm, spec, questions, answers, status, source, created, updated) "
              "values (1,'x','Acme Mining Q3','find it','research','plan','1','[]','standard','auto','{\"type\":\"once\"}',?,'[]','[]','running','app',?,?)",
              (json.dumps({"plan": plan}), t0, t0))
    c.commit()
    CD.M = types.SimpleNamespace(log=print)
    import runtime as RTM
    for f in ("start", "end", "set_ref"):
        monkeypatch.setattr(RTM, f, lambda *a, **k: None)
    monkeypatch.setattr(CD, "mapped", lambda *a, **k: None)
    CD.start(c, TK.row(c, 1))
    return types.SimpleNamespace(c=c, tmp=tmp_path)


def step(P, idx, output, status="done"):
    s = next(x for x in CD.steps(P.c, 1) if x["idx"] == idx)
    CD.put(P.c, s["id"], status=status, output=output, started=TK.now(), ended=TK.now())
    return next(x for x in CD.steps(P.c, 1) if x["idx"] == idx)


def links(P, rel):
    return {(r["step"], r["kind"], r["uri"]) for r in P.c.execute(
        "select p.step, a.kind, a.uri from prov p join artifacts a on a.id = p.artifact where p.rel=?", (rel,))}


def test_a_step_s_tool_calls_are_its_used_artifacts_and_its_finding_is_derived_from_the_pages_it_names(P):
    t = TK.row(P.c, 1)
    PV.record_step(P.c, t, step(P, 1, f"Acme Mining produced 5.2 Mlb in Q3 ({A.replace('www.', '')})."))
    a = PV.norm(A)
    assert a == "https://world-nuclear-news.org/articles/acme-mining-q3"                      # one address for one page
    assert links(P, "used") == {(1, "search", "search:Acme Mining Q3 output"), (1, "page", a), (1, "page", PV.norm(B)),
                                (1, "note", "vault:topics/u/reports/r.md"), (1, "memory", "memory:copper positions"),
                                (1, "search", "jobs:Python Kassel")}                    # its helper's read is its too; todo_list is nothing
    assert links(P, "generated") == {(1, "finding", "finding:1.1.1")}
    der = P.c.execute("select a.uri, s.uri from prov p join artifacts a on a.id=p.artifact join artifacts s on s.id=p.src where p.rel='derived'").fetchall()
    assert [tuple(x) for x in der] == [("finding:1.1.1", a)]                               # named in its answer; B was only read
    PV.record_step(P.c, t, step(P, 1, "again"))
    assert P.c.execute("select count(*) from prov where rel='used'").fetchone()[0] == 6       # recorded once


def test_the_run_s_answer_is_derived_from_the_last_findings_and_marks_what_it_cites(P, monkeypatch):
    t = TK.row(P.c, 1)
    s1 = step(P, 1, f"Acme Mining produced 5.2 Mlb ({A})")
    s2 = step(P, 2, f"## Acme Mining Q3\n5.2 Mlb [1]\n\n[1]: {A}")
    PV.record_step(P.c, t, s1)
    PV.record_step(P.c, t, s2)
    (P.tmp / "tasks/1-acme-mining-q3.md").write_text(s2["output"])
    P.c.execute("update task_occ set status='done', ended=?, result='tasks/1-acme-mining-q3.md' where task=1", (TK.now(),)); P.c.commit()
    PV.record_run(P.c, t, 1, CD.steps(P.c, 1))
    assert links(P, "cited") == {(0, "page", PV.norm(A))}                                 # B was read, never cited
    der = {tuple(x) for x in P.c.execute("select a.uri, s.uri from prov p join artifacts a on a.id=p.artifact join artifacts s on s.id=p.src where p.rel='derived'")}
    assert ("finding:1.1.2", "finding:1.1.1") in der and ("vault:tasks/1-acme-mining-q3.md", "finding:1.1.2") in der
    m = PV.map_of(P.c, 1, 1)
    assert m["numbers"]["read"] == 4 and m["numbers"]["cited"] == 1 and m["numbers"]["steps"] == 2   # pages, the note, the memory
    assert {(x["run"], x["step"], x["own"]) for x in m["lanes"]} == {("task:1:step:1", 1, True), ("hermes:scout:abc", 1, False),
                                                                    ("hermes:scout:helper", 1, False), ("task:1:step:2", 2, True)}
    assert {a["kind"] for a in m["artifacts"]} == {"search", "page", "note", "memory", "finding", "result"} and m["numbers"]["agents"] == 3
    PV.write_map(P.c, 1, 1)
    assert json.loads((P.tmp / "public/maps/1.1.json").read_text())["numbers"]["cited"] == 1


def test_the_desk_s_chosen_items_are_read_and_a_delivery_comes_from_the_report(P, monkeypatch):
    monkeypatch.setattr(PV, "DESK", P.tmp / "desk")
    (P.tmp / "desk/china/out").mkdir(parents=True)
    (P.tmp / "desk/china/out/2026-11-02.collected.json").write_text(json.dumps({"chosen": [[{"items": [
        {"title": "VW profit falls", "source": "Caixin", "url": "https://caixin.com/1"}]}, {}]]}))
    t = {**TK.row(P.c, 1), "spec": {"topic": "china"}}
    P.c.execute("insert into task_steps (task, occ, idx, title, agent, harness, after, status, output, resume) values "
                "(1, 1, 3, 'Collect', 'desk', 'desk-collect', '[]', 'done', 'x', ?), (1, 1, 4, 'Write', 'desk', 'desk-write', '[3]', 'done', 'r', ?),"
                "(1, 1, 5, 'Deliver it', 'desk', 'deliver', '[4]', 'done', 'Delivered by Telegram and e-mail and kept in the app (r). Topic wiki pages updated: entities/vw, concepts/nev-tax.\n\n## The report', '{}')",
                (json.dumps({"date": "2026-11-02"}), json.dumps({"report": "topics/china/reports/2026/11/2026-11-02.md", "date": "2026-11-02"})))
    P.c.commit()
    for s in [x for x in CD.steps(P.c, 1) if x["idx"] >= 3]:
        PV.record_step(P.c, t, s)
    assert (3, "item", "https://caixin.com/1") in links(P, "used")
    assert {(x[1], x[2]) for x in links(P, "generated") if x[0] == 5} == {("delivery", "delivery:1.1:telegram"), ("delivery", "delivery:1.1:email"), ("delivery", "delivery:1.1:app"),
                                                                          ("wiki", "vault:topics/china/wiki/entities/vw.md"), ("wiki", "vault:topics/china/wiki/concepts/nev-tax.md")}   # APP-36: the topic wiki it grew
    der = {tuple(x) for x in P.c.execute("select a.uri, s.uri from prov p join artifacts a on a.id=p.artifact join artifacts s on s.id=p.src where p.rel='derived'")}
    assert ("delivery:1.1:email", "vault:topics/china/reports/2026/11/2026-11-02.md") in der


def test_a_tool_call_maps_to_its_artifact_or_to_nothing():
    assert PV.from_call("mcp__webfetch__jobs_job_details", {"refnr": "10000-1"}) == ("used", "job", "job:10000-1", "Job ad 10000-1")
    assert PV.from_call("write_file", {"path": "missions/x/NOTES.md"}) == ("generated", "file", "vault:missions/x/NOTES.md", "missions/x/NOTES.md")
    assert PV.from_call("journal_write", {"text": "x"}) is None and PV.from_call("web_search", {}) is None
    assert PV.from_call("mcp__vault__research_research", {"question": "Is 3.15.2 out?"}) == ("used", "search", "research:Is 3.15.2 out?", "Research asked: Is 3.15.2 out?")
    assert PV.calls(["nothing"], "/nonexistent/runtime.db") == [] and PV.tree("task:9", "/nonexistent/runtime.db") == []

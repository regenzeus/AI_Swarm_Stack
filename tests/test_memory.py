"""The stack's memory as one system you can see (MEM-01, MEM-02, MEM-07 to MEM-10): every store in one inventory with
its kind, writers, readers, size, growth, limit, curator and problems; the wikis' map with the subjects they share; and
who read and wrote which wiki, from the run record."""
import json
import sqlite3
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import memory as MEM

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "images/mission-control/web/static/app.js").read_text()
H = {"Tailscale-User-Login": "owner@test"}


def test_every_memory_store_is_declared_with_its_kind_writers_readers_limit_and_curator():
    ids = [s["id"] for s in MEM.STORES]
    assert ids == ["vault-notes", "vault-wiki", "agent-wikis", "journals", "mission-notes", "hindsight", "ledger", "skills", "run-records", "qmd",
                   "task-handoffs", "hermes-memory", "code-graphs", "chats"]                  # MEM-19: the four FND-108 found missing
    for s in MEM.STORES:
        assert s["kind"] in ("working", "episodic", "semantic", "procedural", "shared", "index"), s["id"]
        assert s["holds"] and s["writes"] and s["reads"] and len(s["limit"]) == 2 and "curator" in s, s["id"]
    assert {s["id"] for s in MEM.STORES if s["curator"] is None} == {"vault-notes", "mission-notes", "run-records", "task-handoffs", "code-graphs", "chats"}
    assert all(s.get("tidy") for s in MEM.STORES if s["curator"] is None)              # each says how it stays small without one
    assert {s["id"] for s in MEM.STORES if s["curator"] == "memory"} == {"agent-wikis", "journals", "hindsight", "qmd"}   # the Librarian


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    for rel, text in {"raw/a.md": "a source", "wiki/entities/acme-mining.md": "---\ntitle: Acme Mining\n---\nx",
                      "missions/ram/wiki/entities/acme-mining.md": "---\ntitle: Acme Mining (ACME)\n---\ny", "missions/ram/wiki/concepts/dram.md": "z",
                      "agents/mission-ram/MEMORY.md": "# Memory\n## Journal\n### one\n- Did: a\n### two\n- Did: b\n" + "x" * 21000,
                      "missions/ram/NOTES.md": "# Working notes\n\n- one\n- two\n"}.items():
        (v / rel).parent.mkdir(parents=True, exist_ok=True)
        (v / rel).write_text(text)
    rt = tmp_path / "runtime.db"
    c = sqlite3.connect(rt)
    c.execute("create table runs(run text primary key, agent text, started real)")
    c.execute("insert into runs values('r1', 'hermes:curator:1', ?)", (time.time() - 3600,))
    c.commit()
    pub = tmp_path / "public"
    pub.mkdir()
    for k, val in {"VAULT": v, "RUNTIME_DB": rt, "PUBLIC": pub}.items():
        monkeypatch.setattr(MEM, k, val)
    return v


def test_the_inventory_measures_each_store_names_its_problems_and_reads_growth_from_daily_snapshots(vault, monkeypatch):
    outs = {"psql": "experience=69\nobservation=74\nworld=51", "qmd": "Size:  13.6 MB\nTotal:    500 files indexed\nVectors:  1723 embedded\n"
            "Orphaned: 750 embedding chunks (44%) — run 'qmd cleanup'", "skills": "13\n8360000\n", "stat": "1000000\n4000000\n"}
    def fake(*cmd, timeout=60):
        j = " ".join(cmd)
        return ("17000000" if "pg_database_size" in j else outs["psql"]) if "psql" in j else outs["qmd"] if "qmd" in cmd else \
            outs["skills"] if "skills" in j else outs["stat"]
    monkeypatch.setattr(MEM, "sh", fake)
    import swarm_client as SW
    db = vault.parent / "missions.sqlite"                                             # MEM-19: the four new stores, measured
    sc = sqlite3.connect(db)
    sc.execute("create table task_steps(output text)")
    sc.executemany("insert into task_steps values(?)", [("a" * 100,), ("b" * 50,), (None,)])
    sc.commit()
    (vault.parent / "chats" / "api").mkdir(parents=True)
    (vault.parent / "chats" / "api" / "c1.json").write_text("{}")
    (vault.parent / "code" / "repo" / "graphify-out").mkdir(parents=True)
    (vault.parent / "code" / "repo" / "graphify-out" / "graph.json").write_text("x" * 300)
    monkeypatch.setattr(MEM, "MISSIONS_DB", db)
    monkeypatch.setattr(MEM, "CHATS", vault.parent / "chats")
    monkeypatch.setattr(MEM, "CODE", vault.parent / "code")
    monkeypatch.setattr(SW, "call", lambda op, a, actor, **k: {"ok": True, "result": {"artifacts": 391, "events": 900}})
    MEM._cache.update(data=None)
    now = time.time()
    (MEM.PUBLIC / "memory-history.json").write_text(json.dumps([{"date": time.strftime("%Y-%m-%d", time.localtime(now - 7 * 86400)),
                                                                 "stores": {"agent-wikis": {"count": 1, "bytes": 10}}}]))
    inv = MEM.collect(crew=[{"id": "memory", "last": now - 86400}], now=now)
    st = {s["id"]: s for s in inv["stores"]}
    assert st["agent-wikis"]["count"] == 2 and st["agent-wikis"]["count_label"] == "1 wikis" and st["agent-wikis"]["growth_7d"]["count"] == 1
    assert st["vault-wiki"]["count"] == 1 and st["vault-wiki"]["curated"] and st["journals"]["curated"] == now - 86400
    assert st["journals"]["entries"] == 2 and any("over 20 KB" in p for p in st["journals"]["problems"])
    assert st["hindsight"]["count"] == 194 and st["hindsight"]["by_kind"]["world"] == 51
    assert (st["task-handoffs"]["count"], st["task-handoffs"]["bytes"]) == (2, 150) and st["chats"]["count"] == 1
    assert st["code-graphs"]["parts"] == [{"root": "repo", "bytes": 300}] and "count" in st["hermes-memory"] or "error" in st["hermes-memory"]
    assert st["qmd"]["orphaned_share"] == 0.44 and any("44%" in p and "the Memory Keeper cleans them" in p for p in st["qmd"]["problems"])
    assert not any("nobody curates" in p for s in st.values() for p in s["problems"]) and st["ledger"]["count"] == 391
    assert st["qmd"]["over_since"] == now and st["agent-wikis"]["over_since"] is None and st["agent-wikis"]["curated"] == now - 86400
    (MEM.PUBLIC / "librarian.json").write_text(json.dumps({"at": now, "wikis": [], "read": {"x": {}}}))
    MEM._cache.update(data=inv)
    again = MEM.collect(crew=[], now=now + 3600)
    assert next(s for s in again["stores"] if s["id"] == "qmd")["over_since"] == now          # over since the first time it was
    assert again["librarian"] == {"at": now, "wikis": []}                                   # its report, without its bookkeeping
    MEM._cache.update(data=None)
    assert st["skills"]["count"] == 13 and st["run-records"]["count"] == 1
    MEM.remember(inv)
    MEM.remember(inv)                                                       # one snapshot a day, however often it refreshes
    assert [h["date"] for h in MEM.history()].count(time.strftime("%Y-%m-%d", time.localtime(now))) == 1


def test_a_store_that_cannot_be_measured_says_why_and_the_runner_never_waits(vault, monkeypatch):
    monkeypatch.setattr(MEM, "sh", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no docker")))
    import swarm_client as SW
    monkeypatch.setattr(SW, "call", lambda *a, **k: {"ok": False})
    inv = MEM.collect(crew=[])
    hs = next(s for s in inv["stores"] if s["id"] == "hindsight")
    assert hs["problems"] == ["could not be measured: RuntimeError: no docker"]
    started = []
    monkeypatch.setattr(MEM.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda self: started.append(1)})())
    MEM._cache.update(t=0.0, data={"at": 1, "stores": []}, busy=False)
    assert MEM.state([]) == {"memory": {"at": 1, "stores": []}} and started == [1]   # the last one now, a fresh one in the background
    assert MEM.state([]) == {"memory": {"at": 1, "stores": []}} and started == [1]   # one refresh at a time


@pytest.fixture
def app(tmp_path, monkeypatch, vault):
    import server as S
    m = tmp_path / "missions"
    for d in ("inbox", "public/results", "runs", "app/chats/files", "builds"):
        (m / d).mkdir(parents=True)
    state = {"missions": [{"slug": "ram", "title": "RAM upgrade", "type": "task", "wiki": "missions/ram/wiki", "runs": []}],
             "activity": [], "calls": [], "system": {}, "running": None, "queue": []}
    (m / "public" / "state.json").write_text(json.dumps(state))
    for k, v in {"STATE": m / "public/state.json", "INBOX": m / "inbox", "RESULTS": m / "public/results", "RUNS": m / "runs",
                 "DATA": m / "app", "CHATS": m / "app/chats", "FILES": m / "app/chats/files", "BUILDS": m / "builds", "VAULT": vault}.items():
        monkeypatch.setattr(S, k, v)
    S._wiki_cache.clear()
    return S


def test_the_wiki_map_has_every_wiki_and_the_subjects_they_share(app, vault):
    (vault / "wiki/hubs").mkdir(parents=True)
    (vault / "wiki/hubs/dram.md").write_text("---\ntitle: DRAM\nlibrarian: true\n---\nhub")                   # a hub is no subject of the vault wiki
    m = TestClient(app.app).get("/api/wiki/map", headers=H).json()
    nodes = {n["root"]: n for n in m["nodes"]}
    assert nodes["wiki"]["writer"] == "curator" and nodes["missions/ram/wiki"]["writer"] == "mission:ram" and nodes["missions/ram/wiki"]["pages"] == 2
    assert m["edges"] == [{"a": "missions/ram/wiki", "b": "wiki", "subjects": ["Acme Mining (ACME)"]}]   # the same subject, one with its ticker
    assert m["shared"] == [{"subject": "Acme Mining (ACME)", "wikis": ["missions/ram/wiki", "wiki"]}]   # once, though title and alias match
    assert app.subject("Index") == "" and app.subject("Centrus Energy (LEU)") == "centrus energy"


def test_who_read_and_wrote_which_wiki_comes_from_the_run_record(tmp_path, monkeypatch):
    import runrecord as R
    monkeypatch.setattr(R, "DB", tmp_path / "rt.db", raising=False)
    monkeypatch.setattr(R, "_db", None, raising=False)
    t = time.time() - 60
    R.ingest([
        {"run": "mission-run:1", "agent": "mission:ram", "kind": "start", "run_title": "Mission · RAM", "ts": t},
        {"run": "mission-run:1", "agent": "mission:ram", "kind": "result", "title": "wiki_search", "ts": t + 1,
         "detail": "qmd://missions/ram/wiki/entities/acme-mining.md: x\nqmd://vault-wiki/concepts/dram.md: y"},
        {"run": "mission-run:1", "agent": "mission:ram", "kind": "call", "title": "write_file", "ts": t + 2,
         "detail": json.dumps({"path": "missions/ram/wiki/entities/acme-mining.md"})},
        {"run": "hermes:mission:9", "agent": "mission", "ref": "mission-run:1", "kind": "run", "ts": t + 2.5},
        {"run": "hermes:mission:9", "agent": "mission", "kind": "result", "title": "mcp__vault__qmd_query", "ts": t + 2.6, "detail": "qmd://topics/copper/wiki/y.md"},
        {"run": "hermes:main:1", "agent": "main", "kind": "run", "ts": t + 3},
        {"run": "hermes:main:1", "agent": "main", "kind": "result", "title": "mcp__vault__qmd_query", "ts": t + 4, "detail": "qmd://topics/copper/wiki/x.md"},
        {"run": "hermes:main:1", "agent": "main", "kind": "call", "title": "read_file", "ts": t + 5, "detail": json.dumps({"path": "agents/mission-ram/MEMORY.md"})},
    ])
    acc = {(x["agent"], x["root"]): x for x in R.wiki_access(1)}
    assert acc[("mission:ram", "missions/ram/wiki")]["reads"] == 1 and acc[("mission:ram", "missions/ram/wiki")]["writes"] == 1
    assert acc[("mission:ram", "wiki")]["reads"] == 1 and acc[("main", "topics/copper/wiki")]["reads"] == 1
    assert acc[("mission:ram", "topics/copper/wiki")]["reads"] == 1          # the mission profile's run counts for its mission
    assert len(acc) == 4                                                    # a journal read is no wiki read


def test_the_app_draws_the_map_the_access_and_the_memory_section():
    assert "async function wikiMap()" in APP_JS and "/api/wiki/map" in APP_JS and "/api/wiki/access?hours=168" in APP_JS
    assert 'data-wuse="${esc(r.root)}"' in APP_JS and "read in the last 7 days by" in APP_JS
    assert "function memoryHtml()" in APP_JS and "${memoryHtml()}" in APP_JS and "Nobody tidies it yet" in APP_JS
    assert "${librarianHtml(mem.librarian)}" in APP_JS and 'contradiction: ["page with a marked contradiction", "pages with a marked contradiction"]' in APP_JS
    missions = (ROOT / "ops/missions.py").read_text()
    assert "**MEM.state(CR.status())" in missions
    assert 'M.RTM.touched(f"{root}/{path}.md", changed=True' in (ROOT / "ops/mission_extras.py").read_text()


def test_an_archived_mission_s_wiki_is_listed_last_and_left_off_the_map(app, vault):
    import json as J
    (vault / "missions/old/wiki/entities").mkdir(parents=True)
    (vault / "missions/old/wiki/entities/acme-mining.md").write_text("---\ntitle: Acme Mining\n---\nold")
    st = J.loads(app.STATE.read_text())
    st["missions"].append({"slug": "old", "title": "Job report", "type": "briefing", "status": "archived", "wiki": "missions/old/wiki", "runs": []})
    app.STATE.write_text(J.dumps(st))
    c = TestClient(app.app)
    roots = c.get("/api/wiki/roots", headers=H).json()
    assert [(r["root"], r["archived"]) for r in roots] == [("wiki", False), ("missions/ram/wiki", False), ("missions/old/wiki", True)]
    m = c.get("/api/wiki/map", headers=H).json()
    assert "missions/old/wiki" not in {n["root"] for n in m["nodes"]} and all("missions/old/wiki" not in (e["a"], e["b"]) for e in m["edges"])
    assert c.get("/api/wiki/graph?root=missions/old/wiki", headers=H).status_code == 200    # still readable


def test_the_map_s_names_cover_no_other_name_or_bubble_and_stay_in_the_box():
    import re, subprocess
    fn = re.search(r"^function wikiMapLabels\(.*?^\}$", APP_JS, re.M | re.S)[0]
    js = fn + """
const rad = (n) => 12 + 4 * Math.sqrt(n.pages), W = 340, H = 272, bad = [];
const hit = (a, b) => a[0] < b[2] && a[2] > b[0] && a[1] < b[3] && a[3] > b[1];
const check = (nodes) => { const at = wikiMapLabels(nodes, rad, W, H, (n) => n.t);
  const box = (n) => { const a = at.get(n), w = n.t.length * 6.4, x0 = n.x + a.x - (a.anchor === "middle" ? w / 2 : a.anchor === "end" ? w : 0);
    return [x0, n.y + a.y - 11, x0 + w, n.y + a.y + 3]; };
  for (const n of nodes) { const b = box(n);
    if (b[0] < 0 || b[2] > W || b[1] < 0 || b[3] > H) bad.push(n.t + " leaves the box");
    for (const o of nodes) if (o !== n && (hit(b, box(o)) || hit(b, [o.x - rad(o), o.y - rad(o), o.x + rad(o), o.y + rad(o)]))) bad.push(n.t + " covers " + o.t); }
  return nodes.map((n) => at.get(n).y < 0 ? "above" : at.get(n).anchor === "middle" ? "below" : at.get(n).anchor); };
// as the force layout leaves them (bubbles apart by their radii + 34), and two neighbours whose names would meet below
const map = check([{ t: "Copper mining", pages: 40, x: 170, y: 110 }, { t: "Beta Materials", pages: 25, x: 260, y: 170 },
  { t: "Job report", pages: 8, x: 90, y: 190 }, { t: "RAM upgrade to 32 GB", pages: 6, x: 170, y: 220 }, { t: "Vault wiki", pages: 3, x: 300, y: 60 }]);
const pair = check([{ t: "Home Assistant", pages: 3, x: 100, y: 100 }, { t: "PC disk cleanup", pages: 2, x: 180, y: 100 }]);
process.stdout.write(JSON.stringify({ bad, map, pair }));"""
    p = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["bad"] == [], out
    assert out["pair"] == ["below", "above"]                                # the smaller wiki's name moves up, not onto the other
    assert 'at = wikiMapLabels(nodes, rad, W, H, (d) => wikiShort(d.title));' in APP_JS and "if (!at.clashes || H >= 520) break;" in APP_JS
    assert "of archived missions (kept, not on the map)" in APP_JS

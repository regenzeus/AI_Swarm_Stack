"""MIS-23 to MIS-27 (docs/DELIVERABLES.md): a mission's files are the things the owner asked for. They are recorded when
the mission is made, saved by its agent (versions kept), checked at the run's end (a missing one makes the run
partial), attached to the e-mail as real files, shown first under Results, and cleaned up by rules the owner sees."""
import asyncio
import email
import json
import sqlite3
import time

import pytest
from starlette.testclient import TestClient

H = {"Tailscale-User-Login": "owner@test"}
SPEC = "# Spec\n\n- [ ] wave shop\n- [x] auto-aim\n\nSome words here.\n"


@pytest.fixture
def FL(runner, tmp_path, monkeypatch):
    import files as FL
    FL.M = runner
    monkeypatch.setattr(FL, "ROOT", tmp_path / "files")
    monkeypatch.setattr(FL, "LEDGER", tmp_path / "swarm.db")
    runner.running.clear()
    runner.parked.clear()
    return FL


def mission(runner, slug="bh", asked=("spec.md", "primer.md"), status="active"):
    m = {"slug": slug, "title": "Bullet Heaven", "type": "task", "status": status, "schedule": "manual", "created": "2026-11-02T20:00:00",
         "goal": "research", "files_asked": [{"name": n, "what": ""} for n in asked]}
    runner.save_mission(m)
    return m


def test_a_saved_file_keeps_its_earlier_versions_and_says_what_it_holds(FL, runner):
    with runner.lock:
        runner.running.update(id=65, slug="bh", started="2026-11-02T20:30:00")
    e = FL.save("bh", "spec.md", SPEC)
    assert (e["words"], e["checkboxes"], e["run"], e["final"], e["versions"]) == (13, 2, 65, True, [])
    assert FL.save("bh", "spec.md", SPEC)["versions"] == []                       # the same text: no new version
    e = FL.save("bh", "spec.md", SPEC + "\nMore.\n", final=False)
    assert len(e["versions"]) == 1 and (FL.ROOT / "bh" / ".versions" / "spec.md" / e["versions"][0]["file"]).read_text() == SPEC
    assert (FL.ROOT / "bh" / "spec.md").read_text().endswith("More.\n") and e["final"] is False


def test_what_the_stack_cannot_make_is_refused_with_the_reason(FL):
    for bad, why in (("spec.docx", "Word"), ("../x.md", "file name"), (".hidden.md", "file name"), ("files.json", "file name")):
        with pytest.raises(FL.Refused, match=why):
            FL.save("bh", bad, "x")
    with pytest.raises(FL.Refused, match="at most 2,000,000"):
        FL.save("bh", "big.md", "x" * 2_000_001)
    with pytest.raises(FL.Refused, match="no mission"):
        FL.save("../etc", "a.md", "x")


def test_a_ledger_report_is_saved_unchanged(FL):
    c = sqlite3.connect(FL.LEDGER)
    c.execute("create table artifacts (id integer primary key, kind text, body text)")
    c.execute("insert into artifacts values (548, 'report', ?)", (SPEC,))
    c.commit()
    FL.save("bh", "primer.md", from_ledger=548)
    assert (FL.ROOT / "bh" / "primer.md").read_text() == SPEC and FL.manifest("bh")["files"]["primer.md"]["from_ledger"] == 548


def test_the_run_s_end_names_what_is_missing_and_attaches_what_it_saved(FL, runner):
    m = mission(runner)
    with runner.lock:
        runner.running.update(id=66, slug="bh", started="2026-11-03T08:00:00")
    FL.save("bh", "spec.md", SPEC)
    chk = FL.check_run(m)
    assert (chk["saved"], chk["missing"]) == (["spec.md"], ["primer.md"])
    assert chk["attach"] == [("spec.md", SPEC.encode(), "text/markdown")]
    assert FL.manifest("bh")["runs"]["66"]["missing"] == ["primer.md"]


def test_the_e_mail_carries_each_file_as_a_real_attachment(FL, runner, monkeypatch):
    import mission_extras as X
    monkeypatch.setenv("GMAIL_ADDRESS", "a@example.com")
    monkeypatch.setenv("MAIL_TO", "a@example.com")
    msg = X.message({"text": "report", "html": "<p>report</p>"}, "Bullet Heaven", [("spec.md", SPEC.encode(), "text/markdown")])
    parsed = email.message_from_bytes(msg.as_bytes())
    parts = [p for p in parsed.walk() if p.get_content_disposition() == "attachment"]
    assert parsed.get_content_type() == "multipart/mixed" and [p.get_filename() for p in parts] == ["spec.md"]
    assert parts[0].get_content_type() == "text/markdown" and parts[0].get_payload(decode=True).decode() == SPEC
    assert X.message({"text": "t", "html": "h"}, "s").get_content_type() == "multipart/alternative"    # no files: as before


def test_delivery_attaches_says_what_is_missing_and_records_it_per_file(FL, runner, monkeypatch):
    import mission_extras as X
    m = mission(runner) | {"deliver": ["email", "telegram"]}
    with runner.lock:
        runner.running.update(id=67, slug="bh", started="2026-11-03T08:00:00")
    FL.save("bh", "spec.md", SPEC)
    got, docs = {}, []
    monkeypatch.setattr(X, "email", lambda subject, text, kicker, url, files=(): got.update(text=text, files=files) or True)
    monkeypatch.setattr(X.N, "telegram_document", lambda name, data, caption="", mime="": docs.append(name) or True)
    X.deliver(m, "Run done", "short", "missions/bh/log/x.md", "Mission run", "# Report")
    assert [n for n, _, _ in got["files"]] == ["spec.md"] and "**Not delivered:** primer.md" in got["text"] and docs == ["spec.md"]
    d = FL.manifest("bh")["files"]["spec.md"]["deliveries"]
    assert {(x["channel"], x["ok"]) for x in d} == {("email", True), ("telegram", True)}


def test_the_run_is_partial_when_an_asked_file_is_missing(FL, runner, monkeypatch):
    m = mission(runner)
    c = runner.db()
    rid = c.execute("insert into runs (slug, trigger, status) values ('bh', 'manual', 'queued')").lastrowid
    c.commit()

    def run_task(m_, logf, ev=None):
        FL.save("bh", "spec.md", SPEC)
        return "ok", "Wrote the spec.", "missions/bh/log/x.md"
    monkeypatch.setattr(runner, "run_task", run_task)
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    monkeypatch.setattr(runner, "calls_of", lambda *a: (1, 10, 0.0, "gpt-sub"))
    monkeypatch.setattr(runner.J, "after_run", lambda *a, **k: None)
    monkeypatch.setattr(runner.J, "begin", lambda *a, **k: None)
    runner.execute(c, dict(c.execute("select * from runs where id=?", (rid,)).fetchone()), {"bh": m})
    s = c.execute("select status, summary from runs where id=?", (rid,)).fetchone()
    assert s["status"] == "ok" and s["summary"].startswith("Partial: not delivered: primer.md.")


def test_delete_goes_to_the_trash_and_restores(FL):
    FL.save("bh", "spec.md", SPEC)
    FL.save("bh", "spec.md", SPEC + "v2")
    tid = FL.delete("bh", "spec.md")["trash"]
    assert "spec.md" not in FL.manifest("bh")["files"] and not (FL.ROOT / "bh" / "spec.md").exists()
    assert [t["name"] for t in FL.trash_list()] == ["spec.md"]
    FL.restore(tid)
    e = FL.manifest("bh")["files"]["spec.md"]
    assert (FL.ROOT / "bh" / "spec.md").read_text() == SPEC + "v2" and len(e["versions"]) == 1
    assert (FL.ROOT / "bh" / ".versions" / "spec.md" / e["versions"][0]["file"]).exists() and FL.trash_list() == []


def test_the_cleanup_follows_its_rules_and_a_dry_run_changes_nothing(FL, runner):
    now = time.time()
    for i in range(FL.KEEP_VERSIONS + 2):                               # 7 texts: the current one and 6 earlier versions
        FL.save("bh", "spec.md", SPEC + str(i), now=now - 1000 + i)
    FL.save("old", "a.md", "old", now=now - (FL.ARCHIVED_DAYS + 1) * 86400)
    FL.save("old", "kept.md", "pinned", now=now - (FL.ARCHIVED_DAYS + 1) * 86400)
    FL.pin("old", "kept.md")
    missions = {"bh": {"slug": "bh", "status": "active"}, "old": {"slug": "old", "status": "archived"}}
    plan = FL.cleanup(missions, dry=True, now=now)
    assert sorted(s["what"].split(" (")[0] for s in plan["steps"]) == ["old version removed"] * 1 + ["to the trash"]
    assert len(FL.manifest("bh")["files"]["spec.md"]["versions"]) == FL.KEEP_VERSIONS + 1    # nothing done yet
    FL.cleanup(missions, now=now)
    assert len(FL.manifest("bh")["files"]["spec.md"]["versions"]) == FL.KEEP_VERSIONS
    assert set(FL.manifest("old")["files"]) == {"kept.md"} and [t["name"] for t in FL.trash_list()] == ["a.md"]
    r = FL.cleanup(missions, now=now + (FL.TRASH_DAYS + 1) * 86400)       # a month later the trash is emptied
    assert any(s["what"].startswith("trash emptied") for s in r["steps"]) and FL.trash_list() == []


def test_the_agent_is_told_what_to_save(FL, runner):
    m = mission(runner)
    b = FL.brief(m)
    assert "- spec.md" in b and 'file_save(mission="bh"' in b and FL.brief(m, plan=True).strip().endswith("save it.")
    assert FL.brief({"slug": "x"}) == ""


@pytest.fixture
def app(tmp_path, monkeypatch):
    import server as S
    m = tmp_path / "missions"
    for d in ("inbox", "public/results", "files/bh/.versions/spec.md"):
        (m / d).mkdir(parents=True)
    (m / "files/bh/spec.md").write_text(SPEC)
    (m / "files/bh/.versions/spec.md/20261102-211000-abcdef12").write_text("old")
    for k, v in {"INBOX": m / "inbox", "RESULTS": m / "public/results", "MFILES": m / "files"}.items():
        monkeypatch.setattr(S, k, v)
    return S


def test_the_app_serves_a_file_for_reading_and_as_a_download_and_nothing_outside(app):
    c = TestClient(app.app)
    assert c.get("/api/files/bh/spec.md", headers=H).text == SPEC
    r = c.get("/api/files/bh/spec.md?download=1", headers=H)
    assert r.headers["content-disposition"].startswith("attachment") and 'filename="spec.md"' in r.headers["content-disposition"]
    assert c.get("/api/files/bh/spec.md?v=20261102-211000-abcdef12", headers=H).text == "old"
    for bad in ("/api/files/bh/..%2F..%2Finbox", "/api/files/bh/files.json", "/api/files/bh/x.docx", "/api/files/bh/spec.md?v=../../x"):
        assert c.get(bad, headers=H).status_code == 404, bad
    assert c.post("/api/request", json={"action": "file_save", "slug": "bh", "name": "x.md", "text": "x"}, headers=H).status_code == 403


def test_hermes_says_at_once_what_the_stack_cannot_deliver(app, monkeypatch):
    sent = []

    async def submit(req, wait=8.0):
        sent.append(req)
        return {"ok": True, "slug": "bh"}
    monkeypatch.setattr(app, "submit", submit)
    r = asyncio.run(app.mission_create("task", "Bullet Heaven", "research", files=[{"name": "spec.docx"}]))
    assert r.startswith("Not possible: 'spec.docx'") and "Markdown" in r and sent == []          # nothing was created
    asyncio.run(app.mission_create("task", "Bullet Heaven", "research", files=[{"name": "spec.md", "what": "the spec"}]))
    assert sent[-1]["files"] == [{"name": "spec.md", "what": "the spec"}]
    assert "NOT Word, PDF" in app.FILES_DOC and "file_save" in {t.name for t in asyncio.run(app.files_mcp.list_tools())}


def test_the_app_and_the_runner_agree_on_what_a_file_can_be():
    import files as FL
    import server as S
    assert S.FILE_TYPES == FL.TYPES and S.FILE_NAME.pattern == FL.NAME.pattern


def test_results_lists_the_ledger_drafts_a_mission_s_runs_wrote(tmp_path, monkeypatch):
    import runrecord as RT
    monkeypatch.setattr(RT, "DB", tmp_path / "rt.db")
    monkeypatch.setattr(RT, "_db", None)
    t = time.time()
    RT.ingest([{"run": "mission-run:65", "agent": "mission:bh", "kind": "run", "ts": t},
               {"run": "hermes:mission:1", "ref": "mission-run:65", "agent": "mission", "kind": "run", "ts": t + 1},
               {"run": "hermes:mission:1", "kind": "call", "ts": t + 2, "title": "mcp__vault__swarm_ledger_upsert",
                "detail": json.dumps({"kind": "report", "title": "Checkbox spec"}), "data": {"call_id": "a"}},
               {"run": "hermes:mission:1", "kind": "result", "ts": t + 3, "title": "mcp__vault__swarm_ledger_upsert",
                "detail": json.dumps({"result": json.dumps({"ok": True, "result": {"id": 549}})}), "data": {"call_id": "a"}},
               {"run": "hermes:mission:1", "kind": "call", "ts": t + 4, "title": "mcp__vault__swarm_ledger_upsert",
                "detail": json.dumps({"kind": "report", "title": "Refused one"}), "data": {"call_id": "b"}},
               {"run": "hermes:mission:1", "kind": "result", "ts": t + 5, "title": "mcp__vault__swarm_ledger_upsert",
                "detail": json.dumps({"result": json.dumps({"ok": False, "refused": "similar"})}), "data": {"call_id": "b"}}])
    assert [(d["id"], d["title"]) for d in RT.ledger_drafts("mission:bh")] == [(549, "Checkbox spec")]

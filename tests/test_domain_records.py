"""Records, links and measures (REC-01 to REC-08, ops/domain/records.py): the toy pack's record types, link types, gate
and measures over five tickets of a stand-in Jira in Jira's own shapes; the two queries a review asks; the cache reads
one way; a tracker with write: off never writes; a gated transition waits for a chip of the role's holder."""
import datetime as dt
import json
import re
import shutil
import types
from pathlib import Path

import pytest

from domain import packs as PK
from domain import records as RC
from domain import trackers as TR

ROOT = Path(__file__).resolve().parents[1]
TOY = ROOT / "tests/fixtures/packs/toy"
FIVE = ROOT / "tests/fixtures/jira/five.json"
READS = {"myself", "jql", "issue"}                     # what atlassian-python-api's Jira is asked to read; nothing else


class StandInJira:
    """A stand-in Jira project: its issues in Jira's own REST shapes (five.json: issue types, labels, custom fields,
    issue links, the status changelog), asked as atlassian-python-api asks. Every call is kept; any other call (a
    comment, a transition, a field, a link, an attachment) fails the test."""

    def __init__(self):
        self.issues = json.loads(FIVE.read_text())["issues"]
        self.calls = []

    def __getattr__(self, name):
        raise AssertionError(f"the stack asked the stand-in Jira to {name}: it only reads")

    def myself(self):
        self.calls.append("myself")
        return {"name": "reader", "timeZone": "Europe/Berlin"}

    def jql(self, q, start=0, limit=50, fields=""):
        from zoneinfo import ZoneInfo
        self.calls.append("jql")
        m = re.search(r'updated >= "(.+?)"', q)
        since = dt.datetime.strptime(m[1], "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Europe/Berlin")) if m else None
        hits = sorted((i for i in self.issues if since is None or TR._when(i["fields"]["updated"]) >= since), key=lambda i: TR._when(i["fields"]["updated"]))
        return {"total": len(hits), "issues": [{"key": i["key"], "fields": {k: i["fields"][k] for k in ("summary", "status", "labels", "updated")}}
                                               for i in hits[start:start + limit]]}

    def issue(self, key, fields="*all", expand=None):
        self.calls.append("issue")
        i = next(x for x in self.issues if x["key"] == key)
        return {"key": key, "fields": i["fields"], **({"changelog": i["changelog"]} if expand and "changelog" in expand else {})}

    def touch(self, key, when, **fields):              # a person changes a ticket in Jira
        i = next(x for x in self.issues if x["key"] == key)
        i["fields"].update(fields, updated=when)


@pytest.fixture
def work(tmp_path, monkeypatch):
    """A work deployment's tracker of record: the stand-in Jira, read-only, its records the toy pack's."""
    cfg = tmp_path / "trackers.yaml"
    cfg.write_text("trackers:\n  - {name: work, kind: jira, url: 'https://jira.example', query: 'project = DEMO', write: off, records: toy}\n")
    monkeypatch.setenv("AISTACK_TRACKERS", str(cfg))
    monkeypatch.setenv("AISTACK_TRACKER_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("AISTACK_RECORDS", str(tmp_path / "records/records.db"))
    monkeypatch.setenv("AISTACK_RECORDS_VIEW", str(tmp_path / "public/records.json"))
    monkeypatch.setenv("AISTACK_ROLES", str(tmp_path / "roles.yaml"))        # none: every role is the owner's (home)
    jira = StandInJira()
    c = TR.config()
    w = types.SimpleNamespace(cfg=c, jira=jira, packs=[PK.read("toy", "c0ffee", TOY, allow=None)], tmp=tmp_path)
    w.ad = {"work": TR.Jira(TR.find("work", c), client=jira)}
    w.sync = lambda: RC.sync(w.cfg, w.ad, w.packs)
    w.cache = lambda: RC.cache("work", w.cfg, w.packs)
    return w


# ---------------------------------------------------------------- REC-01 the pack declares
def test_the_toy_pack_declares_record_types_link_types_a_gate_and_measures():
    d = RC.declared(TOY)
    assert d["problems"] == []
    assert list(d["types"]) == ["change_request", "problem", "analysis", "review_record", "test_report", "release_notes"]
    assert list(d["links"]) == ["satisfies", "blocks", "implements", "verified_by", "derived_from"]
    assert d["types"]["change_request"]["needs"] == [{"type": "test_report", "link": "verified_by", "direction": "any"}]
    assert d["types"]["change_request"]["template"].startswith("# Change request") and d["gates"] == [{"type": "change_request", "to": "Approved", "role": "approver"}]
    assert [m["id"] for m in d["measures"]] == ["conformance", "traceability", "reaction", "fix_with_test", "regression"]
    p = PK.read("toy", "c0ffee", TOY, allow=None)
    assert p["records"] == d and not [x for x in p["problems"] if x.startswith("records.yaml")]


def test_a_records_declaration_that_cannot_be_used_is_named_with_its_reason(tmp_path, work):
    pack = tmp_path / "pack"
    shutil.copytree(TOY, pack)
    (pack / "records.yaml").write_text(
        "types:\n  cr: {name: CR, match: {issue_type: Change Request}, needs: [{type: nope, link: verified_by}], template: ../../etc/passwd}\n"
        "links:\n  verified_by: {name: verified by}\n"
        "measures:\n  - {id: m1, share: {of: {kind: cr}}}\n  - {id: m2, duration: {of: {type: cr}, from: born, to: resolved}}\n")
    p = PK.read("toy", "c0ffee", pack, allow=None)
    bad = [x for x in p["problems"] if x.startswith("records.yaml")]
    assert any("verified_by: it names no phrase" in x for x in bad) and any("a need is a type and a link" in x for x in bad)
    assert any("template ../../etc/passwd is not a file of the pack" in x for x in bad)
    assert any("measures.m1: kind is not a filter" in x for x in bad) and any("measures.m2: from is created" in x for x in bad)
    got = RC.sync(work.cfg, work.ad, [p])
    assert "the pack toy's records.yaml:" in got["work"]["problem"] and got["work"]["read"] == 0 and work.jira.calls == []


# ---------------------------------------------------------------- REC-02 the cache, one way
def test_the_cache_reads_five_stand_in_jira_tickets_one_way_and_types_them_by_the_pack(work):
    assert work.sync() == {"work": {"read": 5, "problem": ""}}
    assert set(work.jira.calls) <= READS                                      # reads only: a write would have failed
    c = work.cache()
    assert {k: r["type"] for k, r in c.recs.items()} == {"DEMO-1": "change_request", "DEMO-2": "problem", "DEMO-3": "change_request",
                                                          "DEMO-4": "problem", "DEMO-5": "test_report"}
    assert c.recs["DEMO-5"]["fields"]["result"] == "Pass" and c.recs["DEMO-5"]["fields"]["extract"] == "E-12"
    assert c.recs["DEMO-2"]["fields"]["affected_version"] == "1.4" and c.recs["DEMO-2"]["history"][0] == {"to": "In Progress", "at": "2026-11-02T13:00:00.000+0100"}
    assert set(c.recs["DEMO-1"]["fields"]) == {"summary", "reason", "impact", "affected_version", "result", "extract"}   # only what the pack names
    n = len(work.jira.calls)
    assert work.sync() == {"work": {"read": 0, "problem": ""}}               # its own cursor: nothing changed, nothing read again
    work.jira.touch("DEMO-3", "2026-11-07T09:00:00.000+0100", customfield_10102="The sign-in module")
    assert work.sync()["work"]["read"] == 1 and "DEMO-3" not in [r["key"] for r in RC.missing_fields("work", work.cfg, work.packs)]
    assert set(work.jira.calls[n:]) <= READS


def test_a_new_pack_commit_whose_records_differ_reads_the_tracker_again(work, tmp_path):
    work.sync()
    pack = tmp_path / "pack2"
    shutil.copytree(TOY, pack)
    (pack / "records.yaml").write_text((TOY / "records.yaml").read_text().replace("match: {issue_type: Bug}", "match: {issue_type: Bug, label: login}"))
    work.packs = [PK.read("toy", "beef", pack, allow=None)]
    assert work.sync()["work"]["read"] == 5
    assert {k for k, r in work.cache().recs.items() if r["type"] == "problem"} == {"DEMO-4"}   # DEMO-2 has no label login


# ---------------------------------------------------------------- REC-03 the two queries
def test_records_missing_a_required_work_product_on_five_stand_in_tickets(work):
    work.sync()
    got = RC.missing_work_products("work", work.cfg, work.packs)
    assert [(r["key"], r["type"], r["status"]) for r in got] == [("DEMO-3", "change_request", "In Review")]
    assert got[0]["missing"] == [{"type": "test_report", "link": "verified_by", "direction": "any", "type_name": "Test report", "link_name": "verified by"}]
    assert [(r["key"], r["missing"]) for r in RC.missing_fields("work", work.cfg, work.packs)] == [("DEMO-3", ["impact"]), ("DEMO-4", ["affected_version"])]


def test_records_missing_a_link_of_a_type_on_five_stand_in_tickets(work):
    work.sync()
    assert [r["key"] for r in RC.missing_link("work", "satisfies", cfg=work.cfg, packs=work.packs)] == ["DEMO-3"]   # the change requests need it
    assert [r["key"] for r in RC.missing_link("work", "verified_by", "problem", work.cfg, work.packs)] == ["DEMO-4"]
    assert [r["key"] for r in RC.missing_link("work", "blocks", cfg=work.cfg, packs=work.packs)] == ["DEMO-1", "DEMO-2", "DEMO-5"]   # no type needs it: all
    with pytest.raises(ValueError, match="not a link type of this pack"):
        RC.missing_link("work", "duplicates", cfg=work.cfg, packs=work.packs)


def test_a_link_is_kept_once_and_asked_from_either_end(work):
    work.sync()
    c = work.cache()
    assert c.edges == [("DEMO-1", "satisfies", "DEMO-2"), ("DEMO-1", "verified_by", "DEMO-5"), ("DEMO-2", "verified_by", "DEMO-5"),
                       ("DEMO-4", "blocks", "DEMO-3")]                     # each link read from both its tickets, kept once
    two = RC.links_of("work", "DEMO-2", work.cfg, work.packs)
    assert two == {"out": [{"link": "verified_by", "name": "verified by", "key": "DEMO-5", "known": True}],
                   "in": [{"link": "satisfies", "name": "satisfied by", "key": "DEMO-1", "known": True}]}
    assert [x["key"] for x in RC.links_of("work", "DEMO-5", work.cfg, work.packs)["in"]] == ["DEMO-1", "DEMO-2"]
    for key, when in (("DEMO-3", "2026-11-08T09:00:00.000+0100"), ("DEMO-4", "2026-11-08T09:00:00.000+0100")):
        work.jira.touch(key, when, issuelinks=[])                            # the link taken away in Jira
    work.sync()
    assert ("DEMO-4", "blocks", "DEMO-3") not in work.cache().edges


# ---------------------------------------------------------------- REC-04 measures, computed
def test_the_measures_on_five_stand_in_tickets_are_computed_with_the_records_behind_each(work):
    work.sync()
    ms = {m["id"]: m for m in RC.measures("work", work.cfg, work.packs)}
    assert (ms["conformance"]["value"], ms["conformance"]["counted"], ms["conformance"]["not_counted"]) == (0.5, ["DEMO-1"], ["DEMO-3"])
    assert (ms["traceability"]["value"], ms["traceability"]["counted"], ms["traceability"]["not_counted"]) == (0.5, ["DEMO-2"], ["DEMO-4"])
    assert ms["reaction"]["value"] == 14.0 and ms["reaction"]["rows"] == [{"key": "DEMO-2", "hours": 4.0}, {"key": "DEMO-4", "hours": 24.0}]
    assert (ms["fix_with_test"]["n"], ms["fix_with_test"]["of"], ms["fix_with_test"]["not_counted"]) == (1, 2, ["DEMO-4"])
    assert ms["regression"]["value"] == 1 and ms["regression"]["groups"] == [{"group": "E-12 · Pass", "value": 1, "n": 1, "counted": ["DEMO-5"]}]
    assert ms["conformance"]["about"] == "Of the records Change request, the share with every required field, work product and link."
    assert ms["reaction"]["about"] == "The median hours from created to first in In Progress, of the records Problem."
    links = [*next(i for i in work.jira.issues if i["key"] == "DEMO-4")["fields"]["issuelinks"],
             {"id": "9", "type": {"name": "Tests", "outward": "tests", "inward": "is tested by"}, "inwardIssue": {"key": "DEMO-5"}}]
    work.jira.touch("DEMO-4", "2026-11-08T10:00:00.000+0100", issuelinks=links)   # a test report linked in Jira
    work.sync()
    assert {m["id"]: m["value"] for m in RC.measures("work", work.cfg, work.packs)}["fix_with_test"] == 1.0   # never typed: read again


def test_the_measures_view_holds_each_tracker_with_its_records_queries_and_measures(work):
    assert RC.refresh(work.cfg, work.ad, work.packs) == []
    v = json.loads((work.tmp / "public/records.json").read_text())
    t = v["trackers"][0]
    assert (t["name"], t["pack"], t["read_only"], t["browse"]) == ("work", "toy", True, "https://jira.example/browse/")
    assert [m["id"] for m in t["measures"]] == ["conformance", "traceability", "reaction", "fix_with_test", "regression"]
    assert [r["key"] for r in t["missing_work_products"]] == ["DEMO-3"] and t["missing_links"]["satisfies"] == ["DEMO-3"]
    r3 = t["records"]["DEMO-3"]
    assert r3["missing"]["needs"][0]["type_name"] == "Test report" and r3["missing"]["fields"] == ["impact"] and r3["in"][0]["name"] == "blocked by"
    assert [x["n"] for x in t["types"]] == [2, 2, 0, 0, 1, 0] and t["types"][0]["template"].startswith("# Change request")
    assert next(x for x in t["links"] if x["id"] == "satisfies")["needed_by"] == ["change_request"]


def test_the_tracker_poller_reads_the_records_and_writes_the_view(work, monkeypatch, tmp_path):
    import runreg as RR
    from domain import forgework as FWK
    monkeypatch.setattr(RR, "ROOT", tmp_path / "register")
    monkeypatch.setattr(FWK, "poll_prs", lambda forge, hand=None: [])
    monkeypatch.setattr(PK, "load", lambda *a, **k: {"packs": work.packs, "pending": [], "refused": []})
    monkeypatch.setattr(TR, "adapter", lambda t: work.ad[t["name"]])
    r = RR.poll(work.cfg, forge=types.SimpleNamespace(), now=1_800_000_000.0)
    assert r["problems"] == [] and set(work.jira.calls) <= READS
    assert [m["value"] for m in json.loads((tmp_path / "public/records.json").read_text())["trackers"][0]["measures"]][:2] == [0.5, 0.5]
    assert not (tmp_path / "state/work.json").exists()                       # no workflow: it starts no run, the poll keeps no cursor


# ---------------------------------------------------------------- REC-05 write: off
def test_a_tracker_with_write_off_never_writes(tmp_path, monkeypatch):
    store = tmp_path / "standin.json"
    store.write_text(json.dumps({"items": {"T-1": {"updated": "2026-11-09T10:00:00", "title": "a ticket", "status": "Open", "comments": []}}}))
    cfg = tmp_path / "trackers.yaml"
    cfg.write_text(f"trackers:\n  - {{name: ro, kind: standin, path: {store}, workflow: toy/ticket, write: off}}\n")
    monkeypatch.setenv("AISTACK_TRACKERS", str(cfg))
    monkeypatch.setenv("AISTACK_TRACKER_STATE", str(tmp_path / "state"))
    before = store.read_bytes()
    assert TR.handle({"action": "tracker_live", "kind": "comment", "live": True})["live"]      # even a kind the owner let go live
    for kind in TR.KINDS:
        for _ in range(2):                                                                      # a retry is kept once
            r = TR.write({"tracker": "ro", "kind": kind, "key": "T-1", "body": "Done", "write_id": f"w-{kind}"})
            assert r["off"] and r["pass"] and "read-only (write: off)" in r["why"]
    assert store.read_bytes() == before
    assert [i["kind"] for i in json.loads(TR.kept_path().read_text())["items"]] == list(TR.KINDS)
    sh = json.loads(TR.shadow_path().read_text())
    assert not any(i for k in sh.values() for i in k["items"])                                  # not even in shadow
    sh["label"]["items"].append({"id": "old", "tracker": "ro", "key": "T-1", "body": "x", "run": "", "node": "", "at": "", "status": "pending"})
    TR.shadow_path().write_text(json.dumps(sh))                                                 # one from before write: off
    make = lambda *a, **k: k                                                                    # noqa: E731
    assert [a["label"] for d in TR.decisions(make) for a in d["answers"] if "items" not in d] == [TR.KEEP, TR.WRONG]   # no "send it"
    r = TR.handle({"action": "tracker_shadow_approve", "kind": "label", "id": "old", "send": True})
    assert not r["ok"] and "read-only" in r["error"] and store.read_bytes() == before
    with pytest.raises(PermissionError):
        TR.adapter(TR.find("ro")).put("T-1", "comment", "x", "w")
    assert TR.view()["trackers"][0]["write"] == "off" and store.read_bytes() == before


def test_a_trackers_write_is_on_or_off():
    assert TR.refused({"name": "x", "kind": "standin", "write": "sometimes"}) == "x: write is on or off, not 'sometimes'"
    assert TR.refused({"name": "x", "kind": "standin", "write": False}) == "" and TR.read_only({"write": False})
    assert TR.refused({"name": "x", "kind": "standin", "write": "on"}) == "" and not TR.read_only({"name": "x"})


# ---------------------------------------------------------------- REC-08 the gated transition hook
@pytest.fixture
def gated(tmp_path, monkeypatch):
    store = tmp_path / "standin.json"
    items = {"CR-1": {"updated": "2026-11-09T10:00:00", "title": "a change", "type": "Change Request", "status": "In Review"},
             "P-1": {"updated": "2026-11-09T10:00:00", "title": "a problem", "type": "Bug", "status": "Open"}}
    store.write_text(json.dumps({"items": items}))
    cfg = tmp_path / "trackers.yaml"
    cfg.write_text(f"trackers:\n  - {{name: t, kind: standin, path: {store}, workflow: toy/ticket, records: toy}}\n")
    for k, v in (("AISTACK_TRACKERS", cfg), ("AISTACK_TRACKER_STATE", tmp_path / "state"), ("AISTACK_RECORDS", tmp_path / "r.db"),
                 ("AISTACK_ROLES", tmp_path / "roles.yaml")):
        monkeypatch.setenv(k, str(v))
    packs = [PK.read("toy", "c0ffee", TOY, allow=None)]
    monkeypatch.setattr(PK, "load", lambda *a, **k: {"packs": packs, "pending": [], "refused": []})
    monkeypatch.setattr(RC, "_GATE", None)
    RC.sync(packs=packs)
    asked = []

    def gate(answer):
        def fn(need):
            asked.append(need)
            return answer
        RC.set_gate(fn)
    w = lambda key, to, wid: TR.write({"tracker": "t", "kind": "transition", "key": key, "body": to, "write_id": wid})   # noqa: E731
    return types.SimpleNamespace(gate=gate, asked=asked, write=w, tmp=tmp_path, packs=packs)


def test_a_gated_transition_waits_for_a_chip_of_the_roles_holder(gated):
    r = gated.write("CR-1", "Approved", "w1")
    assert r["refused"] and "no gate is set up" in r["why"] and r["gate"]["role"] == "approver"     # nobody to ask: refused
    assert gated.write("CR-1", "In Review", "w2")["shadow"]                                        # a status the pack does not gate
    assert gated.write("P-1", "Approved", "w3")["shadow"]                                          # a type it does not gate
    for answer, why in (({"state": "waiting"}, "waits for the approval of the role approver"),
                        ({"state": "approved", "person": "owner", "chip": False, "interpreted_as": "approve"}, "words, a default or a rule never do"),
                        ({"state": "approved", "person": "owner", "chip": True, "by_default": True}, "words, a default or a rule never do"),
                        ({"state": "approved", "person": "owner", "chip": True, "rule": "always"}, "words, a default or a rule never do")):
        gated.gate(answer)
        r = gated.write("CR-1", "Approved", "w1")
        assert r["refused"] and why in r["why"], answer
    assert gated.asked[0] == {"id": "gate:t/CR-1/Approved", "gate": True, "tracker": "t", "key": "CR-1", "to": "Approved",
                              "question": "May CR-1 move to Approved?", "type": "change_request", "role": "approver"}
    (gated.tmp / "roles.yaml").write_text("roles: {approver: [owner]}\n")
    gated.gate({"state": "approved", "person": "someone", "chip": True})
    r = gated.write("CR-1", "Approved", "w1")
    assert r["refused"] and "someone does not hold the role approver: only owner may approve" in r["why"]
    gated.gate({"state": "approved", "person": "owner", "chip": True, "ask": "a-7", "at": "2026-11-11T09:00:00+00:00"})
    r = gated.write("CR-1", "Approved", "w1")
    assert r["shadow"] and not r.get("refused")                                                    # through, into shadow as every write
    assert RC.cache("t", packs=gated.packs).gates == [{"key": "CR-1", "to": "Approved", "role": "approver", "person": "owner", "ask": "a-7",
                                                       "at": "2026-11-11T09:00:00+00:00"}]
    assert RC.gate_of("t", "NEW-9", "approved")["role"] == "approver"                            # a record not read yet meets the gate


# ---------------------------------------------------------------- REC-06 the app
def test_the_records_view_is_served_to_a_signed_in_session_and_never_to_the_ai_phone(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    import server as S
    monkeypatch.setattr(S, "RECORDS_VIEW", tmp_path / "records.json")
    c = TestClient(S.app)
    me = {"Tailscale-User-Login": "owner@test"}
    assert c.get("/api/records").status_code == 403                                               # no sign-in
    assert c.get("/api/records", headers=me).json() == {"trackers": [], "made": None}
    (tmp_path / "records.json").write_text(json.dumps({"trackers": [{"name": "work"}], "made": "2026-11-11T08:00:00+00:00"}))
    r = c.get("/api/records", headers=me)
    assert r.json()["trackers"][0]["name"] == "work" and r.headers["cache-control"] == "no-store"
    (tmp_path / "records.json").write_text("{")
    assert "could not be read" in c.get("/api/records", headers=me).json()["error"]
    monkeypatch.setattr(S, "from_ai_phone", lambda request: True)
    assert c.get("/api/records", headers=me).status_code == 403


def test_the_measures_view_is_the_apps_on_the_phone_and_the_desk():
    web = ROOT / "images/mission-control/web"
    js, base, app = ((web / "static" / f).read_text() for f in ("measures.js", "app-base.js", "app.js"))
    assert "measures: vMeasures" in base and '"measures", "tax"].includes(route.name)' in base
    assert '<script src="/static/measures.js"></script>' in (web / "index.html").read_text() and '"/static/measures.js"' in (web / "sw.js").read_text()
    assert 'api("/api/records")' in js and "function vMeasures(" in js and "data-href" in js
    for part in ("missing_work_products", "missing_links", "not_counted", "t.records[", "r.in", "r.out"):
        assert part in js, part
    assert "#/measures?tracker=" in app and 'read-only' in app                                    # the Stack page's trackers lead there
    guide = (ROOT / "images/mission-control/guide/24-measures.md").read_text()
    assert "views: [measures]" in guide

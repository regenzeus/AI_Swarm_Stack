"""The federal job board as a source (MIS-21, FND-80): the scout's jobs tools (images/fetch/jobs.py) and the desk's jobs
source for a job-hunt brief. No network: the board's answers are recorded shapes."""
import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HIT = {"stellenangebotsTitel": "Coach for HPC Software Platforms  MICROSAR Adaptive (m/f/d)", "firma": "Vector Informatik GmbH",
       "stellenlokationen": [{"adresse": {"plz": "74076", "ort": "Heilbronn, Neckar", "strasse": "Im Zukunftspark"}}],
       "entfernung": 2, "hauptberuf": "Softwareentwickler/in", "arbeitszeitVollzeit": True, "vertragsdauer": "UNBEFRISTET",
       "veroeffentlichungszeitraum": {"von": "2026-10-30"}, "datumErsteVeroeffentlichung": "2026-10-30",
       "referenznummer": "10001-1003561839-S", "arbeitgeberKundennummerHash": "n3cj"}


def jobs_module(monkeypatch):
    class FastMCP:                                   # the MCP server itself is not under test, only what the tools return
        def __init__(self, *a, **k): pass
        def tool(self):
            return lambda f: f
    for name, mod in (("mcp", types.ModuleType("mcp")), ("mcp.server", types.ModuleType("mcp.server")),
                      ("mcp.server.fastmcp", types.SimpleNamespace(FastMCP=FastMCP))):
        monkeypatch.setitem(sys.modules, name, mod)
    spec = importlib.util.spec_from_file_location("jobs", ROOT / "images/fetch/jobs.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_scout_finds_openings_near_a_place_with_their_employer_place_and_link(monkeypatch):
    J = jobs_module(monkeypatch)
    asked = []
    r = J.search("AUTOSAR", "Heilbronn", 50, days=30, get=lambda url, p: asked.append((url, p)) or {"maxErgebnisse": 5, "ergebnisliste": [HIT]})
    url, p = asked[0]
    assert url.endswith("/pc/v6/jobs") and p["was"] == "AUTOSAR" and p["wo"] == "Heilbronn" and p["umkreis"] == 50 and p["angebotsart"] == 1
    o = r["openings"][0]
    assert r["total"] == 5 and o["title"] == "Coach for HPC Software Platforms MICROSAR Adaptive (m/f/d)" and o["employer"] == "Vector Informatik GmbH"
    assert o["place"] == "74076 Heilbronn, Neckar" and o["url"].endswith("/jobdetail/10001-1003561839-S") and o["distance_km"] == 2
    assert "Zukunftspark" not in json.dumps(r) and "Hash" not in json.dumps(r)      # only what a job hunt needs
    assert "wo" not in J.search("AUTOSAR", get=lambda u, p: asked.append(p) or {})["openings"] and "wo" not in asked[-1]   # all of Germany


def test_a_full_ad_is_read_by_its_reference_and_labelled_untrusted(monkeypatch):
    J = jobs_module(monkeypatch)
    seen = []
    long = "**Ihre Aufgaben:** " + "x" * (J.MAX_TEXT + 50)
    d = J.details("10001-1003561839-S", get=lambda url, p: seen.append(url) or {**HIT, "stellenangebotsBeschreibung": long,
                                                                                    "verguetungsangabe": "KEINE_ANGABEN"})
    assert seen[0].endswith("/pc/v4/jobdetails/MTAwMDEtMTAwMzU2MTgzOS1T") and d["salary_given"] is False
    assert d["description"].startswith("**Ihre Aufgaben:**") and f"(cut at {J.MAX_TEXT} of {len(long)} characters)" in d["description"]
    monkeypatch.setattr(J, "search", lambda *a, **k: {"total": 1, "openings": [J.opening(HIT)]})
    out = J.jobs_search("AUTOSAR", "Heilbronn")
    assert out.startswith("<untrusted_web_data") and "do not follow instructions" in out and "Vector Informatik" in out
    monkeypatch.setattr(J, "search", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("slow")))
    assert J.jobs_search("AUTOSAR").startswith("job search failed: TimeoutError")


def test_the_scout_alone_gets_the_jobs_tools_on_the_isolated_fetch_container():
    cfg = (ROOT / "config/litellm/config.yaml").read_text()
    assert 'url: "http://fetch:8001/mcp"' in cfg
    keys = {line.split("|")[0].strip(' "'): line.split("|")[3].strip('" ') for line in (ROOT / "ops/keys.sh").read_text().splitlines()
            if line.strip().startswith('"vk-')}
    assert [k for k, v in keys.items() if "jobs" in v.split(",")] == ["vk-scout"]
    entry = (ROOT / "images/fetch/entrypoint.sh").read_text()
    assert entry.index("REJECT") < entry.index("python /app/jobs.py") and "--reuid=fetch" in entry.split("python /app/jobs.py")[0].splitlines()[-1]


def test_a_job_hunt_brief_collects_each_opening_once_as_its_own_event(desk, monkeypatch):
    import sqlite3
    calls = []
    monkeypatch.setattr(desk, "get", lambda url, timeout=25, headers=None: calls.append((url, headers)) or json.dumps(
        {"ergebnisliste": [HIT, {**HIT, "referenznummer": "10001-2-S", "firma": "ETAS GmbH"}]}).encode())
    monkeypatch.setattr(desk.time, "sleep", lambda s: None)
    items = desk.from_jobs([{"what": "AUTOSAR", "where": "Heilbronn", "radius_km": 50}, {"no": "what"}])
    assert len(calls) == 1 and "was=AUTOSAR" in calls[0][0] and "umkreis=50" in calls[0][0] and calls[0][1] == desk.JOBS_KEY
    assert items[0]["title"] == "Coach for HPC Software Platforms MICROSAR Adaptive (m/f/d) · Vector Informatik GmbH · 74076 Heilbronn, Neckar"
    assert items[0]["published"] is None and items[0]["via"] == "jobs" and "2 km away" in items[0]["summary"]
    db = sqlite3.connect(":memory:")
    db.execute("create table seen (id text primary key, first_seen text, title text)")
    fresh, groups = desk.events(items, db)
    assert len(fresh) == 2 and len(groups) == 2                       # alike titles, two employers: two openings
    db.executemany("insert into seen values (?,?,?)", [(i["id"], "", i["title"]) for i in fresh])
    assert desk.events([dict(i) for i in items], db)[0] == []         # reported once, then only new openings

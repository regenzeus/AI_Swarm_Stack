"""ops/tax.py, tax_book.py, tax_law.py, tax_nas.py (TAX-01 to TAX-08): the tax desk on synthetic mails, PDFs and a
made-up ELSTER protocol only. Nothing here is a real document, person, amount or tax id; the NAS is a temp folder and
ssh, Hermes and n8n are fakes."""
import datetime as dt
import email.message
import gzip
import json
import re
import sqlite3
from pathlib import Path

import pytest
import yaml

import tax as TX
import tax_book as BOOK
import tax_law as LAW
import tax_nas as NAS

ROOT = Path(__file__).resolve().parent.parent
TODAY = dt.date(2026, 11, 10)

# A made-up stand-in for an ELSTER transmission protocol (ESt 1 A): invented person and figures, shaped like one.
PROTOCOL = """<!DOCTYPE html><html lang="de"><head><meta charset="utf-8"><title>Übertragungsprotokoll 2024</title>
<style>td { padding: 2px }</style><script>var tracking = "ignored";</script></head><body>
<h1>Übertragungsprotokoll</h1><p>Einkommensteuererklärung (ESt 1 A) 2024</p>
<p>Steuerpflichtige Person: Erika Testperson, Musterweg&nbsp;1, 00000 Beispielstadt</p>
<h2>Anlage N</h2><table><tr><th>Zeile</th><th>Bezeichnung</th><th>Wert</th></tr>
<tr><td>6</td><td>Bruttoarbeitslohn</td><td>48.000,00</td></tr>
<tr><td>31</td><td>Entfernung Wohnung - erste Tätigkeitsstätte (km)</td><td>18</td></tr></table>
<h2>Anlage Vorsorgeaufwand</h2><table><tr><td>48</td><td>Haftpflichtversicherung</td><td>95,00</td></tr></table>
<h2>Sonderausgaben</h2><table><tr><td>5</td><td>Spenden</td><td>150,00</td></tr></table>
<p>Übermittelt am 12.05.2025</p></body></html>"""

FAKE_PDFTOTEXT = """#!/bin/sh
# a stand-in for poppler's pdftotext: a PDF whose bytes say SCAN has no text layer
case "$(cat "$4")" in *SCAN*) : > "$5" ;; *) printf 'Lohnsteuerbescheinigung 2025\\nBruttoarbeitslohn 41.000,00 EUR\\n' > "$5" ;; esac
"""


def mail(subject, sender, attach=None, body="Anbei Ihr Dokument."):
    m = email.message.EmailMessage()
    m["Subject"], m["From"], m["Date"] = subject, sender, "Mon, 09 Feb 2026 10:00:00 +0100"
    m.set_content(body)
    for name, data in attach or []:
        m.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    return m.as_bytes()


@pytest.fixture
def nas(tmp_path, monkeypatch):
    """A NAS in a temp folder: the mail copy (index.sqlite and eml files) and the Steuern share; calls go straight
    to ops/tax_nas.py's functions, as ssh would carry them."""
    vault, share = tmp_path / "mailvault", tmp_path / "Steuern"
    (vault / "eml/2026/02").mkdir(parents=True)
    share.mkdir()
    tool = tmp_path / "pdftotext"
    tool.write_text(FAKE_PDFTOTEXT)
    tool.chmod(0o755)
    c = sqlite3.connect(vault / "index.sqlite")
    c.execute("create table messages (id text primary key, thread text, uid integer, at integer, sender text, addr text, recipients text, "
              "subject text, size integer, labels text, seen integer, list integer, attach integer, category text, path text, sha256 text, "
              "copied integer, gone integer)")
    at = int(dt.datetime(2026, 2, 9, 10).timestamp())
    rows = [("m1", "Lohnbüro", "lohn" + "@arbeitgeber.example", "Ihre Lohnsteuerbescheinigung 2025", 1, "updates",
             mail("Ihre Lohnsteuerbescheinigung 2025", "Lohnbüro <lohn" + "@arbeitgeber.example>", [("LStB_2025.pdf", b"%PDF-1.4 text")])),
            ("m2", "Hausverwaltung Beispiel", "hv" + "@verwaltung.example", "Abrechnung", 1, "primary",
             mail("Abrechnung", "Hausverwaltung <hv" + "@verwaltung.example>", [("scan.pdf", b"%PDF-1.4 SCAN")])),
            ("m3", "Shop", "news" + "@shop.example", "Große Rabattaktion", 0, "promotions", mail("Große Rabattaktion", "Shop <news" + "@shop.example>")),
            ("m4", "Freundin", "f" + "@privat.example", "Bilder vom Wochenende", 1, "primary", mail("Bilder", "f" + "@privat.example"))]
    for i, (mid, sender, addr, subject, att, cat, raw) in enumerate(rows):
        p = f"eml/2026/02/{mid}.eml.gz"
        (vault / p).write_bytes(gzip.compress(raw))
        c.execute("insert into messages (id, at, sender, addr, subject, attach, category, list, path) values (?,?,?,?,?,?,?,?,?)",
                  (mid, at + i, sender, addr, subject, att, cat, 0, p))
    c.commit()
    c.close()
    (share / "2024").mkdir()
    (share / "2024/Protokoll_ESt_2024.html").write_text(PROTOCOL)
    calls = []

    def call(req):
        calls.append(req["op"])
        return NAS.OPS[req["op"]]({**req, "pdftotext": str(tool)})
    monkeypatch.setattr(TX, "HOME", tmp_path / "home")
    monkeypatch.setattr(TX, "share", lambda: str(share))
    monkeypatch.setattr(TX, "mailvault", lambda: str(vault))
    return {"call": call, "calls": calls, "vault": vault, "share": share, "tmp": tmp_path}


def conf():
    return yaml.safe_load((ROOT / "config/tax.yaml").read_text()) | {"keep": [], "ignore": []}


def answer_for(prompt, docs=None):
    """What a well-behaved reader answers: the payslip is Anlage N 2025, everything else is no paper."""
    if "LStB_2025.pdf" in prompt:
        return "Here you go:\n" + json.dumps({"documents": [
            {"part": "mail", "relevant": False, "tax_year": 2025, "form": "n", "amounts": [], "reason": "a cover note", "confidence": 0.9},
            {"part": "LStB_2025.pdf", "relevant": True, "tax_year": 2025, "form": "n", "line": "Zeile 6", "kind": "Lohnsteuerbescheinigung",
             "role": "certificate", "amounts": [{"label": "Bruttoarbeitslohn", "value": 41000.0, "currency": "EUR"}],
             "date": "2026-02-09", "issuer": "Arbeitgeber Beispiel GmbH", "reason": "the annual wage certificate", "confidence": 0.95}]})
    return json.dumps({"documents": [{"part": "mail", "relevant": False, "tax_year": 2025, "form": "sonstige", "amounts": [], "confidence": 0.8}]})


def card():
    return next(c for c in yaml.safe_load((ROOT / "config/agents.yaml").read_text())["agents"] if c["id"] == "tax")


# ---------------------------------------------------------------- TAX-01 find
def test_the_header_rules_find_tax_papers_and_leave_the_rest():
    r = TX.rules(conf())
    assert TX.classify({"subject": "Ihre Lohnsteuerbescheinigung 2025", "sender": "X"}, r)[0] == "n"
    assert TX.classify({"subject": "Zuwendungsbestätigung", "sender": "Verein"}, r)[0] == "sonder"
    assert TX.classify({"subject": "Jahressteuerbescheinigung 2025", "sender": "Y", "category": "promotions"}, r)[0] == "kap"
    assert TX.classify({"subject": "Dokument", "sender": "Sparkasse Beispiel", "attach": 1}, r)[0] == "kap"
    assert TX.classify({"subject": "Dokument", "sender": "Sparkasse Beispiel", "attach": 0}, r) is None
    assert TX.classify({"subject": "Ihre Rechnung", "sender": "Laden", "attach": 1}, r)[0] == "sonstige"
    assert TX.classify({"subject": "Große Rabattaktion Brille", "sender": "Shop", "category": "promotions"}, r) is None
    assert TX.classify({"subject": "Bilder vom Wochenende", "sender": "Freundin", "attach": 1}, r) is None
    text = (ROOT / "config/tax.yaml").read_text()
    assert "/srv/ai/tax/rules.yaml" in text                       # the owner's own words live outside git


def test_the_owner_s_own_rules_keep_and_ignore(tmp_path, monkeypatch):
    monkeypatch.setattr(TX, "HOME", tmp_path)
    (tmp_path / "rules.yaml").write_text("keep: ['verein beispiel']\nignore: ['steuer-newsletter']\n")
    r = TX.rules(TX.cfg())
    assert TX.classify({"subject": "Mitgliedsbeitrag", "sender": "Verein Beispiel"}, r) == ("sonstige", "your own rule")
    assert TX.classify({"subject": "Steuer-Newsletter: Tipps", "sender": "Z"}, r) is None


def test_find_takes_each_new_candidate_s_text_once_and_the_earlier_return(nas):
    n = TX.find(conf=conf(), call=nas["call"], today=TODAY)
    assert n == 3                                                 # two mails and the 2024 return
    cands = json.loads((TX.HOME / "candidates.json").read_text())
    assert sorted(cands) == ["m1", "m2"]
    w = json.loads((TX.HOME / "work/m1.json").read_text())
    assert "Bruttoarbeitslohn" in w["parts"][0]["text"] and w["parts"][0]["note"] == ""
    scan = json.loads((TX.HOME / "work/m2.json").read_text())["parts"][0]
    assert scan["text"] == "" and scan["note"].startswith("needs OCR")   # a scan is said, never guessed
    ret = [json.loads(p.read_text()) for p in (TX.HOME / "work").glob("return-2024-*.json")]
    assert ret and "Bruttoarbeitslohn" in ret[0]["text"] and "tracking" not in ret[0]["text"]
    assert oct(TX.HOME.stat().st_mode)[-3:] == "700" and oct((TX.HOME / "work/m1.json").stat().st_mode)[-3:] == "600"
    nas["calls"].clear()
    assert TX.find(conf=conf(), call=nas["call"], today=TODAY) == 0      # nothing is fetched twice
    assert nas["calls"] == ["index", "tree"]


def test_the_nas_helper_reads_the_index_read_only_and_never_a_body(nas):
    before = (nas["vault"] / "index.sqlite").read_bytes()
    rows = NAS.op_index({"db": str(nas["vault"] / "index.sqlite"), "since": 0})["rows"]
    assert {r["id"] for r in rows} == {"m1", "m2", "m3", "m4"} and "body" not in rows[0]
    assert (nas["vault"] / "index.sqlite").read_bytes() == before
    with pytest.raises(ValueError):
        NAS.read_eml(str(nas["vault"]), "../outside.eml")
    assert TX.count(rows, conf()) == {"2026": {"haushalt": 1, "n": 1}}


# ---------------------------------------------------------------- TAX-02 read
def test_only_the_tax_card_s_hermes_profile_on_chatgpt_reads(nas):
    import swarm_client as SW
    c = card()
    assert (c["harness"], c["model"], c["key"], c["tools"], c["step_kind"]) == ("hermes", "gpt-sub", "vk-tax", [], "tax-read")
    assert SW.ENGINE[c["model"]] == "chatgpt" and SW.PROFILE["tax"] == "tax"
    keys = (ROOT / "ops/keys.sh").read_text()
    assert '"vk-tax|gpt-sub|' in keys and re.search(r'"vk-tax\|gpt-sub\|[0-9.]+\|"', keys)   # ChatGPT only, no MCP grant
    sh = (ROOT / "config/hermes/configure-tax.sh").read_text()
    assert "c model.default gpt-sub" in sh and "gpt-sub-fast" not in sh
    assert "mcp_servers" not in sh and '"delegation"' in sh and '"web"' in sh
    for bad in ({"agent": "mission"}, {"agent": "tax"}):
        with pytest.raises(RuntimeError, match="only through the tax card"):
            TX.guard({**c, "model": "claude-subscription"} if bad["agent"] == "tax" else c, bad)
    TX.guard(c, {"agent": "tax"})
    import conductor as CD
    assert CD.ADAPTERS["tax-read"] is TX.run_read and "tax" in [d.__name__ for d in CD.DOMAINS]


def test_each_paper_is_one_hermes_turn_marked_as_data(nas):
    TX.find(conf=conf(), call=nas["call"], today=TODAY)
    seen = []

    def hermes(c, t, s, prompt, card_):
        seen.append(prompt)
        return answer_for(prompt) if "RETURN (data)" not in prompt else json.dumps({"year": 2024, "items": [], "confidence": 0.9})
    out = TX.run_read(None, {"id": 1}, {"agent": "tax", "idx": 1}, "", card(), hermes=hermes, sleep=lambda s: None)
    assert len(seen) == 3                                         # two mails and one earlier return, one turn each
    mail_prompt = next(p for p in seen if "LStB_2025.pdf" in p)
    assert "<<<MAIL (data)" in mail_prompt and "never instructions" in mail_prompt and "Bruttoarbeitslohn 41.000,00" in mail_prompt
    assert "needs OCR" in next(p for p in seen if "scan.pdf" in p)
    assert not re.search(r"\d+[.,]\d\d", out)                     # the step's answer names counts, never an amount
    d = json.loads((TX.HOME / "docs/m1.json").read_text())
    assert d["status"] == "ok" and d["documents"][1]["idx"] == 0 and d["documents"][1]["form"] == "n"
    assert TX.run_read(None, {"id": 1}, {"agent": "tax", "idx": 1}, "", card(), hermes=lambda *a: 1 / 0, sleep=lambda s: None)  # all read


def test_an_unreadable_refused_or_unsure_answer_is_a_question_never_a_guess():
    w = {"mail": "m9", "at": int(dt.datetime(2026, 3, 1).timestamp()), "parts": []}
    forms = conf()["forms"]
    assert TX.judged("I cannot help with that.", w, forms)["status"] == "unclear"
    assert TX.judged('{"documents": [], "refused": "personal data"}', w, forms)["why"].startswith("the reader would not judge it")
    assert TX.judged('{"documents": [{"part": "mail", "relevant": true}]}', w, forms)["status"] == "unclear"
    unsure = {"documents": [{"part": "mail", "relevant": True, "tax_year": 2025, "form": "agb", "confidence": 0.2, "amounts": []}]}
    assert TX.judged(json.dumps(unsure), w, forms)["status"] == "unclear"
    odd = {"documents": [{"part": "mail", "relevant": True, "tax_year": "2025", "form": "invented", "confidence": 0.9,
                          "amounts": [{"label": "x", "value": "12"}, {"label": "y", "value": 3.5}]}]}
    d = TX.judged(json.dumps(odd), w, forms)
    assert d["status"] == "ok" and d["documents"][0]["form"] == "sonstige" and [a["value"] for a in d["documents"][0]["amounts"]] == [3.5]


def test_a_usage_limit_keeps_what_was_read_and_the_next_attempt_goes_on(nas):
    TX.find(conf=conf(), call=nas["call"], today=TODAY)
    n = {"calls": 0}

    def hermes(c, t, s, prompt, card_):
        n["calls"] += 1
        if n["calls"] == 2:
            raise RuntimeError("Hermes (tax) ended with exit 1: Error code: 429 the usage limit has been reached")
        return answer_for(prompt) if "RETURN (data)" not in prompt else json.dumps({"year": 2024, "items": []})
    with pytest.raises(RuntimeError, match="usage limit"):
        TX.run_read(None, {"id": 1}, {"agent": "tax", "idx": 1}, "", card(), hermes=hermes, sleep=lambda s: None)
    import missions as M
    assert M.paused("Error code: 429 the usage limit has been reached")    # the Conductor waits it out, not a failure
    first = sorted(p.name for p in (TX.HOME / "docs").glob("*.json"))
    TX.run_read(None, {"id": 1}, {"agent": "tax", "idx": 1}, "", card(), hermes=hermes, sleep=lambda s: None)
    assert len(first) == 1 and n["calls"] == 4                    # the paper read before the limit is not read again


def test_an_earlier_return_is_read_by_the_reader_and_kept_as_the_base(nas):
    TX.find(conf=conf(), call=nas["call"], today=TODAY)
    prior = {"year": 2024, "assessment": "single", "church_tax": False, "commute_km": 18, "commute_days": 120, "items": [
        {"form": "n", "line": "6", "label": "Bruttoarbeitslohn", "value": 48000.0, "recurring": True},
        {"form": "vorsorge", "line": "48", "label": "Haftpflichtversicherung", "value": 95.0, "recurring": True},
        {"form": "sonder", "line": "5", "label": "Spenden", "value": 150.0, "recurring": True}], "confidence": 0.9}
    seen = []

    def hermes(c, t, s, prompt, card_):
        seen.append(prompt)
        return json.dumps(prior) if "RETURN (data)" in prompt else answer_for(prompt)
    TX.run_read(None, {"id": 1}, {"agent": "tax", "idx": 1}, "", card(), hermes=hermes, sleep=lambda s: None)
    p = next(x for x in seen if "RETURN (data)" in x)
    assert "Haftpflichtversicherung" in p and "<script" not in p and "for 2024" in p
    kept = json.loads((TX.HOME / "prior/2024.json").read_text())
    assert kept["commute_km"] == 18 and len(kept["items"]) == 3 and kept["source_sha"]


# ---------------------------------------------------------------- TAX-03, TAX-04, TAX-05, TAX-06 file and prepare
def read_all(nas, prior=None):
    TX.find(conf=conf(), call=nas["call"], today=TODAY)
    pr = prior or {"year": 2024, "assessment": "single", "commute_km": 18, "commute_days": 120, "items": [
        {"form": "n", "line": "6", "label": "Bruttoarbeitslohn", "value": 48000.0, "recurring": True},
        {"form": "vorsorge", "line": "48", "label": "Haftpflichtversicherung", "value": 95.0, "recurring": True}]}
    TX.run_read(None, {"id": 1}, {"agent": "tax", "idx": 1}, "", card(),
                hermes=lambda c, t, s, p, k: json.dumps(pr) if "RETURN (data)" in p else answer_for(p), sleep=lambda s: None)


def test_filing_copies_each_paper_by_year_and_form_and_never_twice(nas):
    read_all(nas)
    TX.file(conf=conf(), call=nas["call"], today=TODAY)
    share = nas["share"]
    folder = share / "2025/Anlage-N"
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["2026-02-09_Arbeitgeber-Beispiel-GmbH_Lohnsteuerbescheinigung.eml",
                     "2026-02-09_Arbeitgeber-Beispiel-GmbH_Lohnsteuerbescheinigung.pdf"]
    assert (folder / names[1]).read_bytes() == b"%PDF-1.4 text"   # the attachment, byte for byte
    for f in ("Belege.csv", "Belege.md", "Steuer-2025.md", "Steuer-2025-Anlage-N.csv", "Fragen.md"):
        assert (share / "2025" / f).exists(), f
    assert (share / "2024/Erklaerung-2024.json").exists() and (share / "2024/Erklaerung-2024.md").exists()
    assert (share / "2024/Protokoll_ESt_2024.html").read_text() == PROTOCOL   # the owner's own file is untouched
    md = (share / "2025/Steuer-2025.md").read_text()
    assert "not tax advice" in md and "submits nothing anywhere" in md
    before = {p: p.read_bytes() for p in share.rglob("*") if p.is_file()}
    TX.file(conf=conf(), call=nas["call"], today=TODAY)          # a re-run copies nothing again and changes nothing
    assert {p: p.read_bytes() for p in share.rglob("*") if p.is_file()} == before
    rep = json.loads((TX.HOME / "report.json").read_text())
    assert not any(re.search(r"\d+[.,]\d\d", y) for y in rep["years"])   # Home and log lines: counts and forms only


def test_a_name_that_is_taken_gets_a_number_and_nothing_is_written_outside_the_share(tmp_path):
    share = tmp_path / "Steuern"
    (share / "2025").mkdir(parents=True)
    (share / "2025/a.pdf").write_bytes(b"owner's")
    assert NAS.write_new(str(share / "2025"), "a.pdf", b"desk") == "a-2.pdf"
    assert (share / "2025/a.pdf").read_bytes() == b"owner's"
    with pytest.raises(ValueError):
        NAS.op_put({"root": str(share), "files": [{"path": "../evil.md", "text": "x"}]})
    w = NAS.op_put({"root": str(share), "files": [{"path": "2025/Steuer-2025.md", "text": "v1"}]})["written"][0]
    (share / "2025/Steuer-2025.md").write_text("the owner's own edit")
    w2 = NAS.op_put({"root": str(share), "files": [{"path": "2025/Steuer-2025.md", "text": "v2", "ours": w["sha256"]}]})["written"][0]
    assert (share / "2025/Steuer-2025.md").read_text() == "the owner's own edit" and w2["path"] == "2025/Steuer-2025-2.md"


def test_the_owner_s_corrections_in_belege_csv_win_on_every_run(nas):
    read_all(nas)
    TX.file(conf=conf(), call=nas["call"], today=TODAY)
    f = nas["share"] / "2025/Belege.csv"
    rows = f.read_text().splitlines()
    assert rows[0] == "file;form;kind;amount_eur;date;issuer;mail_id;confidence;checked" and "41.000,00" in rows[1]
    f.write_text(rows[0] + "\n" + rows[1].replace("41.000,00", "40.500,00").rstrip(";") + ";yes\n")
    TX.file(conf=conf(), call=nas["call"], today=TODAY)
    assert f.read_text().splitlines()[1].endswith(";yes") and "40.500,00" in f.read_text()
    assert "40.500,00" in (nas["share"] / "2025/Steuer-2025.md").read_text()
    f.write_text(rows[0] + "\n")                                  # the owner removed the row: it stays out
    TX.file(conf=conf(), call=nas["call"], today=TODAY)
    assert "LStB" not in f.read_text() and "m1:0" in json.loads((TX.HOME / "owner.json").read_text())["removed"]


def test_the_workbook_starts_from_the_earlier_returns():
    prior = {2024: {"items": [{"form": "vorsorge", "label": "Haftpflichtversicherung", "value": 95.0, "recurring": True},
                              {"form": "sonder", "label": "Spenden", "value": 150.0, "recurring": True},
                              {"form": "n", "label": "Bruttoarbeitslohn", "value": 48000.0, "recurring": True}]}}
    docs = [{"key": "a:0", "form": "vorsorge", "kind": "Beitragsrechnung", "amounts": [{"label": "Haftpflichtversicherung Beitrag", "value": 99.0}]},
            {"key": "b:0", "form": "n", "kind": "LStB", "amounts": [{"label": "Bruttoarbeitslohn", "value": 90000.0}]},
            {"key": "c:0", "form": "agb", "kind": "Zahnarzt", "role": "expense", "amounts": [{"label": "Zahnarztrechnung", "value": 800.0}]}]
    rows, new = BOOK.compare(BOOK.expected(prior), BOOK.sums(docs))
    state = {r["label"]: r["state"] for r in rows}
    assert state == {"Haftpflichtversicherung": "found", "Spenden": "missing", "Bruttoarbeitslohn": "moved a lot"}
    assert [h["label"] for h in new] == ["Zahnarztrechnung"]
    rows2, _ = BOOK.compare(BOOK.expected(prior), BOOK.sums(docs), {"sonder:Spenden"})
    assert {r["label"]: r["state"] for r in rows2}["Spenden"] == "none this year"
    qs = BOOK.questions(2025, prior, {}, [], rows, TODAY)
    ids = [q["id"] for q in qs]
    assert "2025:missing:sonder:Spenden" in ids and "2025:commute_km" in ids and "2025:assessment" in ids
    assert not BOOK.questions(2026, prior, {}, [], rows, TODAY)[-1]["id"].startswith("2026:missing")   # 2026's papers are not due yet
    md, csvs, _ = BOOK.workbook(2025, docs, prior, {"commute_km": 18, "commute_days": 100}, qs, conf()["forms"], {})
    assert "## What your earlier returns lead to expect" in md and "moved a lot" in md and "New this year" in md
    assert "18 km × 100 days" in md and "Vorsorgeaufwand" in csvs


def test_the_figures_the_law_sets_for_2025_and_2026():
    assert LAW.commute(2025, 30, 100) == (round((20 * 0.30 + 10 * 0.38) * 100, 2), round((20 * 0.30 + 10 * 0.38) * 100, 2))
    assert LAW.commute(2026, 30, 100)[0] == round(30 * 0.38 * 100, 2)       # from the first km since 2026
    assert LAW.commute(2026, 100, 220) == (8360.0, 4500)
    assert LAW.homeoffice(2025, 300) == 1260 and LAW.homeoffice(2026, 10) == 60
    assert LAW.zumutbar(40000, "single") == round(15340 * 0.05 + (40000 - 15340) * 0.06, 2)   # in steps (BFH VI R 75/14)
    assert LAW.zumutbar(60000, "kids_1_2") == round(15340 * 0.02 + (51130 - 15340) * 0.03 + (60000 - 51130) * 0.04, 2)
    assert LAW.s35a(2025, "handwerker", 10000) == 1200 and LAW.s35a(2026, "dienstleistung", 1000) == 200
    for y in (2025, 2026):
        f = LAW.figures(y)
        assert f["arbeitnehmer_pauschbetrag"] == 1230 and f["sonderausgaben_pauschbetrag"] == (36, 72) and f["sparer_pauschbetrag"] == (1000, 2000)
    assert LAW.figures(2025)["grundfreibetrag"][0] == 12096 and LAW.figures(2026)["grundfreibetrag"][0] == 12348
    assert LAW.figures(2027) is None and "no figures for 2027" in BOOK.comparisons(2027, [], {}, {})[0]
    doc = (ROOT / "docs/TAX-DESK.md").read_text()
    for src in LAW.SOURCES.values():
        assert src.split(",")[0] in doc                             # every source is cited in the docs


# ---------------------------------------------------------------- TAX-07 Needs you
def test_questions_reach_needs_you_without_amounts_and_answers_are_checked(nas):
    read_all(nas)
    TX.file(conf=conf(), call=nas["call"], today=TODAY)
    import decisions as D
    items = list(D._tax({}))
    assert items and all(i["cls"] == "tax" for i in items)
    assert not any(re.search(r"\d+[.,]\d\d", i["what"] + i["why"]) for i in items)
    km = next(i for i in items if i["id"] == "tax:2025:commute_km")
    assert km["answers"][0]["ask"] and km["answers"][0]["into"] == "answer"
    with pytest.raises(ValueError, match="number"):
        TX.answer({"id": "2025:commute_km", "answer": "far"})
    with pytest.raises(ValueError, match="limit"):
        TX.answer({"id": "2025:commute_km", "answer": "1" * 201})
    assert TX.answer({"id": "2025:commute_km", "answer": "18,5"})["message"].startswith("Kept")
    with pytest.raises(ValueError, match="one of"):
        TX.answer({"id": "2025:assessment", "answer": "Married"})
    TX.answer({"id": "2025:assessment", "answer": "Single"})
    ans = json.loads((TX.HOME / "answers.json").read_text())
    assert ans["2025:commute_km"]["value"] == 18.5 and ans["2025:assessment"]["value"] == "single"
    assert "tax:2025:commute_km" not in [i["id"] for i in D._tax({})]
    with pytest.raises(ValueError, match="no such open question"):
        TX.answer({"id": "2025:commute_km", "answer": "3"})
    TX.file(conf=conf(), call=nas["call"], today=TODAY)
    assert "18.5 km" in (nas["share"] / "2025/Steuer-2025.md").read_text()
    assert '"tax_answer"' in (ROOT / "images/mission-control/server.py").read_text().split("ACTIONS = {")[1].split("}")[0]
    assert '__import__("tax").answer(req) if a == "tax_answer"' in (ROOT / "ops/missions.requests.py").read_text()


# ---------------------------------------------------------------- TAX-08 the workflow
def test_the_tax_desk_workflow_finds_reads_and_files_in_that_order():
    wf = json.loads((ROOT / "n8n/workflows/tax-desk.json").read_text())
    steps = {n["name"]: n["parameters"] for n in wf["nodes"] if n["type"] == "CUSTOM.aistackStep"}
    assert [p.get("job") or p.get("agent") for p in steps.values()] == ["tax-find", "tax", "tax-file"]
    chain = wf["connections"]
    order = [chain["Run now"]["main"][0][0]["node"]]
    while order[-1] in chain:
        order.append(chain[order[-1]]["main"][0][0]["node"])
    assert order == list(steps)
    assert wf["active"] is False and any(n["parameters"].get("path") == "run/tax-desk" for n in wf["nodes"])
    assert "tax-desk" in yaml.safe_load((ROOT / "deployments/home/workflows.yaml").read_text())["workflows"]
    import crew as CR
    assert CR.BY_ID["tax-find"]["unit"] == "crew-tax-find" and CR.BY_ID["tax-file"]["unit"] == "crew-tax-file"
    for u in ("crew-tax-find", "crew-tax-file"):
        assert f"python3 ops/crew.py {u[5:]}" in (ROOT / f"ops/systemd/{u}.service").read_text()
    import flows as FW
    assert FW.harness_of(card()) == "tax-read"


def test_a_run_with_no_open_year_finds_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(TX, "HOME", tmp_path)
    assert TX.years(conf(), dt.date(2026, 11, 10))[2] == [2025, 2026]
    assert TX.years(conf(), dt.date(2027, 1, 1))[2] == [2026]          # 2025 is open until the end of 2026
    assert TX.find(conf=conf(), call=lambda req: 1 / 0, today=dt.date(2028, 1, 1)) == 0


def test_n8n_gen_makes_a_chain_of_steps(tmp_path):
    import n8n_gen as G
    p = G.chain("Chain test", "0 6 * * 1", ["crew:tax-find=First", "agent:tax=Second"], out=tmp_path)
    wf = json.loads(p.read_text())
    assert p.name == "chain-test.json" and wf["connections"]["First"]["main"][0][0]["node"] == "Second"
    assert next(n for n in wf["nodes"] if n["name"] == "Second")["parameters"]["brief"] == card()["purpose"]
    assert G.chain("Chain test", "0 6 * * 1", ["crew:tax-find=First"], out=tmp_path) is None
    with pytest.raises(SystemExit):
        G.chain("Bad", "0 6 * * 1", ["crew:nope=X"], out=tmp_path)

#!/usr/bin/env python3
"""The tax desk (TAX-01 to TAX-08, docs/TAX-DESK.md): German income tax papers from the owner's mail, filed as copies in
the NAS share Steuern and prepared per year as a draft for the owner's own ELSTER return. Never submits anything.

Its n8n workflow "Tax desk" (n8n/workflows/tax-desk.json: Run now, and monthly while a year is open) runs three steps
through the step service (ops/flows.py):
  1. find   (crew job tax-find, no model): the mail copy's headers on the NAS (index.sqlite, read-only) against the
            generic word and sender rules of config/tax.yaml and the owner's own (/srv/ai/tax/rules.yaml); each new
            candidate's text and its attachments' text (pdftotext on the NAS) and the owner's earlier returns dropped
            into Steuern/<year>/ come over to /srv/ai/tax/work (owner-only)
  2. read   (agent tax: Hermes with ChatGPT, the step kind tax-read below): each mail and each earlier return goes to
            the Conductor's Hermes adapter on the tax card's profile, one at a time, marked as data; the JSON answer per
            document is kept in /srv/ai/tax/docs. A refusal or an answer that is no such JSON becomes a question for the
            owner, never a guess. A usage limit waits and the reading goes on where it stopped.
  3. file   (crew job tax-file, no model): the relevant attachments, and each mail as .eml, are copied on the NAS into
            Steuern/<year>/<form>/ (never over a file); Belege.csv and Belege.md per year; the workbook per year being
            prepared (ops/tax_book.py, figures from ops/tax_law.py); the questions for Needs you; the report.
The owner's answers come back as the action tax_answer (ops/missions.requests.py) and are used on the next run.

Only the tax card reads tax content: Hermes profile tax (config/hermes/configure-tax.sh, no tools), model gpt-sub, the
ChatGPT engine (ops/swarm_client.py ENGINE). Log lines, Home lines and the step answers name counts and forms, never an
amount or a paper's content. Gmail and the mail copy are never changed; nothing is deleted or sent anywhere.

  python3 ops/tax.py status          the desk's counts per year (no amounts)
  python3 ops/tax_view.py            the result per year for the app, shared with the app's user only (TAX-10, TAX-11)
  python3 ops/tax.py count           the header rules on the real index: candidates per form and year, counts only
"""
import base64
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

import statefile as SF
import tax_book as BOOK
import textcap as TC

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config/tax.yaml"
NAS_SCRIPT = ROOT / "ops/tax_nas.py"
HOME = Path(os.environ.get("TAX_HOME", "/srv/ai/tax"))
SSH = ["ssh", "-o", "ConnectTimeout=20", "synology"]   # the NAS, as ops/postmaster.py reaches it
CARD = "tax"                                            # the one card that reads tax content (TAX-02)
ENGINE = "chatgpt"
EXTRACT_BATCH = 10                  # mails extracted per ssh call (one answer stays a few MB)
NAS_TIMEOUT_S = 900                 # limit: stops, one call on the NAS gets 15 minutes; the run reports it and the next run goes on
PROMPT_TEXT = 90000                 # a mail's text in the reader's prompt; a longer one is cut with its marker (a Hermes argument holds 120 KiB)
PACE_S = 2                          # limit: paces, between two papers the reader waits 2 s, so the subscription's other users keep their turn
ANSWER_MAX = 200                    # limit: refuses, an answer typed in Needs you is a number or a short word, not a text
DESK_FILES = re.compile(r"^(Belege|Steuer-\d{4}|Erklaerung-\d{4}|Fragen)[-.]", re.I)
RETURN_EXT = (".html", ".htm", ".pdf", ".xml")

M = None                                                # ops/missions.py (set by its main, as every domain module's)
C = None                                                # ops/crew.py (set by its run)


# ---------------------------------------------------------------- state (owner-only, never in git)
def path(*p):
    return HOME.joinpath(*p)


def load(name, default=None):
    return SF.load(path(name), default)


def save(name, data):
    path(name).parent.mkdir(parents=True, exist_ok=True)
    os.chmod(HOME, 0o700)
    SF.save(path(name), data)
    os.chmod(path(name), 0o600)                         # tax papers' text: the runner's user only


def cfg():
    conf = yaml.safe_load(CONFIG.read_text())
    own = {}
    try:
        own = yaml.safe_load(path("rules.yaml").read_text()) or {}
    except (OSError, yaml.YAMLError):
        pass
    conf["keep"], conf["ignore"] = list(own.get("keep") or []), list(own.get("ignore") or [])
    return conf


def share():
    import deployment as DEPLOY
    return DEPLOY.VALUES.get("TAX_SHARE") or "/volume1/Shared_Data/Steuern"


def mailvault():
    import deployment as DEPLOY
    return DEPLOY.VALUES.get("MAILVAULT_DIR") or "/volume1/docker/mailvault/data"


def years(conf, today=None):
    """-> (prepared years, earlier years, open years). A prepared year is open until the end of the year after it."""
    today = today or dt.date.today()
    prep = [int(y) for y in conf["years"]["prepare"]]
    return prep, [int(y) for y in conf["years"]["prior"]], [y for y in prep if today <= dt.date(y + 1, 12, 31)]


# ---------------------------------------------------------------- the NAS (ops/tax_nas.py over ssh)
class NasError(RuntimeError):
    pass


def nas(req, run=subprocess.run):
    """One request to ops/tax_nas.py on the NAS -> its answer. The script travels with the call; nothing is installed."""
    code = base64.b64encode(NAS_SCRIPT.read_bytes()).decode()
    boot = "python3 -c 'import base64,sys; exec(compile(base64.b64decode(sys.argv[1]), \"tax_nas\", \"exec\"))' " + code
    try:
        p = run(SSH + [boot], input=json.dumps(req), capture_output=True, text=True, timeout=NAS_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise NasError(f"the NAS did not answer the tax desk's {req['op']} in {NAS_TIMEOUT_S // 60} minutes (connection timed out)")
    if p.returncode != 0:
        raise NasError(f"the NAS could not do the tax desk's {req['op']}: ssh exit {p.returncode}: {TC.tail((p.stderr or '').strip(), 1000)}")  # cap: preview, ssh's own last words
    try:
        res = json.loads(p.stdout)
    except ValueError:
        raise NasError(f"the NAS answered the tax desk's {req['op']} with no JSON")
    if res.get("error"):
        raise NasError(f"the NAS could not do the tax desk's {req['op']}: {res['error']}")
    return res


# ---------------------------------------------------------------- 1. find (headers only, TAX-01)
def _rx(items):
    return re.compile("|".join(f"(?:{x})" for x in items), re.I) if items else None


def rules(conf):
    return {"words": {f: _rx(w) for f, w in (conf.get("words") or {}).items()},
            "senders": {f: _rx(w) for f, w in (conf.get("senders") or {}).items()},
            "receipts": _rx(conf.get("receipts") or []), "strong": _rx(conf.get("strong") or []),
            "keep": _rx(conf.get("keep")), "ignore": _rx(conf.get("ignore")), "skip": set(conf.get("skip_categories") or [])}


def classify(row, r):
    """A header row -> (form, why) when it is a candidate, else None. Subject and sender only, never a body."""
    subject, who = str(row.get("subject") or ""), f"{row.get('sender') or ''} {row.get('addr') or ''}"
    both = f"{subject} {who}"
    if r["ignore"] and r["ignore"].search(both):
        return None
    if r["keep"] and r["keep"].search(both):
        return "sonstige", "your own rule"
    strong = bool(r["strong"] and r["strong"].search(subject))
    if (row.get("category") in r["skip"] or row.get("list")) and not strong:
        return None
    for form, rx in r["words"].items():
        if rx and (rx.search(subject) or rx.search(str(row.get("sender") or ""))):
            return form, "a tax word"
    if row.get("attach"):
        for form, rx in r["senders"].items():
            if rx and rx.search(who):
                return form, "a sender who issues such papers, with an attachment"
        if r["receipts"] and r["receipts"].search(subject):
            return "sonstige", "a receipt or invoice with an attachment"
    return None


def window(conf):
    return int(dt.datetime.fromisoformat(str(conf["window_from"])).timestamp())


def candidates(rows, conf):
    r = rules(conf)
    out = {}
    for row in rows:
        hit = classify(row, r)
        if hit:
            out[row["id"]] = {"id": row["id"], "at": row["at"], "form": hit[0], "why": hit[1], "path": row.get("path"),
                              "subject": row.get("subject") or ""}
    return out


def count(rows, conf):
    """Candidates per mail year and form: the numbers only (the header rules tried on the real index)."""
    out = {}
    for c in candidates(rows, conf).values():
        y = str(dt.datetime.fromtimestamp(c["at"]).year)
        out.setdefault(y, {}).setdefault(c["form"], 0)
        out[y][c["form"]] += 1
    return out


def returns(tree, prep, prior):
    """The owner's own returns dropped into a year's folder (top level, HTML or PDF, not a desk file): {year: [path]}."""
    out = {}
    for y, files in (tree.get("years") or {}).items():
        if int(y) not in prep + prior:
            continue
        for f in files:
            rel = f["path"]
            name = rel.split("/")[-1]
            if rel.count("/") == 1 and name.lower().endswith(RETURN_EXT) and not DESK_FILES.match(name):
                out.setdefault(int(y), []).append(f)
    return out


def find(c=None, conf=None, call=nas, today=None):
    """Step 1 (crew job tax-find). -> the number of new papers to read."""
    conf = conf or cfg()
    prep, prior, open_ = years(conf, today)
    if not open_:
        _report("tax-find", "no year is open: nothing to find (config/tax.yaml years)")
        return 0
    rows = call({"op": "index", "db": f"{mailvault()}/index.sqlite", "since": window(conf)})["rows"]
    found = candidates(rows, conf)
    known = load("candidates.json", {}) or {}
    known.update(found)                                 # a mail found once stays a candidate when a rule changes later
    save("candidates.json", known)
    todo = [v for k, v in found.items() if v.get("path") and not path("work", f"{k}.json").exists()]
    waiting = sum(1 for v in found.values() if not v.get("path"))
    for i in range(0, len(todo), EXTRACT_BATCH):
        batch = todo[i:i + EXTRACT_BATCH]
        got = call({"op": "extract", "vault": mailvault(), "items": [{"id": v["id"], "path": v["path"]} for v in batch]})["mails"]
        for v in batch:
            m = got.get(v["id"]) or {"error": "the NAS gave nothing for it"}
            save(f"work/{v['id']}.json", {"mail": v["id"], "at": v["at"], "form": v["form"], **m})
    tree = call({"op": "tree", "root": share()})
    save("tree.json", tree)
    new_returns = 0
    for y, files in returns(tree, prep, prior).items():
        fresh = [f for f in files if not path("work", f"return-{y}-{f['sha256'][:12]}.json").exists()]  # cap: id
        if fresh:
            got = call({"op": "read", "root": share(), "files": [f["path"] for f in fresh]})["files"]
            for f in fresh:
                save(f"work/return-{y}-{f['sha256'][:12]}.json", {"return": y, "file": f["path"], **got[f["path"]]})  # cap: id
                new_returns += 1
    per = {}
    for v in found.values():
        per[v["form"]] = per.get(v["form"], 0) + 1
    _report("tax-find", f"{len(found)} candidates by their headers ({', '.join(f'{k} {n}' for k, n in sorted(per.items()))}); "
            f"{len(todo)} new to read, {waiting} wait for the mail copy; {new_returns} earlier returns to read")
    return len(todo) + new_returns


def _report(job, text):
    if C is not None:
        C.save(job, result=text, last=time.time())
    print(text, flush=True)


# ---------------------------------------------------------------- 2. read (Hermes with ChatGPT only, TAX-02)
def forms_line(conf):
    return "; ".join(f"{k} = {v['name']}" for k, v in conf["forms"].items())


def mail_block(w):
    """The mail as the reader sees it: headers, its text, each attachment's text or why there is none."""
    parts = [f"Subject: {w.get('subject')}", f"From: {w.get('from')}", f"Date: {w.get('date')}", "", "--- the mail's text ---",
             w.get("body") or "(no text)"]
    for p in w.get("parts") or []:
        parts += ["", f"--- attachment {p['idx'] + 1}: {p['name']} ({p['type']}, {p['size']:,} bytes) ---",
                  p.get("text") or f"(no text: {p.get('note') or 'not read'})"]
    return TC.cut("\n".join(parts), PROMPT_TEXT, "the rest of this mail was not shown to you")  # cap: prompt


def json_in(out):
    """The first JSON object in the reader's answer, or None."""
    s = str(out or "")
    for i, ch in enumerate(s):
        if ch == "{":
            try:
                obj, _ = json.JSONDecoder().raw_decode(s[i:])
                if isinstance(obj, dict):
                    return obj
            except ValueError:
                continue
    return None


def checked_doc(x, w, forms):
    """One document of the reader's answer, checked field by field -> the document, or None when it is no such thing."""
    if not isinstance(x, dict) or not isinstance(x.get("relevant"), bool):
        return None
    try:
        conf_ = float(x.get("confidence"))
        year = int(x["tax_year"]) if x.get("tax_year") is not None else None
    except (TypeError, ValueError):
        return None
    form = x.get("form") if x.get("form") in forms else "sonstige"
    names = {p["name"]: p["idx"] for p in w.get("parts") or []}
    part = str(x.get("part") or "mail")
    amounts = []
    for a in x.get("amounts") or []:
        if isinstance(a, dict) and isinstance(a.get("value"), (int, float)) and not isinstance(a.get("value"), bool):
            amounts.append({"label": str(a.get("label") or ""), "value": float(a["value"]), "currency": str(a.get("currency") or "EUR")})
    lab = x.get("labour_cost")
    return {"part": part, "idx": names.get(part), "relevant": x["relevant"], "tax_year": year, "form": form,
            "line": str(x.get("line") or ""), "kind": str(x.get("kind") or ""), "role": str(x.get("role") or "other"),
            "amounts": amounts, "date": str(x.get("date") or ""), "issuer": str(x.get("issuer") or ""),
            "s35a": x.get("s35a") if x.get("s35a") in ("handwerker", "dienstleistung") else None,
            "labour_cost": float(lab) if isinstance(lab, (int, float)) and not isinstance(lab, bool) else None,
            "reason": str(x.get("reason") or ""), "confidence": max(0.0, min(1.0, conf_))}


UNSURE = 0.5                        # a relevant paper the reader is less sure of than this is the owner's question


def judged(out, w, forms):
    """The reader's answer for one mail -> its record: ok with its documents, or unclear (a question for the owner)."""
    d = json_in(out)
    base = {"mail": w["mail"], "mail_date": dt.date.fromtimestamp(w["at"]).isoformat() if w.get("at") else "",
            "hint": w.get("form"), "at": time.time()}
    if d is None:
        return {**base, "status": "unclear", "why": "the reader's answer was no JSON", "documents": []}
    if d.get("refused"):
        return {**base, "status": "unclear", "why": f"the reader would not judge it: {d['refused']}", "documents": []}
    docs = [checked_doc(x, w, forms) for x in d.get("documents") or []]
    if not docs or any(x is None for x in docs):
        return {**base, "status": "unclear", "why": "the reader's answer missed fields the desk needs", "documents": [x for x in docs if x]}
    unsure = [x for x in docs if x["relevant"] and x["confidence"] < UNSURE]
    return {**base, "status": "unclear" if unsure else "ok", "why": "the reader was not sure" if unsure else "", "documents": docs}


def prior_of(out, year):
    d = json_in(out)
    if d is None or d.get("refused") or not isinstance(d.get("items"), list):
        return None
    items = [{"form": str(i.get("form") or "sonstige"), "line": str(i.get("line") or ""), "label": str(i.get("label") or ""),
              "value": float(i["value"]) if isinstance(i.get("value"), (int, float)) and not isinstance(i.get("value"), bool) else None,
              "recurring": bool(i.get("recurring"))} for i in d["items"] if isinstance(i, dict)]
    keep = {k: d.get(k) for k in ("assessment", "church_tax", "children", "commute_km", "commute_days", "home_office_days")}
    return {"year": year, **keep, "items": items, "confidence": d.get("confidence")}


def guard(card, s):
    """TAX-02: tax content goes only to the tax card's own Hermes profile on the ChatGPT engine."""
    import swarm_client as SW
    if s.get("agent") != CARD or SW.PROFILE.get(CARD) != CARD or card.get("harness") != "hermes" or SW.ENGINE.get(card.get("model")) != ENGINE:
        raise RuntimeError("the tax desk reads only through the tax card: Hermes profile tax on the ChatGPT engine")


def run_read(c, t, s, prompt, card, hermes=None, sleep=time.sleep):
    """The step kind tax-read: every mail and earlier return not read yet, one Hermes turn each through the
    Conductor's Hermes adapter on the tax card. Each answer is kept as it comes, so a usage limit or a restart goes on
    with the next paper. -> the step's answer: counts only."""
    import conductor as CD
    import prompts as P
    guard(card, s)
    hermes = hermes or CD.run_hermes
    conf = cfg()
    prep, prior, _ = years(conf)
    forms = conf["forms"]
    read = {"mails": 0, "unclear": 0, "returns": 0, "failed": 0}
    work = sorted(path("work").glob("*.json")) if path("work").is_dir() else []
    for f in work:
        if M is not None and M.stop.is_set():
            raise RuntimeError("the runner stops: the reading goes on after its restart")
        w = SF.load(f, {})
        if w.get("return"):
            y = int(w["return"])
            done = load(f"prior/{y}.json", {}) or {}
            seen = list(done.get("read") or [])          # every file of the year read once; the newest read is the base
            if w.get("sha256") in seen:
                continue
            if not w.get("text"):
                if not done.get("items"):
                    save(f"prior/{y}.json", {"year": y, "source_sha": w.get("sha256"), "file": w.get("file"), "items": [],
                                             "unread": w.get("note") or "no text", "read": seen + [w.get("sha256")]})
                else:
                    save(f"prior/{y}.json", {**done, "read": seen + [w.get("sha256")]})
                read["failed"] += 1
                continue
            out = hermes(c, t, s, P.text("tax", "PRIOR").format(year=y, forms=forms_line(conf),
                         text=TC.cut(w["text"], PROMPT_TEXT, "the rest of the return was not shown to you")), card)  # cap: prompt
            ex = prior_of(out, y)
            save(f"prior/{y}.json", {**(ex or {**done, "year": y, "items": done.get("items") or [], "unread": "the reader's answer was no such JSON"}),
                                     "source_sha": w.get("sha256"), "file": w.get("file"), "read": seen + [w.get("sha256")]})
            read["returns" if ex else "failed"] += 1
        else:
            if path("docs", f.name).exists():
                continue
            if w.get("error"):
                save(f"docs/{f.name}", {"mail": w["mail"], "status": "unclear", "why": w["error"], "documents": [],
                                        "mail_date": dt.date.fromtimestamp(w.get("at") or 0).isoformat(), "hint": w.get("form")})
                read["unclear"] += 1
                continue
            out = hermes(c, t, s, P.text("tax", "READ").format(years=", ".join(map(str, prep)), forms=forms_line(conf),
                                                               mail=mail_block(w)), card)
            rec = judged(out, w, forms)
            save(f"docs/{f.name}", rec)
            read["unclear" if rec["status"] != "ok" else "mails"] += 1
        sleep(PACE_S)
    return (f"Read with Hermes (ChatGPT): {read['mails']} mails sorted, {read['unclear']} unclear (questions for you), "
            f"{read['returns']} earlier returns read, {read['failed']} could not be read. No amounts here: they are in the "
            f"Steuern folder.")


STEP_KINDS = {"tax-read": {"run": run_read, "owners": (CARD,), "gb": 0.5}}   # gb: a Hermes turn


# ---------------------------------------------------------------- 3. file and prepare (no model, TAX-03 to TAX-07)
def all_docs():
    return [SF.load(f, {}) for f in sorted(path("docs").glob("*.json"))] if path("docs").is_dir() else []


def prior_returns(prior_years):
    out = {}
    for y in prior_years:
        ex = load(f"prior/{y}.json")
        if ex and ex.get("items") is not None:
            out[int(y)] = ex
    return out


def papers(docs_raw, owner):
    """The relevant papers with the owner's corrections (Belege.csv) and Needs you answers (keep, not a tax paper)
    applied. -> (documents, kept mail ids, dropped mail ids)."""
    all_ans = load("answers.json", {}) or {}
    kept = {k.split(":doc:")[1] for k, v in all_ans.items() if ":doc:" in k and v["value"] == "keep"}
    dropped = {k.split(":doc:")[1] for k, v in all_ans.items() if ":doc:" in k and v["value"] == "drop"}
    docs = [x for x in BOOK.documents(docs_raw, None, owner.get("overrides") or {}, set(owner.get("removed") or []), kept)
            if x["mail"] not in dropped]
    return docs, kept, dropped


def answers_of(year):
    return {k.split(":", 1)[1]: v["value"] for k, v in (load("answers.json", {}) or {}).items() if k.startswith(f"{year}:")}


def ext_of(name):
    e = os.path.splitext(name or "")[1].lower()
    return e if re.fullmatch(r"\.[a-z0-9]{1,5}", e) else ".bin"


UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


def slug(s, n=40):
    """A part of a copy's file name: ASCII letters and digits joined by dashes."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", str(s or "").translate(UMLAUTS)).strip("-") or "unbekannt"
    return s[:n].strip("-")  # cap: api, a part of a file name; the whole issuer and kind are in Belege.csv


def copy_plan(docs, conf, filed, works):
    """The copies still to make: each relevant attachment, and each paper's mail as .eml once per folder."""
    items, eml_done = [], set()
    for x in docs:
        if x["key"] in filed or x.get("tax_year") is None:
            continue
        w = works.get(x["mail"]) or {}
        folder = f"{x['tax_year']}/{conf['forms'][x['form'] if x['form'] in conf['forms'] else 'sonstige']['folder']}"
        date = x.get("date") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", x.get("date") or "") else x.get("mail_date") or "undatiert"
        stem = f"{date}_{slug(x.get('issuer'))}_{slug(x.get('kind'), 30)}"
        if x.get("idx") is not None:
            part = next((p for p in w.get("parts") or [] if p["idx"] == x["idx"]), {})
            items.append({"key": x["key"], "path": w.get("path_eml"), "part": x["idx"], "folder": folder, "name": stem + ext_of(part.get("name"))})
        eml_key = f"{x['mail']}:eml:{folder}"
        if eml_key not in filed and eml_key not in eml_done:
            items.append({"key": eml_key if x.get("idx") is not None else x["key"], "path": w.get("path_eml"), "part": None,
                          "folder": folder, "name": stem + ".eml"})
            eml_done.add(eml_key)
    return [i for i in items if i["path"]]


def put_file(rel, text, written, puts):
    """A desk file for the share: over its last own version only (ops/tax_nas.py op_put)."""
    last = written.get(rel) or {}
    puts.append({"logical": rel, "path": last.get("path") or rel, "text": text, "ours": last.get("sha256")})


def file(c=None, conf=None, call=nas, today=None):
    """Step 3 (crew job tax-file): copies, Belege, workbooks, questions. -> the number of new copies."""
    conf = conf or cfg()
    today = today or dt.date.today()
    prep, prior_years, open_ = years(conf, today)
    forms = conf["forms"]
    cands = load("candidates.json", {})
    docs_raw = all_docs()
    works = {}
    for d in docs_raw:
        w = load(f"work/{d['mail']}.json", {}) or {}
        works[d["mail"]] = {**w, "path_eml": (cands.get(d["mail"]) or {}).get("path")}
    filed = load("filed.json", {})
    written = load("written.json", {})
    owner = load("owner.json", {"overrides": {}, "removed": [], "order": {}})
    tree = call({"op": "tree", "root": share()})
    shas = {f["path"]: f["sha256"] for fs in (tree.get("years") or {}).values() for f in fs}
    # the owner's corrections in Belege.csv win: read each one that is no longer the desk's own version
    for y in sorted({int(x) for x in (tree.get("years") or {})}):
        rel = (written.get(f"{y}/Belege.csv") or {}).get("path") or f"{y}/Belege.csv"
        mine = written.get(f"{y}/Belege.csv") or {}
        if rel in shas and mine.get("sha256") and shas[rel] != mine["sha256"]:
            theirs = call({"op": "read", "root": share(), "files": [rel]})["files"][rel]["text"]
            changed, removed, order = BOOK.owner_changes(mine.get("text") or "", theirs)
            for k, v in changed.items():
                owner["overrides"][k] = {**owner["overrides"].get(k, {}), **v}
            owner["removed"] = sorted(set(owner["removed"]) | set(removed))
            owner["order"][str(y)] = order
            written[f"{y}/Belege.csv"] = {**mine, "sha256": shas[rel]}   # taken in: the next version keeps every change of the owner's
    save("owner.json", owner)
    docs, kept, dropped = papers(docs_raw, owner)
    plan = copy_plan(docs, conf, filed, works)
    copied = call({"op": "copy", "root": share(), "vault": mailvault(), "items": plan})["copied"] if plan else []
    for r in copied:
        if r.get("path"):
            filed[r["key"]] = r["path"]
    save("filed.json", filed)
    prior = prior_returns(prior_years + prep)
    unclear = [d for d in docs_raw if d.get("status") == "unclear" and d["mail"] not in kept | dropped]
    puts, report, all_q = [], [], []
    for y, ex in prior.items():
        if ex.get("unread"):                            # said in the report and in Erklaerung-<year>.md, never guessed
            report.append(f"{y}: your own return could not be read ({ex['unread']}); put it in again as HTML or a PDF with text")
        put_file(f"{y}/Erklaerung-{y}.json", json.dumps(ex, ensure_ascii=False, indent=1) + "\n", written, puts)
        put_file(f"{y}/Erklaerung-{y}.md", BOOK.erklaerung_md(y, ex, forms), written, puts)
    for y in sorted({x["tax_year"] for x in docs if x.get("tax_year")} | set(prep)):
        ydocs = [x for x in docs if x.get("tax_year") == y]
        rows = BOOK.belege_rows(ydocs, filed)
        if rows:
            text = BOOK.belege_csv(rows, owner["order"].get(str(y), ()))
            put_file(f"{y}/Belege.csv", text, written, puts)
            put_file(f"{y}/Belege.md", BOOK.belege_md(y, rows, forms), written, puts)
        if y not in prep:
            report.append(f"{y}: {len(ydocs)} papers filed (an earlier year: not summed)")
            continue
        yun = [{"mail": d["mail"], "date": d.get("mail_date") or ""} for d in unclear if _year_of(d) == y]
        expect_rows = BOOK.compare(BOOK.expected({k: v for k, v in prior.items() if k < y}), BOOK.sums(ydocs),
                                   {k[len("missing:"):] for k, v in answers_of(y).items() if k.startswith("missing:") and v == "none"})[0]
        qs = BOOK.questions(y, prior, answers_of(y), yun, expect_rows, today)
        all_q += qs
        md, csvs, rows_e = BOOK.workbook(y, ydocs, prior, answers_of(y), qs, forms, filed, today)
        put_file(f"{y}/Steuer-{y}.md", md, written, puts)
        for folder, text in csvs.items():
            put_file(f"{y}/Steuer-{y}-{folder}.csv", text, written, puts)
        subjects = {d["mail"]: (cands.get(d["mail"]) or {}).get("subject") or "" for d in unclear}
        put_file(f"{y}/Fragen.md", BOOK.fragen_md(y, qs, subjects), written, puts)
        per = {}
        for x in ydocs:
            per[x["form"]] = per.get(x["form"], 0) + 1
        missing = sum(1 for r in rows_e if r["state"] == "missing")
        by_form = ", ".join(f"{forms[k]['name']} {n}" for k, n in sorted(per.items()) if k in forms) or "none yet"
        report.append(f"{y}{' (open)' if y in open_ else ''}: {len(ydocs)} papers ({by_form}); "
                      f"{missing} expected papers missing; {len(qs)} questions open; folder Steuern/{y}")
    if puts:
        got = call({"op": "put", "root": share(), "files": [{k: p[k] for k in ("path", "text", "ours")} for p in puts]})["written"]
        for p, g in zip(puts, got):
            written[p["logical"]] = {"path": g["path"], "sha256": g["sha256"], **({"text": p["text"]} if p["logical"].endswith("Belege.csv") else {})}
    save("written.json", written)
    save("questions.json", all_q)
    rep = {"at": time.time(), "years": report, "copies": len(copied), "questions": len(all_q)}
    save("report.json", rep)
    import tax_view as VIEW                             # TAX-10: the result in the app, for the owner only (TAX-11)
    shared = VIEW.refresh(conf, today)
    _report("tax-file", f"{len(copied)} new copies in Steuern. " + " · ".join(report) + ("" if shared else " · the app's view was not written"))
    return len(copied)


def _year_of(d):
    ys = [x.get("tax_year") for x in d.get("documents") or [] if x.get("tax_year")]
    if ys:
        return ys[0]
    try:
        y = int((d.get("mail_date") or "")[:4])
    except ValueError:
        return None
    return y - 1 if (d.get("mail_date") or "")[5:7] in ("01", "02", "03", "04", "05") else y


# ---------------------------------------------------------------- Needs you (TAX-07)
LABELS = {"Single": "single", "Joint": "joint", "Separate": "separate", "Yes": True, "No": False, "Keep": "keep",
          "Not a tax paper": "drop", "I will add it to the folder": "later", "None this year": "none"}


def decisions(_d):
    """Each open question of the desk as a Needs you item: its buttons, or a typed answer. Names no amount, no content."""
    for q in load("questions.json", []) or []:
        if q["ask"]:
            ans = [{"label": "Answer", "act": {"action": "tax_answer", "id": q["id"]}, "ask": q["ask"], "into": "answer"}]
        else:
            ans = [{"label": a, "act": {"action": "tax_answer", "id": q["id"], "answer": a}} for a in q["answers"]]
        yield _d(f"tax:{q['id']}", "tax", q["text"], q["why"], "#/decide", unanswered="the draft leaves it open",
                 answers=ans, routine=q["id"].split(":")[1] in ("doc", "missing"))


def answer(req):
    """The action tax_answer: one answer to one open question, checked, kept for the next run (never sent anywhere)."""
    qid = str(req.get("id") or "")
    q = next((x for x in load("questions.json", []) or [] if x["id"] == qid), None)
    if not q:
        raise ValueError("the tax desk has no such open question (answered already, or the desk asked again since)")
    raw = TC.limit(str(req.get("answer") or "").strip(), ANSWER_MAX, "the answer")
    if q["ask"]:
        try:
            value = BOOK.number(raw)
        except ValueError:
            raise ValueError(f"the answer must be a number, not {raw!r}")
        if value is None or value < 0:
            raise ValueError("the answer must be a number of 0 or more")
    elif raw in q["answers"]:
        value = LABELS.get(raw, raw)
    else:
        raise ValueError(f"the answer must be one of {', '.join(q['answers'])}")
    ans = load("answers.json", {}) or {}
    ans[qid] = {"value": value, "at": time.time(), "by": req.get("who") or "owner"}
    save("answers.json", ans)
    save("questions.json", [x for x in load("questions.json", []) or [] if x["id"] != qid])
    import tax_view as VIEW                             # the app's view drops the question at once (TAX-10)
    VIEW.refresh()
    return {"message": "Kept: the tax desk's next run uses it"}


# ---------------------------------------------------------------- the command line
def status():
    rep = load("report.json", {}) or {}
    return "\n".join(rep.get("years") or ["The tax desk has not run yet."])


def main(argv):
    if argv[1:] == ["status"]:
        print(status())
        return 0
    if argv[1:] == ["count"]:
        conf = cfg()
        rows = nas({"op": "index", "db": f"{mailvault()}/index.sqlite", "since": window(conf)})["rows"]
        print(json.dumps(count(rows, conf), indent=1, sort_keys=True))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

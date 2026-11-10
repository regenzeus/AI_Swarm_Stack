"""The tax desk's books (TAX-03 to TAX-06): what the read papers become in the Steuern share, without a model.

Pure functions over the reader's answers, the owner's earlier returns and the owner's answers; ops/tax.py hands them
their data and writes what they make:
  Belege.csv / Belege.md     a year's papers: file, form, kind, amount, date, issuer, source mail, confidence, checked.
                             The owner edits Belege.csv; what the owner changed or removed wins on every later run.
  Steuer-<year>.md / -<form>.csv   the workbook: per form its lines with sums and papers, the comparisons with the
                             figures the law sets for the year (ops/tax_law.py), what the earlier returns lead to expect
                             (found, missing, new, moved a lot) and the questions that are open
  Erklaerung-<year>.md       an earlier return as the reader extracted it
Every workbook says at its top that it is a draft for the owner's own ELSTER return, not tax advice, and that the
desk submits nothing anywhere.
"""
import csv
import datetime as dt
import io
import re

import tax_law as LAW

COLUMNS = ["file", "form", "kind", "amount_eur", "date", "issuer", "mail_id", "confidence", "checked"]
DRAFT = ("> **A draft for your own ELSTER return, not tax advice.** The tax desk prepared it from your mail and your "
         "earlier returns; it submits nothing anywhere. Check every figure against the paper it names.")
MOVED = 0.5                         # a sum that moves by more than half against the prior year is flagged
MOVED_EUR = 100                     # ... and by more than 100 EUR (small items move by a few euros all the time)
YES = ("yes", "ja", "x", "1", "true")


def money(v):
    """1234.5 -> '1.234,50' (as a German return writes it)."""
    if v is None:
        return ""
    s = f"{float(v):,.2f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def number(s):
    """'1.234,50' or '1234.50' or '1234,5' -> 1234.5; '' -> None; anything else -> ValueError."""
    s = str(s or "").strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def words(s):
    return {w for w in re.findall(r"[a-zäöüß]{4,}", str(s or "").lower())}


# ---------------------------------------------------------------- the papers of a year
def documents(docs, year=None, overrides=None, dismissed=(), kept=()):
    """The relevant documents, each with its key and the owner's corrections applied: a row the owner removed from
    Belege.csv is gone, a value the owner changed wins, a paper the owner kept in Needs you counts. -> [doc]."""
    out, overrides = [], overrides or {}
    for d in docs:
        for i, x in enumerate(d.get("documents") or []):
            key = f"{d['mail']}:{x.get('idx') if x.get('idx') is not None else 'mail'}"
            if key in dismissed or not (x.get("relevant") or d["mail"] in kept):
                continue
            x = {**x, "key": key, "mail": d["mail"], "mail_date": d.get("mail_date") or ""}
            o = overrides.get(key) or {}
            for f in ("form", "kind", "date", "issuer"):
                if o.get(f):
                    x[f] = o[f]
            if o.get("amount_eur") not in (None, ""):
                am = list(x.get("amounts") or [])
                first = {**(am[0] if am else {"label": x.get("kind") or "amount", "currency": "EUR"}), "value": o["amount_eur"]}
                x["amounts"] = [first] + am[1:]
            x["checked"] = bool(o.get("checked"))
            try:
                x["tax_year"] = int(o.get("tax_year") or x.get("tax_year"))
            except (TypeError, ValueError):
                x["tax_year"] = None
            if year is None or x["tax_year"] == year:
                out.append(x)
    return out


def first_amount(x):
    am = x.get("amounts") or []
    return am[0].get("value") if am else None


def belege_rows(docs, files):
    """One row per paper: its copy's file (files: key -> path in the share), or the mail's when it has no copy yet."""
    rows = []
    for x in docs:
        rows.append({"file": files.get(x["key"]) or "", "form": x.get("form") or "", "kind": x.get("kind") or "",
                     "amount_eur": money(first_amount(x)), "date": x.get("date") or x.get("mail_date") or "",
                     "issuer": x.get("issuer") or "", "mail_id": x["key"], "confidence": f"{float(x.get('confidence') or 0):.2f}",
                     "checked": "yes" if x.get("checked") else ""})
    return rows


def belege_csv(rows, owner_order=()):
    """Belege.csv: the owner's rows first, in the owner's order, then the new ones. ';' and a decimal comma, as a
    German spreadsheet opens it."""
    order = {k: i for i, k in enumerate(owner_order)}
    rows = sorted(rows, key=lambda r: (order.get(r["mail_id"], len(order)), r["date"], r["mail_id"]))
    buf = io.StringIO()
    w = csv.DictWriter(buf, COLUMNS, delimiter=";", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def parse_belege(text):
    """The owner's Belege.csv -> ({mail_id: corrections}, [mail_id in the owner's order]). A row's mail_id is its key;
    an amount that is no number is left as the desk had it."""
    rows = list(csv.DictReader(io.StringIO((text or "").lstrip("﻿")), delimiter=";"))
    out, order = {}, []
    for r in rows:
        key = (r.get("mail_id") or "").strip()
        if not key:
            continue
        o = {f: (r.get(f) or "").strip() for f in ("form", "kind", "date", "issuer")}
        try:
            o["amount_eur"] = number(r.get("amount_eur"))
        except ValueError:
            o["amount_eur"] = None
        o["checked"] = (r.get("checked") or "").strip().lower() in YES
        out[key] = o
        order.append(key)
    return out, order


def owner_changes(desk_text, owner_text):
    """What the owner changed in Belege.csv against the desk's last version: (corrections, removed keys, order)."""
    mine, _ = parse_belege(desk_text)
    theirs, order = parse_belege(owner_text)
    changed = {k: {f: v for f, v in o.items() if v != (mine.get(k) or {}).get(f)} for k, o in theirs.items()}
    return {k: v for k, v in changed.items() if v}, sorted(set(mine) - set(theirs)), order


def belege_md(year, rows, forms):
    lines = [f"# Belege {year}", "", DRAFT, "",
             "Each paper the desk filed for this year. Correct a form, an amount or mark a paper checked in **Belege.csv**: "
             "the desk keeps your changes, and a row you delete stays out.", "",
             "| File | Form | Kind | Amount (EUR) | Date | Issuer | Confidence | Checked |", "|---|---|---|---:|---|---|---:|---|"]
    for r in rows:
        lines.append(f"| {r['file'] or '(no copy yet)'} | {(forms.get(r['form']) or {}).get('name', r['form'])} | {r['kind']} | "
                     f"{r['amount_eur']} | {r['date']} | {r['issuer']} | {r['confidence']} | {r['checked']} |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- the earlier returns as the base (TAX-06)
def expected(prior):
    """The recurring items of the earlier returns, newest first: (form, label) -> {year: value, line}."""
    out = {}
    for y in sorted(prior, reverse=True):
        for it in (prior[y] or {}).get("items") or []:
            if not it.get("recurring") or not it.get("form"):
                continue
            k = (it["form"], str(it.get("label") or it.get("line") or "").strip())
            e = out.setdefault(k, {"form": it["form"], "label": k[1], "line": it.get("line") or "", "values": {}})
            e["values"].setdefault(int(y), it.get("value"))
    return out


def sums(docs):
    """(form, label) -> {sum, papers}: every amount of the year's papers, by form and label."""
    out = {}
    for x in docs:
        for a in x.get("amounts") or []:
            if not isinstance(a.get("value"), (int, float)):
                continue
            k = (x.get("form") or "sonstige", str(a.get("label") or x.get("kind") or "").strip())
            s = out.setdefault(k, {"form": k[0], "label": k[1], "line": x.get("line") or "", "sum": 0.0, "papers": []})
            s["sum"] = round(s["sum"] + float(a["value"]), 2)
            if x["key"] not in s["papers"]:
                s["papers"].append(x["key"])
    return out


def compare(expect, have, none_this_year=()):
    """Each expected item against this year's sums: found (and moved a lot or not), missing, or none this year by the
    owner's word; and the sums no earlier return had (new). -> (rows, new)."""
    rows, used = [], set()
    for k, e in expect.items():
        hit = have.get(k) or next((h for hk, h in have.items() if hk[0] == e["form"] and hk not in used
                                   and words(hk[1]) & words(e["label"])), None)
        last_year = max(e["values"]) if e["values"] else None
        last = e["values"].get(last_year) if last_year else None
        if hit:
            used.add((hit["form"], hit["label"]))
            moved = (isinstance(last, (int, float)) and abs(hit["sum"] - last) > max(MOVED * abs(last), MOVED_EUR))
            rows.append({**e, "state": "moved a lot" if moved else "found", "sum": hit["sum"], "last_year": last_year, "last": last})
        else:
            rows.append({**e, "state": "none this year" if f"{e['form']}:{e['label']}" in none_this_year else "missing",
                         "sum": None, "last_year": last_year, "last": last})
    new = [h for hk, h in have.items() if hk not in used and hk not in expect]
    return rows, new


def key_of(e):
    return f"{e['form']}:{e['label']}"


# ---------------------------------------------------------------- the comparisons the law sets (TAX-05)
def facts(answers, prior):
    """What the owner said for the year, else what the newest earlier return says (marked as from it)."""
    last = (prior[max(prior)] if prior else {}) or {}
    out = {}
    for k in ("assessment", "church_tax", "children", "commute_km", "commute_days", "home_office_days"):
        if answers.get(k) is not None:
            out[k] = (answers[k], "your answer")
        elif last.get(k) is not None:
            out[k] = (last[k], f"your {max(prior)} return")
    return out


def label_sum(have, form, *needles):
    return round(sum(h["sum"] for (f, label), h in have.items() if f == form and any(n in label.lower() for n in needles)), 2)


def comparisons(year, docs, have, fx):
    """The usual comparisons in plain sentences, with the figures the law sets for the year. -> [line]."""
    f = LAW.figures(year)
    if not f:
        return [f"The desk has no figures for {year} yet (ops/tax_law.py): no comparison is made."]
    out = []
    km, days = (fx.get("commute_km") or (None,))[0], (fx.get("commute_days") or (None,))[0]
    ho = (fx.get("home_office_days") or (None,))[0]
    full, capped = LAW.commute(year, km, days)
    office = LAW.homeoffice(year, ho)
    costs = round(sum(float(a.get("value") or 0) for x in docs if x.get("form") == "n" and x.get("role") == "expense"
                      for a in x.get("amounts") or [] if isinstance(a.get("value"), (int, float))), 2)
    steps = " and ".join(f"{money(r)} EUR from km {s}" for s, r in f["km_rates"])
    if full is None:
        out.append(f"**Entfernungspauschale**: needs your one-way km and working days at the workplace ({steps}; "
                   f"at most {money(f['km_cap'])} EUR unless you drive your own car). Answer the question in Needs you.")
    else:
        out.append(f"**Entfernungspauschale**: {km} km × {days} days at {steps} = {money(full)} EUR"
                   + (f" (by public transport or carpool at most {money(f['km_cap'])} EUR: {money(capped)} EUR)" if capped < full else "") + ".")
    if office is None:
        out.append(f"**Homeoffice-Pauschale**: {money(f['homeoffice_day'])} EUR a day at home, at most "
                   f"{money(f['homeoffice_max'])} EUR: needs your days at home (not on days you drove to work).")
    else:
        out.append(f"**Homeoffice-Pauschale**: {ho} days × {money(f['homeoffice_day'])} EUR = {money(office)} EUR "
                   f"(at most {money(f['homeoffice_max'])} EUR).")
    wk = round(costs + (full or 0) + (office or 0), 2)
    pb = f["arbeitnehmer_pauschbetrag"]
    out.append(f"**Werbungskosten against the Arbeitnehmer-Pauschbetrag**: your work costs from the papers {money(costs)} EUR"
               f" + commute + home office = {money(wk)} EUR; the Pauschbetrag is {money(pb)} EUR, so "
               + (f"claiming them gives {money(wk - pb)} EUR more." if wk > pb else "the Pauschbetrag is higher: it applies without papers."))
    joint = (fx.get("assessment") or (None,))[0] == "joint"
    sa = round(label_sum(have, "sonder", "") , 2)
    sp = f["sonderausgaben_pauschbetrag"][1 if joint else 0]
    out.append(f"**Sonderausgaben** (donations, church tax paid): {money(sa)} EUR against the Sonderausgaben-Pauschbetrag of "
               f"{money(sp)} EUR: " + ("enter them." if sa > sp else "the Pauschbetrag applies."))
    kap = round(sum(float(a.get("value") or 0) for x in docs if x.get("form") == "kap" and x.get("role") in ("income", "certificate")
                    for a in x.get("amounts") or [] if isinstance(a.get("value"), (int, float)) and "ertr" in str(a.get("label") or "").lower()), 2)
    spb = f["sparer_pauschbetrag"][1 if joint else 0]
    out.append(f"**Anlage KAP**: capital income labelled as Erträge on your certificates {money(kap)} EUR against the "
               f"Sparer-Pauschbetrag of {money(spb)} EUR. Anlage KAP pays when tax was withheld beyond it, church tax "
               f"was not withheld, or a Freistellungsauftrag was not used up.")
    gross = label_sum(have, "n", "brutto")
    agb = round(sum(float(a.get("value") or 0) for x in docs if x.get("form") == "agb" and x.get("role") == "expense"
                    for a in x.get("amounts") or [] if isinstance(a.get("value"), (int, float))), 2)
    kids = (fx.get("children") or (0,))[0] or 0
    case = "kids_3" if kids >= 3 else "kids_1_2" if kids >= 1 else "joint" if joint else "single"
    if gross:
        income = round(gross - max(wk, pb), 2)
        z = LAW.zumutbar(income, case)
        out.append(f"**Außergewöhnliche Belastungen**: {money(agb)} EUR of costs; the zumutbare Belastung on an estimated "
                   f"Gesamtbetrag der Einkünfte of {money(income)} EUR (gross wages less work costs) is {money(z)} EUR "
                   f"(§ 33 Abs. 3, in steps), so " + (f"{money(agb - z)} EUR count." if agb > z else "nothing counts this year."))
    else:
        out.append(f"**Außergewöhnliche Belastungen**: {money(agb)} EUR of costs; the zumutbare Belastung needs your "
                   f"Gesamtbetrag der Einkünfte (from the Lohnsteuerbescheinigung, not here yet).")
    for kind, label in (("handwerker", "Handwerkerleistungen"), ("dienstleistung", "haushaltsnahe Dienstleistungen")):
        labour = round(sum(float(x.get("labour_cost") or 0) for x in docs if x.get("s35a") == kind), 2)
        if labour:
            share, cap = f["s35a_handwerk" if kind == "handwerker" else "s35a_dienst"]
            out.append(f"**§ 35a {label}**: labour costs {money(labour)} EUR × {int(share * 100)} % = "
                       f"{money(LAW.s35a(year, kind, labour))} EUR off the tax (at most {money(cap)} EUR; paid by transfer, not in cash).")
    av = f["altersvorsorge_max"][1 if joint else 0]
    so = f["sonstige_vorsorge_max"]
    out.append(f"**Vorsorgeaufwand**: retirement contributions count up to {money(av)} EUR; other insurances (liability, "
               f"accident, disability) together with health and care insurance up to {money(so[0])} EUR (employees) or "
               f"{money(so[1])} EUR (who pay their health insurance alone), and basic health and care insurance always in full.")
    return out


def figures_table(year):
    f = LAW.figures(year)
    if not f:
        return ""
    rows = [f"| {k} | {v} | {LAW.WHERE.get(k, '')} |" for k, v in f.items()]
    rows.append(f"| zumutbare_belastung | {LAW.ZUMUTBAR} up to {LAW.ZUMUTBAR_BANDS} | {LAW.WHERE['zumutbare_belastung']} |")
    return "\n".join([f"## The figures the law sets for {year}", "", "| Figure | Value | Where |", "|---|---|---|", *rows, "",
                      "Sources: " + "; ".join(f"{k}: {v}" for k, v in LAW.SOURCES.items())])


# ---------------------------------------------------------------- the workbook (TAX-05)
def workbook(year, docs, prior, answers, questions, forms, files, now=None):
    """-> (Steuer-<year>.md, {form folder: csv}) for a year being prepared."""
    have = sums(docs)
    rows, new = compare(expected({y: v for y, v in prior.items() if int(y) < year}), have,
                        {k[len("missing:"):] for k, v in answers.items() if k.startswith("missing:") and v == "none"})
    fx = facts(answers, {y: v for y, v in prior.items() if int(y) < year})
    md = [f"# Steuer {year}", "", DRAFT, "",
          f"Made on {(now or dt.date.today()).isoformat()} from {len(docs)} papers. Change **Belege.csv** to correct a paper; "
          "the desk keeps your changes on every run.", ""]
    csvs = {}
    for key, form in forms.items():
        part = sorted((h for h in have.values() if h["form"] == key), key=lambda h: h["label"])
        if not part:
            continue
        md += [f"## {form['name']}", "", "| Line | Item | Sum (EUR) | Papers |", "|---|---|---:|---|"]
        md += [f"| {h['line']} | {h['label']} | {money(h['sum'])} | {', '.join(files.get(p) or p for p in h['papers'])} |" for h in part]
        md.append("")
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\n")
        w.writerow(["line", "item", "sum_eur", "papers"])
        w.writerows([[h["line"], h["label"], money(h["sum"]), " ".join(files.get(p) or p for p in h["papers"])] for h in part])
        csvs[form["folder"]] = buf.getvalue()
    md += ["## Comparisons", ""] + [f"- {x}" for x in comparisons(year, docs, have, fx)] + [""]
    if fx:
        md += ["What these use: " + "; ".join(f"{k} {v} ({src})" for k, (v, src) in fx.items()) + ".", ""]
    if rows:
        md += ["## What your earlier returns lead to expect", "", "| Form | Item | Earlier | This year | State |", "|---|---|---:|---:|---|"]
        md += [f"| {(forms.get(r['form']) or {}).get('name', r['form'])} | {r['label']} | "
               f"{money(r['last']) if isinstance(r['last'], (int, float)) else ''} ({r['last_year']}) | {money(r['sum'])} | {r['state']} |" for r in rows]
        md.append("")
    if new:
        md += ["## New this year (no earlier return had it)", ""] + [f"- {(forms.get(h['form']) or {}).get('name', h['form'])}: {h['label']}" for h in new] + [""]
    open_q = [q for q in questions if q["year"] == year]
    md += ["## Questions for you", ""] + ([f"- {q['text']}" for q in open_q] or ["- None open."]) + [""]
    md += [figures_table(year), ""]
    return "\n".join(md), csvs, rows


def erklaerung_md(year, ex, forms):
    """An earlier return as the reader extracted it, for the owner to check."""
    lines = [f"# Erklärung {year} (your own return, as the tax desk read it)", "",
             "Extracted from the protocol you filed, by the tax desk's reader (ChatGPT through Hermes). Check it against "
             "the protocol: the desk prepares later years from it.", "",
             *([f"> **Not read:** {ex['unread']}. The desk has no base from this year.", ""] if ex.get("unread") else []),
             f"- Assessment: {ex.get('assessment') or 'not stated'}; church tax: {ex.get('church_tax')}; children: {ex.get('children')}",
             f"- Commute: {ex.get('commute_km')} km, {ex.get('commute_days')} days; home office: {ex.get('home_office_days')} days", "",
             "| Form | Line | Item | Value | Recurring |", "|---|---|---|---:|---|"]
    for it in ex.get("items") or []:
        lines.append(f"| {(forms.get(it.get('form')) or {}).get('name', it.get('form'))} | {it.get('line') or ''} | {it.get('label') or ''} | "
                     f"{money(it.get('value')) if isinstance(it.get('value'), (int, float)) else ''} | {'yes' if it.get('recurring') else ''} |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- the questions (TAX-07)
def due(year, today):
    """A year's annual certificates are due by the end of May of the next year."""
    return today >= dt.date(year + 1, 6, 1)


def questions(year, prior, answers, unclear, rows, today):
    """The questions the desk asks the owner for a year: what only the owner knows, the papers it could not sort, and
    the expected papers that never came. Each: id, year, text, why, and its answers (buttons) or ask (a typed answer).
    Texts name dates, forms and kinds, never an amount or a paper's content."""
    last_y = max((int(y) for y in prior if int(y) < year), default=None)
    last = prior.get(last_y) or {} if last_y else {}
    qs = []

    def q(qid, text, why, answers_=None, ask=None):
        if qid not in answers:
            qs.append({"id": f"{year}:{qid}", "year": year, "text": text, "why": why, "answers": answers_ or [], "ask": ask})
    year_over = today >= dt.date(year, 12, 1)
    q("assessment", f"Your income tax {year}: assessed alone or jointly with a spouse?",
      f"It sets the Pauschbeträge and the zumutbare Belastung. Your {last_y} return said {last.get('assessment')}." if last.get("assessment") else
      "It sets the Pauschbeträge and the zumutbare Belastung.", ["Single", "Joint", "Separate"])
    q("church_tax", f"Were you a member of a church that levies church tax in {year}?", "Church tax paid counts as Sonderausgaben.", ["Yes", "No"])
    if year_over:
        q("commute_km", f"Your commute in {year}: how many km one way from home to your first workplace?",
          "The Entfernungspauschale is km times working days there.", ask="Kilometres one way (a number, 0 if none)")
        q("commute_days", f"On how many days in {year} did you go to your first workplace?",
          "The Entfernungspauschale counts each day you went.", ask="Days (a number)")
        q("home_office_days", f"On how many days in {year} did you work at home all day?",
          "The Homeoffice-Pauschale is 6 EUR a day at home, at most 210 days.", ask="Days (a number)")
    if last.get("children") or answers.get("children") is None and any(r["form"] == "kind" for r in rows):
        q("children", f"How many children count for you in {year} (Kindergeld or Kinderfreibetrag)?",
          "Children lower the zumutbare Belastung and need Anlage Kind.", ask="Children (a number)")
    for u in unclear:
        q(f"doc:{u['mail']}", f"A mail of {u['date']} could not be sorted with certainty: keep it as a paper for {year}?",
          f"Its subject is in Steuern/{year}/Fragen.md. The reader said: not sure.", ["Keep", "Not a tax paper"])
    if due(year, today):
        for r in rows:
            if r["state"] == "missing":
                q(f"missing:{key_of(r)}", f"Expected for {year} from your {r['last_year']} return: {r['label']} "
                  f"({r['form']}). It did not come by mail.", "Put the paper into the year's folder, or say there is none this year.",
                  ["I will add it to the folder", "None this year"])
    return qs


def fragen_md(year, qs, unclear_subjects):
    lines = [f"# Fragen {year}", "", "The tax desk's open questions for this year. Answer them in the app (Needs you).", ""]
    for x in qs:
        if x["year"] != year:
            continue
        lines.append(f"- {x['text']}")
        mid = x["id"].split(":doc:")[-1] if ":doc:" in x["id"] else None
        if mid and unclear_subjects.get(mid):
            lines.append(f"  - The mail: {unclear_subjects[mid]}")
    return "\n".join(lines) + "\n"

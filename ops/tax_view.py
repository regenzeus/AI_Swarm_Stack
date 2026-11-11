"""TAX-10, TAX-11: the tax desk's result for the app, per year, from the desk's own outputs on the PC (/srv/ai/tax).

What a year shows: the papers found per form (counts), the sums per form line, what the earlier returns lead to expect
that is missing, the open questions, the earlier return as the reader extracted it, the workbook (Steuer-<year>.md) and
Belege as the desk made them, and where each file lies on the NAS share. Built without a model and without the NAS:
the same books as the share's (ops/tax_book.py), from the papers read, the owner's corrections and answers.

These are the owner's tax figures. The app (another user on this PC) may read them, and nobody else: the folder and
the file carry a POSIX access ACL for the app's user alone (the owner of the app's own data folder), with no group and
no other access, so the view is never readable by another container's user or anyone on the PC. A filesystem that
takes no ACL gets no view (fail closed). It never goes into the app's state, a task's page, a log, Home, a push or
n8n; the app serves it only to the owner's signed-in session (images/mission-control/server.tax.py).

    python3 ops/tax_view.py        build the view from what the desk has now and share it with the app (counts printed)
"""
import datetime as dt
import json
import os
import re
import struct
import sys
import time
from pathlib import Path

import tax as TX
import tax_book as BOOK

OUT = Path(os.environ.get("TAX_VIEW_DIR", "/srv/ai/missions/tax"))   # in the app's mount (/missions/tax), outside public/
APP_HOME = Path("/srv/ai/missions/app")              # the app writes its own data here: its owner is the app's user on this PC
NAME = "view.json"
ACL_KEY = "system.posix_acl_access"
USER_OBJ, USER, GROUP_OBJ, MASK, OTHER = 0x01, 0x02, 0x04, 0x10, 0x20
ANY = 0xFFFFFFFF                                     # the kernel's "no id" for the entries that name none


# ---------------------------------------------------------------- the view
def plain(md):
    """The workbook's disclaimer as a sentence (no quote mark, no bold)."""
    return re.sub(r"\*\*|^>\s*", "", md).strip()


def smb(rel=""):
    """A path in the Steuern share as Windows opens it (\\\\<NAS>\\Shared_Data\\Steuern\\...), or the share-relative path
    when this deployment names no NAS."""
    import deployment as DEPLOY
    host = DEPLOY.VALUES.get("NAS_HOST") or ""
    share = re.sub(r"^/volume\d+/", "", TX.share()).strip("/")
    parts = [p for p in (share + "/" + str(rel or "")).split("/") if p]
    return ("\\\\" + host + "\\" if host else "") + "\\".join(parts)


def _desk_file(written, rel):
    """The share path of a desk file: its last own version (a numbered name when the owner changed the first)."""
    return (written.get(rel) or {}).get("path") or rel


def year_view(y, docs, prior, filed, written, questions, forms, prep, open_, today):
    """One year: its papers, sums, what is missing, its questions, its earlier return, its files."""
    ydocs = [x for x in docs if x.get("tax_year") == y]
    per = {}
    for x in ydocs:
        per[x["form"]] = per.get(x["form"], 0) + 1
    name = lambda k: (forms.get(k) or {}).get("name", k)  # noqa: E731
    order = list(forms)
    v = {"year": y, "prepared": y in prep, "open": y in open_, "total": len(ydocs),
         "papers": [{"form": k, "name": name(k), "n": per[k]} for k in sorted(per, key=lambda k: (order.index(k) if k in order else 99, k))]}
    rows = BOOK.belege_rows(ydocs, filed)
    v["belege"] = [{"file": r["file"], "name": r["file"].split("/")[-1] if r["file"] else "", "nas": smb(r["file"]) if r["file"] else "",
                    "form": name(r["form"]), "kind": r["kind"], "amount": BOOK.number(r["amount_eur"]) if r["amount_eur"] else None,
                    "date": r["date"], "issuer": r["issuer"], "checked": bool(r["checked"]), "confidence": float(r["confidence"])}
                   for r in sorted(rows, key=lambda r: (r["date"], r["mail_id"]))]
    files = {"folder": smb(str(y))}
    if rows:
        files["belege"] = smb(_desk_file(written, f"{y}/Belege.csv"))
    if y in prep:
        qs = [q for q in questions if q.get("year") == y]
        md, _, expect = BOOK.workbook(y, ydocs, prior, TX.answers_of(y), questions, forms, filed, today)
        v["workbook"] = md
        v["lines"] = [{"form": h["form"], "name": name(h["form"]), "line": h["line"], "label": h["label"], "sum": h["sum"],
                       "papers": [(filed.get(p) or p).split("/")[-1] for p in h["papers"]]}
                      for h in sorted(BOOK.sums(ydocs).values(), key=lambda h: (order.index(h["form"]) if h["form"] in order else 99, h["label"]))]
        v["missing"] = [{"form": r["form"], "name": name(r["form"]), "label": r["label"], "last_year": r["last_year"], "last": r["last"]}
                        for r in expect if r["state"] == "missing"]
        v["questions"] = [{"id": q["id"], "text": q["text"]} for q in qs]
        files["workbook"] = smb(_desk_file(written, f"{y}/Steuer-{y}.md"))
        files["fragen"] = smb(_desk_file(written, f"{y}/Fragen.md"))
    ex = prior.get(y)
    if ex:
        v["return"] = {**{k: ex.get(k) for k in ("assessment", "church_tax", "children", "commute_km", "commute_days", "home_office_days", "unread")},
                       "items": [{"form": i.get("form"), "name": name(i.get("form")), "line": i.get("line") or "", "label": i.get("label") or "",
                                  "value": i.get("value"), "recurring": bool(i.get("recurring"))} for i in ex.get("items") or []]}
        v["erklaerung"] = BOOK.erklaerung_md(y, ex, forms)
        files["erklaerung"] = smb(_desk_file(written, f"{y}/Erklaerung-{y}.md"))
    v["files"] = files
    return v


def build(conf=None, today=None):
    """The view of every year the desk knows: those it prepares, those its papers concern, the earlier returns."""
    conf = conf or TX.cfg()
    today = today or dt.date.today()
    prep, prior_years, open_ = TX.years(conf, today)
    forms = conf["forms"]
    owner = TX.load("owner.json", {"overrides": {}, "removed": [], "order": {}}) or {"overrides": {}, "removed": []}
    docs, _, _ = TX.papers(TX.all_docs(), owner)
    filed, written = TX.load("filed.json", {}) or {}, TX.load("written.json", {}) or {}
    prior = TX.prior_returns(prior_years + prep)
    questions = TX.load("questions.json", []) or []
    years = sorted({x["tax_year"] for x in docs if x.get("tax_year")} | set(prep) | set(prior), reverse=True)
    rep = TX.load("report.json", {}) or {}
    return {"made": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "ran": dt.datetime.fromtimestamp(rep["at"]).astimezone().isoformat(timespec="seconds") if rep.get("at") else None,
            "draft": plain(BOOK.DRAFT), "share": smb(), "questions": len(questions),
            "years": [year_view(y, docs, prior, filed, written, questions, forms, prep, open_, today) for y in years]}


# ---------------------------------------------------------------- shared with the app's user only
def acl(owner, uid, perm):
    """A POSIX access ACL in the kernel's form (version 2, entries by tag): the file's owner, one other user (`uid`),
    and no group and no others. The mask is that user's permission."""
    entries = [(USER_OBJ, owner, ANY), (USER, perm, uid), (GROUP_OBJ, 0, ANY), (MASK, perm, ANY), (OTHER, 0, ANY)]
    return struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *e) for e in entries)


def app_uid(home=None):
    """The app's user on this PC: the owner of the folder the app writes its own data into (rootless Docker maps the
    container's user to a uid of the stack user's range). Raises OSError when the app has never run here."""
    return Path(home or APP_HOME).stat().st_uid


def publish(view, out=None, uid=None, setx=None):
    """The view, readable by this user and the app's user only: the folder 0700 and the file 0600, each with an ACL
    entry for the app's user (read; the folder also to pass). Whole or not at all; an ACL that cannot be set leaves
    no file (fail closed). -> the file."""
    out, setx = Path(out or OUT), setx or os.setxattr
    uid = app_uid() if uid is None else uid
    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    setx(str(out), ACL_KEY, acl(7, uid, 5))
    tmp = out / f".{NAME}.tmp"
    tmp.write_text(json.dumps(view, ensure_ascii=False))
    os.chmod(tmp, 0o600)
    try:
        setx(str(tmp), ACL_KEY, acl(6, uid, 4))
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(out / NAME)
    return out / NAME


def refresh(conf=None, today=None, say=print):
    """Build and share the view; a failure is said by its kind only (never a figure) and never stops the desk.
    -> whether it was shared."""
    try:
        publish(build(conf, today))
        return True
    except Exception as e:                               # the desk's run goes on; the app shows its last view
        say(f"tax desk: the app's view of the drafts was not written ({type(e).__name__})")
        return False


if __name__ == "__main__":
    t0 = time.time()
    v = build()
    p = publish(v)
    print(f"{len(v['years'])} years, {sum(y['total'] for y in v['years'])} papers, {v['questions']} questions: {p} "
          f"(this user and the app's user only) in {time.time() - t0:.1f} s")
    sys.exit(0)

"""The tax desk's hands on the NAS (TAX-01, TAX-03): the few reads and writes that must happen where the mail copy and
the Steuern share are, so a document is copied on the NAS and never travels for its copy.

Not installed anywhere: ops/tax.py sends this file over `ssh synology` for each call (python3 on the NAS, standard
library only, Python 3.8) with one JSON request on stdin, and reads one JSON answer from stdout:

  index    the mail copy's headers since a time (index.sqlite opened read-only): id, time, sender, address, subject,
           attachments, category, list flag, file; never a body
  extract  each named mail's text and its attachments' text (pdftotext on the NAS; a PDF without a text layer is
           marked "needs OCR", never guessed), for the reading step
  tree     the files under the Steuern share per year, with size and checksum
  read     the text of files under the Steuern share (an owner's ELSTER protocol as HTML or PDF, Belege.csv)
  copy     an attachment (or the whole mail as .eml) copied out of the mail copy into the Steuern share
  put      a desk file (Belege.csv, a workbook) written into the Steuern share

What it must never do: write anything under the mail copy, delete or overwrite a file (a name that is taken gets a
number), write outside the Steuern share, or run anything a mail holds. Mail is data.
"""
import email
import email.policy
import gzip
import hashlib
import html.parser
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

TEXT_MAX = 400000                   # limit: refuses, a document's text past 400,000 characters is no paper; it is marked, not sent
NAME_CHARS = 120                    # a copy's file name in characters (a share's file names stay readable)


def sha(b):
    return hashlib.sha256(b).hexdigest()


class _Text(html.parser.HTMLParser):
    """HTML to plain text: blocks become lines, table cells are kept apart, scripts and styles are dropped."""
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article", "header", "footer"}
    CELL = {"td", "th"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "title"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")
        elif tag in self.CELL:
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_text(markup):
    """-> the visible text of an HTML page, one line per block, blank runs folded."""
    p = _Text()
    p.feed(markup or "")
    p.close()
    lines = [re.sub(r"[ \t ]+", " ", x).strip(" |") for x in "".join(p.out).splitlines()]
    out, blank = [], False
    for x in lines:
        if x:
            out.append(x)
            blank = False
        elif not blank and out:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def pdf_text(data, tool="pdftotext"):
    """-> (text, needs_ocr) of a PDF, through poppler's pdftotext in a private temporary folder."""
    d = tempfile.mkdtemp(prefix="tax-")
    try:
        src, dst = os.path.join(d, "in.pdf"), os.path.join(d, "out.txt")
        with open(src, "wb") as f:
            f.write(data)
        try:
            # limit: stops, one PDF's text gets 120 s; a PDF that takes longer is marked unread, the others go on
            p = subprocess.run([tool, "-layout", "-enc", "UTF-8", src, dst], capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            return "", "pdftotext could not read it ({})".format(type(e).__name__)
        if p.returncode != 0 or not os.path.exists(dst):
            return "", "pdftotext could not read it (exit {})".format(p.returncode)
        with open(dst, encoding="utf-8", errors="replace") as f:
            text = f.read().strip()
        return text, ("" if len(re.sub(r"\s", "", text)) >= 20 else "needs OCR: no text layer")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def mail_of(raw):
    return email.message_from_bytes(raw, policy=email.policy.default)


def body_text(msg):
    """The mail's own text: its plain part, else its HTML part as text."""
    plain = html_part = None
    for part in msg.walk():
        if part.is_multipart() or part.get_filename() or part.get_content_disposition() == "attachment":
            continue
        ct = part.get_content_type()
        try:
            text = part.get_content()
        except (LookupError, ValueError):
            text = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        if ct == "text/plain" and plain is None:
            plain = text
        elif ct == "text/html" and html_part is None:
            html_part = text
    return (plain if plain and plain.strip() else html_text(html_part or "")).strip()


def attachments(msg):
    """-> [(index, part)] of the mail's attachments, numbered in the order the mail holds them."""
    out = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        if part.get_filename() or part.get_content_disposition() == "attachment":
            out.append((len(out), part))
    return out


def part_text(name, ctype, data, tool="pdftotext"):
    """-> (text, note) of one attachment: a PDF through pdftotext, HTML and plain text as they are, others named only."""
    low = (name or "").lower()
    if ctype == "application/pdf" or low.endswith(".pdf"):
        return pdf_text(data, tool)
    if ctype in ("text/html",) or low.endswith((".html", ".htm")):
        return html_text(data.decode("utf-8", "replace")), ""
    if ctype.startswith("text/") or low.endswith((".txt", ".csv", ".xml")):
        return data.decode("utf-8", "replace"), ""
    if ctype.startswith("image/"):
        return "", "needs OCR: an image"
    return "", "not read: {}".format(ctype)


def read_eml(vault, path):
    full = os.path.realpath(os.path.join(vault, path))
    if not full.startswith(os.path.realpath(vault) + os.sep):
        raise ValueError("a mail's file lies outside the mail copy")
    with open(full, "rb") as f:
        raw = f.read()
    return gzip.decompress(raw) if full.endswith(".gz") else raw


def op_index(req):
    c = sqlite3.connect("file:{}?mode=ro".format(req["db"]), uri=True)
    c.row_factory = sqlite3.Row
    rows = c.execute("select id, at, sender, addr, subject, attach, category, list, path, gone from messages where at >= ? order by at",
                     (int(req["since"]),)).fetchall()
    return {"rows": [dict(r) for r in rows]}


def op_extract(req):
    out = {}
    for it in req["items"]:
        try:
            msg = mail_of(read_eml(req["vault"], it["path"]))
        except (OSError, ValueError) as e:
            out[it["id"]] = {"error": "the mail's copy could not be read: {}: {}".format(type(e).__name__, e)}
            continue
        parts = []
        for i, part in attachments(msg):
            data = part.get_payload(decode=True) or b""
            name = part.get_filename() or "attachment-{}".format(i + 1)
            text, note = part_text(name, part.get_content_type(), data, req.get("pdftotext") or "pdftotext")
            if len(text) > TEXT_MAX:
                text, note = "", "not read: {:,} characters of text, over {:,}".format(len(text), TEXT_MAX)
            parts.append({"idx": i, "name": name, "type": part.get_content_type(), "size": len(data), "sha256": sha(data),
                          "text": text, "note": note})
        body = body_text(msg)
        if len(body) > TEXT_MAX:
            body = "[the mail's text has {:,} characters, over {:,}: not read]".format(len(body), TEXT_MAX)
        out[it["id"]] = {"subject": str(msg.get("subject") or ""), "from": str(msg.get("from") or ""), "date": str(msg.get("date") or ""),
                         "body": body, "parts": parts}
    return {"mails": out}


def under(root, path):
    full = os.path.realpath(path)
    if full != os.path.realpath(root) and not full.startswith(os.path.realpath(root) + os.sep):
        raise ValueError("{} lies outside {}".format(path, root))
    return full


def op_tree(req):
    root, out = req["root"], {}
    if not os.path.isdir(root):
        return {"years": {}, "missing": True}
    for year in sorted(os.listdir(root)):
        yd = os.path.join(root, year)
        if not (re.fullmatch(r"\d{4}", year) and os.path.isdir(yd)):
            continue
        files = []
        for base, _dirs, names in os.walk(yd):
            for n in sorted(names):
                p = os.path.join(base, n)
                with open(p, "rb") as f:
                    files.append({"path": os.path.relpath(p, root), "size": os.path.getsize(p), "sha256": sha(f.read())})
        out[year] = files
    return {"years": out}


def op_read(req):
    root, out = req["root"], {}
    for rel in req["files"]:
        p = under(root, os.path.join(root, rel))
        with open(p, "rb") as f:
            data = f.read()
        text, note = part_text(os.path.basename(p), "", data, req.get("pdftotext") or "pdftotext")
        out[rel] = {"text": text, "note": note, "sha256": sha(data)}
    return {"files": out}


def free_name(folder, name):
    """A name not taken yet in the folder: the name itself, else name-2, name-3 (never an overwrite)."""
    stem, ext = os.path.splitext(name)
    cand, n = name, 1
    while os.path.exists(os.path.join(folder, cand)):
        n += 1
        cand = "{}-{}{}".format(stem, n, ext)
    return cand


def clean(name):
    """A file name the share takes: letters, digits, dot, dash and underscore."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "Beleg"
    stem, ext = os.path.splitext(name)
    return stem[:NAME_CHARS] + ext[:10]  # cap: api, a file name the share keeps readable; the whole issuer is in Belege.csv


def write_new(folder, name, data):
    os.makedirs(folder, exist_ok=True)
    final = free_name(folder, clean(name))
    fd = os.open(os.path.join(folder, final), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o664)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return final


def op_copy(req):
    root, out = req["root"], []
    for it in req["items"]:
        folder = under(root, os.path.join(root, it["folder"]))
        raw = read_eml(req["vault"], it["path"])
        if it.get("part") is None:
            data = raw
        else:
            found = [p for i, p in attachments(mail_of(raw)) if i == it["part"]]
            if not found:
                out.append({"key": it["key"], "error": "the mail has no attachment {}".format(it["part"])})
                continue
            data = found[0].get_payload(decode=True) or b""
        name = write_new(folder, it["name"], data)
        out.append({"key": it["key"], "path": os.path.relpath(os.path.join(folder, name), root), "sha256": sha(data)})
    return {"copied": out}


def op_put(req):
    """A desk file: written over only when the file there is still the desk's own last version (its checksum); a file
    the owner changed stays, and the desk's new version goes next to it under a numbered name."""
    root, out = req["root"], []
    for it in req["files"]:
        target = under(root, os.path.join(root, it["path"]))
        folder, name = os.path.split(target)
        os.makedirs(folder, exist_ok=True)
        data = it["text"].encode("utf-8")
        if os.path.exists(target):
            with open(target, "rb") as f:
                there = sha(f.read())
            if there == sha(data):
                out.append({"path": it["path"], "sha256": there, "same": True})
                continue
            if there != it.get("ours"):
                name = free_name(folder, name)
                target = os.path.join(folder, name)
        tmp = target + ".tmp-desk"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, target)
        out.append({"path": os.path.relpath(target, root), "sha256": sha(data)})
    return {"written": out}


OPS = {"index": op_index, "extract": op_extract, "tree": op_tree, "read": op_read, "copy": op_copy, "put": op_put}


def main():
    req = json.load(sys.stdin)
    try:
        res = OPS[req["op"]](req)
    except Exception as e:                     # the answer says what went wrong; the desk reports it
        res = {"error": "{}: {}".format(type(e).__name__, e)}
    json.dump(res, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()

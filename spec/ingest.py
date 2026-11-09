"""Spec comprehension, step 1: PDF -> structured spec model (offline, no model calls).
  python3 spec/ingest.py <spec.pdf> <out-dir> [--id-pattern REGEX]
Writes <out-dir>/spec.json (sections with text and page, requirements with id/text/section/page) and one
Markdown page per section in <out-dir>/pages/ for search (qmd) and for reading.
Requirements with explicit IDs (e.g. [MQTT-3.1.2-24]) are taken from the body text. Specs without IDs need the
model-based extractor (spec/extract.py), which is measured against the explicit ones on a spec that has both.
"""
import json, re, sys
from collections import Counter
from pathlib import Path

import pdfplumber

TOC = re.compile(r"\.{5,}\s*\d+\s*$")
LINENO = re.compile(r"^\d{1,5}(?: |$)")
HEAD = re.compile(r"^(\d+(?:\.\d+){0,5})\s+([A-Z][^\n]{1,90})$")


def pages(pdf):
    with pdfplumber.open(pdf) as p:
        for n, pg in enumerate(p.pages, 1):
            yield n, pg.extract_text() or ""


def furniture(all_pages):
    """Page headers and footers: lines that recur (digits ignored) on at least a quarter of the pages."""
    seen = Counter()
    for _, text in all_pages:
        seen.update({re.sub(r"\d+", "#", LINENO.sub("", l).strip()) for l in text.splitlines() if l.strip()})
    return {k for k, v in seen.items() if v >= max(3, len(all_pages) // 4) and len(k) > 3}


def parse(pdf, id_pat):
    sections, cur, body_lines = [], None, []
    all_pages = list(pages(pdf))
    skip = furniture(all_pages)
    for page, text in all_pages:
        for raw in text.splitlines():
            if TOC.search(raw):
                continue
            line = LINENO.sub("", raw).strip()
            if re.sub(r"\d+", "#", line) in skip:
                continue
            if not line:
                continue
            m = HEAD.match(line)
            if m and len(m.group(1)) <= 12 and not re.search(r"\[[A-Z]+-", line):
                cur = {"id": m.group(1), "title": m.group(2).strip(), "page": page, "text": []}
                sections.append(cur)
                continue
            if line.startswith("Appendix "):
                cur = {"id": line.split(".")[0], "title": line, "page": page, "text": []}
                sections.append(cur)
                continue
            if cur is not None:
                cur["text"].append(line)
            body_lines.append((page, cur["id"] if cur else "", line))
    for s in sections:
        s["text"] = " ".join(s["text"])
    # Requirements: the sentence that ends with (or contains) an explicit ID. Appendix copies are skipped.
    reqs = {}
    for s in sections:
        if s["id"].startswith("Appendix"):
            continue
        prev = ""
        for sent in re.split(r"(?<=[.:])\s+(?=[A-Z\[])", s["text"]):
            for rid in re.findall(id_pat, sent):
                text = re.sub(id_pat, "", sent).strip(" .;")
                if not re.search(r"[A-Za-z]{3}", text):     # "... U+0000. [ID]." : the ID belongs to the sentence before
                    text = re.sub(id_pat, "", prev).strip(" .;")
                if rid not in reqs:
                    reqs[rid] = {"id": rid.strip("[]"), "text": text, "section": s["id"],
                                 "section_title": s["title"], "page": s["page"]}
            prev = sent
    return sections, list(reqs.values())


def main():
    pdf, out = sys.argv[1], Path(sys.argv[2])
    id_pat = sys.argv[sys.argv.index("--id-pattern") + 1] if "--id-pattern" in sys.argv else r"\[[A-Z]+-[0-9.]+-[0-9]+\]"
    sections, reqs = parse(pdf, id_pat)
    out.mkdir(parents=True, exist_ok=True)
    (out / "spec.json").write_text(json.dumps({"source": Path(pdf).name, "sections": sections,
                                               "requirements": reqs}, indent=1, ensure_ascii=False))
    pg = out / "pages"; pg.mkdir(exist_ok=True)
    by_sec = {}
    for r in reqs:
        by_sec.setdefault(r["section"], []).append(r)
    for s in sections:
        name = re.sub(r"[^A-Za-z0-9.]+", "-", f"{s['id']}-{s['title']}")[:80].strip("-")  # cap: id (a file name; the title is in the file)
        lines = [f"# {s['id']} {s['title']}", "", f"Source: {Path(pdf).name}, page {s['page']}", "", s["text"]]
        if by_sec.get(s["id"]):
            lines += ["", "## Requirements in this section", ""]
            lines += [f"- **{r['id']}**: {r['text']}" for r in by_sec[s["id"]]]
        (pg / f"{name}.md").write_text("\n".join(lines) + "\n")
    print(f"{len(sections)} sections, {len(reqs)} requirements with IDs -> {out}")


if __name__ == "__main__":
    main()

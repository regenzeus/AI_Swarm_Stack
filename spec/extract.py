"""Spec comprehension, step 1b: requirements from specs WITHOUT numbered requirements (most real-world PDFs).
  python3 spec/extract.py <spec.json> <out.jsonl> [--section 3.1.] [--pace S] [--model gpt-sub-fast]
Per section, the model lists every atomic requirement, including implicit ones ("It is a Protocol Error to ...",
"the value can only be 0, 1 or 2"), split compound sentences, and records strength, actor and condition.
Existing requirement IDs are hidden from it. On a spec that has IDs this measures recall: how many of the numbered
requirements the extraction found (token overlap >= 0.6 within the section). spec/pilot/extract_baseline.py is the
model-free yardstick (MUST/SHALL sentences).
"""
import json, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import link  # noqa: E402

TAG = re.compile(r"\[[A-Z]+-[0-9.]+-[0-9]+\]")
WORD = re.compile(r"[a-z0-9]+")


def toks(t):
    return set(WORD.findall(t.lower()))


def main():
    spec_p, out = sys.argv[1:3]
    arg = lambda k, d: type(d)(sys.argv[sys.argv.index(k) + 1]) if k in sys.argv else d
    section, pace, model = arg("--section", ""), arg("--pace", 8.0), arg("--model", "gpt-sub-fast")
    spec = json.load(open(spec_p))
    secs = [s for s in spec["sections"] if s["id"].startswith(section) and not s["id"].startswith("Appendix")
            and len(s["text"]) > 40]
    done = {json.loads(l)["section"] for l in open(out)} if Path(out).exists() else set()
    with open(out, "a") as f:
        for n, s in enumerate(secs, 1):
            if s["id"] in done:
                continue
            text = TAG.sub("", s["text"])
            text = text[:9000] + (f" [… {len(text) - 9000:,} more characters cut]" if len(text) > 9000 else "")  # cap: prompt
            r = link.ask(
                f"Section {s['id']} {s['title']} of a technical specification:\n\n{text}\n\n"
                "List every requirement this section states, as atomic statements (one obligation each): explicit ones "
                "(MUST, MUST NOT, SHALL, REQUIRED, SHOULD, MAY) and implicit ones (\"It is a Protocol Error to ...\", "
                "\"the value can only be ...\", \"is not permitted\"). Split compound sentences; keep the spec's wording; "
                "skip pure explanations and examples.\n"
                'Answer only JSON: {"requirements": [{"text": "...", "strength": "must|should|may", '
                '"actor": "client|server|sender|receiver|both|other", "condition": "... or empty"}]}', model)
            items = r.get("requirements", [])
            f.write(json.dumps({"section": s["id"], "title": s["title"], "items": items,
                                "error": r.get("error")}) + "\n"); f.flush()
            print(f"[{n}/{len(secs)}] {s['id']:12} {len(items):3} requirements  {s['title'][:50]}", flush=True)  # cap: id (a progress line; the record above keeps the title)
            time.sleep(pace)
    # Score against the numbered requirements of the same sections
    rows = [json.loads(l) for l in open(out)]
    got = {x["section"]: [i.get("text", "") for i in x["items"]] for x in rows}
    reqs = [q for q in spec["requirements"] if q["section"] in got]
    hit = [q for q in reqs if any(len(toks(q["text"]) & toks(t)) / max(len(toks(q["text"])), 1) >= 0.6
                                  for t in got[q["section"]])]
    total = sum(len(v) for v in got.values())
    print(f"\n{len(rows)} sections: {total} requirements extracted; numbered requirements found {len(hit)}/{len(reqs)} "
          f"({len(hit) / max(len(reqs), 1):.0%}); not found: {[q['id'] for q in reqs if q not in hit][:12]}")  # cap: list (the count is above)


if __name__ == "__main__":
    main()

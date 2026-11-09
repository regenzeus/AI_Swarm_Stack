"""Extraction baseline without a model: how many of a spec's numbered requirements would plain MUST/SHALL sentence
matching find if the numbers were not there? The yardstick for the model-based extractor (spec/extract.py).
  python3 spec/pilot/extract_baseline.py <spec.json>"""
import json, re, sys

TAG = re.compile(r"\[[A-Z]+-[0-9.]+-[0-9]+\]")
WORD = re.compile(r"[a-z0-9]+")
STRONG = re.compile(r"\b(MUST|SHALL|REQUIRED)\b")
ANY = re.compile(r"\b(MUST|SHALL|REQUIRED|SHOULD|MAY)\b")


def toks(t):
    return set(WORD.findall(t.lower()))


def sentences(spec):
    for s in spec["sections"]:
        if s["id"].startswith("Appendix"):
            continue
        for sent in re.split(r"(?<=[.:])\s+(?=[A-Z\[])", TAG.sub("", s["text"])):
            yield s["id"], sent


def covered(req, cands, threshold=0.8):
    rt = toks(req["text"])
    return any(sec == req["section"] and len(rt & toks(t)) / max(len(rt), 1) >= threshold for sec, t in cands)


def main():
    spec = json.load(open(sys.argv[1]))
    all_s = list(sentences(spec))
    strong = [x for x in all_s if STRONG.search(x[1])]
    soft = [x for x in all_s if ANY.search(x[1])]
    reqs = spec["requirements"]
    f_strong = sum(covered(r, strong) for r in reqs)
    f_any = sum(covered(r, soft) for r in reqs)
    print(f"{len(reqs)} numbered requirements; {len(strong)} MUST/SHALL sentences, {len(soft)} incl. SHOULD/MAY")
    print(f"MUST/SHALL sentences cover {f_strong} ({f_strong / len(reqs):.0%}); incl. SHOULD/MAY {f_any} ({f_any / len(reqs):.0%})")
    missed = [r for r in reqs if not covered(r, soft)]
    for r in missed[:8]:  # cap: list (the first eight; the counts are above)
        print(f"  missed {r['id']}: {(e := r['text'])[:110]}{'…' if len(e) > 110 else ''}")  # cap: preview (the whole text is in the requirements file)
    if len(sys.argv) > 2:                     # model extraction file (spec/extract.py): alone and combined
        rows = [json.loads(l) for l in open(sys.argv[2])]
        model = [(x["section"], i.get("text", "")) for x in rows for i in x["items"]]
        secs = {x["section"] for x in rows}
        sub = [r for r in reqs if r["section"] in secs]
        k = lambda c, t=0.6: sum(covered(r, c, t) for r in sub)
        kw = [x for x in soft if x[0] in secs]
        both = kw + model
        print(f"sections with model extraction: {len(secs)}, numbered requirements there: {len(sub)}")
        print(f"  keyword only {k(kw)}/{len(sub)}, model only {k(model)}/{len(sub)}, combined {k(both)}/{len(sub)}")
        print(f"  statements to review: keyword {len(kw)}, model {len(model)}")
        for r in [r for r in sub if not covered(r, both, 0.6)]:
            print(f"  still missed {r['id']}: {(e := r['text'])[:110]}{'…' if len(e) > 110 else ''}")  # cap: preview (the whole text is in the requirements file)


if __name__ == "__main__":
    main()

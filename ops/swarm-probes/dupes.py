"""Phase 0, proof 3a: which similarity finds the known duplicates among the 27 ideas of 2026-10-29?
Ground truth (the owner's triage): {13,15,17,21,24,25} partial-read, {19,26} tool errors, {20,22} backup rsync.
Lexical TF-IDF cosine here (stdlib, no model); embeddings come in as a JSON file of vectors per id (argv[2]).
Run: python3 dupes.py ideas.json [emb.json]  (ideas.json = id, title, why, description of the proposals table;
emb.json = the "vectors" of embed_in_hindsight.py, run with docker exec -i in aistack-hindsight-1)."""
import json, math, re, sys
from collections import Counter
from itertools import combinations

rows = json.load(open(sys.argv[1]))
GROUPS = [{13, 15, 17, 21, 24, 25}, {19, 26}, {20, 22}]
dup = lambda a, b: any(a in g and b in g for g in GROUPS)
text = {r["id"]: " ".join(str(r.get(k) or "") for k in ("title", "why", "description")) for r in rows}
STOP = set("the a an and or of to in for on is are be it its this that with as by not no from at when only one".split())


def toks(s):
    return [w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 2]


df = Counter(w for t in text.values() for w in set(toks(t)))
N = len(text)
vec = {}
for i, t in text.items():
    tf = Counter(toks(t))
    v = {w: (1 + math.log(c)) * math.log(N / df[w]) for w, c in tf.items()}
    n = math.sqrt(sum(x * x for x in v.values())) or 1
    vec[i] = {w: x / n for w, x in v.items()}
lex = lambda a, b: sum(x * vec[b].get(w, 0) for w, x in vec[a].items())

emb = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else {}
emb = {int(k): v for k, v in emb.items()}
cos = lambda a, b: sum(x * y for x, y in zip(emb[a], emb[b])) / (math.sqrt(sum(x * x for x in emb[a])) * math.sqrt(sum(y * y for y in emb[b])))

pairs = list(combinations(sorted(text), 2))
for name, f in (("lexical tf-idf", lex), ("embedding", cos)):
    if name == "embedding" and not emb:
        continue
    scored = sorted(((f(a, b), dup(a, b), a, b) for a, b in pairs), reverse=True)
    pos = sum(d for _, d, *_ in scored)
    # AUC: chance a duplicate pair scores above a non-duplicate pair
    neg = len(scored) - pos
    rank_sum, seen_neg = 0, 0
    for s, d, *_ in reversed(scored):
        if d:
            rank_sum += seen_neg
        else:
            seen_neg += 1
    auc = rank_sum / (pos * neg)
    best = max(((t, sum(1 for s, d, *_ in scored if s >= t and d), sum(1 for s, d, *_ in scored if s >= t and not d))
                for t in sorted({round(s, 3) for s, *_ in scored})), key=lambda x: (x[1] - 2 * x[2]))
    top = scored[:pos]
    print(f"{name}: {pos} duplicate pairs of {len(pairs)}; AUC {auc:.3f}; of the top {pos} pairs {sum(d for _, d, *_ in top)} are duplicates;"
          f" best threshold {best[0]:.2f} catches {best[1]}/{pos} with {best[2]} false")
    missed = [(round(s, 2), a, b) for s, d, a, b in scored if d and s < best[0]]
    print("   missed at that threshold:", missed[:8])
    # the guard's real question: for each idea, is its nearest earlier idea a true duplicate?
    hits = sum(1 for b in sorted(text) if any(dup(a, b) for a in text if a < b) and
               max((a for a in text if a < b), key=lambda a: f(a, b)) in {a for a in text if dup(a, b)})
    need = sum(1 for b in sorted(text) if any(dup(a, b) for a in text if a < b))
    print(f"   nearest earlier idea is a true duplicate for {hits}/{need} later duplicates")

import json, resource, sys, time
from sentence_transformers import SentenceTransformer
rows = json.load(sys.stdin)
t = time.time()
m = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
load = time.time() - t
t = time.time()
texts = [" ".join(str(r.get(k) or "") for k in ("title", "why", "description")) for r in rows]
v = m.encode(texts, normalize_embeddings=True)
per = (time.time() - t) / len(texts)
print(json.dumps({"vectors": {r["id"]: list(map(float, x)) for r, x in zip(rows, v)},
                  "load_s": round(load, 1), "encode_ms_each": round(per * 1000, 1),
                  "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)}))

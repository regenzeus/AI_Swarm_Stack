"""Retrieval quality per qmd collection: recall@8, nDCG@8 and MRR against hand-made qrels.

  python3 eval/retrieval.py            bm25, vector, hybrid (no rerank: what Hermes uses today)
  python3 eval/retrieval.py --rerank   also hybrid + LLM rerank (minutes on CPU), for the rerank on/off decision
qrels: eval/qrels/<collection>.json  {"collection", "queries": [{"id", "query", "expected_files": [...]}]}
Results: eval/results/<stamp>-retrieval*.json
"""
import json, math, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
K = 8
MODES = {"bm25": ["search"], "vector": ["vsearch"], "hybrid": ["query", "--no-rerank"], "rerank": ["query"]}


def search(mode, query, collection):
    t = time.time()
    p = subprocess.run(["docker", "exec", "aistack-qmd-1", "qmd", *MODES[mode], query, "-c", collection,
                        "--json", "-n", str(K)], capture_output=True, text=True)
    try:
        hits = json.loads(p.stdout[p.stdout.index("["):])
    except ValueError:
        hits = []
    prefix = f"qmd://{collection}/"
    files = []
    for h in hits:  # one hit per chunk; keep the first rank of each file
        f = h["file"].removeprefix(prefix)
        if f not in files:
            files.append(f)
    return files[:K], time.time() - t


def score(files, expected):
    rel = [f in expected for f in files]
    recall = sum(rel) / len(expected)
    dcg = sum(1 / math.log2(i + 2) for i, r in enumerate(rel) if r)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(expected), K)))
    mrr = next((1 / (i + 1) for i, r in enumerate(rel) if r), 0.0)
    return recall, dcg / idcg, mrr


def main():
    modes = ["bm25", "vector", "hybrid"] + (["rerank"] if "--rerank" in sys.argv else [])
    out = {}
    for f in sorted((HERE / "qrels").glob("*.json")):
        qrels = json.loads(f.read_text())
        c = qrels["collection"]
        rows = {m: [] for m in modes}
        for q in qrels["queries"]:
            for m in modes:
                files, secs = search(m, q["query"], c)
                r, n, mrr = score(files, q["expected_files"])
                rows[m].append({"id": q["id"], "recall": r, "ndcg": n, "mrr": mrr, "secs": round(secs, 2),
                                "top": files[:3]})
        summary = {m: {k: round(sum(x[k] for x in v) / len(v), 3) for k in ("recall", "ndcg", "mrr", "secs")}
                   for m, v in rows.items()}
        out[c] = {"summary": summary, "queries": rows}
        print(f"{c} ({len(qrels['queries'])} queries)")
        for m, s in summary.items():
            print(f"  {m:7} recall@{K} {s['recall']:.2f}  nDCG@{K} {s['ndcg']:.2f}  MRR {s['mrr']:.2f}  {s['secs']:.1f} s/query")
        weak = [x["id"] for x in rows["hybrid"] if x["recall"] < 0.5]
        if weak:
            print(f"  hybrid finds less than half for: {', '.join(weak)}")
    path = HERE / "results" / f"{time.strftime('%Y%m%d-%H%M%S')}-retrieval{'-rerank' if 'rerank' in modes else ''}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    print("->", path.relative_to(HERE.parent))


if __name__ == "__main__":
    main()

"""Spec comprehension, step 2: which code implements which requirement? (traceability link recovery)
  python3 spec/link.py <spec.json> <repo> <graph.json> <out.jsonl> [--section 3.1.] [--limit N] [--pace S]
                       [--model gpt-sub-fast] [--k 40]
Narrowing in two stages, like SpecMap: (1) a keyword search (BM25 over identifiers and comments) picks k
candidate functions out of the whole code base, (2) the model reads the requirement and, for each candidate, its
signature plus the passage that matches the requirement best, and picks the functions that implement it.
Requirement IDs written in the code are hidden from both stages; where they exist they serve as ground truth.
Two scores: "exact" (the tagged function) and "near" (the tagged function or a direct caller/callee in the code
graph: requirements are often enforced across a call chain, while developers tag one spot).
Functions and call edges come from the Graphify code graph, so any language Graphify parses works.
Model via LiteLLM on vk-spec (subscription only). Env: LITELLM_URL, VK_SPEC.
"""
import json, math, os, re, sys, time, urllib.request
from collections import Counter, defaultdict
from pathlib import Path

TAG = re.compile(r"\[?MQTT-[0-9.]+-[0-9]+\]?")          # pilot: the spec's ID format; generalise per spec
WORD = re.compile(r"[A-Za-z][a-z]+|[A-Z]+(?![a-z])|\d+")
STOP = set("the a an and or of to in is be by for if it this that with as on at not must may should shall "
           "any all are when which from its than then has have been".split())
TESTS = re.compile(r"(_test\.go|test_.*\.py|\.test\.[jt]s)$")


def tokens(text):
    return [w.lower() for w in WORD.findall(text) if w.lower() not in STOP and len(w) > 1]


def query_tokens(text):
    """Spec words plus adjacent pairs joined: the spec writes "Keep Alive", the code "keepalive"."""
    words = [w.lower() for w in WORD.findall(text)]
    pairs = [a + b for a, b in zip(words, words[1:]) if a not in STOP and b not in STOP]
    return tokens(text) + pairs


def chunks(repo, graph, tests=False):
    g = json.load(open(graph))
    starts = defaultdict(set)
    for n in g["nodes"]:
        f, loc = n.get("source_file") or "", n.get("source_location") or ""
        if f and loc.startswith("L") and (tests or not TESTS.search(f)):
            starts[f].add((int(loc[1:]), n["label"], n["id"]))
    out = []
    for f, s in starts.items():
        try:
            lines = (Path(repo) / f).read_text(errors="replace").splitlines()
        except OSError:
            continue
        s = sorted(s)
        for i, (line, label, node) in enumerate(s):
            if line <= 1 and label == Path(f).name:
                continue                                    # the file node itself
            end = (s[i + 1][0] - 1) if i + 1 < len(s) else len(lines)
            text = "\n".join(lines[line - 1:end])
            out.append({"id": len(out), "node": node, "file": f, "symbol": label, "start": line, "end": end,
                        "tags": sorted({t.strip("[]") for t in TAG.findall(text)}), "text": TAG.sub("", text)})
    return out, g


def neighbours(g, ch):
    """chunk id -> chunk ids of direct callers and callees (code graph call edges)."""
    by_node = {c["node"]: c["id"] for c in ch}
    nb = defaultdict(set)
    for l in g.get("links", []):
        if l.get("relation") in ("calls", "indirect_call", "method") and l["source"] in by_node and l["target"] in by_node:
            a, b = by_node[l["source"]], by_node[l["target"]]
            nb[a].add(b); nb[b].add(a)
    return nb


class BM25:
    def __init__(self, docs, k1=1.4, b=0.75):
        self.docs = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = sum(self.len) / max(len(docs), 1)
        df = Counter(w for d in self.docs for w in d)
        n = len(docs)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}
        self.k1, self.b = k1, b

    def top(self, query, k):
        q = set(query)
        scores = []
        for i, d in enumerate(self.docs):
            s = sum(self.idf.get(w, 0) * d[w] * (self.k1 + 1) /
                    (d[w] + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg)) for w in q if w in d)
            scores.append((s, i))
        return [i for s, i in sorted(scores, reverse=True)[:k] if s > 0]


def excerpt(c, query, width=30, cap=1700):
    """Signature plus the window of the function that overlaps most with the requirement's words."""
    lines = c["text"].splitlines()
    if len(lines) <= width + 4:
        return c["text"][:cap]
    q = set(query)
    score = [len(q & set(tokens(l))) for l in lines]
    best = max(range(3, len(lines) - width + 1), key=lambda i: sum(score[i:i + width]))
    win = lines[best:best + width]
    return ("\n".join(lines[:3]) + f"\n    ... (lines {c['start'] + best}-{c['start'] + best + width - 1}) ...\n"
            + "\n".join(win))[:cap]


def ask(prompt, model):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(os.environ.get("LITELLM_URL", "http://litellm:4000") + "/v1/chat/completions",
                                 data=body, headers={"Authorization": f"Bearer {os.environ['VK_SPEC']}",
                                                     "Content-Type": "application/json"})
    err = None
    for attempt in range(4):
        try:
            text = json.load(urllib.request.urlopen(req, timeout=240))["choices"][0]["message"]["content"]
            return json.loads(re.search(r"\{.*\}", text, re.S).group(0))
        except Exception as e:
            err = e
            time.sleep(30 * (attempt + 1))
    return {"error": str(err)}


def pick(req, cands, query, model):
    listing = "\n\n".join(f"[{i}] {c['file']}:{c['start']}-{c['end']} {c['symbol']}\n{excerpt(c, query)}"
                          for i, c in enumerate(cands))
    prompt = (f"Requirement {req['id']} (section {req['section']} {req['section_title']}):\n{req['text']}\n\n"
              "Below are candidate functions from the implementation, each shown with its signature and the "
              "passage most related to the requirement. Which of them implement, enforce or check this requirement? "
              "Mind who the requirement binds (client or server) and the direction (sending or receiving): for a rule "
              "on what the other side must not send, the implementation is the code that checks incoming data. "
              "Pick at most 3, best first; pick none if none does.\n\n" + listing +
              '\n\nAnswer only JSON: {"picks": [candidate numbers], "reason": "<25 words>"}')
    r = ask(prompt, model)
    return [cands[i]["id"] for i in r.get("picks", []) if isinstance(i, int) and 0 <= i < len(cands)], r


def summary(rows):
    s = [x for x in rows if x["truth"]]
    if not s:
        return "no requirements with ground truth"
    f = lambda k: f"{sum(x[k] for x in s)} ({sum(x[k] for x in s) / len(s):.0%})"
    return (f"ground truth for {len(s)}: keyword stage had the right code in {f('in_candidates')}; "
            f"model exact {f('hit')}, exact-or-neighbour {f('near')}")


def main():
    spec, repo, graph, out = sys.argv[1:5]
    arg = lambda k, d: type(d)(sys.argv[sys.argv.index(k) + 1]) if k in sys.argv else d
    section, limit, pace = arg("--section", ""), arg("--limit", 10**6), arg("--pace", 8.0)
    model, k, expand = arg("--model", "gpt-sub-fast"), arg("--k", 40), "--expand" in sys.argv
    reqs = [r for r in json.load(open(spec))["requirements"] if r["section"].startswith(section)][:limit]
    ch, g = chunks(repo, graph)
    nb = neighbours(g, ch)
    bm = BM25([tokens(c["symbol"] + " " + c["text"]) for c in ch])
    truth = defaultdict(set)
    for c in ch:
        for t in c["tags"]:
            truth[t].add(c["id"])
    done = {json.loads(l)["id"] for l in open(out)} if Path(out).exists() else set()
    print(f"{len(ch)} functions, {sum(len(v) for v in nb.values()) // 2} call edges, {len(reqs)} requirements "
          f"({sum(r['id'] in truth for r in reqs)} with ground truth), model {model}")
    with open(out, "a") as f:
        for n, r in enumerate(reqs, 1):
            if r["id"] in done:
                continue
            query = query_tokens(r["text"] + " " + r["section_title"])
            if expand:   # the spec's words are not the code's words: let the model guess identifiers first
                terms = ask(f"Requirement: {r['text']}\n\nList 10-15 words, identifiers or constants that source code "
                            "implementing or checking this requirement would likely contain (function, field, variable "
                            'and error names; split camelCase into words is fine). Answer only JSON: {"terms": [...]}',
                            model).get("terms", [])
                query = query + tokens(" ".join(str(t) for t in terms)) * 2
            cand_ids = bm.top(query, k)
            picks, raw = pick(r, [ch[i] for i in cand_ids], query, model)
            gt = truth.get(r["id"], set())
            near = gt | {j for t in gt for j in nb[t]}
            rec = {"id": r["id"], "truth": sorted(gt), "candidates": cand_ids, "picks": picks,
                   "in_candidates": bool(gt & set(cand_ids)) if gt else None,
                   "hit": bool(gt & set(picks)) if gt else None, "near": bool(near & set(picks)) if gt else None,
                   "picked": [f"{ch[i]['file']}:{ch[i]['start']} {ch[i]['symbol']}" for i in picks],
                   "reason": raw.get("reason", raw.get("error", ""))}
            f.write(json.dumps(rec) + "\n"); f.flush()
            mark = lambda v: "Y" if v else ("-" if gt else " ")
            print(f"[{n}/{len(reqs)}] {r['id']:16} truth={len(gt)} cand={mark(rec['in_candidates'])} "
                  f"exact={mark(rec['hit'])} near={mark(rec['near'])} {rec['picked'][:2]}", flush=True)
            time.sleep(pace)
    print("\n" + summary([json.loads(l) for l in open(out)]))


if __name__ == "__main__":
    main()

"""Spec comprehension, step 3: does the code meet the requirement? One verdict per requirement, with evidence.
  python3 spec/judge.py <spec.json> <repo> <graph.json> <links.jsonl[,more]> <out.jsonl> --ids ID,ID,...
                        [--oracle] [--pace S] [--model gpt-sub]
Reads the functions step 2 linked to each requirement (or, with --oracle, the functions the code's own requirement
tags point to: that isolates judging errors from linking errors), shows them in full together with the
requirement and its section, and asks for a verdict:
  implemented | partial | missing | contradicted | not_applicable (binds the other side, e.g. a client rule in a broker)
with the exact lines as evidence. Requirement tags in the code are hidden. Model via LiteLLM on vk-spec.
"""
import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import link  # noqa: E402


def code_of(c, cap=7000):
    lines = c["text"].splitlines()
    numbered = "\n".join(f"{c['start'] + i:5} {l}" for i, l in enumerate(lines))
    return numbered[:cap] + ("\n      ... (truncated)" if len(numbered) > cap else "")


def main():
    spec_p, repo, graph, links_p, out = sys.argv[1:6]
    arg = lambda k, d: type(d)(sys.argv[sys.argv.index(k) + 1]) if k in sys.argv else d
    ids, pace, model, oracle = arg("--ids", "").split(","), arg("--pace", 10.0), arg("--model", "gpt-sub"), "--oracle" in sys.argv
    spec = json.load(open(spec_p))
    reqs = {r["id"]: r for r in spec["requirements"]}
    sections = {s["id"]: s for s in spec["sections"]}
    ch, g = link.chunks(repo, graph)
    nb = link.neighbours(g, ch)
    tagged = {}
    for c in ch:
        for t in c["tags"]:
            tagged.setdefault(t, []).append(c["id"])
    links = {}
    for p in links_p.split(","):
        if Path(p).exists():
            for l in open(p):
                x = json.loads(l)
                links[x["id"]] = x["picks"]
    done = {json.loads(l)["id"] for l in open(out)} if Path(out).exists() else set()
    with open(out, "a") as f:
        for n, rid in enumerate(ids, 1):
            if rid in done or rid not in reqs:
                continue
            r = reqs[rid]
            fn = tagged.get(rid, []) if oracle else links.get(rid, [])
            context = sections.get(r["section"], {}).get("text", "")
            context = context[:2500] + (" [… more of the section cut]" if len(context) > 2500 else "")  # cap: prompt
            code = "\n\n".join(f"--- {ch[i]['file']} {ch[i]['symbol']}\n{code_of(ch[i])}" for i in fn) or "(no code was linked)"
            # Requirements are often fulfilled one call away: show the most related direct callers/callees too.
            query = link.tokens(r["text"] + " " + r["section_title"])
            near = sorted({j for i in fn for j in nb[i]} - set(fn),
                          key=lambda j: -len(set(query) & set(link.tokens(ch[j]["text"]))))[:4]
            if near:
                code += "\n\nDirectly connected functions (callers/callees), most related passage:\n" + "\n\n".join(
                    f"--- {ch[j]['file']}:{ch[j]['start']} {ch[j]['symbol']}\n{link.excerpt(ch[j], query)}" for j in near)
            prompt = (f"You audit an implementation against its specification. The implementation is a server (an MQTT broker).\n\n"
                      f"Requirement {rid} (section {r['section']} {r['section_title']}):\n{r['text']}\n\n"
                      f"Section context:\n{context}\n\nThe code that was linked to this requirement (line numbers on the left):\n{code}\n\n"
                      "Judge from this code. Verdicts:\n"
                      "- implemented: the code makes the requirement true\n"
                      "- contradicted: the code does something the requirement forbids, or uses a different value or behaviour\n"
                      "- partial: ONLY if you can name a concrete case (input or situation) that this code handles against the requirement\n"
                      "- missing: the code is clearly where this would have to happen, and it does not happen\n"
                      "- not_here: this code does not decide the matter; the implementation may well be elsewhere\n"
                      "- not_applicable: the requirement binds the other side and needs nothing from a server\n"
                      "Check values, conditions and directions exactly. Do not report missing or partial just because you cannot see the whole system.\n"
                      'Answer only JSON: {"verdict": "...", "evidence": "file:line[-line]", "explanation": "<40 words>", '
                      '"confidence": 0.0-1.0}')
            v = link.ask(prompt, model)
            rec = {"id": rid, "oracle": oracle, "functions": [f"{ch[i]['file']}:{ch[i]['start']} {ch[i]['symbol']}" for i in fn], **v}
            f.write(json.dumps(rec) + "\n"); f.flush()
            print(f"[{n}/{len(ids)}] {rid:16} {v.get('verdict', '?'):14} {v.get('evidence', '')[:40]:40} {v.get('explanation', v.get('error', ''))[:90]}", flush=True)  # cap: id (a progress line; the record above is whole)
            time.sleep(pace)


if __name__ == "__main__":
    main()

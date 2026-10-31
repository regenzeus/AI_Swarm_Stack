"""Spec pilot report: linking and judging scores from the run files.
  python3 spec/pilot/report.py <runs dir> <mutations.json> <controls,comma,separated> [--tag v2]
Two flag levels: "deviation" (contradicted: the code does something else) and "review" (missing/partial).
Collateral: requirements a planted change also breaks (found by the first judge run) are expected hits, not controls."""
import json, sys
from pathlib import Path

runs, muts, controls = Path(sys.argv[1]), json.load(open(sys.argv[2])), sys.argv[3].split(",")
tag = sys.argv[sys.argv.index("--tag") + 1] if "--tag" in sys.argv else ""
COLLATERAL = {"MQTT-3.1.2-25": "too-large packets not discarded (follows from the doubled size limit)",
              "MQTT-3.2.2-16": "assigned ids not unique (follows from the 2-character ids)"}
expected = {m["id"]: m["change"] for m in muts} | COLLATERAL
controls = [c for c in controls if c not in expected]
load = lambda p: {json.loads(l)["id"]: json.loads(l) for l in open(p)} if Path(p).exists() else {}
DEV, REVIEW = {"contradicted"}, {"missing", "partial"}

out = [f"# Spec pilot: MQTT 5.0 spec vs mochi-mqtt {tag}".rstrip(), ""]
links = {}
for p in sorted(runs.glob("link-*.jsonl")):
    links.update(load(p))
s = [x for x in links.values() if x["truth"]]
if s:
    pc = lambda k: f"{sum(x[k] for x in s)}/{len(s)} ({sum(x[k] for x in s) / len(s):.0%})"
    out += ["## Linking (requirement -> code)", f"- requirements with ground truth: {len(s)}",
            f"- keyword stage had the right function among 40 candidates: {pc('in_candidates')}",
            f"- model picked the tagged function: {pc('hit')}; tagged function or a direct caller/callee: {pc('near')}", ""]

suffix = f"-{tag}" if tag else ""
for name, f in [("original, correct code given", "judge-oracle-original"),
                ("deviated copy, correct code given", "judge-oracle-mutant"),
                ("deviated copy, code found by the pipeline", "judge-pipeline-mutant")]:
    j = load(runs / f"{f}{suffix}.jsonl")
    if not j:
        continue
    out.append(f"## Judging: {name}")
    if "mutant" in f:
        dev = [i for i in expected if j.get(i, {}).get("verdict") in DEV]
        rev = [i for i in expected if j.get(i, {}).get("verdict") in REVIEW]
        seen = [i for i in expected if i in j]
        out.append(f"- broken requirements: {len(seen)}; reported as deviation {len(dev)}, as needs-review {len(rev)}, "
                   f"missed {len(seen) - len(dev) - len(rev)}")
        for i in seen:
            v = j[i]
            out.append(f"  - {i} ({expected[i]}): {v.get('verdict', '-')} {v.get('evidence', '')} - {v.get('explanation', '')[:110]}")
    ctl = [j[i] for i in controls if i in j]
    if ctl:
        dv = [x for x in ctl if x.get("verdict") in DEV]
        rv = [x for x in ctl if x.get("verdict") in REVIEW]
        out.append(f"- unchanged requirements ({len(ctl)}): false deviations {len(dv)}, needs-review {len(rv)}"
                   + "".join(f"\n  - {x['id']}: {x.get('verdict')} - {x.get('explanation', '')[:110]}" for x in dv + rv))
    out.append("")
text = "\n".join(out)
print(text)
(runs / f"REPORT{suffix}.md").write_text(text + "\n")

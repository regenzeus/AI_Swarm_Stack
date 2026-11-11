#!/usr/bin/env python3
"""The interim scorer (docs/spikes/EVAL.md): an exam set as a Phoenix dataset, a rubric judge as a Phoenix evaluator,
each scoring as a Phoenix experiment. Runs inside run.sh's pinned container; Phoenix's own client and evals do the work.

  exam.py run <set.yaml> [--results R.jsonl] [--model M] [--name N] [--json]
      Puts the set into Phoenix as dataset exam-<name>-<hash of the file> (reused when it is already there), runs one
      experiment whose output per case is its result (from R.jsonl, one {"id", "result"} per line, else the case's own
      `result`), and judges each with rubric.md. Where a case has a person's `label`, a second evaluator,
      agrees_with_label, compares the judge with it, and the summary counts agreement and the confusion matrix.
      Exit 0 when every case got a verdict, 1 when one could not be judged, 2 for a bad call.
  exam.py from-bench <bench.yaml> <results.json>...
      A set (YAML on stdout) from the frozen benchmark's judged answers: each case with a judge rubric and an answer,
      labelled with the benchmark judge's verdict. For comparing the two judges; it is not a person's label.

Environment: PHOENIX_BASE_URL (the site's Phoenix), LITELLM_BASE_URL (the site's gateway, OpenAI-compatible, ending in
/v1), JUDGE_MODEL (default gpt-sub-fast), JUDGE_KEY_VAR (the name of the variable that holds the gateway key, default
VK_EVAL). The key is read from the environment and never printed.
"""
import argparse
import contextlib
import hashlib
import json
import os
import sys
from pathlib import Path

import yaml
from phoenix.client import Client
from phoenix.evals import LLM, create_classifier

HERE = Path(__file__).resolve().parent
# Labels with descriptions make phoenix.evals ask for the verdict by tool call, which the gateway's subscription models
# honour; they ignore a JSON response format (docs/spikes/EVAL.md, "What the gateway does").
CHOICES = {"pass": (1.0, "the result achieves every part of the expected outcome, shown by evidence"),
           "fail": (0.0, "a part of the expected outcome is missing, different, or not shown by evidence")}
# limit: stops, one judge call past 180 seconds is ended and that case counts as not judged (exit 1), never as a fail
CALL_TIMEOUT = 180


def load(path, results=None):
    """The set, its cases with the result to judge, and the dataset's name (the file's content decides it)."""
    raw = Path(path).read_bytes()
    s = yaml.safe_load(raw)
    given = {}
    if results:
        for line in Path(results).read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                given[r["id"]] = r["result"]
    cases = []
    for c in s["cases"]:
        res = given.get(c["id"], c.get("result"))
        if res is None:
            raise SystemExit(f"case {c['id']} has no result: give --results")
        cases.append({**c, "result": res})
    return s, cases, f"exam-{s['name']}-{hashlib.sha256(raw).hexdigest()[:10]}"  # cap: id (the whole hash is the file's)


def dataset(px, name, s, cases):
    try:
        return px.datasets.get_dataset(dataset=name)
    except Exception:                      # not there yet: Phoenix answers 404, the client raises
        return px.datasets.create_dataset(
            name=name, dataset_description=s.get("title", ""),
            inputs=[{"id": c["id"], "request": c["request"], "expected_outcome": c["expected_outcome"]} for c in cases],
            outputs=[{"label": c["label"], "why": c.get("why", "")} if c.get("label") else {} for c in cases],
            metadata=[{"case": c["id"]} for c in cases])


def confusion(rows):
    """Person's label against the judge's verdict, over the cases that have both."""
    m = {"pass/pass": 0, "pass/fail": 0, "fail/pass": 0, "fail/fail": 0}
    for r in rows:
        if r["label"] in ("pass", "fail") and r["verdict"] in ("pass", "fail"):
            m[f"{r['label']}/{r['verdict']}"] += 1
    n = sum(m.values())
    agree = m["pass/pass"] + m["fail/fail"]
    po = agree / n if n else 0.0
    pe = (((m["pass/pass"] + m["pass/fail"]) * (m["pass/pass"] + m["fail/pass"])
           + (m["fail/pass"] + m["fail/fail"]) * (m["pass/fail"] + m["fail/fail"])) / (n * n)) if n else 0.0
    kappa = (po - pe) / (1 - pe) if n and pe < 1 else None
    return {"labelled": n, "agree": agree, "agreement": round(po, 3), "kappa": None if kappa is None else round(kappa, 3),
            "person/judge": m}


def run(a):
    s, cases, name = load(a.set, a.results)
    by_id = {c["id"]: c for c in cases}
    px = Client(base_url=os.environ.get("PHOENIX_BASE_URL", "http://127.0.0.1:6006"))
    ds = dataset(px, name, s, cases)
    key = os.environ.get(os.environ.get("JUDGE_KEY_VAR", "VK_EVAL"), "")
    if not key:
        raise SystemExit("no gateway key in the environment (run under sops exec-env, see run.sh)")
    model = a.model or os.environ.get("JUDGE_MODEL", "gpt-sub-fast")
    llm = LLM(provider="openai", model=model, base_url=os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000/v1"),
              api_key=key, timeout=CALL_TIMEOUT)
    rubric = (HERE / "rubric.md").read_text()
    judge = create_classifier(name="judge", prompt_template=rubric, llm=llm, choices=CHOICES)
    verdicts = {}

    def task(input):                       # the run's output for this case: the result as it was reported
        return by_id[input["id"]]["result"]

    def judged(input, output):
        sc = judge.evaluate({"request": input["request"], "expected_outcome": input["expected_outcome"], "result": output})[0]
        verdicts[input["id"]] = (sc.label, sc.explanation or "")
        return {"label": sc.label, "score": sc.score, "explanation": sc.explanation}

    def agrees_with_label(input, expected):
        v = verdicts.get(input["id"], ("not judged", ""))[0]
        ok = v == expected.get("label")
        return {"label": "agrees" if ok else "disagrees", "score": float(ok),
                "explanation": f"judge: {v}; person: {expected.get('label')} ({expected.get('why', '')})"}

    exp_name = a.name or f"{model} on {s['name']}"
    labelled = any(c.get("label") for c in cases)
    with contextlib.redirect_stdout(sys.stderr):      # the client's progress lines; stdout is the result alone
        ran = px.experiments.run_experiment(
            dataset=ds, task=task, evaluators={"judge": judged}, experiment_name=exp_name, print_summary=False,
            experiment_metadata={"model": model, "set": name,
                                 "rubric": hashlib.sha256(rubric.encode()).hexdigest()[:10]},  # cap: id (the rubric's file is whole)
            timeout=CALL_TIMEOUT)
        if labelled:
            px.experiments.evaluate_experiment(experiment=ran, evaluators={"agrees_with_label": agrees_with_label},
                                               print_summary=False)
    rows = [{"id": c["id"], "label": c.get("label", ""), "verdict": verdicts.get(c["id"], ("not judged", ""))[0],
             "why": verdicts.get(c["id"], ("", ""))[1]} for c in cases]
    out = {"set": name, "experiment": ran["experiment_id"], "model": model,
           "url": px.experiments.get_experiment_url(dataset_id=ran["dataset_id"], experiment_id=ran["experiment_id"]),
           "cases": len(rows), "passed": sum(r["verdict"] == "pass" for r in rows),
           "not_judged": [r["id"] for r in rows if r["verdict"] not in ("pass", "fail")], "rows": rows}
    if labelled:
        out["calibration"] = confusion(rows)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        for r in rows:
            mark = "" if not r["label"] else ("  ok" if r["label"] == r["verdict"] else f"  DISAGREES (person: {r['label']})")
            print(f"{r['id']:<28} {r['verdict']:<11}{mark}\n    {r['why']}")
        print(f"\n{out['passed']} of {out['cases']} pass; not judged: {', '.join(out['not_judged']) or 'none'}")
        if labelled:
            k = out["calibration"]
            print(f"agreement with the person: {k['agree']} of {k['labelled']} ({k['agreement']:.0%}), kappa {k['kappa']}; "
                  f"person/judge {k['person/judge']}")
        print(f"Phoenix: {out['url']}")
    return 1 if out["not_judged"] else 0


def from_bench(a):
    rubrics = {c["id"]: c for c in yaml.safe_load(Path(a.bench).read_text())["cases"] if c.get("judge")}
    cases = []
    for f in a.results:
        for r in json.loads(Path(f).read_text()).get("results", []):
            c = rubrics.get(r["id"])
            if not c or not r.get("answer") or any(x.startswith("error") for x in r["fails"]):
                continue                   # no rubric, or the benchmark could not measure it
            said = [x for x in r["fails"] if x.startswith("judge")]
            cases.append({"id": f"{r['id']}@{Path(f).stem}", "request": c["q"], "expected_outcome": c["judge"],
                          "result": r["answer"], "label": "fail" if said else "pass",
                          "why": said[0] if said else "the benchmark judge passed it"})
    yaml.safe_dump({"name": "bench-v1-judged", "title": "The frozen benchmark's judged answers, labelled by its own judge",
                    "cases": cases}, sys.stdout, allow_unicode=True, sort_keys=False, width=120)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="exam")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("set")
    r.add_argument("--results")
    r.add_argument("--model")
    r.add_argument("--name")
    r.add_argument("--json", action="store_true")
    b = sub.add_parser("from-bench")
    b.add_argument("bench")
    b.add_argument("results", nargs="+")
    a = p.parse_args(argv)
    return run(a) if a.cmd == "run" else from_bench(a)


if __name__ == "__main__":
    sys.exit(main())

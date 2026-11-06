"""Run the frozen Hermes benchmark against profile main and score it.

  python3 eval/bench.py run [--gate] [--label NAME] [--only ID,ID]   -> eval/results/<stamp>-<label>.json
  python3 eval/bench.py compare OLD.json NEW.json                   -> regressions, exit 1 if worse
Run with secrets in the environment:
  sops exec-env secrets/secrets.enc.yaml 'sops exec-env secrets/agent-keys.enc.yaml "python3 eval/bench.py run"'
Everything runs on the ChatGPT subscription (Hermes: gpt-sub, judge: gpt-sub-fast via vk-curator); no credit.
"""
import argparse, hashlib, json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
BENCH = HERE / "bench-v1.yaml"
FROZEN = HERE / "FROZEN.sha256"
RESULTS = HERE / "results"
HERMES = "http://127.0.0.1:8642/v1/chat/completions"
LITELLM = "http://127.0.0.1:4000/v1/chat/completions"
BULLET = re.compile(r"^\s*([-*•]|\d+[.)])\s+", re.M)
# Answers that mean "could not measure" (model rate limit, gateway down), not "Hermes got it wrong".
INFRA = re.compile(r"rate-limited|usage limit|too many requests|\[bench error", re.I)


def post(url, body, key, timeout=300):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def mark_test(q):
    """SWM-112: this question is a replay, not the owner's: the map keeps it apart from real work (interactions.py)."""
    try:
        with open("/srv/ai/missions/public/test-prompts.jsonl", "a") as f:
            f.write(json.dumps({"ts": time.time(), "prompt": q[:60]}, ensure_ascii=False) + "\n")   # cap: id (a question's head names it)
    except OSError:
        pass


def ask(q, chat):
    mark_test(q)
    body = {"model": "hermes-agent", "messages": [{"role": "system", "content": f"chat {chat}"},
                                                  {"role": "user", "content": q}]}
    for attempt in range(4):
        try:
            d = post(HERMES, body, os.environ["API_SERVER_KEY"])
            return d["choices"][0]["message"]["content"] or ""
        except Exception as e:  # gateway draining / restarting
            err = str(e)
            time.sleep(10 * (attempt + 1))
    return f"[bench error: {err}]"


def research_calls(since):
    out = subprocess.run(["docker", "logs", "--since", str(since), "aistack-research-1"],
                         capture_output=True, text=True)
    text = out.stdout + out.stderr
    return {"any": text.count("research call:"), "forwarded": text.count("research call: forwarded")}


def judge(rubric, q, answer):
    prompt = (f"You grade an assistant's answer. Question: {q}\n\nAnswer:\n{answer}\n\n"
              f"Pass criterion: {rubric}\n\nThe answer may be in German. Reply with exactly PASS or FAIL, "
              "then ' - ' and at most 12 words why.")
    d = post(LITELLM, {"model": "gpt-sub-fast", "messages": [{"role": "user", "content": prompt}]},
             os.environ["VK_CURATOR"], timeout=120)
    text = d["choices"][0]["message"]["content"].strip()
    return text.upper().startswith("PASS"), text[:160]


def check(case, answer, calls):
    fails = []
    for rx in case.get("must", []):
        if not re.search(rx, answer, re.I | re.S):
            fails.append(f"missing /{rx}/")
    for rx in case.get("must_not", []):
        if re.search(rx, answer, re.I | re.S | re.M):
            fails.append(f"forbidden /{rx}/")
    if case.get("research") is True and not calls["forwarded"]:
        fails.append("research not used")
    if case.get("research") is False and calls["any"]:
        fails.append("research used")
    if case.get("fmt"):
        bullets = len(BULLET.findall(answer))
        first = next((l for l in answer.splitlines() if l.strip()), "")
        if bullets > 3:
            fails.append(f"{bullets} bullets (>3)")
        if bullets and not BULLET.match(first) and not first.lstrip().startswith("#"):
            fails.append("intro before bullets")
    note = ""
    if INFRA.search(answer):
        return ["error: " + INFRA.search(answer).group(0)], "infra"
    if "judge" in case:
        try:
            ok, note = judge(case["judge"], case["q"], answer)
        except Exception as e:  # judge rate-limited: the case is unmeasured, not failed
            return [f"error: judge {e}"[:120]], "infra"
        if not ok:
            fails.append("judge: " + note)
    return fails, note


def run(args):
    raw = BENCH.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    cases = yaml.safe_load(raw)["cases"]              # parse before freezing, so a broken file never gets frozen
    if not FROZEN.exists():
        FROZEN.write_text(f"{sha}  {BENCH.name}\n")
    elif FROZEN.read_text().split()[0] != sha:
        sys.exit(f"{BENCH.name} changed after it was frozen; add a new bench version instead")
    if args.gate:
        cases = [c for c in cases if c.get("gate")]
    if args.only:
        cases = [c for c in cases if c["id"] in args.only.split(",")]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    results, streak = [], 0
    for i, c in enumerate(cases, 1):
        if streak >= 3:                                 # three unmeasurable answers in a row: stop hammering
            results.append({"id": c["id"], "pass": False, "error": True, "fails": ["error: skipped (rate limit)"],
                            "seconds": 0, "research": {}, "answer": ""})
            continue
        t0 = int(time.time())
        answer = ask(c["q"], f"bench-{stamp}-{c['id']}")
        time.sleep(2)
        calls = research_calls(t0)
        fails, note = check(c, answer, calls)
        err = note == "infra"
        streak = streak + 1 if err else 0
        results.append({"id": c["id"], "pass": not fails, "error": err, "fails": fails,
                        "seconds": int(time.time()) - t0, "research": calls, "answer": answer[:1500]})
        verdict = "ERR " if err else "PASS" if not fails else "FAIL"
        print(f"[{i:2}/{len(cases)}] {verdict} {c['id']:24} {int(time.time()) - t0:4}s"
              f"  {'; '.join(fails)[:150]}", flush=True)
    passed = sum(r["pass"] for r in results)
    errors = sum(r.get("error", False) for r in results)
    measured = len(results) - errors
    out = {"bench": BENCH.name, "sha256": sha, "label": args.label, "stamp": stamp, "gate": bool(args.gate),
           "passed": passed, "total": len(results), "errors": errors,
           "score": round(passed / max(measured, 1), 3), "results": results}
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{stamp}-{args.label}.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"\nscore {passed}/{measured} = {out['score']:.0%}" + (f" ({errors} not measurable)" if errors else "")
          + f"  -> {path}")
    # Benchmark chats must not become long-term memories (Hindsight retains every turn, a few seconds later).
    time.sleep(30)
    sys.path.insert(0, str(HERE.parent / "ops"))
    import hindsight_forget
    docs, units = hindsight_forget.forget([c["q"] for c in cases])
    print(f"long-term memory: removed {docs} benchmark conversation(s), {units} fact(s)")
    return out


def compare(a, b, quiet=False):
    return compare_results(*(json.loads(Path(p).read_text()) for p in (a, b)), quiet=quiet)


def compare_results(old, new, quiet=False):
    """Compare two runs on the cases measured in both (unmeasurable answers are left out, and counted)."""
    o = {r["id"]: r["pass"] for r in old["results"] if not r.get("error")}
    n = {r["id"]: r["pass"] for r in new["results"] if not r.get("error")}
    common = sorted(set(o) & set(n))
    skipped = len({r["id"] for r in old["results"]} | {r["id"] for r in new["results"]}) - len(common)
    lost = [i for i in common if o[i] and not n[i]]
    won = [i for i in common if n[i] and not o[i]]
    so, sn = sum(o[i] for i in common), sum(n[i] for i in common)
    if not quiet:
        print(f"{old['label']} {so}/{len(common)} -> {new['label']} {sn}/{len(common)}"
              f"  lost: {', '.join(lost) or '-'}  gained: {', '.join(won) or '-'}"
              + (f"  ({skipped} not measurable)" if skipped else ""))
    return {"old": so, "new": sn, "n": len(common), "lost": lost, "gained": won, "unmeasured": skipped}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--gate", action="store_true")
    r.add_argument("--label", default="adhoc"); r.add_argument("--only")
    c = sub.add_parser("compare"); c.add_argument("old"); c.add_argument("new")
    a = ap.parse_args()
    if a.cmd == "run":
        run(a)
    else:
        sys.exit(1 if compare(a.old, a.new)["lost"] else 0)

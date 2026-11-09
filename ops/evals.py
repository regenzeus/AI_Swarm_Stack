#!/usr/bin/env python3
"""Agent-change experiments and replay sets (requirements SWM-18, SWM-82): replay an agent's past runs with its current
card (baseline) and with the change applied (candidate), score both the same way, and let the Ledger's gate decide.

  python3 ops/evals.py run <id>     one experiment for agent change #id (the swarm-eval@<id> unit; swarm-sync starts it)
  python3 ops/evals.py sync         mirror every agent's replay set to Phoenix (dataset replay-<agent>)

The replay prompt gives the agent its card (purpose, responsibilities, standing instructions, tools) and one past input
(the signal it worked from and its context pack), and asks what it would write, as JSON operations. Nothing is applied.
Scores, each the share of the examples it applies to:
  valid              JSON with known operations; every new artifact has a 40+ character body and evidence
  keeps_proven       where the artifact was proven, it proposes it again (TF-IDF cosine >= the Ledger's 0.20)
  avoids_declined    where the owner declined it, it does not propose it again
  avoids_duplicates  where it was a duplicate, it does not propose it again
  no_noise           where the agent wrote nothing, it writes nothing
Both arms run on the same examples. Phoenix gets the dataset, both arms as experiments and every score as an
evaluation, best effort: the Ledger's result is the record. Models: the agent's own (Claude Code on the subscription
in the builder sandbox, without tools: a replay answers from its input; ChatGPT models through LiteLLM on the vk-eval
key). Stdlib only.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "images/swarm"))
import ledger as LG          # noqa: E402  the Ledger's similarity, metrics and gate (pure)
import registry as REG       # noqa: E402
from textcap import STORE, cut                    # visible caps and input limits (AGENTS.md, truncation)
import textcap as TC
import modelpolicy as MP                          # the Claude CLI's access under this deployment's model policy (GEN-05)
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md

PHOENIX = os.environ.get("PHOENIX_HOST", "http://127.0.0.1:6006")
LITELLM = os.environ.get("LITELLM_URL", "http://127.0.0.1:4000/v1/chat/completions")
BUILDER = "aistack-builder-1"
EXAMPLES, EXAMPLES_MAX = 10, 16
SETTLED = ("proven", "declined", "duplicate", "no_output")
UNIT = "swarm-eval@{}.service"

REPLAY = P.text("eval", "REPLAY")


# ---------------------------------------------------------------- the candidate card and the prompt
def apply_change(card, change):
    """The card with an agent change applied: instructions {add, remove} or a whole new list; tools (a new list),
    model, harness."""
    c = json.loads(json.dumps(card))
    ins = change.get("instructions")
    if isinstance(ins, list):
        c["instructions"] = [str(x) for x in ins]
    elif isinstance(ins, dict):
        keep = [x for x in c.get("instructions") or [] if x not in set(ins.get("remove") or [])]
        c["instructions"] = keep + [str(x) for x in ins.get("add") or [] if x not in keep]
    for k in ("tools", "model", "harness"):
        if change.get(k):
            c[k] = change[k]
    return c


def input_of(ex):
    inp = ex.get("inputs") or {}
    pack = {k: v for k, v in (inp.get("pack") or {}).items() if k not in ("instructions", "cut") and v}
    parts = []
    if inp.get("signal"):
        parts.append("Signal:\n" + TC.cut(str(inp["signal"]), 3000))  # cap: prompt
    if pack:
        parts.append("Context pack:\n" + TC.cut(json.dumps(pack, ensure_ascii=False, default=str), 6000))  # cap: prompt
    return "\n\n".join(parts) or "(no input was recorded for this run)"


def prompt(card, ex):
    ins = card.get("instructions") or []
    return REPLAY.format(agent=card["id"], purpose=card.get("purpose", ""), resp="; ".join(card.get("responsibilities") or []),
                         owns=json.dumps(card.get("owns") or {}), tools=", ".join(card.get("tools") or []) or "none",
                         instructions=("Standing instructions (follow them):\n" + "\n".join(f"- {x}" for x in ins) + "\n") if ins else "",
                         input=input_of(ex))


# ---------------------------------------------------------------- models
def ask(card, text, ref=""):
    """One replay answer from the card's model. Claude Code runs read-only in the builder sandbox; ChatGPT models go
    through LiteLLM on vk-eval, tagged swarm-replay."""
    P.record(text)                                  # MEM-11: the run records the prompt's version
    model = card.get("model")
    if model == "claude-subscription":
        import runtime as RTM
        p = subprocess.run(["docker", "exec", "-u", "hermes", *MP.claude_args(), "-w", "/work/ai-stack", *RTM.env_args(),
                            "-e", f"AISTACK_AGENT=claude-eval-{card['id']}", "-e", f"AISTACK_TITLE=replay of {card['id']} {ref}", BUILDER,
                            # limit: stops, a replay is one answer, no tools
                            "timeout", "300", "claude", "-p", text, "--output-format", "json", "--max-turns", "2",
                            "--disallowedTools", "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch,Read,Grep,Glob,Task,TodoWrite",
                            "--settings", "/config/claude-hooks/claude-runtime-settings.json"],
                           capture_output=True, text=True, timeout=360, env={**os.environ})
        import builds as B
        out = B.claude_text(p.stdout)
        if re.search(r"usage limit|hit your limit", out or "", re.I):
            raise RuntimeError("Claude usage limit")
        return out
    if str(model).startswith("gpt-"):
        key = os.environ.get("VK_EVAL") or ""
        if not key:
            raise RuntimeError("VK_EVAL is not set (run under sops exec-env secrets/agent-keys.enc.yaml)")
        body = json.dumps({"model": model, "messages": [{"role": "user", "content": text}], "metadata": {"tags": ["swarm-replay"]}}).encode()
        req = urllib.request.Request(LITELLM, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return TC.answer(json.load(r), model)
    raise RuntimeError(f"{card['id']} has no model to replay ({model})")


# ---------------------------------------------------------------- scoring
def parse(text):
    m = re.search(r"\{.*\}", str(text or ""), re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    return d if isinstance(d, dict) and isinstance(d.get("ops", []), list) else None


def ups(d):
    return [o for o in (d or {}).get("ops") or [] if isinstance(o, dict) and o.get("op") == "upsert"]


def text_of(o):
    return f"{o.get('title', '')} {o.get('body', '')}"


def score(ex, d, vec, ref_ids, out_ids):
    """One example's scores (None where a score does not apply). vec: the experiment's TF-IDF vectors; ref_ids: the
    example's own artifacts; out_ids: this answer's proposals."""
    s = {m: None for m in LG.METRICS}
    ok = d is not None and all(isinstance(o, dict) and o.get("op") in ("upsert", "evidence", "transition", "link", "send")
                               for o in d.get("ops") or [])
    s["valid"] = 1.0 if ok and all(len(str(o.get("body") or "")) >= 40 and o.get("evidence") for o in ups(d)) else 0.0
    again = any(LG.cosine(vec[o], vec[r]) >= LG.SIMILAR for o in out_ids for r in ref_ids)
    lab = ex["label"]
    if lab == "proven" and ref_ids:
        s["keeps_proven"] = 1.0 if again else 0.0
    elif lab == "declined" and ref_ids:
        s["avoids_declined"] = 0.0 if again else 1.0
    elif lab == "duplicate" and ref_ids:
        s["avoids_duplicates"] = 0.0 if again else 1.0
    elif lab == "no_output":
        s["no_noise"] = 1.0 if not ups(d) else 0.0
    return s


def mean(rows, m):
    v = [r[m] for r in rows if r.get(m) is not None]
    return round(sum(v) / len(v), 3) if v else None


def pick(examples, n):
    """Settled examples, the newest of each label in turn, so a label with many examples does not drown the rest."""
    by = {}
    for ex in sorted(examples, key=lambda x: -x["ts"]):
        if ex["label"] in SETTLED:
            by.setdefault(ex["label"], []).append(ex)
    out = []
    while len(out) < n and any(by.values()):
        for lab in SETTLED:
            if by.get(lab) and len(out) < n:
                out.append(by[lab].pop(0))
    return out


def refs_of(examples, send):
    """{example id: [texts of its artifacts]}: what each example's agent wrote, from the Ledger (or its history output)."""
    out = {}
    for ex in examples:
        texts = []
        for aid in ex.get("artifacts") or []:
            r = send("get", {"id": int(aid)}, "system")
            if r.get("ok"):
                texts.append(text_of(r["result"]))
        out[ex["id"]] = texts or [text_of(o) for o in ups(ex.get("output"))]
    return out


def evaluate(card, cand, examples, send, ask_fn=ask, ref=""):
    """Both arms on the same examples. -> (baseline scores, candidate scores, detail rows)."""
    refs = refs_of(examples, send)
    answers = []
    for ex in examples:
        a = {}
        for arm, c in (("baseline", card), ("candidate", cand)):
            t0 = time.time()
            try:
                a[arm] = (ask_fn(c, prompt(c, ex)), time.time() - t0)
            except RuntimeError:
                raise
            except Exception as e:                                 # one bad answer is an invalid answer, not a failed experiment
                a[arm] = (f"error: {type(e).__name__}: {str(e)}", time.time() - t0)
        answers.append(a)
    docs, keys = {}, {}
    for i, ex in enumerate(examples):
        for j, t in enumerate(refs[ex["id"]]):
            docs[f"r{i}.{j}"] = t
        for arm in ("baseline", "candidate"):
            for j, o in enumerate(ups(parse(answers[i][arm][0]))):
                docs[f"{arm[0]}{i}.{j}"] = text_of(o)
    vec = LG.tfidf(docs) if docs else {}
    rows = {"baseline": [], "candidate": []}
    detail = []
    for i, ex in enumerate(examples):
        ref_ids = [k for k in docs if k.startswith(f"r{i}.")]
        d = {"example": ex["id"], "label": ex["label"], "source": ex.get("source")}
        for arm in ("baseline", "candidate"):
            parsed = parse(answers[i][arm][0])
            out_ids = [k for k in docs if k.startswith(f"{arm[0]}{i}.")]
            s = score(ex, parsed, vec, ref_ids, out_ids)
            rows[arm].append(s)
            d[arm] = {"scores": s, "proposed": [o.get("title") for o in ups(parsed)][:5], "seconds": round(answers[i][arm][1], 1),  # cap: top
                      "answer": cut(answers[i][arm][0], STORE)}  # cap: store
        detail.append(d)
    return ({m: mean(rows["baseline"], m) for m in LG.METRICS}, {m: mean(rows["candidate"], m) for m in LG.METRICS}, detail)


# ---------------------------------------------------------------- Phoenix (best effort)
def _px(method, path, body=None):
    req = urllib.request.Request(PHOENIX + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r) if r.status != 204 else {}


def ex_id(x):
    return re.sub(r"[^A-Za-z0-9_.-]", "-", str(x))[:120]  # cap: id


def upload(agent, examples):
    """The agent's whole replay set as Phoenix dataset replay-<agent> (update: new examples added, changed labels
    updated, gone ones removed, by example id). -> dataset id."""
    if not examples:
        return None
    r = _px("POST", "/v1/datasets/upload?sync=true", {
        "action": "update", "name": f"replay-{agent}", "description": f"Replay set of the swarm agent {agent} (ops/evals.py, SWM-82)",
        "inputs": [{"input": input_of(x), "card": x.get("card"), "tools": (x.get("inputs") or {}).get("tools")} for x in examples],
        "outputs": [x.get("output") or {} for x in examples],
        "metadata": [{"label": x["label"], "reason": x.get("label_reason", ""), "source": x.get("source"), "run": x["id"],
                      "failure": (x.get("failure") or {}).get("mode")} for x in examples],
        "example_ids": [ex_id(x["id"]) for x in examples]})
    return r["data"]["dataset_id"]


def log_experiment(agent, aid, examples, detail):
    """Both arms as Phoenix experiments on the agent's dataset, every score an evaluation. -> {dataset, baseline, candidate}."""
    ds = upload(agent, examples)
    node = {e["id"]: e["node_id"] for e in _px("GET", f"/v1/datasets/{ds}/examples")["data"]["examples"]}
    out = {"dataset": ds}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for arm in ("baseline", "candidate"):
        x = _px("POST", f"/v1/datasets/{ds}/experiments", {"name": f"agent change #{aid} {arm}", "metadata": {"agent_change": aid, "arm": arm}})
        eid = x["data"]["id"]
        out[arm] = eid
        for d in detail:
            if ex_id(d["example"]) not in node:
                continue
            run = _px("POST", f"/v1/experiments/{eid}/runs", {"dataset_example_id": node[ex_id(d["example"])], "output": {"answer": d[arm]["answer"]},
                                                              "repetition_number": 1, "start_time": now, "end_time": now})
            for m, v in d[arm]["scores"].items():
                if v is not None:
                    _px("POST", "/v1/experiment_evaluations", {"experiment_run_id": run["data"]["id"], "name": m, "annotator_kind": "CODE",
                                                               "result": {"score": v}, "start_time": now, "end_time": now})
    return out


# ---------------------------------------------------------------- the experiment
def run(aid, send=None, ask_fn=ask, phoenix=log_experiment, cards=None):
    """One experiment for agent change #aid, recorded in the Ledger (which decides the gate). -> its result, or None
    when it waits (not ready, or the engine is at its usage limit)."""
    import swarm_client as SW
    send = send or SW.call
    r = send("get", {"id": int(aid)}, "system")
    if not r.get("ok"):
        raise ValueError(r.get("refused"))
    a = r["result"]
    if a["kind"] != "agent_change" or a["state"] != "ready":
        return None
    plan = a.get("plan") or {}
    cards = cards or {c["id"]: c for c in REG.load().get("agents") or []}
    card = cards.get(plan.get("agent"))
    res = {"version": a["version"], "agent": plan.get("agent"), "examples": 0}
    if not card:
        res["error"] = f"no agent {plan.get('agent')}"
    else:
        cand = apply_change(card, plan.get("change") or {})
        if "none" in (card.get("model"), cand.get("model")) or not card.get("model"):
            res["error"] = f"{card['id']} has no model, so its runs cannot be replayed"
        elif SW.limited(SW.ENGINE.get(card.get("model"), "")) or SW.limited(SW.ENGINE.get(cand.get("model"), "")):
            return None                                            # waits out the usage limit; the next sync starts it again
        else:
            rx = send("replays", {"agent": card["id"]}, "system")
            pool = rx.get("result") or [] if rx.get("ok") else []
            n = min(int((plan.get("experiment") or {}).get("examples") or EXAMPLES), EXAMPLES_MAX)
            examples = pick(pool, n)
            res["examples"] = len(examples)
            if len(examples) >= LG.MIN_EXAMPLES:
                try:
                    res["baseline"], res["candidate"], res["detail"] = evaluate(card, cand, examples, send, ask_fn, ref=f"#{aid}")
                except RuntimeError as e:
                    if "limit" in str(e).lower():
                        return None
                    res["error"] = str(e)
                if res.get("detail") and phoenix:
                    try:
                        res["phoenix"] = phoenix(card["id"], aid, examples, res["detail"])
                    except Exception as e:
                        res["phoenix"] = {"error": f"{type(e).__name__}: {str(e)}"}
    out = send("experiment", {"idem": f"experiment:{aid}:v{a['version']}", "id": int(aid), "result": res}, "system")
    if not out.get("ok"):
        raise ValueError(out.get("refused"))
    return {**res, **out["result"]}


def due(send=None, start=None, active=None):
    """From swarm-sync: start the experiment of a ready agent change that has none for its current version, one at a
    time (unit swarm-eval@<id>). -> the id started, or None."""
    import swarm_client as SW
    send = send or SW.call
    r = send("agent_changes", {"states": ["ready"]}, "system")
    for a in (r.get("result") or []) if r.get("ok") else []:
        ex = a.get("experiment")
        if ex and ex.get("version") == a["version"]:
            continue
        if (active or _any_active)():
            return None
        (start or _start)(a["id"])
        return a["id"]
    return None


def _any_active():
    p = subprocess.run(["systemctl", "--user", "list-units", "--state=active,activating", "--no-legend", "swarm-eval@*"], capture_output=True, text=True)
    return bool(p.stdout.strip())


def _start(aid):
    subprocess.run(["systemctl", "--user", "start", "--no-block", UNIT.format(int(aid))], capture_output=True)


def sync(send=None, every=600, now=None):
    """Mirror each agent's replay set to Phoenix when it changed (at most every 10 minutes). -> agents uploaded."""
    import swarm_client as SW
    send, now = send or SW.call, now or time.time()
    st = SW._load("phoenix.json", {})
    if now - st.get("_t", 0) < every:
        return []
    st["_t"] = now
    done = []
    for card in REG.load().get("agents") or []:
        if card.get("model") in (None, "none"):
            continue
        r = send("replays", {"agent": card["id"]}, "system")
        ex = r.get("result") or [] if r.get("ok") else []
        h = LG.card_hash([[x["id"], x["label"]] for x in ex])
        if not ex or st.get(card["id"]) == h:
            continue
        try:
            upload(card["id"], ex)
            st[card["id"]] = h
            done.append(card["id"])
        except Exception as e:
            print(f"phoenix: replay-{card['id']}: {type(e).__name__}: {str(e)}", file=sys.stderr)
    SW._save("phoenix.json", st)
    return done


def main(argv):
    if len(argv) > 2 and argv[1] == "run":
        import runtime as RTM
        rid, t0 = f"eval:{argv[2]}:{time.strftime('%Y%m%d-%H%M%S')}", time.time()
        RTM.set_ref(rid, "evals")
        RTM.start(rid, "evals", f"Experiment · agent change #{argv[2]}")
        try:
            res = run(int(argv[2]))
        except Exception as e:
            RTM.end(rid, "evals", "failed", f"{type(e).__name__}: {str(e)}", time.time() - t0)
            raise
        summary = "waits (not ready, or the engine is at its usage limit)" if res is None else \
            f"{'passed' if res.get('passed') else 'not passed'}: {res.get('why')}"
        RTM.emit(rid, "say", agent="evals", title="Result", detail=json.dumps({k: v for k, v in (res or {}).items() if k != "detail"}, default=str))
        RTM.end(rid, "evals", "done", summary, time.time() - t0)
        print(summary)
        return 0
    if len(argv) > 1 and argv[1] == "sync":
        print(json.dumps({"uploaded": sync(every=0)}))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

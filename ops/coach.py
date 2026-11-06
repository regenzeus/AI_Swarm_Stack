#!/usr/bin/env python3
"""The Coach (requirement SWM-83): once a month, every agent's scorecard becomes agent-change artifacts where it shows
a problem: each with its evidence, a target score and an experiment plan. The change itself (a few standing
instructions for the agent's card) is drafted by Claude Code, read-only; the gate of SWM-18 decides whether it ships
(ops/evals.py replays the agent's past runs with and without it; the owner taps Build it only after a pass).

Triggers (a scorecard over its last 90 days, at least MIN_IDEAS ideas or labelled runs):
  declined share >= 30 %       target avoids_declined     (the owner's decline reasons are the evidence)
  duplicate share >= 30 %      target avoids_duplicates   (merged or refused as a copy)
  3+ runs whose writes failed  target valid               (refused for missing evidence or incomplete operations, FM-1.1)
The Coach never writes a change for itself (the Ledger refuses it, SWM-70); an agent without a model is skipped.
"""
import json
import textcap as TC                              # visible caps (AGENTS.md, truncation)
import re
import sys
from pathlib import Path
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md

sys.path.insert(0, str(Path(__file__).resolve().parent))

MIN_IDEAS = 5
SHARE = 0.30
FC1_MIN = 3
HELP_MIN = 3             # SWM-109: judged steps into other agents' lanes before their usefulness counts
ME = "coach"

DRAFT = P.text("coach", "DRAFT")


def findings(cards, scorecards):
    """{agent: scorecard} -> [{agent, target, problem, evidence}]: the problems worth an agent change."""
    out = []
    for agent, sc in sorted((scorecards or {}).items()):
        card = cards.get(agent) or {}
        if agent == ME or not sc or card.get("model") in (None, "none"):
            continue
        ideas = int(sc.get("ideas") or 0)
        labels = ((sc.get("replays") or {}).get("labels")) or {}
        settled = sum(labels.get(k, 0) for k in ("proven", "declined", "duplicate", "failed", "gone"))
        if ideas >= MIN_IDEAS and (sc.get("declined") or 0) / ideas >= SHARE:
            reasons = "; ".join(f"{r} ({n}x)" for r, n in sc.get("decline_reasons") or [])
            out.append({"agent": agent, "target": "avoids_declined",
                        "problem": f"the owner declined {sc['declined']} of its {ideas} ideas ({sc['declined'] / ideas:.0%})",
                        "evidence": [f"scorecard: {sc['declined']} of {ideas} ideas declined", f"his reasons: {reasons}" if reasons else ""]})
        if settled >= MIN_IDEAS and labels.get("duplicate", 0) / settled >= SHARE:
            out.append({"agent": agent, "target": "avoids_duplicates",
                        "problem": f"{labels['duplicate']} of its {settled} settled runs wrote a duplicate ({labels['duplicate'] / settled:.0%})",
                        "evidence": [f"replay set: {labels['duplicate']} of {settled} settled runs labelled duplicate"]})
        refused = int((sc.get("failures") or {}).get("refused_fc1") or 0)     # its own writes refused, not the owner's declines
        if refused >= FC1_MIN:
            out.append({"agent": agent, "target": "valid",
                        "problem": f"{refused} of its runs had their writes refused for missing or incomplete fields (MAST FM-1.1)",
                        "evidence": [f"failure classes: FM-1.1 disobey task specification, {refused} failed runs"]})
        hp = sc.get("helps") or {}
        judged = int(hp.get("useful") or 0) + int(hp.get("not_useful") or 0)
        if judged >= HELP_MIN and int(hp.get("not_useful") or 0) / judged >= 0.5:      # SWM-109: it steps in where it does not help
            out.append({"agent": agent, "target": "no_noise",
                        "problem": f"{hp['not_useful']} of its {judged} judged steps into other agents' lanes were not useful",
                        "evidence": [f"helps in 30 days: {hp.get('given', 0)} given, {hp.get('useful', 0)} useful, {hp['not_useful']} not useful, "
                                     f"{hp.get('pending', 0)} not judged yet (judged by the agent it helped, by the owner, or by what became of the work)"]})
    for f in out:
        f["evidence"] = [e for e in f["evidence"] if e]
    return out


def draft(f, card, ask, lessons=""):
    """The model's instructions for one finding (with the owner's decisions on the Coach's earlier changes). -> {instructions, why} or None."""
    prompt = DRAFT.format(agent=f["agent"], purpose=card.get("purpose", ""), resp="; ".join(card.get("responsibilities") or []),
                          instructions=json.dumps(card.get("instructions") or []), problem=f["problem"],
                          evidence="\n".join(f"- {e}" for e in f["evidence"]), lessons=lessons)
    P.record(prompt)                                      # MEM-11: the run records the prompt's version
    text = ask(prompt)
    m = re.search(r"\{.*\}", str(text or ""), re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        return None
    ins = [TC.cut(str(x).strip(), 300) for x in d.get("instructions") or [] if str(x).strip()][:3]  # cap: top (untrusted)
    return {"instructions": ins, "why": TC.cut(str(d.get("why") or ""), 400)} if ins else None  # cap: untrusted


def coach(send=None, ask=None, cards=None, run=""):
    """One Coach run. -> the agent changes written (ids)."""
    import registry as REG
    import swarm_client as SW
    send = send or SW.call
    cards = cards or {c["id"]: c for c in REG.load().get("agents") or []}
    scores = {}
    for agent in cards:
        r = send("scorecard", {"agent": agent}, "system")
        if r.get("ok") and r.get("result"):
            scores[agent] = r["result"]
    made, lessons = [], SW.lessons_text(ME, send)
    for f in findings(cards, scores):
        key = f"coach:{f['agent']}:{f['target']}"
        have = send("find", {"kind": "agent_change", "key": key}, ME).get("result") or []
        while have and have[0]["state"] == "done":          # an earlier change held and the problem is back: a new change
            key = f"coach:{f['agent']}:{f['target']}:after-{have[0]['id']}"
            have = send("find", {"kind": "agent_change", "key": key}, ME).get("result") or []
        if have and have[0]["state"] in ("active", "checking", "declined", "gone"):
            continue                        # in flight, or the owner said no: his decision stands (a done one may come back)
        d = draft(f, cards[f["agent"]], ask or _ask, lessons)
        if not d:
            continue
        body =(f"{f['problem'][0].upper()}{f['problem'][1:]}. Proposed standing instructions for {f['agent']}: "
                + " ".join(f"({n}) {x}" for n, x in enumerate(d["instructions"], 1)) + (f" Why: {d['why']}" if d["why"] else ""))
        plan = {"agent": f["agent"], "change": {"instructions": {"add": d["instructions"]}},
                "target": {"score": f["target"], "why": f["problem"]},
                "experiment": {"examples": 10, "rule": "every replay score holds and the target rises (SWM-18)"},
                "files": ["config/agents.yaml"], "test": "tests/test_registry.py"}
        r = send("upsert", {"idem": f"{key}:{run}", "kind": "agent_change", "key": key, "title": f"Coach: {f['agent']} — {f['target'].replace('_', ' ')}",
                            "body": body, "plan": plan, "evidence": [{"text": e, "ref": "scorecard"} for e in f["evidence"]],
                            "impact": "medium", "confidence": "medium", "effort": "small"}, ME, run=run)
        if not r.get("ok"):
            print(f"coach: {key}: {r.get('refused')}", file=sys.stderr)
            continue
        aid = r["result"]["id"]
        state = (send("get", {"id": aid}, ME).get("result") or {}).get("state", "draft")
        for to in ("open", "ready")[("draft", "open").index(state) if state in ("draft", "open") else 2:]:
            send("transition", {"idem": f"{key}:{run}:{to}", "id": aid, "to": to, "reason": "the Coach's claim: evidence, target and plan"}, ME, run=run)
        made.append(aid)
    return made


def _ask(prompt):
    import crew
    return crew._ask_claude(prompt, ME)


def run(c=None):
    """crew.py's entry for the crew-coach unit. -> how many agent changes it wrote."""
    import crew
    made = coach(run=crew.RUN.get("id", ""))
    crew.save(ME, result=f"{len(made)} agent change{'s' if len(made) != 1 else ''} for the gate" if made else "no agent needs a change",
              last=__import__("time").time())
    return len(made)

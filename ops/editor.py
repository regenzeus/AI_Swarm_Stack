"""The Editor (crew; DEC-47, AI change requests step 2): sorts every open idea of the stack so the owner sees few,
coherent ones. It changes nothing yet: no idea moves, nothing is built; the owner sees its sorting first.

  1. the open ideas from the swarm's Ledger, the ideas decided lately with the owner's reasons, the requirements not met
     yet (planned work) and the stack's decisions
  2. one Claude task (ops/claude_tasks.py, read-only on a copy of ai-stack main, so it can check whether a fix is in
     the code already): per idea a verdict with its reason: in (with the title of the change request it belongs to),
     held, covered (by what) or dropped
  3. a program checks the answer: every verdict names an open idea, one of the four, with a reason; an idea left out is
     listed as not sorted. The sorting is saved on the Editor's card; the app shows it on each idea and the Ideas view.

  python3 ops/crew.py editor     (crew-editor.service: daily, and Run now)
If the Claude task has to wait for a usage limit, the Editor ends cleanly and reads the answer on its next run.
"""
import collections
import time

import yaml

import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md
import textcap as TC                              # visible caps (AGENTS.md, truncation)

C = M = None                                      # ops/crew.py and ops/missions.py (set by crew.run)
WAIT_S = 50 * 60                                  # how long one run waits for its Claude task (the queue is one at a time)
# limit: paces, open ideas one pass sorts (the oldest first); the rest the next pass, and the result says how many waited
MAX_IDEAS = 60
BODY = 1500                                       # cap: prompt (an idea's body in the Editor's context; its page has all of it)
VERDICTS = ("in", "held", "covered", "dropped")
QUESTION = P.text("editor", "SORT")


def board(send=None):
    """The Ledger's open ideas and the ones decided lately -> (open, recent)."""
    import swarm_client as SW
    r = (send or SW.call)("board", {"kind": "idea"}, "system")
    b = (r.get("result") or {}) if r.get("ok") else {}
    return list(b.get("open") or []), list(b.get("recent") or [])


def _items(path):
    d = yaml.safe_load(path.read_text()) or {}
    return d.get("items") or [] if isinstance(d, dict) else d


def planned(root):
    """The requirements not met yet and the decisions, one line each -> (requirements, decisions)."""
    req, dec = [], []
    for f in sorted((root / "requirements").glob("*.yaml")):
        for r in _items(f):
            if not isinstance(r, dict) or not r.get("id"):
                continue
            if str(r["id"]).startswith("DEC-"):
                dec.append(f"- {r['id']}: {r.get('title', '')}")
            elif r.get("status") in ("partial", "proposed"):
                req.append(f"- {r['id']} ({r['status']}): {r.get('title', '')}" + (f". Still open: {TC.cut(' '.join(str(r['gap']).split()), 300)}" if r.get("gap") else ""))  # cap: prompt
    return req, dec


def context(ideas, recent, root):
    """The Claude task's context file: the open ideas in full, the owner's recent decisions, planned work, decisions."""
    out = ["# Open ideas"]
    for x in ideas:
        out.append(f"\n## Idea #{x['id']} · by {x.get('owner') or '?'} · {x.get('state')} · seen {x.get('evidence') or 1} time(s)\n{x.get('title', '')}\n\n"
                   f"{TC.cut(str(x.get('body') or ''), BODY)}")  # cap: prompt (its page has all of it)
    out.append("\n# Decided lately (the owner's reasons where he gave one)")
    out += [f"- #{x['id']} {x.get('state')}{': ' + x['decision']['reason'] if (x.get('decision') or {}).get('reason') else ''}: {x.get('title', '')}" for x in recent]
    req, dec = planned(root)
    out.append("\n# Requirements not met yet (planned work)")
    out += req or ["- none"]
    out.append("\n# The stack's decisions")
    out += dec or ["- none"]
    return "\n".join(out)


def ask(ideas, ctx):
    """Queue the Claude task (or keep waiting for the pending one) -> (task id, status, answer, the ideas it was asked about)."""
    CT = M.CT
    CT.M, CT.B, M.B.M = M, M.B, M
    c = M.db()
    CT.table(c)
    pend = C.agent_file("editor").get("pending") or {}
    tid = pend.get("task")
    row = c.execute("select status from claude_tasks where id=?", (tid,)).fetchone() if tid else None
    if not row or row["status"] == "failed":
        if not ideas:
            return None, "none", "", []
        q = QUESTION.format(count=len(ideas))
        P.record(q)                                  # MEM-11: the run records the prompt's version
        tid = CT.handle({"question": q, "mode": "analyse", "repo": "ai-stack", "context": ctx, "source": "crew:editor"}, c)["id"]
        C.save("editor", pending={"task": tid, "ideas": [{k: x.get(k) for k in ("id", "title", "owner")} for x in ideas]})
    else:
        ideas = pend.get("ideas") or ideas              # the answer belongs to the ideas it was asked about
    t0 = time.time()
    while time.time() - t0 < WAIT_S:
        r = c.execute("select status, answer, error, retry_at from claude_tasks where id=?", (tid,)).fetchone()
        if r["status"] in ("done", "failed", "waiting"):
            return tid, r["status"], {"done": r["answer"], "waiting": r["retry_at"]}.get(r["status"], r["error"]) or "", ideas
        C.save("editor", result=f"Claude task #{tid} is {r['status']}…")
        time.sleep(10)
    return tid, "timeout", "", ideas


def verdicts_of(d, ideas):
    """The answer's JSON -> ({idea id: verdict}, [requests], [ids not sorted]). Only what can be checked is kept: an open
    idea, one of the four verdicts, a reason, and a request's title for "in"."""
    ids = {int(x["id"]) for x in ideas}
    out = {}
    for v in d.get("ideas") or []:
        if not isinstance(v, dict):
            continue
        try:
            i = int(v.get("id"))
        except (TypeError, ValueError):
            continue
        verdict, reason, req = v.get("verdict"), str(v.get("reason") or "").strip(), str(v.get("request") or "").strip()
        if i not in ids or verdict not in VERDICTS or not reason or (verdict == "in" and not req):
            continue
        out[str(i)] = {"verdict": verdict, "request": TC.cut(req, 120) if verdict == "in" else "",  # cap: untrusted
                       "covered_by": TC.cut(str(v.get("covered_by") or ""), 200) if verdict == "covered" else "", "reason": TC.cut(reason, 800)}  # cap: untrusted
    used = {v["request"] for v in out.values() if v["verdict"] == "in"}
    why = {str(r.get("title") or "").strip(): TC.cut(str(r.get("why") or ""), 300) for r in d.get("requests") or [] if isinstance(r, dict)}  # cap: untrusted
    reqs = [{"title": t, "why": why.get(t, ""), "ideas": sorted(int(k) for k, v in out.items() if v["request"] == t)} for t in sorted(used)]
    return out, reqs, sorted(ids - {int(k) for k in out})


def run(c):
    t0 = time.time()
    C.save("editor", result="reading the open ideas…", started=t0)
    every, recent = board()
    ideas = sorted(every, key=lambda x: int(x["id"]))[:MAX_IDEAS]   # cap: list (the result says how many wait for the next pass)
    waited = len(every) - len(ideas)
    pending = C.agent_file("editor").get("pending")
    if not ideas and not pending:
        C.save("editor", result="no open ideas to sort", verdicts={}, requests=[], missing=[], seconds=round(time.time() - t0), last=time.time())
        return 0
    ctx = context(ideas, recent, C.STACK) if ideas else ""
    if ctx and c is not None:                             # SWM-61: the owner's reasons on the Editor's work come first
        import swarm_client as SW
        lessons = SW.lessons_text("editor")
        ctx = (lessons + "\n\n" if lessons else "") + ctx
    tid, status, answer, ideas = ask(ideas, ctx)
    if status == "none":
        C.save("editor", pending=None, result="no open ideas to sort", seconds=round(time.time() - t0), last=time.time())
        return 0
    if status == "waiting":                               # not a failure: the next run reads the answer
        C.save("editor", result=f"Claude task #{tid} waits for the Claude usage limit (until {str(answer)[11:16]}); the Editor reads it next run",
               seconds=round(time.time() - t0), last=time.time())
        return 0
    if status == "timeout":
        C.save("editor", result=f"Claude task #{tid} is still queued or running; the Editor reads it next run", seconds=round(time.time() - t0), last=time.time())
        return 0
    C.save("editor", pending=None)
    if status != "done":
        raise RuntimeError(f"Claude task #{tid} failed: {answer}")
    verdicts, reqs, missing = verdicts_of(C.json_in(answer), ideas)
    if not verdicts:
        raise RuntimeError(f"Claude task #{tid} sorted no idea: {TC.tail(str(answer), 4000)}")  # cap: store
    n = collections.Counter(v["verdict"] for v in verdicts.values())
    res = (f"{len(ideas)} ideas: {n['in']} into {len(reqs)} request{'s' if len(reqs) != 1 else ''}, {n['held']} held, {n['covered']} covered, {n['dropped']} dropped"
           + (f", {len(missing)} not sorted" if missing else "") + (f" · {waited} wait for the next pass" if waited else "") + f" (Claude task #{tid})")
    C.save("editor", result=res, verdicts=verdicts, requests=reqs, missing=missing, task=tid, sorted_at=time.time(),
           seconds=round(time.time() - t0), last=time.time())
    return len(verdicts)

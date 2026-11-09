"""Change requests (CHG-01 to CHG-18, docs/CHANGE-REQUESTS.md): the stack as the developer of the onboarded repositories.

A request becomes a specification, the specification a plan by size class on the Conductor, and every plan ends in one branch
with the evidence, for the owner's review on the existing build page. Nothing merges without his tap.

  specify    the intake writes the acceptance criteria, scope, size class, risks and budget; S starts, M and L wait for the Go
  begin      the branch change/<id>-<slug> from the default branch; the plan; the Conductor runs it
  steps      coder, tester and breaker are builds onto the change's branch; judge, reviewers, prober, deliver and scribe are
             adapters here. The judge is a program: a baseline, red before green, reruns, what a change may not touch
  deliver    the report, a carrier build in review (CI, merge queue, deploy and rollback stay the builder's), a pull request
  review     Request changes reopens the coder and every step after it; Reject and Merge end it; each is a lesson
  scribe     folds what the run learned into the repository's wiki (ops/repowiki.py)

STEP_KINDS and TASK_KINDS at the end are what the Conductor loads of this (TSK-36, ops/stepkinds.py).
"""
import datetime as dt
import json
import os
import re
import signal
import shutil
import subprocess
import time
from pathlib import Path

import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md
import repowiki as RW
import runtime as RTM
import textcap as TC                              # visible caps (AGENTS.md, truncation)
import modelpolicy as MP                          # the Claude CLI's access under this deployment's model policy (GEN-05)

M = None                                          # ops/missions.py (set by its main)
ACTIONS = {"change_request", "change_go", "change_resume", "change_leave", "change_rule"}
SIZES = ("S", "M", "L")
# limit: stops, a change past its class's budget stops with the reason; shown on the specification, and the owner's Go or Resume raises it
BUDGETS = {"S": {"tokens": 1_500_000}, "M": {"tokens": 5_000_000}, "L": {"tokens": 12_000_000}}   # no hours: a change waits for memory and usage limits, and that is no spending (task 170)
# limit: stops, fix rounds a change gets before it comes back to the owner with what still fails
ROUNDS = 3
# limit: refuses, what a change request on ai-stack may not touch unless the owner names the path on its specification (CHG-15)
PROTECTED = ("ops/check.sh", "ops/changes.py", "ops/repowiki.py", "ops/limits.py", "ops/truncation.py", "ops/req.py", "ops/publish.py",
             "ops/land.sh", "ops/deploy.py", "tests/test_changes.py", "tests/test_repowiki.py", "tests/test_replay.py", "eval/", "secrets/")
TEST_PATH = re.compile(r"(^|/)(tests?|spec|specs|__tests__|testdata)/|(^|/)test_[^/]*$|_test\.[a-z]+$|\.(test|spec)\.[a-z]+$")
ACCEPT_LINE = re.compile(r"^[ \t*>-]*`?(C\d+)`?[ \t]*[:=][ \t]*`?(\S+?(?:\[[^\]\n]*\])?)`?[ \t]*$", re.M)   # the whole line: "C3: the mixed-input tests" names no test (task 171)
JUDGE_SLOT = "j"                                  # the judge's own clone: never the merge queue's, never a builder's
OUTPUT = 400                                      # cap: parse (the lines of a test run the judge reads)
EVIDENCE = Path("/srv/ai/workbench/.evidence")
PUBLIC_DIR = "changes"


# ---------- the door ----------
def create(req, c):
    """change_request: one sentence for one repository -> a task the intake worker specifies."""
    import builds as B
    import tasks as TK
    repo, text = str(req.get("repo") or "").strip(), re.sub(r"\s+", " ", str(req.get("text") or "")).strip()
    if repo not in B.repos():
        raise ValueError(f"{repo or 'That repository'} is not one the builder may change: on its page, tap Let the builder change it first (it runs the repository's tests in the sealed sandbox)."
                         if repo else "name the repository of the change")
    return TK.create({"text": text, "kind": "change", "repo": repo, "source": req.get("source") or "app", "autonomy": req.get("autonomy"),
                      "change": {k: req[k] for k in ("wiki_of", "no_wiki", "auto_go", "skills", "allow_paths", "trial", "brief", "facts_at",
                                                     "memory", "notes", "memory_budget", "knowledge") if k in req}}, c)


def size_of(size, files, criteria):
    """CHG-04: the first real changes came back too big (a wording fix M, an API field and its page L): on a repository that keeps
    tests and requirements, one code file is never one file. The size follows the code files the specification names; with
    none named, the intake's word stands."""
    code = [f for f in files if not TEST_PATH.search(f) and not f.startswith(("requirements/", "docs/")) and not f.endswith(".md")]
    if not code:
        return size
    if size == "L" and len(code) <= 3:
        size = "M"
    if size == "M" and len(code) == 1 and len(criteria) <= 3:
        size = "S"
    return size


def valid_spec(raw, known=()):
    """The intake's answer -> a clean specification, or ValueError saying what is wrong (CHG-02)."""
    crit = [re.sub(r"\s+", " ", str(x)).strip() for x in raw.get("criteria") or [] if str(x).strip()]
    if not crit:
        raise ValueError("the specification has no acceptance criteria")
    weak = [x for x in crit if not re.search(r"\b(shall|must)\b", x, re.I)]
    if weak:
        raise ValueError(f"an acceptance criterion a test cannot be written for: {TC.cut(weak[0], 200)}")  # cap: preview
    size = str(raw.get("size") or "M").upper()
    if size not in SIZES:
        raise ValueError(f"the size class is {size!r}, not one of {', '.join(SIZES)}")
    words = lambda k: [str(x).strip() for x in raw.get(k) or [] if str(x).strip()]
    size = size_of(size, words("files"), crit)
    return {"size": size, "asked_size": str(raw.get("size") or "M").upper(), "criteria": [{"id": f"C{i}", "text": x} for i, x in enumerate(TC.first(crit, 15, "acceptance criteria"), 1)],  # cap: untrusted (its prompt names the limit)
            "scope": words("scope"), "out_of_scope": words("out_of_scope"), "files": [f for f in words("files") if not known or f in known or "/" in f],
            "risks": words("risks"), "assumptions": words("assumptions"), "questions": TC.first(words("questions"), 3, "questions of a specification")}  # cap: untrusted (its prompt names the limit)


def specify(c, t, ask=None):
    """CHG-02, CHG-03: the specification. A question only when it blocks the plan; S starts at once, M and L wait for the Go."""
    import tasks as TK
    tid, s = t["id"], t["spec"]
    repo = s.get("repo") or (s.get("preset") or {}).get("repo")
    ch = dict(s.get("change") or {})
    run, t0 = f"task-intake:{tid}-{len(t['answers'])}", time.time()
    RTM.start(run, "intake", f"Task #{tid}: change specification", detail=t["text"], ref=f"task:{tid}")   # under the task's run (TSK-26)
    RTM.set_ref(run, "intake")
    try:
        known = RW.tracked(repo)
        tree = "\n".join(TC.more(sorted(known), 500, "more files"))  # cap: prompt
        prompt = P.text("intake", "CHANGE_SPEC").format(text=t["text"], repo=repo, today=dt.date.today().isoformat(), files=tree,
                                                        wiki=memory_of(ch, repo, "intake", request=t["text"], run=run) or "(no memory yet)",   # MEM-31
                                                        answers="\n".join(f"- {q}: {a}" for q, a in s.get("answered") or []) or "(none)")
        raw = (ask or (lambda p: M.ask_json(p, os.environ["VK_INTAKE"])))(prompt)
        spec = valid_spec(raw, known)
    except Exception as e:
        if M.paused(str(e)) and TK.wait_for_limit(c, tid, "The specification"):   # RUN-R9: waited out, not failed
            RTM.end(run, "intake", "limit", str(e), time.time() - t0)
            RTM.set_ref(None)
            return
        TK.put(c, tid, status="failed", error=f"specification: {type(e).__name__}: {e}")
        M.event("task", "", f"Task #{tid} could not be specified: {e}", title="Tasks")
        RTM.end(run, "intake", "limit" if M.paused(str(e)) else "failed", str(e), time.time() - t0)
        RTM.set_ref(None)
        return
    RTM.end(run, "intake", "done", f"{spec['size']}: {len(spec['criteria'])} criteria", time.time() - t0)
    RTM.set_ref(None)
    ch.update(spec)
    title = TK.title_of(raw.get("title") or t["text"])
    full = {**s, "repo": repo, "change": ch, "budget": dict(BUDGETS[spec["size"]])}
    TK.put(c, tid, title=title if len(title) >= 3 else t["text"], goal=str(raw.get("goal") or t["text"]).strip(), kind="change",
           done=[x["text"] for x in ch["criteria"]], spec=full, questions=spec["questions"], error=None)
    if spec["questions"]:
        TK.put(c, tid, status="needs_answer")
        M.notify_task(tid, title, "has a question on its specification")
    elif (spec["size"] != "S" or t.get("autonomy") == "ask") and not ch.get("auto_go"):
        TK.put(c, tid, status="waiting_approval")
        M.notify_task(tid, title, f"waits for your Go on its specification ({spec['size']})")
    else:
        begin(c, TK.row(c, tid))


def go(req, c):
    """The owner's Go, with his edits: criteria (one per line), paths he allows, a bigger budget."""
    import tasks as TK
    t = TK.row(c, int(req.get("id") or 0))
    if t["kind"] != "change" or t["status"] != "waiting_approval":
        raise ValueError("this change does not wait for your Go")
    ch = dict(t["spec"].get("change") or {})
    if req.get("criteria"):
        lines = [ln.strip() for ln in str(req["criteria"]).splitlines() if ln.strip()]
        ch["criteria"] = [{"id": f"C{i}", "text": x} for i, x in enumerate(TC.limit_items(lines, 15, "acceptance criteria"), 1)]
    if req.get("allow_paths") is not None:
        ch["allow_paths"] = [str(x).strip() for x in req["allow_paths"] if str(x).strip()]
    TK.put(c, t["id"], status="planned", spec={**t["spec"], "change": ch}, done=[x["text"] for x in ch["criteria"]])
    begin(c, TK.row(c, t["id"]))
    return {"task": t["id"]}


def resume(req, c):
    """A change stopped at its budget or a failed step: go on from there, with its budget doubled."""
    import conductor as CD
    import tasks as TK
    t = TK.row(c, int(req.get("id") or 0))
    if t["kind"] != "change" or t["status"] != "failed" or t["door"] != "plan":
        raise ValueError("only a change that stopped can go on")
    b = {k: v * 2 for k, v in (t["spec"].get("budget") or {}).items()}
    occ = CD.occ_of(c, t["id"])
    for s in CD.steps(c, t["id"], occ):
        if s["status"] == "failed":
            CD.put(c, s["id"], status="pending", attempts=0, error=None, waiting_for=None)
    c.execute("update task_occ set status='running', ended=null where task=? and occ=?", (t["id"], occ))
    c.commit()
    TK.put(c, t["id"], status="running", error=None, spec={**t["spec"], "budget": b})
    return {"task": t["id"], "budget": b}


def leave(req, c):
    """The owner's no to a stopped change: it stays as it stopped and leaves the queue (GEN-02); its page and branch are kept."""
    import tasks as TK
    t = TK.row(c, int(req.get("id") or 0))
    if t["kind"] != "change" or t["status"] != "failed":
        raise ValueError("only a change that stopped can be left stopped")
    TK.put(c, t["id"], status="cancelled")
    return {"task": t["id"]}


def rule(req, c):
    """A sentence of the owner's that holds from now on: on the repository wiki's Conventions, as his decision (CHG-11)."""
    repo, text = str(req.get("repo") or ""), TC.limit(str(req.get("text") or "").strip(), 2000, "the rule")
    if len(text) < 5:
        raise ValueError("say the rule in a sentence")
    if not RW.lesson(repo, text, f"the owner, {dt.date.today().isoformat()}", rule=True):
        raise ValueError(f"{repo} has no wiki yet: onboard it first")
    return {"repo": repo}


def handle(req, c):
    return {"change_request": create, "change_go": go, "change_resume": resume, "change_leave": leave, "change_rule": rule}[req["action"]](req, c)


# ---------- the plan ----------
def plan_of(size, need_profile=True):
    """CHG-04: the template by size class; the Orchestrator's checkpoints may change it within the budget."""
    def add(step, agent, why, harness=None):
        out.append({"step": step, "agent": agent, "why": why, "after": [len(out)] if out else [], **({"harness": harness} if harness else {})})
    out = []
    if need_profile:
        add("Find how to set the repository up and run its tests, by running them", "scribe", "the judge and the coders need the real commands", "change-profile")
    add("Run the suite before the change", "judge", "failures that are there already are no fault of this change", "change-baseline")
    if size == "L":
        add("Check the request against the code and refine the criteria", "analyst", "a large change misread is the most expensive mistake")
        add("Design the change and split it into tasks with their files", "planner", "tasks that do not share files can run at the same time")
        add("Give the design's tasks their own coders", "scribe", "one coder per task, each holding its files", "change-split")
    if size != "S":
        add("Write the acceptance tests from the criteria", "tester", "before the code exists, so it cannot shape them")
        add("See every acceptance test fail before the change", "judge", "a test that passes already proves nothing", "change-red")
    add("Implement the change", "builder", "in the repository's style, on the change's branch")
    add("Run everything and compare with the baseline", "judge", "a program decides, and sends failures back", "change-judge")
    if size != "S":
        add("Try to break it", "breaker", "edge cases and odd inputs, each failure a reproducing test")
        add("Run everything again", "judge", "the breaker's failures go back to the coder", "change-judge")
    add("Review it through three lenses on the other engine", "reviewer", "requirements, security and this repository's conventions", "change-review")
    if size != "S":
        add("Try it for real", "prober", "start it and use the changed behaviour", "change-probe")
    add("Write the report and put it up for your review", "presenter", "the branch, the evidence per criterion, the cost", "change-deliver")
    add("Fold what this run learned into the repository's wiki", "scribe", "so the next change starts from it", "change-scribe")
    return out


def slug_of(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40] or "change"  # cap: id


def begin(c, t):
    """The change's branch from the default branch, its plan, and the Conductor's first steps."""
    import builds as B
    import conductor as CD
    import tasks as TK
    tid, s = t["id"], t["spec"]
    repo, ch = s.get("repo"), dict(s.get("change") or {})
    try:
        path = B.clone(repo)
        B.git(path, "fetch", "-q", "origin", "--prune")
        main = B.default_branch(path)
        base = B.git(path, "rev-parse", f"origin/{main}")
        branch = f"change/{tid}-{slug_of(t['title'])}"
        B.git(path, "push", "-q", "origin", f"{base}:refs/heads/{branch}", timeout=120)
        need = not RW.profile(ch.get("wiki_of") or repo)
        ch.update(branch=branch, base=base, main=main, rounds={}, judge={}, status="running")
        spec = {**s, "change": ch, "plan": plan_of(ch.get("size") or "M", need)}
        TK.put(c, tid, spec=spec)
        CD.graph(spec["plan"])
        CD.start(c, TK.row(c, tid))
    except Exception as e:
        TK.put(c, tid, status="failed", door="plan", error=f"could not start: {type(e).__name__}: {e}")
        M.event("task", "", f"Task #{tid} could not start: {e}", title="Tasks")
        return
    TK.put(c, tid, door="plan", ref=str(tid), status="running")
    M.event("task", "", f"Change #{tid} started on {repo}, size {ch.get('size')}, branch {branch}: {t['title']}", title="Tasks")


# ---------- a step's brief ----------
ROLE = {"builder": "ROLE_CODER", "tester": "ROLE_TESTER", "breaker": "ROLE_BREAKER", "analyst": "ROLE_ANALYST", "planner": "ROLE_ARCHITECT"}
AGENT_STEPS = ("build", "claude-code")                # the steps an agent is briefed for; the others are this module's programs


def criteria_text(ch):
    return "\n".join(f"- {x['id']}: {x['text']}" for x in ch.get("criteria") or [])


def brief_of(ch, repo, request, files):
    """CHG-19: what the stack knows for this task, where a trial's arm asks for it. A run goes on without it, and is told."""
    import repofacts as RF
    try:
        return RF.brief(ch.get("wiki_of") or repo, request, files or ch.get("files"), code=repo, at=ch.get("facts_at"))
    except Exception as e:
        return f"## What the stack knows for this task\nUnknown: the brief could not be made ({type(e).__name__}: {e})."


REVIEW_ROLES = ("reviewer", "prober", "intake", "presenter")


def memory_of(ch, repo, role, request="", files=None, run=None):
    """What the role starts from (MEM-31, MEM-33): the memory stack's opening for this step's task, built from its own request and
    files: the code sector for the repository (the named or matched files, their facts, tests, failures and wiki lines, the
    commands), the role's lessons and its journal, within the run kind's budget. A trial's arm may ask for the memory as it was:
    `memory: wiki` (the fixed wiki opening and the brief when `brief` is set), or no wiki at all (`no_wiki` without `brief`)."""
    arm = ch.get("memory") or ("none" if ch.get("no_wiki") and not ch.get("brief") else "brief" if ch.get("brief") else "stack")
    if arm in ("stack", "stack+notes", "knowledge"):
        import memstack as MS
        card = role if role in MS.registry() else None
        subs = None
        if ch.get("trial"):                                # an exam's run starts clean: the role's journal holds earlier runs of
            subs = [x for x in MS.subscriptions(card or MS.agent_id(f"crew:{role}"), f"crew:{role}", repo=repo,   # the same case
                                                roles=[role] if not card else None) if not x.startswith(("agent:", "howto:lessons"))]
        return MS.opening(f"crew:{role}", kind="review" if role in REVIEW_ROLES else "code", task=request, card=card, role=role,
                          files=files or ch.get("files"), repo=repo, wiki_of=ch.get("wiki_of"), at=ch.get("facts_at"), run=run,
                          budget=ch.get("memory_budget"), subs=subs, knowledge=bool(ch.get("knowledge", not ch.get("trial"))))
    parts = []
    if arm == "wiki":
        parts.append(RW.opening(ch.get("wiki_of") or repo, role))
    if ch.get("brief"):
        parts.append(brief_of(ch, repo, request, files))
    try:
        import journal as J
        text, _ = J.memory_text(J.load(f"crew:{role}"), 3000) if not ch.get("trial") else ("", None)   # an exam's run: none (see above)
        if text.strip():
            parts.append(f"## Your own journal\n{text}")
    except Exception as e:                                # a run goes on without it
        print(f"journal of {role}: {type(e).__name__}: {e}", flush=True)
    return "\n\n".join(x for x in parts if x)


def skills_of(ch, role):
    """CHG-18: the pinned skills of a role, only where the trial's arm or the owner switched them on."""
    if not ch.get("skills"):
        return ""
    import skills as SK
    return SK.text(role)


def prompt_for(t, s, all_steps, agents):
    """The brief of one step of a change: its role, the specification, and the memory as the part that may be long."""
    if s["harness"] not in AGENT_STEPS or s["resume"].get("build") or s["resume"].get("claude_task"):
        return P.Prompt("")                               # a program, or an agent already at work: nothing to brief
    ch = t["spec"].get("change") or {}
    repo = t["spec"].get("repo")
    role = s["agent"]
    extra = ""
    design = [x for x in all_steps if x["agent"] in ("planner", "analyst") and x["status"] == "done"]
    if role in ROLE:
        extra = str(P.text("builder", ROLE[role]))
    files = s.get("resume", {}).get("files") if isinstance(s.get("resume"), dict) else None
    brief = str(P.text("shared", "CHANGE_STEP").format(repo=repo, title=t["title"], goal=t["goal"], request=t["text"], criteria=criteria_text(ch),
                                                       scope="; ".join(ch.get("scope") or []) or "(as the criteria need)",
                                                       out="; ".join(ch.get("out_of_scope") or []) or "(nothing named)",
                                                       risks="; ".join(ch.get("risks") or []) or "(none named)",
                                                       assumptions="; ".join(ch.get("assumptions") or []) or "(none)",
                                                       step=s["title"], role=extra))
    if files:
        brief += "\n\nYour task's files (the others are another coder's): " + ", ".join(files)
    how = RW.profile(ch.get("wiki_of") or repo)
    if how.get("test"):
        brief += f"\n\nHow to set it up: {how.get('setup') or '(nothing to set up)'}\nHow to run its tests: {how['test']}"
    import conductor as CD
    step_run = f"{CD.run_of(t['id'], s.get('occ') or 1)}:step:{s['idx']}"
    memory = memory_of(ch, repo, role, request=f"{t['title']}. {t['text']}\n{criteria_text(ch)}", files=files, run=step_run)
    results ="\n\n".join(f"### {x['title']} ({x['agent']})\n{x['output']}" for x in design if x["output"])
    tail = TC.cut("\n\n".join(y for y in (memory, skills_of(ch, role), results) if y), 75000, "the wiki, the journal and the steps' results are in the vault and on the task")  # cap: api (a build's context limit)
    prompt = P.Prompt(brief + (f"\n\n## Results of the steps before yours\n{tail}" if tail else ""))
    prompt.ref = getattr(P.text("shared", "CHANGE_STEP"), "ref", "")
    return prompt


def lane_problem(agent, files):
    """A tester's or breaker's build changes tests only, and the requirements that claim them where a repository keeps those
    (ai-stack refuses a test no requirement claims). -> what it touched outside them."""
    if agent not in ("tester", "breaker"):
        return []
    return [f for f in files if not TEST_PATH.search(f) and not f.startswith("requirements/")]


def assign(t, s):
    """What run_build adds for a change's build: onto its branch, without a review of its own, and the files it holds."""
    ch = t["spec"].get("change") or {}
    return {"onto": ch.get("branch"), **({"files": s["resume"]["files"]} if s["resume"].get("files") else {})}


def merged_step(c, t, s, r):
    """A step's build came back: into the change's branch, tests tracked, the role's journal written. -> the step's answer."""
    import builds as B
    import conductor as CD
    import tasks as TK
    ch = t["spec"].get("change") or {}
    files = [f[-1] for f in json.loads(r["files"] or "[]")]
    outside = lane_problem(s["agent"], files)
    again = {k: v for k, v in s["resume"].items() if k != "build"}   # the next attempt keeps its feedback and its files
    if outside:
        B.handle({"action": "build_reject", "id": r["id"]}, c)
        CD.put(c, s["id"], resume=again)
        raise RuntimeError(f"build #{r['id']} of {s['agent']} changed {', '.join(outside[:5])}, which are no tests")  # cap: top
    sha = B.change_merge(c, dict(r), ch["branch"])
    if not sha:
        CD.put(c, s["id"], resume=again)
        raise RuntimeError(f"build #{r['id']} does not merge onto {ch['branch']} (it conflicts with a build merged since)")
    if s["agent"] in ("tester", "breaker"):               # from here on these tests are the coder's to pass, not to change
        fresh = TK.row(c, t["id"])
        cur = dict(fresh["spec"].get("change") or {})
        tests = [f for f in files if TEST_PATH.search(f)]     # the tests are the coder's to pass; requirements stay everyone's to keep current
        cur.update(tester_commit=sha, tester_files=sorted({*(cur.get("tester_files") or []), *tests}))
        TK.put(c, t["id"], spec={**fresh["spec"], "change": cur})
    out = f"Build #{r['id']} merged into {ch['branch']} as {sha[:12]}.\n\n{r['summary'] or ''}".strip()
    journal(s["agent"], t, s, "done", TC.cut(out, 1500))  # cap: preview (the step keeps all of it)
    return out


def journal(role, t, s, state, summary):
    if ((t["spec"].get("change") or {}).get("trial")):   # an exam's run writes no entry a later run of the same case would read
        return
    try:
        import journal as J
        import conductor as CD
        run = f"{CD.run_of(t['id'], s.get('occ') or 1)}:step:{s['idx']}"
        J.record(f"crew:{role}", f"Change #{t['id']} on {t['spec'].get('repo')}: {s['title']}", run, state, summary, result=summary)
    except Exception as e:                                # the change goes on without the entry
        print(f"journal of {role}: {type(e).__name__}: {e}", flush=True)


# ---------- reopening: one step's failure goes back to the step that can mend it ----------
def fresh_ch(c, t):
    import tasks as TK
    row = TK.row(c, t["id"])
    return row, dict(row["spec"].get("change") or {})


def save_ch(c, t, row, ch):
    import tasks as TK
    TK.put(c, t["id"], spec={**row["spec"], "change": ch})


def reopen(c, t, s, target_agent, feedback, why, count=True):
    """The latest step of target_agent before s runs again with the feedback, and every step after it. -> False when its
    rounds are spent: the failure is then the owner's to see."""
    import conductor as CD
    row, ch = fresh_ch(c, t)
    rounds = dict(ch.get("rounds") or {})
    if count and rounds.get(target_agent, 0) >= ROUNDS:
        return False
    occ = s.get("occ") or 1
    ss = CD.steps(c, t["id"], occ)
    coders = sorted((x for x in ss if x["agent"] == target_agent and x["idx"] < s["idx"]), key=lambda x: x["idx"])
    if not coders:
        return False
    target = coders[-1] if target_agent != "builder" else coders[0]   # parallel coders: the first takes the fix (it may touch all files)
    n = rounds.get(target_agent, 0) + 1
    rounds[target_agent] = n
    ch["rounds"] = rounds
    save_ch(c, t, row, ch)
    between = [x for x in ss if target["idx"] < x["idx"] <= s["idx"]]
    judges = [x["idx"] for x in between if x["harness"] == "change-judge"]
    first = True
    for x in between:
        if x["agent"] == "breaker" or (x["harness"] == "change-judge" and x["idx"] != max(judges)) or (x["agent"] == target_agent and x["idx"] != target["idx"]):
            continue                                      # its tests stand; one judge runs everything once
        after = sorted({*x["after"], target["idx"]}) if first else x["after"]    # waits for the fix, not only for a step that stays done
        CD.put(c, x["id"], status="pending", attempts=0, error=None, waiting_for=None, resume={}, after=json.dumps(after))
        first = False
    CD.put(c, target["id"], status="pending", attempts=0, error=None, waiting_for=None, resume={"feedback": feedback, "round": n})
    M.event("task", "", f"Change #{t['id']}: {why}; back to {target_agent}, round {n} of {ROUNDS}", title="Tasks")
    return True


# ---------- the sandbox ----------
def workdir(repo):
    import builds as B
    return B.place(repo, JUDGE_SLOT)


def checkout(repo, ref):
    """The judge's own clone at a ref of origin. -> its path."""
    import builds as B
    path = B.clone(repo, JUDGE_SLOT)
    B.git(path, "fetch", "-q", "origin", "--prune")
    B.git(path, "reset", "-q", "--hard")
    B.git(path, "clean", "-fdq")
    B.git(path, "checkout", "-q", "--detach", ref if re.fullmatch(r"[0-9a-f]{7,40}", ref) else f"origin/{ref}")
    return path


STOP_EVERY = 10          # seconds between looks at whether the task was cancelled while its suite runs


def sandbox(repo, command, timeout=1800, run=subprocess.run, stop=None):
    """One command in the sandbox, in the judge's clone. -> (exit code, its last lines). With stop (a function), a long run
    looks every few seconds whether to stop, and then ends the command's processes and raises conductor.Cancelled (overnight 9 Nov 2026:
    a cancelled exam change's full sympy suite ran on for twenty minutes after the cancel, beside the next arm)."""
    import builds as B
    script = (f"umask 000; export PATH=/opt/tools/bin:$PATH PYTEST_ADDOPTS='-rfE'; out=$(mktemp); ( {command} ) > \"$out\" 2>&1; rc=$?; "
              f"tail -n {OUTPUT} \"$out\"; rm -f \"$out\"; echo __RC__$rc")
    argv = ["docker", "exec", "-u", "hermes", "-w", f"/work/{workdir(repo)}", B.BUILDER, "sh", "-c", script]
    if stop is None:
        p = run(argv, capture_output=True, text=True, timeout=timeout)
        out, err = p.stdout, p.stderr
    else:
        out, err = watched(argv, timeout, stop, f"/work/{workdir(repo)}")
    m = re.search(r"__RC__(\d+)\s*$", out or "")
    return (int(m[1]) if m else 1), re.sub(r"__RC__\d+\s*$", "", out or err or "")


def watched(argv, timeout, stop, where, popen=subprocess.Popen, end=None):
    """argv run to its end, its time limit, or stop() saying so: then every process working in `where` ends. -> (stdout, stderr)."""
    end = end or end_in
    p = popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + timeout
    while True:
        try:
            return p.communicate(timeout=STOP_EVERY)
        except subprocess.TimeoutExpired:
            pass
        late = time.time() > deadline
        if late or stop():
            end(where)
            p.kill()
            p.communicate()
            if late:
                raise subprocess.TimeoutExpired(argv, timeout)
            import conductor as CD
            raise CD.Cancelled("its task was cancelled")


def end_in(where):
    """Every process whose working folder is `where` (or below it) ends: a docker exec's own end leaves its command running
    in the container. The sandbox's processes show on the host with their container paths."""
    n = 0
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            cwd = os.readlink(d / "cwd")
        except OSError:
            continue
        if cwd == where or cwd.startswith(where.rstrip("/") + "/") or cwd.startswith(where + ".j"):
            try:
                os.kill(int(d.name), signal.SIGTERM)
                n += 1
            except OSError:
                pass
    return n


def cancelled(c, tid):
    """Whether the owner cancelled the task, read fresh."""
    r = c.execute("select status from tasks where id=?", (tid,)).fetchone()
    return bool(r) and r[0] == "cancelled"


SANDBOX_WORKERS = 2      # limit: paces, parallel test workers in the builder sandbox (2 GB, 3 CPUs in compose): more were killed for memory


def fit_workers(test):
    """A suite's parallel workers capped at what the sandbox holds (overnight 9 Nov 2026: sympy's profile said pytest -n 8,
    from the host's 8 cores; the sandbox's 2 GB killed the workers again and again and the suite never finished)."""
    def cap(m):
        n = m.group(2)
        return m.group(0) if n.isdigit() and int(n) <= SANDBOX_WORKERS else f"{m.group(1)}{SANDBOX_WORKERS}"
    return re.sub(r"(\s(?:-n|--numprocesses)[ =])(\d+|auto|logical)", cap, test)


def suite_command(repo, ch):
    import builds as B
    how = RW.profile(ch.get("wiki_of") or repo)
    test = fit_workers(B.CHECKS.get(repo) or how.get("test") or B.DEFAULT_CHECK)
    return f"{how['setup']} && {test}" if how.get("setup") else test


SUITE_MAX = 4 * 3600     # limit: stops, a suite run past 4 h counts as failed whatever the profile says (a hung suite)


def suite_timeout(repo, ch):
    """Seconds the judge gives the whole suite: three times the profile's minutes and ten for the setup, at least the old
    30 minutes (overnight 9 Nov 2026: sympy's suite with its install took longer than a fixed 30 minutes, the baseline
    timed out twice and the change stopped)."""
    minutes = RW.profile(ch.get("wiki_of") or repo).get("minutes")
    try:
        want = int((float(minutes) * 3 + 10) * 60)
    except (TypeError, ValueError):
        want = 1800
    return min(SUITE_MAX, max(1800, want))


def one_command(how, test_id):
    """One test by its id: the repository's own way, else pytest's and go's. -> the command, or None."""
    safe = re.fullmatch(r"[\w./:\[\]-]+", test_id or "")
    if not safe:
        return None
    if how.get("test_one"):
        return how["test_one"].replace("{id}", test_id)
    if ".py" in test_id:
        return f"pytest -q {test_id}"
    if "_test.go" in test_id:
        path, _, name = test_id.partition("::")
        return f"go test ./{os.path.dirname(path) or '.'} -run '^{name}$'" if name else f"go test ./{os.path.dirname(path) or '.'}"
    return None


FAILED = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)|^--- FAIL:\s+(\S+)|^\s*FAIL\s+([\w./-]+)\s", re.M)
SUMMARY = re.compile(r"\b(\d+) (passed|failed|errors?|skipped)\b")


def read_run(rc, out):
    """A test run as data: did it pass, which tests failed by name, the counts."""
    names = sorted({a or b or c for a, b, c in FAILED.findall(out)})
    return {"ok": rc == 0, "rc": rc, "failed": names or ([] if rc == 0 else ["(the test command failed: no test named)"]),
            "counts": {w.rstrip("s") if w.startswith("error") else w: int(n) for n, w in SUMMARY.findall(out)}, "tail": TC.tail(out, 3000)}  # cap: preview


def acceptance_of(ss):
    """The acceptance tests the tester (or an S change's coder) named for each criterion: {C1: test id}."""
    out = {}
    for s in ss:
        if s["agent"] in ("tester", "builder") and s["output"]:
            for cid, test in ACCEPT_LINE.findall(s["output"]):
                out.setdefault(cid, test)
    return out


# ---------- the judge's steps ----------
def run_baseline(c, t, s, prompt, card):
    """CHG-05: the suite before the change, on the change's branch as it was cut."""
    repo = t["spec"]["repo"]
    row, ch = fresh_ch(c, t)
    checkout(repo, ch["base"])
    rc, out = sandbox(repo, suite_command(repo, ch), timeout=suite_timeout(repo, ch), stop=lambda: cancelled(c, t["id"]))
    r = read_run(rc, out)
    ch["baseline"] = {"ok": r["ok"], "failed": r["failed"], "counts": r["counts"]}
    save_ch(c, t, row, ch)
    return (f"Baseline at {ch['base'][:12]}: " + ("the suite passes" if r["ok"] else f"{len(r['failed'])} already fail: {', '.join(TC.first(r['failed'], 20, 'baseline failures'))}")  # cap: list (the task's record keeps them all)
            + f" {r['counts']}")


def run_red(c, t, s, prompt, card):
    """CHG-06: each acceptance test must fail before the change; one that passes proves nothing and goes back to the tester."""
    repo = t["spec"]["repo"]
    row, ch = fresh_ch(c, t)
    import conductor as CD
    ss = CD.steps(c, t["id"], s.get("occ") or 1)
    tests = acceptance_of([x for x in ss if x["agent"] == "tester"])
    checkout(repo, ch["branch"])
    how = RW.profile(ch.get("wiki_of") or repo)
    states, passing, unnamed = {}, [], []
    for x in ch.get("criteria") or []:
        test = tests.get(x["id"])
        cmd = one_command(how, test) if test else None
        if not cmd:
            if not test:
                unnamed.append(x["id"])
            states[x["id"]] = {"test": test, "before": "not run"}
            continue
        rc, _ = sandbox(repo, cmd, timeout=600)
        states[x["id"]] = {"test": test, "before": "fails" if rc else "passes"}
        if not rc:
            passing.append(f"{x['id']} ({test})")
    ch["acceptance"] = states
    save_ch(c, t, row, ch)
    if (passing or unnamed) and reopen(c, t, s, "tester", (f"These acceptance tests pass before any change, so they prove nothing: {', '.join(passing)}. " if passing else "")
                                       + (f"These criteria have no test named on a line like `C1: path::test`: {', '.join(unnamed)}." if unnamed else ""),
                                       f"{len(passing)} tests pass already, {len(unnamed)} criteria have no test", count=True):
        raise CD.Reopened("back to the tester")
    return "Before the change: " + "; ".join(f"{k}: {v['before']}" for k, v in states.items())


def changed_files(repo, base, ref="HEAD"):
    import builds as B
    path = B.clone(repo, JUDGE_SLOT)
    return B.git(path, "diff", "--name-only", f"{base}..{ref}", timeout=120).split()


def base_of(path, ch):
    """Where this change leaves the default branch: what its diff is measured from, after main was merged in."""
    import builds as B
    return B.git(path, "merge-base", f"origin/{ch['main']}", "HEAD", check=False) or ch["base"]


def with_main(repo, path, ch):
    """Others land while a change runs: main merged into its branch, so the judge sees the code it will land on. -> False on a conflict."""
    import builds as B
    if B.git(path, "rev-list", "--count", f"HEAD..origin/{ch['main']}") == "0":
        return True
    if not B.merge(path, f"origin/{ch['main']}", f"Merge {ch['main']} into the change's branch"):
        return False
    B.git(path, "push", "-q", "origin", f"HEAD:refs/heads/{ch['branch']}", timeout=120)
    return True


def protected_hits(repo, files, allowed=()):
    if repo != "ai-stack":
        return []
    return [f for f in files if f.startswith(PROTECTED) and not any(f == a or f.startswith(a) for a in allowed)]


def run_judge(c, t, s, prompt, card):
    """CHG-05: everything on the branch against the baseline; what is new goes back to the coder. A program decides."""
    import builds as B
    import conductor as CD
    repo = t["spec"]["repo"]
    row, ch = fresh_ch(c, t)
    path = checkout(repo, ch["branch"])
    if not with_main(repo, path, ch):
        B.git(path, "reset", "-q", "--hard")
        if reopen(c, t, s, "builder", f"The branch no longer merges with {ch['main']}, where others landed since. Merge origin/{ch['main']} into it, resolve the conflicts and commit.", f"{ch['main']} moved and conflicts"):
            raise CD.Reopened("back to the coder")
    base = base_of(path, ch)
    rc, out = sandbox(repo, suite_command(repo, ch), timeout=suite_timeout(repo, ch), stop=lambda: cancelled(c, t["id"]))
    first = read_run(rc, out)
    known = set((ch.get("baseline") or {}).get("failed") or [])
    new = [f for f in first["failed"] if f not in known]
    flaky = []
    if new and rc:                                        # a test that failed once runs again: a flake is no failure of this change
        how = RW.profile(ch.get("wiki_of") or repo)
        for name in TC.first(new, 10, "tests run again"):  # cap: list (the rest count as failed)
            cmd = one_command(how, name)
            if cmd and not sandbox(repo, cmd, timeout=600)[0]:
                flaky.append(name)
        new = [f for f in new if f not in flaky]
    files = changed_files(repo, base)
    bad = protected_hits(repo, files, ch.get("allow_paths") or [])
    tampered = []
    if ch.get("tester_commit") and ch.get("tester_files"):         # merges don't count: main may touch a test file too
        tampered = sorted(set(B.git(path, "log", "--no-merges", "--name-only", "--format=", f"{ch['tester_commit']}..HEAD", "--", *ch["tester_files"], timeout=120).split()))
    ss = CD.steps(c, t["id"], s.get("occ") or 1)
    tests = acceptance_of(ss)
    how = RW.profile(ch.get("wiki_of") or repo)
    states = dict(ch.get("acceptance") or {})
    for x in ch.get("criteria") or []:
        test = tests.get(x["id"]) or (states.get(x["id"]) or {}).get("test")
        cmd = one_command(how, test) if test else None
        cur = states.get(x["id"]) or {"test": test, "before": "not run"}
        cur["test"] = test
        cur["after"] = ("passes" if not sandbox(repo, cmd, timeout=600)[0] else "fails") if cmd else "not run"
        states[x["id"]] = cur
    missing = [k for k, v in states.items() if v.get("after") == "fails"]
    proven, proof = True, ""
    if (path / "ops/req.py").exists():
        proven, _, proof = B.prove({"repo": repo}, JUDGE_SLOT, base)
    problems = []
    if new:
        problems.append("New test failures:\n" + "\n".join(f"- {x}" for x in new))
    if missing:
        problems.append("Acceptance tests that fail: " + ", ".join(f"{k} ({states[k]['test']})" for k in missing))
    if bad:
        problems.append("This change may not touch (restore them): " + ", ".join(bad))
    if tampered:
        problems.append("The acceptance tests were changed after the tester wrote them (restore them and make the code pass them): " + ", ".join(tampered))
    if not proven:
        problems.append("Requirements not proven (ops/req.py prove):\n" + TC.tail(proof, 1500))  # cap: prompt
    checks = run_checks(repo, path, base, checks_of(ch.get("wiki_of") or repo))      # the deployment's own (GEN-15)
    for v in checks:
        if not v["pass"]:
            problems.append(f"The check {v['name']} ({v['where']}) fails:\n" + "\n".join(v["problems"]))
    ok = not problems
    ch["acceptance"] = states
    ch["judge"] = {"ok": ok, "new": new, "known": sorted(known), "flaky": flaky, "counts": first["counts"], "protected": bad, "tampered": tampered,
                   "proven": proven, "head": B.git(path, "rev-parse", "HEAD"), "tail": first["tail"], "checks": checks}
    save_ch(c, t, row, ch)
    if flaky:
        RW_note(repo, ch, f"These tests failed once and passed when run again: {', '.join(flaky)}", f"change #{t['id']}")
    if problems and reopen(c, t, s, "builder", "\n\n".join(problems) + f"\n\nThe end of the test run:\n```\n{first['tail']}\n```", f"the judge found {len(problems)} problem(s)"):
        raise CD.Reopened("back to the coder")
    if problems:
        return "The change still fails after its fix rounds:\n\n" + "\n\n".join(problems)
    return f"All good against the baseline: {first['counts']}" + (f"; flaky: {', '.join(flaky)}" if flaky else "") + f"; {len(known)} failures that were there before."


# ---------- the deployment's own checks for a repository (GEN-15) ----------
def checks_of(repo, folder=None):
    """The checks this deployment adds to the judge for a repository (deployments/<name>/checks/<repo>.yaml). The owner
    sets them there: a repository's profile is a model's writing, and the judge is not the model's to change. A check:
      name, where (wsl: a command in the sandbox, like the suite; windows: a job kind of the Windows worker), minutes, and
      command (wsl) or job and values (windows; the judge adds commit, the change's base, and patch, the change as a diff).
    A Windows job may leave artifacts/verdict.json, {pass, problems, evidence}: that is its verdict."""
    import deployment as DEPLOY
    import yaml
    f = Path(folder or DEPLOY.FOLDER) / "checks" / f"{repo}.yaml"
    if not f.is_file():
        return []
    out = []
    for c in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("checks") or []:
        where = c.get("where", "wsl")
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,40}", str(c.get("name") or "")) or where not in ("wsl", "windows") or \
                (where == "wsl" and not c.get("command")) or (where == "windows" and not c.get("job")):
            raise ValueError(f"{f}: a check has a name, where (wsl or windows), and a command (wsl) or a job (windows): {c}")
        out.append({"name": c["name"], "where": where, "command": c.get("command"), "job": c.get("job"),
                    "values": dict(c.get("values") or {}), "minutes": int(c.get("minutes") or 30)})
    return out


def run_checks(repo, path, base, checks, ww=None):
    """-> [{name, where, pass, problems, evidence}]: each check's verdict. Output from Windows is untrusted text."""
    import builds as B
    out = []
    for c in checks:
        if c["where"] == "wsl":
            rc, said = sandbox(repo, c["command"], timeout=c["minutes"] * 60)
            out.append({"name": c["name"], "where": "wsl", "pass": not rc, "evidence": ["the sandbox's output"],
                        "problems": [] if not rc else [f"`{c['command']}` exited with {rc}:\n" + TC.tail(said, 2000)]})  # cap: prompt
            continue
        if ww is None:
            import winworker as ww
        diff = B.git(path, "diff", "--no-color", f"{base}..HEAD", timeout=120)
        try:
            if diff.strip():
                rid = ww.submit(c["job"], {**c["values"], "commit": base, "patch": "change.diff"}, files={"change.diff": diff + "\n"})
            else:                                         # no change (a control run): the job runs on the base commit, with no
                rid = ww.submit(c["job"], {**c["values"], "commit": base}, files={})   # patch value a job would refuse as empty (GEN-15)
            st = ww.wait(rid, timeout=c["minutes"] * 60, retry_kind=c["job"])
        except Exception as e:                            # a check that cannot run is no pass (GEN-01)
            out.append({"name": c["name"], "where": "windows", "pass": False, "evidence": [], "problems": [f"the check could not run: {e}"]})
            continue
        arts = ww.ANSWERS / rid / "artifacts"
        verdict = None
        try:
            verdict = json.loads((arts / "verdict.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if st.get("status") == "done" and verdict is not None:
            ok, probs = bool(verdict.get("pass")), [str(x) for x in verdict.get("problems") or []]
            ev = [str(x) for x in verdict.get("evidence") or []]
        else:
            ok, ev = st.get("status") == "done", [str(arts / a) for a in st.get("artifacts") or []]
            probs = [] if ok else [f"the Windows job {c['job']} {st.get('status')}: {st.get('error') or ''}"]
            if not ok and (arts / "log.txt").is_file():
                probs.append("The end of its log (untrusted output of the build):\n" + TC.tail((arts / "log.txt").read_text(encoding="utf-8", errors="replace"), 2000))  # cap: prompt
        out.append({"name": c["name"], "where": "windows", "pass": ok, "problems": probs, "evidence": ev})
    return out


def RW_note(repo, ch, text, evidence):
    if not ch.get("no_wiki") and not ch.get("trial"):      # an exam's run teaches the exam, not the wiki
        try:
            RW.lesson(ch.get("wiki_of") or repo, text, evidence)
        except Exception as e:                            # the run goes on; the retro has it too
            print(f"wiki note: {type(e).__name__}: {e}", flush=True)


# ---------- the reviewers ----------
def run_review(c, t, s, prompt, card, one=None):
    """Three lenses on the other engine; its findings go back to the coder once, then to the owner (CHG-07)."""
    import builds as B
    import codegraph as CG
    import conductor as CD
    from concurrent.futures import ThreadPoolExecutor
    repo = t["spec"]["repo"]
    row, ch = fresh_ch(c, t)
    path = checkout(repo, ch["branch"])
    base = base_of(path, ch)
    diff = B.git(path, "diff", f"{base}..HEAD", timeout=120)
    files = changed_files(repo, base)
    blast = CG.text(CG.pack(path, repo, files))
    conv = memory_of(ch, repo, "reviewer", request=f"{t['title']}. {t['text']}", files=files,           # MEM-31: for the files it changed
                     run=f"{CD.run_of(t['id'], s.get('occ') or 1)}:step:{s['idx']}")
    fake = {"repo": repo, "id": t["id"], "title": t["title"], "description": f"{t['text']}\n\nAcceptance criteria:\n{criteria_text(ch)}", "engine": "claude"}
    engine, ok, ref = B.reviewer_for("claude"), bool((ch.get("judge") or {}).get("ok")), RTM.ref()

    def look(lens):
        RTM.set_ref(ref)
        ctx = f"{conv}\n\n{blast}" if lens == "conventions" else blast
        return (one or B.one_review)(engine, fake, path, diff, ok, lens, JUDGE_SLOT, ctx, [x["id"] for x in ch.get("criteria") or []])
    with ThreadPoolExecutor(3) as ex:
        reviews = list(ex.map(look, ("requirements", "security", "conventions")))
    result = B.combine(reviews)
    ch["review"] = result
    save_ch(c, t, row, ch)
    verdict = result.get("verdict")
    if verdict in ("changes", "block") and not (ch.get("rounds") or {}).get("review"):
        row, ch = fresh_ch(c, t)
        ch.setdefault("rounds", {})["review"] = 1
        save_ch(c, t, row, ch)
        found = "\n".join(f"- [{f.get('lens')}, {f['severity']}] {f['file']}:{f['line']}: {f['issue']} Fix: {f['fix']}" for f in result.get("findings") or [])
        if reopen(c, t, s, "builder", f"The reviewers ask for this ({verdict}):\n{found}", f"the reviewers said {verdict}"):
            raise CD.Reopened("back to the coder")
    return f"Reviewers: {verdict or 'none finished'}. {result.get('summary') or result.get('error') or ''}"


# ---------- the prober ----------
def run_probe(c, t, s, prompt, card, run=subprocess.run):
    """CHG-14: the change tried for real in the sandbox, with its evidence; what could not be tried is said."""
    import builds as B
    import conductor as CD
    repo, tid = t["spec"]["repo"], t["id"]
    row, ch = fresh_ch(c, t)
    checkout(repo, ch["branch"])
    how = RW.profile(ch.get("wiki_of") or repo)
    p = P.text("prober", "PROBE").format(repo=repo, tid=tid, request=t["text"], criteria=criteria_text(ch), setup=how.get("setup") or "(none known)",
                                         wiki=memory_of(ch, repo, "prober", request=f"{t['title']}. {t['text']}", files=ch.get("files"),
                                                        run=f"{CD.run_of(tid, s.get('occ') or 1)}:step:{s['idx']}") or "(no memory)")
    P.record(p)
    (EVIDENCE / str(tid)).mkdir(parents=True, exist_ok=True)
    os.chmod(EVIDENCE / str(tid), 0o777)
    q = run(["docker", "exec", "-u", "hermes", *MP.claude_args(), "-w", f"/work/{workdir(repo)}", *RTM.env_args(), "-e", "AISTACK_AGENT=prober",
             "-e", f"AISTACK_TITLE=Probe of change #{tid}", B.BUILDER, "timeout", "1500", "claude", "-p", str(p), "--output-format", "json",
             # limit: stops, a probe past 40 turns is reported as stopped; the change goes on to the owner with that said
             "--max-turns", "40", "--allowedTools", "Bash,Read,Grep,Glob", "--disallowedTools", "Edit,NotebookEdit,WebFetch,WebSearch",
             "--settings", "/config/claude-hooks/claude-runtime-settings.json"], capture_output=True, text=True, timeout=1600, env={**os.environ})
    text = B.claude_text(q.stdout)
    if re.search(r"usage limit|hit your limit", text or "", re.I):
        raise RuntimeError("Claude usage limit")
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        v = json.loads(m.group(0)) if m else {}
    except ValueError:
        v = {}
    kept = keep_evidence(tid)
    row, ch = fresh_ch(c, t)
    ch["probe"] = {"ran": bool(v.get("ran")), "ok": bool(v.get("ok")), "notes": TC.cut(str(v.get("notes") or text or "no answer"), 3000), "evidence": kept}  # cap: preview
    save_ch(c, t, row, ch)
    if v.get("ran") and not v.get("ok") and reopen(c, t, s, "builder", f"The prober tried it for real and it did not work:\n{v.get('notes')}", "the prober found it does not work"):
        raise CD.Reopened("back to the coder")
    return f"Probe: {'it works' if v.get('ok') else 'it did not work' if v.get('ran') else 'it could not be tried'}. {ch['probe']['notes']}"


def keep_evidence(tid):
    """The prober's files, where the app serves them. -> their names."""
    src, dst = EVIDENCE / str(tid), M.PUBLIC / PUBLIC_DIR / str(tid)
    if not src.is_dir():
        return []
    dst.mkdir(parents=True, exist_ok=True)
    names = []
    for f in sorted(src.iterdir()):
        # limit: drops, a probe's evidence file past 5 MB; its name is said in the notes it wrote
        if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".txt", ".log", ".json") and f.stat().st_size < 5_000_000:
            shutil.copy(f, dst / f.name)
            os.chmod(dst / f.name, 0o644)
            names.append(f.name)
    return names


# ---------- the report and the owner's review ----------
def cost_of(c, t, s):
    import conductor as CD
    hours, tokens = CD.spent(c, t, s)
    return f"{tokens:,} tokens, {hours * 60:.0f} minutes"


def report(c, t, s):
    """CHG-16: what was asked, each criterion with its evidence, what the checks and reviewers said, what it cost."""
    row, ch = fresh_ch(c, t)
    j, rv, pr = ch.get("judge") or {}, ch.get("review") or {}, ch.get("probe")
    states = ch.get("acceptance") or {}
    lines = [f"**{row['title']}** on `{row['spec'].get('repo')}`, size {ch.get('size')}", "", f"The request: {row['text']}", "", "## Acceptance criteria", ""]
    for x in ch.get("criteria") or []:
        st = states.get(x["id"]) or {}
        met = st.get("after") == "passes" and st.get("before") != "passes"
        word = "met" if met else "no test run" if st.get("after") in (None, "not run") else "not met"
        lines.append(f"- **{x['id']} {word}**: {x['text']}" + (f" Test `{st['test']}`: before the change it {st.get('before')}, after it {st.get('after')}." if st.get("test") else ""))
    lines += ["", "## Checks", "", f"- The suite: {'passes against the baseline' if j.get('ok') else 'NOT passing'} {j.get('counts') or ''}"]
    if j.get("known"):
        lines.append(f"- Already failing before this change: {', '.join(TC.first(j['known'], 20, 'known failures'))}")  # cap: list (the task's record keeps them all)
    if j.get("new"):
        lines.append(f"- New failures: {', '.join(j['new'])}")
    if j.get("flaky"):
        lines.append(f"- Failed once, then passed: {', '.join(j['flaky'])}")
    for what, key in (("Touches what it may not", "protected"), ("Changed the acceptance tests", "tampered")):
        if j.get(key):
            lines.append(f"- {what}: {', '.join(j[key])}")
    lines += ["", "## Reviewers", "", f"- Verdict: {rv.get('verdict') or 'none finished'}" + (f", not done: {', '.join(rv['missing'])}" if rv.get("missing") else ""), *(f"- [{f.get('lens')}, {f['severity']}] {f['file']}: {f['issue']}" for f in rv.get("findings") or [])]
    if pr is not None:
        lines += ["", "## Tried for real", "", f"- {'It works' if pr['ok'] else 'It did not work' if pr['ran'] else 'It could not be tried'}. {pr['notes']}"]
        if pr.get("evidence"):
            lines.append(f"- Evidence: {', '.join(pr['evidence'])}")
    rounds = {k: v for k, v in (ch.get("rounds") or {}).items() if v}
    if ch.get("assumptions"):
        lines += ["", "## Assumptions it made", "", *(f"- {x}" for x in ch["assumptions"])]
    lines += ["", "## Cost", "", f"- {cost_of(c, t, s)}" + (f"; fix rounds: {rounds}" if rounds else "")]
    return "\n".join(lines)


def run_deliver(c, t, s, prompt, card):
    """The report, a carrier build in review, a pull request, one message; then it waits for the owner's tap."""
    import builds as B
    import conductor as CD
    import notify as N
    bid = s["resume"].get("carrier")
    if not bid:
        row, ch = fresh_ch(c, t)
        repo = row["spec"]["repo"]
        text = report(c, t, s)
        if ch.get("trial"):                               # the exam scores the branch: no review, no pull request, no message
            ch.update(report=text, outcome="scored by the exam")
            save_ch(c, t, row, ch)
            return text
        path = checkout(repo, ch["branch"])
        head = B.git(path, "rev-parse", "HEAD")
        base = base_of(path, ch)
        files = [ln.split("\t") for ln in B.git(path, "diff", "--name-status", f"{base}..HEAD").splitlines()]
        j = ch.get("judge") or {}
        checks = ("ALL CHECKS PASSED" if j.get("ok") else "CHECKS FAILED") + f" (the change's judge: {j.get('counts') or 'no counts'})\n\n{j.get('tail') or ''}"
        rv = ch.get("review") or None
        t0 = M.now().isoformat(timespec="seconds")
        old = ch.get("carrier")
        pr = c.execute("select pr, pr_number from builds where id=?", (old,)).fetchone() if old else None
        cur = c.execute("insert into builds (repo, title, description, status, branch, base, head, summary, files, checks, ci, created, updated, attempts, engine, "
                        "ai_review, source, pr, pr_number) values (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?)",
                        (repo, TC.fit(f"Change #{t['id']}: {row['title']}", 200), row["text"], "review", ch["branch"], base, head, text, json.dumps(files), checks,  # cap: id
                         "pending", t0, t0, "claude", json.dumps(rv) if rv else None, f"change:{t['id']}", pr["pr"] if pr else None, pr["pr_number"] if pr else None))
        c.commit()
        bid = cur.lastrowid
        (B.OUT / f"{bid}.diff").write_text(TC.cut(B.git(path, "diff", f"{base}..HEAD", timeout=120), 600000))  # cap: store
        CD.step_ref(c, "build", bid, t["id"])
        B.save_files(bid)
        B.open_pr(c, bid)
        ch.update(carrier=bid, report=text)
        save_ch(c, t, row, ch)
        CD.put(c, s["id"], resume={"carrier": bid})
        ok = sum((ch.get("acceptance") or {}).get(x["id"], {}).get("after") == "passes" for x in ch.get("criteria") or [])
        N.send(f"Change #{t['id']} is ready for your review: {row['title']}\n{ok} of {len(ch.get('criteria') or [])} criteria met · checks {'passed' if j.get('ok') else 'FAILED'} · "
               f"reviewers: {rv.get('verdict') if rv else 'none'}", "build", by="presenter", title="Code", push_on=True, event_kind="build",
               buttons=[[("🔍 Review it", f"{M.X.APP}/#/task/{t['id']}")]])
    r = c.execute("select status, merged, error from builds where id=?", (bid,)).fetchone()
    if r and r["status"] in ("merged", "deployed", "rejected", "rolled_back"):
        row, ch = fresh_ch(c, t)
        ch["outcome"] = r["status"]
        save_ch(c, t, row, ch)
        return f"{ch.get('report') or ''}\n\n## Your review\n\n{r['status']}" + (f" as {r['merged'][:12]}" if r["merged"] else "")
    if r and r["status"] == "cancelled":                  # a request for changes went on without this one
        raise RuntimeError("its review was superseded")
    raise CD.Waiting(f"build #{bid}: " + ("waits for your review" if r and r["status"] == "review" else (r["status"] if r else "starting")))


def on_revise(c, b, feedback):
    """Request changes on a change: a lesson candidate, the carrier ended, the coder and every step after it run again (CHG-11)."""
    import builds as B
    import conductor as CD
    import tasks as TK
    tid = int(str(b["source"]).split(":", 1)[1])
    t = TK.row(c, tid)
    ch = t["spec"].get("change") or {}
    occ = CD.occ_of(c, tid)
    deliver = next((x for x in CD.steps(c, tid, occ) if x["harness"] == "change-deliver"), None)
    if not deliver:
        raise ValueError("this change's plan has no review step")
    B.put(c, b["id"], status="cancelled", note="the owner asked for changes: the change's pipeline goes on")
    RW_note(t["spec"]["repo"], ch, feedback, f"the owner's review of change #{tid}")
    waited = (M.now() - dt.datetime.fromisoformat(b["created"])).total_seconds() / 3600
    budget = dict(t["spec"].get("budget") or {})
    if budget.get("hours"):                               # the time it waited for his review was none of its own
        budget["hours"] = round(budget["hours"] + waited, 2)
        TK.put(c, tid, spec={**t["spec"], "budget": budget})
    if not reopen(c, t, deliver, "builder", f"The owner reviewed this and asks for changes:\n{feedback}", "the owner asked for changes", count=False):
        raise ValueError("this change has no coder to send it back to")
    M.event("build", "", f"Change #{tid}: changes requested", title="Code")
    return {"queued": True, "task": tid}


def on_reject(c, b, reason=""):
    """A rejection is a lesson candidate; the step sees it and the Scribe writes the retro."""
    import tasks as TK
    tid = int(str(b["source"]).split(":", 1)[1])
    t = TK.row(c, tid)
    RW_note(t["spec"]["repo"], t["spec"].get("change") or {}, f"Rejected change: {t['title']}" + (f". {reason}" if reason else ""), f"the owner's review of change #{tid}")


# ---------- the scribe's steps ----------
def run_profile(c, t, s, prompt, card):
    """How the repository is set up and tested, found by running it in a throwaway copy (CHG-12, CHG-13)."""
    import claude_tasks as CT
    import conductor as CD
    repo = t["spec"]["repo"]
    tid = s["resume"].get("claude_task")
    if not tid:
        q = str(P.text("scribe", "PROFILE").format(repo=repo))
        tid = CT.handle({"action": "claude_task", "question": q, "mode": "analyse", "repo": repo, "source": f"{CD.run_of(t['id'], s.get('occ') or 1)}:step:{s['idx']}"}, c)["id"]
        CD.put(c, s["id"], resume={"claude_task": tid})
        CD.step_ref(c, "claude", tid, t["id"])
    r = c.execute("select status, answer, error from claude_tasks where id=?", (tid,)).fetchone()
    if not r or r["status"] in ("queued", "running", "waiting"):
        raise CD.Waiting(f"Claude task #{tid}")
    if r["status"] != "done":
        CD.put(c, s["id"], resume={})
        raise RuntimeError(f"Claude task #{tid} {r['status']}: {r['error'] or ''}")
    m = re.search(r"\{.*\}", r["answer"] or "", re.S)
    if not m:
        raise RuntimeError("the profile came back without its JSON")
    doc = json.loads(m.group(0))
    doc = {k: doc.get(k) for k in ("toolchain", "setup", "test", "test_one", "minutes", "notes", "ran")}
    doc["found"] = dt.date.today().isoformat()
    RW.save_profile((t["spec"].get("change") or {}).get("wiki_of") or repo, doc)
    if RW.exists(repo):
        RW.lesson(repo, f"Set up with: {doc.get('setup') or 'nothing'}. Tests run with: {doc.get('test')}. {doc.get('notes') or ''}", f"run in the sandbox, change #{t['id']}")
    return json.dumps(doc, ensure_ascii=False)


def run_split(c, t, s, prompt, card):
    """L: the architect's tasks become one coder each, holding their files. One task stays one coder."""
    import conductor as CD
    occ = s.get("occ") or 1
    ss = CD.steps(c, t["id"], occ)
    design = next((x for x in ss if x["agent"] == "planner"), None)
    m = re.search(r"\{.*\"tasks\".*\}", (design or {}).get("output") or "", re.S)
    tasks = []
    if m:
        try:
            tasks = [x for x in json.loads(m.group(0)).get("tasks") or [] if isinstance(x, dict) and x.get("title")]
        except ValueError:
            pass
    coder = next((x for x in ss if x["agent"] == "builder"), None)
    if not coder or len(tasks) < 2:
        return "One coder takes the whole change."
    tasks = TC.first(tasks, 3, "tasks for parallel coders")  # cap: untrusted (two slots; its prompt names the limit)
    CD.put(c, coder["id"], title=f"Implement: {tasks[0]['title']}", resume={"files": tasks[0].get("files") or []})
    judge = next(x for x in ss if x["harness"] == "change-judge" and x["idx"] > coder["idx"])
    nxt = max(x["idx"] for x in ss) + 1
    extra = []
    for task in tasks[1:]:
        c.execute("insert into task_steps (task, occ, idx, title, item, agent, harness, model, after, why, status, attempts, loop, resume) values (?,?,?,?,?,?,?,?,?,?,?,0,null,?)",
                  (t["id"], occ, nxt, f"Implement: {task['title']}", None, "builder", "build", coder["model"], json.dumps(coder["after"]), "one coder per task, holding its files",
                   "pending", json.dumps({"files": task.get("files") or []})))
        extra.append(nxt)
        nxt += 1
    CD.put(c, judge["id"], after=json.dumps(sorted(set(judge["after"]) | set(extra))))
    c.commit()
    return f"{len(tasks)} coders: " + "; ".join(x["title"] for x in tasks)


def run_scribe(c, t, s, prompt, card):
    """CHG-08 to CHG-11: what the run learned, folded into the wiki. A failure here never fails the change."""
    import conductor as CD
    row, ch = fresh_ch(c, t)
    repo = row["spec"]["repo"]
    head = ch.get("report") or ""
    ss = CD.steps(c, t["id"], s.get("occ") or 1)
    if ch.get("no_wiki") or ch.get("trial") or not RW.exists(repo):
        return f"{head}\n\n## Repository wiki\n\nNot written: " + ("an exam's run leaves it as it is." if ch.get("no_wiki") or ch.get("trial") else "the repository has no wiki yet.")
    retro = "\n\n".join(f"### {x['title']} ({x['agent']}, {x['status']})\n{TC.cut(x['output'] or x['error'] or '', 4000)}" for x in ss if x["idx"] != s["idx"])  # cap: prompt
    rel = f"tasks/{t['id']}-change-retro-{s.get('occ') or 1}.md"
    (M.VAULT / rel).parent.mkdir(parents=True, exist_ok=True)
    (M.VAULT / rel).write_text(f"---\ntask: {t['id']}\nrepo: {repo}\nbranch: {ch.get('branch')}\n---\n# Retro of change #{t['id']}: {row['title']}\n\n{head}\n\n{retro}\n")
    try:
        pages = RW.fold(repo, f"The retro of change #{t['id']} ({row['title']}, outcome: {ch.get('outcome') or 'open'}).\n\n{head}\n\n{retro}", rel,
                        key=os.environ["VK_" + card["key"][3:].upper().replace("-", "_")])
        M.vault_commit([f"repos/{repo}", rel], f"repo wiki: {repo}: what change #{t['id']} learned")
        M.reindex()
        gaps = RW.lines_without_evidence(repo)
        said = f"{len(pages)} pages: {', '.join(pages)}" + (f"; {len(gaps)} lines without evidence for the Librarian" if gaps else "")
    except Exception as e:
        if M.paused(str(e)):
            raise
        said = f"not written: {type(e).__name__}: {e}"
        M.log(f"change #{t['id']}: the wiki not written: {said}")
    return f"{head}\n\n## Repository wiki\n\n{said}"


def looks_again(t):
    """CHG-04: a small change's plan needs no second look."""
    return (t["spec"].get("change") or {}).get("size") != "S"


# ---------- what the Conductor runs of this (TSK-36, ops/stepkinds.py) ----------
# held: a change's judge, review and delivery are not the plan's to drop.
# even_spent: the report and the wiki come even at a spent budget: what was done is shown, and what it taught is kept.
STEP_KINDS = {"change-baseline": {"run": run_baseline, "owners": ("judge",), "gb": 0.75, "held": True},
              "change-red": {"run": run_red, "owners": ("judge",), "gb": 0.5, "held": True},
              "change-judge": {"run": run_judge, "owners": ("judge",), "gb": 0.75, "held": True},
              "change-review": {"run": run_review, "owners": ("reviewer",), "gb": 0.25, "held": True},
              "change-probe": {"run": run_probe, "owners": ("prober",), "gb": 1.0, "held": True},
              "change-deliver": {"run": run_deliver, "owners": ("presenter",), "gb": 0.1, "held": True, "waits": True, "even_spent": True},
              "change-profile": {"run": run_profile, "owners": ("scribe",), "gb": 0.75, "held": True, "waits": True},
              "change-split": {"run": run_split, "owners": ("scribe",), "gb": 0.1, "held": True},
              "change-scribe": {"run": run_scribe, "owners": ("scribe",), "gb": 0.25, "held": True, "even_spent": True}}
# a change's brief is its own; its builds go onto its branch with its lanes, into its branch when they come back; its steps stay their roles'
TASK_KINDS = {"change": {"brief": prompt_for, "assign": assign, "built": merged_step, "checkpoints": looks_again, "lane": False, "routing": False}}

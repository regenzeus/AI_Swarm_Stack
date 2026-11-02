"""The planner (SWM-91): splits an approved idea into tasks with dependencies, so that parallel builders can take the
pieces that do not depend on each other. ops/builds.py calls split() when the owner taps Build it; the tasks become
Ledger artifacts of kind task (images/swarm/ledger.py plan()).

An idea whose files lie in one area is one task, without a model call. Ideas that span areas go to the model, which
answers JSON; anything it gets wrong (no files, a dependency on a later task, too many tasks) falls back to one task.
An area is images/<x>/ or config/<x>/, else the first folder; tests/, requirements/ and docs/ go with the code.
"""
import json
import textcap as TC                              # visible caps (AGENTS.md, truncation)
import re
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md

FOLLOW = ("tests/", "requirements/", "docs/", "AGENTS.md", "CLAUDE.md", "README.md")
MAX_TASKS = 5
REQ_ID = re.compile(r"\b[A-Z]{2,3}-\d{2,3}\b")

PROMPT = P.text("planner", "PLAN")


def area(path):
    p = str(path).strip("/")
    if p.startswith(FOLLOW):
        return None
    parts = p.split("/")
    if parts[0] in ("images", "config") and len(parts) > 2:
        return "/".join(parts[:2])
    return parts[0] if len(parts) > 1 else "."


def areas(files):
    return sorted({a for a in (area(f) for f in files or []) if a})


def one(idea, files):
    return [{"title": TC.cut(idea["title"], 120), "body": idea.get("body") or idea["title"], "files": list(files),  # cap: untrusted
             "depends_on": [], "requirements": sorted(set(REQ_ID.findall(f"{idea['title']} {idea.get('body') or ''}")))}]


def valid(tasks):
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= MAX_TASKS:
        return None
    out = []
    for n, t in enumerate(tasks):
        if not isinstance(t, dict) or not str(t.get("title") or "").strip() or not t.get("files"):
            return None
        deps = [d for d in t.get("depends_on") or [] if isinstance(d, int)]
        if any(not 0 <= d < n for d in deps):
            return None
        out.append({"title": TC.cut(str(t["title"]).strip(), 120), "body": TC.cut(str(t.get("body") or t["title"]).strip(), 4000),  # cap: untrusted
                    "files": TC.first([str(f) for f in t["files"] if str(f).strip()], 30, "files of a task"), "depends_on": sorted(set(deps)),  # cap: untrusted
                    "requirements": TC.first([str(x) for x in t.get("requirements") or [] if REQ_ID.fullmatch(str(x))], 20, "requirements of a task")})  # cap: untrusted
    seen = {}                                       # the same file in two tasks: the later one waits for the earlier
    for n, t in enumerate(out):
        for f in t["files"]:
            if f in seen and seen[f] not in t["depends_on"]:
                t["depends_on"] = sorted(set(t["depends_on"]) | {seen[f]})
            seen[f] = n
    return out


def split(idea, ask=None, context=""):
    """-> [{title, body, files, depends_on, requirements}] and how it was decided ("one area", "model", "fallback: ...")."""
    plan = idea.get("plan") or {}
    files = [str(f) for f in plan.get("files") or []]
    if len(areas(files)) <= 1 or ask is None:
        return one(idea, files), "one area" if len(areas(files)) <= 1 else "no planner model"
    prompt = PROMPT.format(max=MAX_TASKS, id=idea["id"], title=idea["title"], body=TC.cut((idea.get("body") or ""), 4000),  # cap: prompt
                           files=", ".join(files) or "none", context=TC.cut(context, 6000))  # cap: prompt
    P.record(prompt)                                  # MEM-11: the run records the prompt's version
    try:
        raw = ask(prompt)
        m = re.search(r"\{.*\}", raw or "", re.S)
        tasks = valid(json.loads(m[0]).get("tasks")) if m else None
    except Exception as e:                          # the planner never stops a build: it falls back to one task
        return one(idea, files), f"fallback: {type(e).__name__}: {str(e)}"
    if not tasks:
        return one(idea, files), "fallback: the plan was not usable"
    return tasks, "model"

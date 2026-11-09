# A part of builds.py (PLT-25): the second pair of eyes: every build reviewed by the other engine. It runs in builds.py's namespace where it stood (_part); not a module of its own.
# ---------- the second pair of eyes: every build is reviewed by the other engine ----------
REVIEW_PROMPT = P.text("builder", "REVIEW")


LENSES = {        # SWM-95: two reviewers, each with its own lens and a fresh context, neither the builder's engine
    "requirements": "Your lens: requirements and correctness. The build names these requirements: {reqs}. Does the change make "
                    "each of them true (read its statement in requirements/*.yaml), and do its tests show it? Does it do what the "
                    "assignment asks, is it correct, and does anything in the blast radius above break (callers, tests)?",
    "security": "Your lens: security and data flow, nothing else. Look for secrets or tokens in code, logs or prompts; injection "
                "(shell, SQL, path, prompt); authentication, permission or approval checks weakened or skipped; new network "
                "exposure or egress; private data reaching a tool that can send it out (fetch, browser, phone, mail); unsafe "
                "defaults. An empty findings list with verdict approve is the right answer when there is none.",
    "conventions": "Your lens: does this change do things the way this repository does them, nothing else. The repository's wiki above and its own "
                   "AGENTS.md, CLAUDE.md or CONTRIBUTING say how: style, naming, where tests, docs and requirements live, and what a change must keep "
                   "current. Name a rule it breaks with where the rule stands. Taste is no finding. An empty findings list with verdict approve is "
                   "the right answer when it fits.",
}
BUILD_LENSES = ("requirements", "security")           # a build's own review; a change's reviewers add conventions (CHG-07)
WORST = {"block": 3, "changes": 2, "approve": 1}


def reviewer_for(engine):
    """The other engine reviews: ChatGPT builds by Claude Code (when connected), Claude builds by ChatGPT."""
    return "hermes" if (engine or "hermes") == "claude" or not claude_ready() else "claude"


def parse_review(text, engine):
    try:
        r = json.loads(re.search(r"\{.*\}", text or "", re.S).group(0))
    except (AttributeError, ValueError):
        return {"engine": engine, "error": "the reviewer gave no readable verdict", "at": M.now().isoformat(timespec="seconds")}
    verdict = r.get("verdict") if r.get("verdict") in ("approve", "changes", "block") else "changes"
    findings = [{"severity": f.get("severity") if f.get("severity") in ("high", "medium", "low") else "medium",
                 "file": TC.cut(str(f.get("file", "")), 200), "line": int(f.get("line") or 0) if str(f.get("line") or 0).isdigit() else 0,  # cap: untrusted
                 "issue": cut(f.get("issue", ""), 4000), "fix": cut(f.get("fix", ""), 4000)}  # cap: untrusted
                for f in TC.first(r.get("findings") or [], 20, "review findings") if isinstance(f, dict) and f.get("issue")]  # cap: untrusted
    return {"engine": engine, "verdict": verdict, "summary": cut(r.get("summary", ""), 4000), "findings": findings,  # cap: untrusted
            "at": M.now().isoformat(timespec="seconds")}


LIMITED = re.compile(r"usage limit|hit your limit|429|too many requests|rate limit", re.I)


def review_with(engine, b, path, diff, checks_ok, lens="requirements", slot=None, context="", reqs=()):
    fill = dict(repo=b["repo"], id=b["id"], title=b["title"], description=TC.cut(b["description"], 4000),  # cap: prompt
                checks="passed" if checks_ok else "FAILED", context=TC.cut(context, 9000 if lens == "conventions" else 5000),  # cap: prompt (the conventions lens reads the card and the wiki)
                lens=LENSES[lens].format(reqs=", ".join(reqs) or "none (say so if the change needs one)"))
    if engine == "claude":
        (path / ".git" / f"BUILD_REVIEW.{lens}.diff").write_text(TC.cut(diff, 400000))  # cap: prompt
        prompt = REVIEW_PROMPT.format(where=f"in the file .git/BUILD_REVIEW.{lens}.diff (read it; you may read any file of the repo for context; change nothing)", **fill)
        P.record(prompt)                                  # MEM-11: the run records the prompt's version
        p = subprocess.run(["docker", "exec", "-u", "hermes", *MP.claude_args(), "-w", f"/work/{place(b['repo'], slot)}", *RTM.env_args(),
                            "-e", "AISTACK_AGENT=claude-review", "-e", f"AISTACK_TITLE=Review of build #{b['id']} ({lens})", BUILDER,
                            "timeout", "900", "claude", "-p", prompt, "--output-format", "json", "--allowedTools", "Read,Grep,Glob",
                            "--disallowedTools", "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch", "--settings", "/config/claude-hooks/claude-runtime-settings.json"],
                           capture_output=True, text=True, timeout=960, env={**os.environ})
        out = claude_text(p.stdout)
        if re.search(r"usage limit|hit your limit", out, re.I):
            raise RuntimeError("Claude usage limit")
    else:
        prompt = REVIEW_PROMPT.format(where="below.\n\n```diff\n" + TC.cut(diff, 60000) + "\n```", **fill)  # cap: prompt
        P.record(prompt)                                  # MEM-11: the run records the prompt's version
        out = M.ask_text(prompt, os.environ["VK_BUILDER"], timeout=600)
    return parse_review(out, engine)


def one_review(engine, b, path, diff, checks_ok, lens, slot, context, reqs):
    """One lens. When the other engine is at its usage limit, the builder's own engine reviews instead (marked
    same_engine), so the build is not left without that look until the limit resets."""
    try:
        result = review_with(engine, b, path, diff, checks_ok, lens, slot, context, reqs)
    except Exception as e:
        other = "hermes" if engine == "claude" else "claude"
        result = {"engine": engine, "error": f"review not done: {str(e)}", "at": M.now().isoformat(timespec="seconds")}
        if LIMITED.search(str(e)) and (other == "hermes" or claude_ready()):
            try:
                result = review_with(other, b, path, diff, checks_ok, lens, slot, context, reqs)
                result["same_engine"] = other == (b["engine"] or "hermes")
                result["note"] = f"{ENGINES[engine]} was at its usage limit, so {ENGINES[other]} reviewed instead."
            except Exception as e2:
                result["error"] += f"; fallback {ENGINES[other]}: {str(e2)}"
    result["lens"] = lens
    return result


def combine(reviews):
    """The reviews as one verdict for the page and Approve: the worst one wins. A lens that failed is a look nobody took,
    so what the others approved reads "incomplete", never "approve" (QA-26), and `missing` names it."""
    done = [r for r in reviews if r.get("verdict")]
    if not done:
        return {"engine": reviews[0].get("engine") if reviews else None, "error": "; ".join(r.get("error", "") for r in reviews),
                "reviews": reviews, "at": M.now().isoformat(timespec="seconds")}
    worst = max(done, key=lambda r: WORST[r["verdict"]])
    missing = [r["lens"] for r in reviews if not r.get("verdict")]
    return {"engine": worst["engine"], "verdict": "incomplete" if missing and worst["verdict"] == "approve" else worst["verdict"],
            "summary": " ".join(f"[{r['lens']}] {r.get('summary', '')}" for r in done),
            "findings": TC.first([{**f, "lens": r["lens"]} for r in done for f in r.get("findings") or []], 30, "findings of all lenses"),  # cap: untrusted
            "same_engine": any(r.get("same_engine") for r in done), "note": " ".join(r["note"] for r in done if r.get("note")),
            "reviews": reviews, "missing": missing, "at": M.now().isoformat(timespec="seconds")}


def review_open(rv):
    """QA-26: a review that is still going, or where a lens or all of them failed: no look was had, so it is not "ready"."""
    return bool(rv) and bool(rv.get("pending") or rv.get("missing") or (rv.get("error") and not rv.get("verdict")))


def agent_gate(b, files, send=None):
    """SWM-70: a build that changes what defines an agent (its card, its key's grants, a Hermes profile, the builder's
    own code) needs a linked agent change whose experiment passed for its current version. -> None, or why not."""
    hit = sorted({f for f in files if f.startswith(AGENT_FILES)})
    if not hit:
        return None
    send = send or swarm
    a = send("get", {"id": b["idea"]}) if b["idea"] else None
    if a and a.get("kind") == "agent_change" and a.get("state") in ("ready", "active"):
        ex = (send("experiments", {"id": b["idea"]}) or [None])[0]
        if ex and ex.get("passed") and ex.get("version") == a.get("version"):
            return None
        return (f"agent change #{b['idea']} has no passed experiment for its version {a.get('version')} (SWM-18), and this build "
                f"changes {', '.join(hit)}")
    return (f"it changes {', '.join(hit)}, which define agents, without a linked agent change that passed its experiment "
            "(SWM-70). Deploy it only if you mean to change an agent by hand: approve with your reason.")


def ai_review(c, b, path, diff, checks_ok, slot=None, context="", reqs=(), files=()):
    """Two reviewers of the other engine, each with one lens and its own fresh context (SWM-95), in parallel, and the
    agents rule (SWM-70) when the build changes what defines an agent; each verdict is evidence on the build's idea. A
    block stops the deploy until changes or the owner's override."""
    engine = reviewer_for(b["engine"])
    put(c, b["id"], ai_review=json.dumps({"engine": engine, "pending": True, "lenses": list(BUILD_LENSES)}))
    ref = RTM.ref()

    def look(lens):
        RTM.set_ref(ref)                                  # the reviews show under the build's run (the ref is per thread)
        return one_review(engine, b, path, diff, checks_ok, lens, slot, context, reqs)
    with ThreadPoolExecutor(len(BUILD_LENSES)) as ex:
        reviews = list(ex.map(look, BUILD_LENSES))
    why = agent_gate(b, files)
    if why:
        reviews.append({"lens": "agents", "engine": "rule", "verdict": "block", "summary": why, "at": M.now().isoformat(timespec="seconds"),
                        "findings": [{"severity": "high", "file": f, "line": 0, "issue": "defines an agent (SWM-70)",
                                      "fix": "link the agent change that passed its experiment, or approve with your reason"}
                                     for f in files if f.startswith(AGENT_FILES)][:10]})  # cap: top
    result = combine(reviews)
    put(c, b["id"], ai_review=json.dumps(result))
    if b["idea"]:
        for r in reviews:
            if r.get("verdict"):
                swarm("evidence", {"idem": f"review:{b['id']}:{b['head'] or ''}:{r['lens']}:{r['at']}", "id": b["idea"],
                                   "text": f"review of build #{b['id']} ({r['lens']} lens, {ENGINES.get(r['engine'], 'rule')}): {r['verdict']}. {r.get('summary', '')}",
                                   "ref": f"build:{b['id']}"})
    if result.get("verdict") in ("changes", "block"):
        M.event("build", "", f"Build #{b['id']}: the AI review says {'do not deploy' if result['verdict'] == 'block' else 'improve first'} "
                f"({len(result['findings'])} findings)", push=result["verdict"] == "block", title="Builder")
    return result

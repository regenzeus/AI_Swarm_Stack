"""Self-improvement loop: the stack looks at its own signals once a week and proposes small builds (ops/missions.py sets
M to itself, routes the proposal_* requests here and runs worker() in a thread).

  signals   -> failed mission runs, failed jobs (systemd), error events, failed or rolled-back builds, red CI, open items
               of the latest review (docs/REVIEW-*.md), newer releases of pinned components (ops/upgrade_check.py)
  propose   -> one model call (subscription, key vk-review) turns them into at most MAX small, concrete ideas, written to
               the swarm's Ledger (ops/swarm_client.propose): a known idea gets new evidence instead of a copy
  decide    -> the owner taps "Build it" (the idea becomes a normal builder assignment, so review and tap-to-deploy still
               follow) or "Dismiss" (with an optional reason, which reaches the agent that proposed it as a lesson)
Nothing here changes code or starts a build by itself.
"""
import datetime as dt, json, os, re, subprocess, traceback
from pathlib import Path

import swarm_client as SW
from textcap import limit                    # visible caps and input limits (AGENTS.md, truncation)
import textcap as TC
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md
import deployment as DEPLOY                        # this deployment's hosts and paths (config/deployment.env)

M = B = None
STACK = Path(DEPLOY.STACK_DIR)
EVERY = dt.timedelta(days=7)
# limit: drops, ideas past 5 a self-review; its prompt names the limit and the log says
MAX = 5
STATE = Path("/srv/ai/missions/builds/improve.json")

PROMPT = P.text("self-review", "REVIEW")


def table(c):
    c.execute("""create table if not exists proposals (id integer primary key, created text, title text, why text, signal text,
                 area text, size text, description text, status text, build_id integer, reason text, updated text)""")
    cols = {r[1] for r in c.execute("pragma table_info(proposals)")}
    if "source" not in cols:                              # which agent proposed it
        c.execute("alter table proposals add column source text")
    if "covers" not in cols:                              # JSON list: the health issues / detector kinds it is the fix for
        c.execute("alter table proposals add column covers text")


def now():
    return M.now().isoformat(timespec="seconds")


def last_scan():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_scan(**kw):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps({**last_scan(), **kw}))
    tmp.rename(STATE)


# ---------- signals ----------
def since(days):
    return (M.now() - dt.timedelta(days=days)).isoformat(timespec="seconds")


def signals(c, unread=None):
    """The week's signals. `unread` collects, as sentences, what could not be read (QA-26): a silent gap reads as a quiet week."""
    unread = [] if unread is None else unread
    out = []
    runs =c.execute("select slug, started, summary from runs where status='failed' and started >= ? order by started desc limit 15",  # cap: list (the self-review's sample: the newest 15)
                     (since(7),)).fetchall()
    for r in runs:
        if not M.paused(r["summary"] or ""):                  # usage-limit pauses are normal, not a defect
            out.append(f"failed mission run {r['slug']} {r['started'][:16]}: {TC.cut((r['summary'] or ''), 200)}")  # cap: prompt
    for u in M.sh("systemctl", "--user", "list-units", "--failed", "--plain", "--no-legend").split():
        if u.endswith((".service", ".timer")):
            out.append(f"failed systemd job: {u}")
    try:
        lines = (M.PUBLIC / "events.jsonl").read_text().splitlines()[-2000:]  # cap: parse (the newest 2,000 events are searched for signals)
    except Exception:
        lines = []
    seen = set()
    for ln in reversed(lines):
        try:
            e = json.loads(ln)
        except Exception:
            continue
        if e.get("ts", "") < since(7) or e.get("kind") not in ("error", "run_failed") and "failed" not in e.get("text", "").lower():
            continue
        key = re.sub(r"\d+", "#", e.get("text", ""))[:120]  # cap: id
        if key not in seen and not M.paused(e.get("text", "")):
            seen.add(key)
            out.append(f"event {e.get('ts', '')[:16]} {e.get('kind')}: {TC.cut(e.get('text', ''), 200)}")  # cap: prompt
    for b in c.execute("select id, title, status, error from builds where status in ('failed','rolled_back') and updated >= ?", (since(30),)):
        out.append(f"build #{b['id']} {b['status']}: {b['title']} ({TC.cut((b['error'] or ''), 160)})")  # cap: prompt
    try:
        for ci in M.stack_info().get("ci", []):
            if ci.get("status") == "failure":
                out.append(f"CI failing on {ci['repo']} at {ci['sha']}")
            elif ci.get("status") == "unknown":              # missions.stack_info: Forgejo did not answer for it
                unread.append(f"CI's status of {ci['repo']} could not be read, so whether it is failing is not known")
    except Exception as e:
        unread.append(f"CI's status could not be read ({type(e).__name__}: {e}), so whether CI is failing is not known")
    reviews =sorted((STACK / "docs").glob("REVIEW-*.md"))
    if reviews:
        text = reviews[-1].read_text()
        for head in ("Half-built or not thought to the end", "Technical debt", "Recommended next steps"):
            m = re.search(rf"^## {re.escape(head)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
            if m:
                out.append(f"review {reviews[-1].name}, {head}:\n{TC.cut(m[1].strip(), 2500)}")  # cap: prompt
    try:
        p = subprocess.run(["python3", str(STACK / "ops/upgrade_check.py")], capture_output=True, text=True, timeout=180)
        newer = [ln for ln in p.stdout.splitlines() if re.search(r"newer|->|→", ln)]
        if newer:
            out.append("newer releases of pinned components:\n" + "\n".join(TC.more(newer, 20, "more")))  # cap: prompt
        if p.returncode:
            unread.append(f"The upgrade check ended with exit code {p.returncode}, so which pinned components are out of date is not fully known")
    except Exception as e:
        unread.append(f"The upgrade check could not run ({type(e).__name__}: {e}), so which pinned components are out of date is not known")
    return out


# ---------- proposing ----------
def known(c):
    """What is already open or decided in the Ledger, and recent builds: the model must not repeat them."""
    rows = [SW.lessons_text("self-review"), SW.known()]
    rows += [f"- build ({b['status']}): {b['title']}" for b in c.execute("select title, status from builds where created >= ? order by id desc limit 40",  # cap: list (the self-review's sample: the newest 40)
                                                                        (since(60),))]
    return "\n".join(x for x in rows if x) or "(nothing yet)"


def scan(c, trigger="weekly"):
    """One pass: signals -> ideas in the Ledger. Returns the number of new ideas (or raises on a model error)."""
    unread = []
    sig = signals(c, unread)
    save_scan(last=now(), signals=len(sig), trigger=trigger, unknown=unread)     # crew.job_unknown: on the self-review's card
    if not sig:
        save_scan(result="no signals: nothing to improve this week" + (f", but {len(unread)} could not be read" if unread else ""), new=0)
        return 0
    amap = re.search(r"## Repository map\n(.*?)\n## ", (STACK / "AGENTS.md").read_text(), re.S)
    prompt = PROMPT.format(max=MAX, map=amap[1].strip() if amap else "", signals=TC.cut("\n".join(f"- {s}" for s in sig), 14000),  # cap: prompt
                           known=TC.cut(known(c), 4000))  # cap: prompt
    P.record(prompt)                                  # MEM-11: the run records the prompt's version
    d = M.ask_json(prompt, os.environ["VK_REVIEW"], timeout=600)
    new, refined = SW.propose("self-review", TC.first(d.get("proposals") or [], MAX, "proposals"), "weekly self-review")  # cap: untrusted (its prompt names the limit)
    save_scan(result=f"{new} new idea{'s' if new != 1 else ''} from {len(sig)} signals" + (f", {refined} known ones refined" if refined else ""), new=new)
    if new:
        M.event("build", "", f"The stack proposes {new} improvement{'s' if new > 1 else ''}: review them in Build", push=True, title="Improvements")
    return new


def handle(req, c):
    """The owner's decisions on ideas from the app (ids are Ledger artifact ids since the switch-over, DEC-22)."""
    a = req["action"]
    if a == "improve_scan":
        save_scan(requested=now())
        return {"scanning": True}
    if a not in ("proposal_accept", "proposal_dismiss"):
        raise ValueError("unknown proposal action")
    try:
        p = SW.get(int(req.get("id", 0)))
    except (TypeError, ValueError):
        raise ValueError("no open idea with that id")
    if p.get("kind") == "agent_change" and p.get("state") in ("open", "ready"):
        by = str(req.get("by") or "app")
        if a == "proposal_dismiss":
            SW.dismiss(p["id"], limit(str(req.get("reason", "")).strip(), 2000, "the reason"), by=by)
            return {"dismissed": True}
        return {"build": change_accept(p, req, c, by)}
    if p.get("kind") != "idea" or p.get("state") not in ("draft", "open", "ready", "blocked"):
        raise ValueError("no open idea with that id")
    by = str(req.get("by") or "app")
    if a == "proposal_accept":
        sig = next((e["text"] for e in p.get("evidence") or []), "")
        r = B.handle({"action": "build_assign", "repo": "ai-stack", "title": p["title"], "engine": req.get("engine") or "hermes",
                      "description": f"{p['body']}\n\nFrom the stack's idea #{p['id']} ({p['owner']}). Signal: {sig}",
                      "idea": p["id"], "files": (p.get("plan") or {}).get("files") or []}, c)     # the planner splits it (SWM-91)
        SW.accept(p["id"], r["id"], by=by)
        return {"build": r["id"]}
    SW.dismiss(p["id"], limit(str(req.get("reason", "")).strip(), 2000, "the reason"), by=by)
    return {"dismissed": True}


def change_accept(p, req, c, by):
    """Build it on an agent change (SWM-18, SWM-70): only after its experiment passed for its current version; the build
    edits the agent's card in config/agents.yaml exactly as the change says. -> the build id."""
    ex = (SW.call("experiments", {"id": p["id"]}, "system").get("result") or [None])[0]
    if p["state"] != "ready" or not ex or not ex.get("passed") or ex.get("version") != p["version"]:
        raise ValueError("this agent change has not passed its experiment yet: it ships only after its replay shows no score "
                         "dropping and its target rising" + (f" (last: {ex['why']})" if ex else ""))
    plan = p.get("plan") or {}
    desc = (f"Apply agent change #{p['id']} to the card of the agent '{plan.get('agent')}' in config/agents.yaml, exactly as "
            f"written, and nothing else:\n{json.dumps(plan.get('change'), indent=1, ensure_ascii=False)}\n\n"
            "instructions {add: [...]} appends these strings to the card's instructions list (create it after 'autonomy'); "
            "{remove: [...]} removes those; a list replaces it. tools, model or harness replace the card's value; a model or "
            "tools change also changes that agent's key row in ops/keys.sh so the registry check passes.\n\n"
            f"Why: {p['body']}\nExperiment {ex['id']}: {ex['why']}.\nRequirements: SWM-18, SWM-70")
    r = B.handle({"action": "build_assign", "repo": "ai-stack", "title": p["title"][:100],  # cap: id
                  "engine": req.get("engine") or ("claude" if B.claude_ready() else "hermes"),
                  "description": desc, "idea": None, "files": ["config/agents.yaml"]}, c)
    c.execute("update builds set idea=? where id=?", (p["id"], r["id"]))            # linked, but not split by the planner
    c.commit()
    SW.accept(p["id"], r["id"], by=by)
    return r["id"]


def due(s):
    if s.get("retry_at"):
        return "retry" if s["retry_at"] <= now() else None
    if s.get("requested") and s["requested"] > s.get("last", ""):
        return "on request"
    last = s.get("last")
    if not last:                     # first start: wait a week (or a request) instead of scanning on every new install
        save_scan(last=now(), result="first scan in a week, or tap Look for improvements")
        return None
    return "weekly" if M.now() - dt.datetime.fromisoformat(last) >= EVERY else None


def worker():
    c = M.db()
    while not M.stop.is_set():
        try:
            why = due(last_scan())
            if why and SW.paused("self-review"):          # SWM-26: paused by the owner: wait, do not scan
                why = None
            if why:
                try:
                    scan(c, why)
                    save_scan(retry_at=None)
                except Exception as e:
                    text = f"{type(e).__name__}: {e}"
                    pause = M.paused(text)          # usage limit: try again in an hour; any other error: tomorrow
                    retry = (M.now() + (dt.timedelta(hours=1) if pause else dt.timedelta(days=1))).isoformat(timespec="seconds")
                    save_scan(result="waiting for ChatGPT (usage limit)" if pause else f"scan failed: {text}", retry_at=retry)
                    if not pause:
                        M.log(traceback.format_exc())
        except Exception:
            M.log(traceback.format_exc())
        M.stop.wait(60)


def state(c):
    return {"improve": last_scan()}           # the ideas themselves are S.swarm.board (ops/swarm_client.publish)

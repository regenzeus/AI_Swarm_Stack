"""The Checker (crew job crew-checker, hourly, no model): ground truth decides whether a shipped idea worked (SWM-07,
SWM-44 to SWM-47), the owner's autonomy rules start ideas he allowed (SWM-42), a failing agent stops itself (SWM-71),
and the swarm's own failure signals reach the health board (SWM-80).

Success checks, typed (images/swarm/ledger.py CHECKS); "since" is when the idea entered checking:
  health_issue_absent {keys|key|kind, days=7}   the health issue (or every issue of that detector kind) stays off the
                                                board for `days`; back after a 2-hour grace -> reopened
  log_count {container, pattern, max=0, hours=24}  the pattern appears at most `max` times in the container's logs
  test_passes {nodeid}                          the test exists and CI is green on the current main
  ci_green {repo=ai-stack}                      CI is green on the current main
  smoke_ok                                      a deploy after shipping passed its smoke test
  metric {name, op, value, days=7}              health_alerts (open alerts now) or failed_runs (failed mission runs
                                                since shipping) holds the comparison for `days`
  owner_confirms {why}                          the owner tapped "It works" (only when no code can check it)
A check that holds for its window moves the idea to done; one that fails moves it back to open with the evidence. A
done idea whose check fails again within 30 days reopens (a regression) and climbs the ranking. Only the Checker
moves to done: no agent certifies its own work (SWM-46).
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

import swarm_client as SW
import deployment as DEPLOY                        # this deployment's hosts and paths (config/deployment.env)

M = None                                       # ops/missions.py, set by crew.py
STACK = Path(os.environ.get("AISTACK", DEPLOY.STACK_DIR))
PUBLIC = Path("/srv/ai/missions/public")
DEPLOYS = Path("/srv/ai/state/deploys.jsonl")
GRACE = 2 * 3600                               # the health board needs a little while to forget a fixed issue
REGRESSION_DAYS = 30
WAIT_CI = 2 * 86400
REFUSALS_ALERT = 10                            # refused writes per agent and day before it is a health signal
REFUSALS_QUIET = 2 * 3600                      # ... unless none came for 2 h: its cause stopped (FND-93: a fixed cause
                                               # kept the Checker failing for the rest of the day)
PROPOSERS = ("doctor", "maintainability", "tests", "self-review")
OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "==": lambda a, b: a == b}
METRICS = ("health_alerts", "failed_runs")


# ---------------------------------------------------------------- facts from the running stack
class Facts:
    """What the checks read, gathered once per run (and replaced by fakes in the tests)."""

    def __init__(self):
        try:
            self.state = json.loads((PUBLIC / "state.json").read_text())
        except (OSError, ValueError):
            self.state = {}
        issues = [i for it in (self.state.get("health") or {}).get("items") or [] for i in it.get("issues") or []]
        self.issue_keys = {i.get("key") for i in issues}
        self.issue_kinds = {i.get("kind") for i in issues}
        self.alerts = sum(1 for i in issues if i.get("severity") == "alert")
        self.ci = {c["repo"]: c for c in (self.state.get("system") or {}).get("ci") or []}
        self.head = self._git("rev-parse", "--short=7", "HEAD")
        self.deploys = []
        try:
            self.deploys = [json.loads(x) for x in DEPLOYS.read_text().splitlines() if x.strip()]
        except (OSError, ValueError):
            pass
        self._tests = None

    def _git(self, *a):
        try:
            p = subprocess.run(["git", *a], cwd=STACK, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return ""                                  # no live checkout here (CI, tests): nothing is green
        return p.stdout.strip()

    def tests(self):
        if self._tests is None:
            import req
            self._tests = req.tests_in(STACK)
        return self._tests

    def log_count(self, container, pattern, since):
        """Lines matching pattern in a container's logs, or in a host unit's journal ("unit:missions"). None: no logs."""
        if str(container).startswith("unit:"):
            cmd = ["journalctl", "--user", "-u", container[5:], "--since", f"@{int(since)}", "-o", "cat", "--no-pager"]
        else:
            cmd = ["docker", "logs", "--since", str(int(since)), container]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        if p.returncode:
            return None
        return len(re.findall(pattern, p.stdout + p.stderr, re.M))

    def containers(self):
        """What a log_count may read: the containers, and the host's user services as unit:<name>."""
        out = set()
        for cmd, unit in ((["docker", "ps", "-a", "--format", "{{.Names}}"], False),
                          (["systemctl", "--user", "list-units", "--all", "--type=service", "--no-legend", "--plain"], True)):
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.SubprocessError):
                continue
            for line in p.stdout.splitlines():
                name = line.split()[0] if line.split() else ""
                if name:
                    out.add("unit:" + name.removesuffix(".service") if unit else name)
        return out

    def failed_runs(self, since):
        try:
            import sqlite3
            c = sqlite3.connect("file:/srv/ai/missions/missions.sqlite?mode=ro", uri=True)
            iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(since))
            return c.execute("select count(*) from runs where status='failed' and started>=?", (iso,)).fetchone()[0]
        except Exception:
            return None


# ---------------------------------------------------------------- one check
def tell(send, to, text, artifact_id=None, key=""):
    """The Checker's news on the Board (an inform, never an instruction)."""
    send("send", {"idem": f"checker:{key or text[:40]}", "to": to, "act": "inform", "text": text, "artifact_id": artifact_id}, "checker")  # cap: id


def ask(send, a, text):
    """A tracked request to the agent that owns the idea; it completes when that agent works on it (SWM-12)."""
    if a.get("owner") and a["owner"] not in ("owner", "system"):
        send("send", {"idem": f"checker:ask:{a['id']}:{a['version']}", "to": [f"agent:{a['owner']}"], "act": "request", "text": text,
                      "artifact_id": a["id"], "expires_h": 7 * 24}, "checker")
    tell(send, ["room:health"], f"Reopened #{a['id']} {a['title']}: {text.split(': ', 1)[-1]}", a["id"], f"reopened:{a['id']}:{a['version']}")


def validate(check, facts):
    """SWM-45: what a check names must exist before it counts. -> list of problems."""
    t = (check or {}).get("type")
    out = []
    if t == "health_issue_absent" and not (check.get("keys") or check.get("key") or check.get("kind")):
        out.append("health_issue_absent needs keys, key or kind")
    if t == "log_count":
        if not check.get("pattern"):
            out.append("log_count needs a pattern")
        if check.get("container") not in facts.containers():
            out.append(f"no container {check.get('container')!r}")
    if t == "test_passes" and check.get("nodeid") not in facts.tests():
        out.append(f"no test {check.get('nodeid')!r}")
    if t == "metric" and (check.get("name") not in METRICS or check.get("op") not in OPS):
        out.append(f"metric needs a name of {METRICS} and an op of {sorted(OPS)}")
    if t == "owner_confirms" and not str(check.get("why") or "").strip():
        out.append("owner_confirms needs why no other check can do it (SWM-44)")
    return out


def evaluate(a, facts, now=None):
    """-> ("pass" | "fail" | "wait", one sentence). `a` is the artifact as ledger.get returns it."""
    now = now or time.time()
    c, since = a.get("check") or {}, a.get("state_since") or now
    t, age = c.get("type"), now - since
    if t == "health_issue_absent":
        days = float(c.get("days") or 7)
        keys = set(c.get("keys") or ([c["key"]] if c.get("key") else []))
        back = sorted(keys & facts.issue_keys) + ([f"kind:{c['kind']}"] if c.get("kind") and c["kind"] in facts.issue_kinds else [])
        if back:
            return ("fail" if age > GRACE else "wait"), f"the health issue is on the board ({', '.join(back)})"
        if age >= days * 86400:
            return "pass", f"the health issue stayed away for {days:g} days"
        return "wait", f"the health issue is away: {age / 86400:.1f} of {days:g} days"
    if t == "log_count":
        n = facts.log_count(c.get("container"), c.get("pattern"), since)
        mx, hours = int(c.get("max") or 0), float(c.get("hours") or 24 * float(c.get("days") or 1))   # days counts too
        if n is None:
            return "wait", f"no logs from {c.get('container')}"
        if n > mx:
            return "fail", f"{n} log lines match {c.get('pattern')!r} since it shipped (at most {mx})"
        return ("pass" if age >= hours * 3600 else "wait"), f"{n} matching log lines in {age / 3600:.0f} of {hours:g} hours"
    if t in ("ci_green", "test_passes"):
        if t == "test_passes" and c.get("nodeid") not in facts.tests():
            return "fail", f"the test {c.get('nodeid')} does not exist"
        ci = facts.ci.get(c.get("repo") or "ai-stack") or {}
        if ci.get("status") == "success" and ci.get("sha") and facts.head.startswith(ci["sha"]):
            return "pass", f"CI is green on {ci['sha']}" + (f" with {c['nodeid']}" if t == "test_passes" else "")
        if ci.get("status") == "failure" and facts.head.startswith(ci.get("sha") or "-"):
            return "fail", f"CI failed on {ci['sha']}"
        return ("fail" if age > WAIT_CI else "wait"), f"CI is {ci.get('status') or 'unknown'} on {ci.get('sha') or '?'}"
    if t == "smoke_ok":
        after = [d for d in facts.deploys if d.get("ts", 0) >= since]
        if any(d.get("ok") for d in after):
            return "pass", "a deploy since it shipped passed the smoke test"
        if after:
            return "fail", "the deploys since it shipped failed"
        return "wait", "no deploy since it shipped"
    if t == "metric":
        val = facts.alerts if c.get("name") == "health_alerts" else facts.failed_runs(since)
        if val is None or c.get("op") not in OPS:
            return "wait", f"metric {c.get('name')} is not readable"
        if not OPS[c["op"]](val, float(c.get("value") or 0)):
            return "fail", f"{c['name']} is {val}, not {c['op']} {c.get('value')}"
        days = float(c.get("days") or 7)
        return ("pass" if age >= days * 86400 else "wait"), f"{c['name']} is {val} ({age / 86400:.1f} of {days:g} days)"
    if t == "owner_confirms":
        ok = any(e.get("origin") == "owner" and str(e.get("text", "")).startswith("confirmed") and e.get("ts", 0) >= since
                 for e in a.get("evidence") or [])
        return ("pass", "the owner confirmed it works") if ok else ("wait", "waits for your \"It works\"")
    return "wait", f"no check of a known type ({t})"


# ---------------------------------------------------------------- the run
def check_all(facts, now=None, send=None):
    """Checking -> done or open; done within 30 days -> open again on a regression. -> (done, reopened, waiting)."""
    send = send or SW.call
    now = now or time.time()
    done = reopened = 0
    progress = {}
    for a in (send("artifacts_in", {"states": ["checking"]}, "checker").get("result") or []):
        verdict, why = evaluate(a, facts, now)
        if verdict == "pass":
            r = send("transition", {"idem": f"check:{a['id']}:{a['version']}:done", "id": a["id"], "to": "done", "reason": why,
                                    "evidence": [{"text": f"checker: {why}", "ref": "crew:checker"}]}, "checker")
            done += bool(r.get("ok"))
            if r.get("ok"):
                tell(send, ["room:health"], f"Proved #{a['id']} {a['title']}: {why}.", a["id"], f"proved:{a['id']}")
        elif verdict == "fail":
            r = send("transition", {"idem": f"check:{a['id']}:{a['version']}:{int(now // 3600)}:open", "id": a["id"], "to": "open",
                                    "reason": f"its check failed: {why}", "evidence": [{"text": f"checker: {why}", "ref": "crew:checker"}]}, "checker")
            reopened += bool(r.get("ok"))
            if r.get("ok"):
                ask(send, a, f"Your idea #{a['id']} shipped but its success check failed: {why}. Refine it (new evidence or a new "
                             "plan), or mark it gone if the problem is elsewhere.")
        else:
            progress[str(a["id"])] = why
            tell(send, ["room:health"], f"Checking #{a['id']} {a['title']}: {why}.", a["id"], f"checking:{a['id']}:{a['version']}")
    for a in (send("artifacts_in", {"states": ["done"]}, "checker").get("result") or []):
        if now - (a.get("state_since") or now) > REGRESSION_DAYS * 86400 or (a.get("check") or {}).get("type") not in ("health_issue_absent", "log_count", "metric"):
            continue
        c = dict(a["check"], days=0, hours=0)                # a regression: the condition fails again, no new window
        verdict, why = evaluate({**a, "check": c, "state_since": a["state_since"] - GRACE - 1}, facts, now)
        if verdict == "fail":
            r = send("transition", {"idem": f"regress:{a['id']}:{int(now // 3600)}", "id": a["id"], "to": "open", "reason": f"regression: {why}",
                                    "evidence": [{"text": f"checker: regression, {why}", "ref": "crew:checker"}]}, "checker")
            reopened += bool(r.get("ok"))
            if r.get("ok"):
                ask(send, a, f"Your idea #{a['id']} was proved, but its problem is back: {why}. Look at it again.")
    send("expire", {}, "checker")                             # SWM-50: requests past their expiry are canceled
    SW._save("checker.json", {"progress": progress, "ts": now})
    return done, reopened, len(progress)


TEMPLATES = {    # the autonomy rules the owner can switch on in the app (SWM-42); each still needs his tap to deploy
    "doctor-small-fixes": {"kind": "idea", "owner_agent": "doctor", "title": "The Health doctor may start building its small fixes that have a health check",
                           "conditions": {"effort": ["small"], "check_types": ["health_issue_absent"], "max_per_day": 1}},
    "tests-new-tests": {"kind": "idea", "owner_agent": "tests", "title": "The test agent may start building new unit tests",
                        "conditions": {"effort": ["small"], "check_types": ["ci_green", "test_passes"], "max_per_day": 1}},
}


def autonomy(c, facts, send=None, assign=None):
    """For each enabled rule, the best open idea it covers starts building: open -> ready (the definition of ready
    applies) -> active, a build is assigned. Its deploy still waits for the owner's tap. -> ids started."""
    send = send or SW.call
    started = []
    for rule in send("rules", {}, "system").get("result") or []:
        actor = f"rule:{rule['id']}"
        board = (send("board", {"kind": "idea"}, "system").get("result") or {}).get("open") or []
        for idea in [x for x in board if x["owner"] == rule["owner_agent"] and x["state"] == "open"]:
            a = SW.get(idea["id"], send)
            if not a.get("check"):
                send("set_check", {"idem": f"check-for:{a['id']}", "key": a["key"], "title": a["title"], "check": SW.check_for(a)}, "system")
                a = SW.get(idea["id"], send)
            if validate(a["check"], facts):
                continue
            r = send("transition", {"idem": f"{actor}:{a['id']}:ready", "id": a["id"], "to": "ready", "reason": rule["title"]}, actor)
            if not r.get("ok"):
                continue                                      # not ready (or not covered): the next idea
            bid = (assign or _assign)(c, a)
            r = send("transition", {"idem": f"{actor}:{a['id']}:active", "id": a["id"], "to": "active",
                                    "reason": f"{rule['title']}: build #{bid}"}, actor)
            if not r.get("ok"):
                send("transition", {"idem": f"{actor}:{a['id']}:back", "id": a["id"], "to": "open", "reason": r.get("refused", "")}, "system")
                break
            send("ref", {"idem": f"{actor}:{a['id']}:ref", "id": a["id"], "system": "build", "ref": str(bid)}, "system")
            started.append(a["id"])
            tell(send, ["room:code"], f"Started build #{bid} for #{a['id']} {a['title']} under the owner's rule \"{rule['title']}\"; "
                                      "its deploy waits for his tap.", a["id"], f"auto:{a['id']}")
            if M:
                M.event("build", "", f"Build #{bid} started by itself under your rule \"{rule['title']}\": idea #{a['id']} {a['title']}. "
                                     "Its deploy still waits for your tap.", push=True, title="Autonomy")
            break                                             # one per rule and run
    return started


def _assign(c, a):
    import builds as B
    B.M = M
    sig = next((e["text"] for e in a.get("evidence") or []), "")
    r = B.handle({"action": "build_assign", "repo": "ai-stack", "title": a["title"], "engine": "hermes",
                  "description": f"{a['body']}\n\nFrom the stack's idea #{a['id']} ({a['owner']}), started by an autonomy rule. Signal: {sig}"}, c)
    return r["id"]


def self_pause(cards, history, send=None):
    """SWM-71: an agent that proposes and whose last 3 runs failed pauses itself (the owner resumes it). -> paused ids."""
    send = send or SW.call
    out = []
    for card in cards:
        if card["id"] not in PROPOSERS or not card.get("jobs"):
            continue
        runs = history(card["jobs"][0])[:3]
        if len(runs) == 3 and all(r.get("state") == "failed" for r in runs) and not SW.paused(card["id"]):
            r = send("pause", {"agent": card["id"], "on": True}, "system")
            if r.get("ok"):
                out.append(card["id"])
                SW.publish(send)                          # the runner's own pause list follows at once
                tell(send, ["room:ops"], f"{card['id']} failed its last 3 runs and paused itself; the owner resumes it on its page.",
                     None, f"paused:{card['id']}:{int(time.time() // 86400)}")
                if M:
                    M.event("health", "", f"{card['id']} failed 3 runs in a row and paused itself; resume it on its page when fixed",
                            push=True, title="Swarm")
    return out


# limit: stops, an agent refused this often by the Board's guards in 24 h pauses itself, with a note (SWM-71)
GUARD_TRIPS = 3            # SWM-71: messages refused by the Board's guards within 24 h before an agent pauses itself
EXPIRED_ALERT = 3          # SWM-80: requests to one agent that expired unanswered within 24 h
REFUSED_WAKES = 3          # SWM-80: wakes refused because the agent's daily budget was spent, within 24 h


def signals(send=None, now=None):
    """SWM-80: the swarm's own failure signals -> sentences (empty when healthy). An agent whose messages tripped the
    Board's guards GUARD_TRIPS times in 24 h is paused (SWM-71), once, with a note in #ops."""
    send, now = send or SW.call, now or time.time()
    r = send("stats", {}, "system")
    st = r.get("result") or {}
    out = []
    causes = st.get("refusal_causes_24h") or {}
    for actor, n in (st.get("refusals_24h") or {}).items():
        why = causes.get(actor) or []
        if n <= REFUSALS_ALERT or (why and now - max(w["last"] for w in why) > REFUSALS_QUIET):
            continue
        top = why[0] if why else None
        out.append(f"{actor} had {n} refused swarm writes in 24 h" + (f", {top['n']} of them {top['op']}: {top['reason']}" if top else ""))
    for actor, n in (st.get("guard_trips_24h") or {}).items():
        if n >= GUARD_TRIPS and not SW.paused(actor) and actor not in ("owner", "system", "checker"):
            if send("pause", {"agent": actor, "on": True}, "system").get("ok"):
                SW.publish(send)
                tell(send, ["room:ops"], f"{actor}'s messages tripped the Board's guards {n} times in 24 h (loops, floods or repeats); "
                     "it paused itself. The owner resumes it on its page.", None, f"guard-pause:{actor}:{int(now // 86400)}")
                out.append(f"{actor} tripped the Board's guards {n} times in 24 h and was paused")
    for agent, n in (st.get("expired_24h") or {}).items():
        if n >= EXPIRED_ALERT and agent != "owner":
            out.append(f"{n} requests to {agent} expired unanswered in 24 h")
    for agent, times in (SW._load("wakes.json", {}).get("_refused") or {}).items():
        n = sum(1 for t in times if now - t < 86400)
        # limit: paces, only raises a health alert (SWM-80)
        if n >= REFUSED_WAKES:
            out.append(f"{agent}'s wakes were refused {n} times in 24 h (its daily wake budget is spent; requests wait)")
    return out


WATCH_MIN = 3              # SWM-18: runs settled after a change shipped before its watch may call it worse
LIVE = {"avoids_declined": lambda c, n: 1 - c.get("declined", 0) / n, "avoids_duplicates": lambda c, n: 1 - c.get("duplicate", 0) / n,
        "keeps_proven": lambda c, n: c.get("proven", 0) / n, "valid": lambda c, n: 1 - c.get("_fc1", 0) / n}


def live_score(runs, target, lo, hi):
    """A target score from real runs between lo and hi (their labels), or None with too few settled runs."""
    rows = [r for r in runs if r.get("source") == "run" and lo <= r["ts"] < hi and r["label"] not in ("pending", "no_output")]
    if len(rows) < WATCH_MIN or target not in LIVE:
        return None, len(rows)
    cnt = {}
    for r in rows:
        cnt[r["label"]] = cnt.get(r["label"], 0) + 1
        cnt["_fc1"] = cnt.get("_fc1", 0) + (1 if str((r.get("failure") or {}).get("mode", "")).startswith("FM-1.1") else 0)
    return round(LIVE[target](cnt, len(rows)), 3), len(rows)


def watch_changes(send=None, now=None):
    """SWM-18: a shipped agent change is watched for 14 days on the agent's real runs. Worse than the 30 days before it
    shipped: reopened, with the one-step revert offered (a health signal). Held for 14 days: done. -> sentences."""
    send, now = send or SW.call, now or time.time()
    import evals
    LG = evals.LG                                          # images/swarm/ledger.py, the Ledger's constants
    out = []
    for a in send("agent_changes", {"states": ["checking"]}, "system").get("result") or []:
        plan, since = a.get("plan") or {}, a["state_since"]
        target = (plan.get("target") or {}).get("score")
        runs = send("replays", {"agent": plan.get("agent")}, "system").get("result") or []
        before, nb = live_score(runs, target, since - 30 * 86400, since)
        after, na = live_score(runs, target, since, now + 1)
        build = (a.get("builds") or [""])[-1]
        if before is not None and after is not None and after < before:
            why = f"watch: {target} of {plan.get('agent')} fell from {before:.2f} ({nb} runs before) to {after:.2f} ({na} runs since it shipped)"
            if send("transition", {"idem": f"watch:{a['id']}:{a['version']}", "id": a["id"], "to": "open", "reason": why,
                                   "evidence": [{"text": why, "ref": "watch"}]}, "checker").get("ok"):
                out.append(f"agent change #{a['id']} made {plan.get('agent')} worse ({target} {before:.2f} -> {after:.2f}): "
                           + (f"revert build #{build} in one tap on its build page" if build else "revert it"))
        elif now - since >= LG.WATCH_DAYS * 86400:
            note = (f"{target} {before:.2f} -> {after:.2f}" if before is not None and after is not None else
                    f"too few settled runs to compare ({nb} before, {na} since)")
            send("transition", {"idem": f"watch-done:{a['id']}:{a['version']}", "id": a["id"], "to": "done",
                                "reason": f"watched {LG.WATCH_DAYS} days without a drop: {note}"}, "checker")
    return out


def run(c):
    """The crew job. A fault the swarm shows is its finding, kept as `faults` and raised as an alert on its card
    (crew.checker_faults); the run fails only when the job itself breaks (FND-112: 25 runs counted failed for a fault
    they had found and reported)."""
    import crew as C
    import observe as O
    import registry
    facts = Facts()
    done, reopened, waiting = check_all(facts)
    started = autonomy(c, facts)
    paused = self_pause(registry.load().get("agents") or [], lambda unit: O.crew_history(unit))
    bad = signals() + watch_changes()
    SW.publish()
    res = (f"{done} proven, {reopened} reopened, {waiting} still being checked" + (f" · started {len(started)} by your rules" if started else "")
           + (f" · paused {', '.join(paused)} (3 failed runs)" if paused else "") + (f" · {len(bad)} fault{'s' if len(bad) != 1 else ''} in the swarm" if bad else ""))
    C.save("checker", result=res, last=time.time(), faults=bad)
    return done + reopened

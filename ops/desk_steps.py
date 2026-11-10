"""The Topic Desk's steps under the Conductor (TSK-21, TSK-22): a briefing's and an alert's plan, and the desk's collect,
write, alert and delivery steps, as step kinds (TSK-36).

Loaded by ops/conductor.py (DOMAINS), run by its worker in the runner; ops/tasks.py takes the plans from here. The desk
itself is ops/desk.sh and its container (images/desk). A failing topic wiki never fails a delivery.
"""
import datetime as dt
import json
import os
import re
import subprocess

import textcap as TC

M = None                                          # ops/missions.py (set by its main)


# ---------- a briefing as a plan (TSK-22): collect, research per key question, write, deliver ----------
RESEARCH = "Research the run's window"            # TSK-49: its dates are the occurrence's, in every step's prompt


def briefing_plan(t, topic):
    """The plan of every occurrence of a briefing task, from its topic (topics/<slug>/TOPIC.md). The research step names
    no number of days: each occurrence has its own window (TSK-49), and a briefing's run once reads the topic's own."""
    qs = [str(q).strip() for q in topic.get("key_questions") or [] if str(q).strip()][:6] or [t["goal"]]   # cap: list (scouts per run)
    return [{"step": "Collect the news, feeds, filings, job openings and prices", "agent": "desk", "harness": "desk-collect", "after": [],
             "why": "the Topic Desk reads the brief's sources on its isolated network and keeps what is new and on topic"},
            {"step": RESEARCH, "agent": "scout", "each": qs, "after": [1],
             "why": "one scout per key question, at the same time: the web and the job board beyond what the desk collected"},
            {"step": "Write the briefing, every claim cited", "agent": "desk", "harness": "desk-write", "after": [2],
             "why": "the Topic Desk writes from the collected events and the scouts' findings and checks each citation"},
            {"step": "Deliver it", "agent": "desk", "harness": "deliver", "after": [3],
             "why": "files it in the vault and sends it the ways the task asked"}]


def alert_plan(t):
    """The plan of each occurrence of a briefing task that runs on an event: the desk's alert, then its delivery."""
    return [{"step": "Write the alert from the event's sources", "agent": "desk", "harness": "desk-alert", "after": [],
             "why": "the Topic Desk reads what the event points to and writes a short alert against the topic's key questions"},
            {"step": "Deliver it", "agent": "desk", "harness": "deliver", "after": [1], "why": "sends it the ways the task asked"}]


def desk_env(window):
    """TSK-49: the run's window for ops/desk.sh (the desk reads and writes exactly it), or nothing: its brief's own."""
    import conductor as CD
    return {"DESK_SINCE": window["start"], "DESK_UNTIL": window["end"], "DESK_PERIOD": CD.period_text(window)} if window else {}


def desk_run(slug, mode, date, findings=None, window=None):
    """One step of the Topic Desk through ops/desk.sh -> its last line (collected: ..., filed: <path>)."""
    import conductor as CD
    if findings is not None:     # into the runner's own in/, read-only for the desk (review IMG-R13: out/ is the container's)
        (CD.DESK / slug / "in").mkdir(parents=True, exist_ok=True)
        (CD.DESK / slug / "in/findings.json").write_text(json.dumps(findings, ensure_ascii=False))
    p = subprocess.run(["bash", str(CD.ROOT / "ops/desk.sh"), slug, "--date", date], capture_output=True, text=True, timeout=CD.STEP_TIMEOUT,
                       env=dict(os.environ, DESK_TELEGRAM="0", DESK_MODE=mode, **desk_env(window)))
    lines = p.stdout.strip().splitlines()
    last = lines[-1] if lines else ""
    if p.returncode or not last or " failed: " in last or " NOT filed: " in last:
        raise RuntimeError(f"Topic Desk ({mode}): {last or TC.tail(p.stderr.strip(), 400) or 'no output'}")  # cap: preview
    return last


def run_desk_collect(c, t, s, prompt, card):
    import conductor as CD
    slug, date = t["spec"]["topic"], s["resume"].get("date") or dt.date.today().isoformat()
    desk_run(slug, "collect", date, window=t.get("window"))
    CD.put(c, s["id"], resume={"date": date})           # the writing step files under the same date, also after midnight
    saved = json.loads((CD.DESK / slug / "out" / f"{date}.collected.json").read_text())
    st, chosen = saved["stats"], saved["chosen"]
    return (f"{st['items']} items collected, {st['new']} new in the window, {st['events']} events; {len(chosen)} chosen:\n"
            + "\n".join(f"- {g['items'][0]['title']} · {g['items'][0]['source']} · {g['items'][0]['url']}" for g, _ in chosen))


def run_desk_write(c, t, s, prompt, card):
    import conductor as CD
    ss = CD.steps(c, t["id"], s.get("occ") or 1)
    col = next(x for x in ss if x["harness"] == "desk-collect")
    date = col["resume"].get("date") or dt.date.today().isoformat()
    findings = [{"question": x["item"] or x["title"], "text": x["output"] or ""} for x in ss if x["idx"] in s["after"]]
    out = desk_run(t["spec"]["topic"], "write", date, findings, window=t.get("window"))
    m = re.search(r"(?<!NOT )filed: (\S+)", out)              # desk.sh's "NOT filed: <path>" is no report (review RUN-R5)
    if not m or "NOT filed:" in out:
        raise RuntimeError("Topic Desk (write): the report was not filed" + (" (the vault refused it)" if "NOT filed:" in out else ""))
    CD.put(c, s["id"], resume={"report": m.group(1), "date": date})
    return (M.VAULT / m.group(1)).read_text()


def run_desk_alert(c, t, s, prompt, card):
    """An event-triggered briefing's alert (TSK-21): the desk writes it from the event's sources; it is filed under the
    topic's alerts, as a briefing mission's event run files it."""
    import conductor as CD
    ev = t.get("event")
    if not ev:
        raise RuntimeError("an alert step needs the event that started its run")
    a, log = M.X.alert_of(t["spec"]["topic"], ev)
    if not a:
        raise RuntimeError(f"Topic Desk (alert): {(log.strip().splitlines() or ['no output'])[-1]}")
    rel = M.X.file_alert(t["spec"]["topic"], a, ev)
    CD.put(c, s["id"], resume={"report": rel, "short": a.get("short", ""), "title": a.get("title") or ev.get("summary", "")[:80]})  # cap: id
    return a["markdown"]


def topic_wiki(t, slug, rel, text, card):
    """The topic's wiki grows with each report, as a briefing mission's does (missions.run_briefing), unless the owner
    deleted it (wiki_off on the mission that holds the topic). The pages it wrote, for the step's answer (its task page
    and swarm map list them, APP-36)."""
    import mission_extras as X
    try:                                                  # nothing here can fail the delivery
        if any(m.get("wiki_off") and (m.get("topic") or m["slug"]) == slug for m in M.load_missions().values()):
            return []
        n = X.compile_into(f"topics/{slug}/wiki", t["title"], rel, text, os.environ["VK_" + card["key"][3:].upper().replace("-", "_")])
        M.vault_commit([f"topics/{slug}/wiki"], f"wiki: {slug} from {rel}")
        M.log(f"conductor: task {t['id']}: wiki {slug}: {len(n)} pages updated")
        return list(n)
    except Exception as e:                                # the report is delivered all the same; logged
        M.log(f"conductor: task {t['id']}: the wiki of {slug} not updated: {type(e).__name__}: {e}")
        return []


def run_deliver(c, t, s, prompt, card):
    """The report or alert the ways the task asked (the app always; Telegram, e-mail), as a briefing mission delivers (MIS-15)."""
    import conductor as CD
    w = next(x for x in CD.steps(c, t["id"], s.get("occ") or 1) if x["harness"] in ("desk-write", "desk-alert"))
    rel, slug = w["resume"]["report"], t["spec"]["topic"]
    text = (M.VAULT / rel).read_text()
    ways = t["spec"].get("deliver") or ["telegram", "app"]
    outcome = {}                                          # each way's own result, filled by the delivery (TSK-50)
    if w["harness"] == "desk-alert":
        sent = M.X.deliver({"slug": slug, "title": t["title"], "deliver": ways}, w["resume"].get("title") or t["title"], w["resume"].get("short", ""),
                           rel, f"Alert · {(t.get('event') or {}).get('trigger', 'an event')}", text, outcome=outcome)
    else:
        head = re.search(r'^headline: "?(.*?)"?$', text, re.M)
        title = json.loads(f'"{head.group(1)}"') if head else t["title"]
        win = t.get("window")
        if win:                                           # TSK-49: the reporting period in the subject, as the report states it
            title = f"{title} · {span(win)}"
        tg = CD.DESK / slug / "out" / f"{w['resume']['date']}.telegram.txt"
        sent = M.X.deliver({"slug": slug, "title": t["title"], "deliver": ways}, title, tg.read_text() if tg.exists() else "", rel,
                           f"{M.period({'schedule': t['rhythm'].get('schedule')})} briefing · {M.now():%d %b %Y}", text, empty=M.X.briefing_empty(text),
                           outcome=outcome)
    pages = topic_wiki(t, slug, rel, text, card) if sent and w["harness"] != "desk-alert" else []
    body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S).strip()
    CD.put(c, s["id"], resume={"sent": outcome, "ways": ways})    # the delivery's own record, for the judge (TSK-50)
    said = "Nothing new was chosen: kept in the app, not sent" if not sent else delivered(ways, outcome)
    failed = [WAY[k] for k, v in outcome.items() if k in WAY and v.get("ok") is False]
    if failed:                                            # a delivery that did not go out is said, never passed as one
        M.event("task", slug, f"Task #{t['id']}: the {' and the '.join(failed)} of {rel} did not go out", push=True, title="Tasks")
    wiki = f" Topic wiki pages updated: {', '.join(pages)}." if pages else ""
    return f"{said} ({rel}).{wiki}\n\n{body}"


WAY = {"telegram": "Telegram message", "email": "e-mail"}


def span(w):
    """A window as a reporting period for a subject: "2 Nov – 9 Nov 2026" (its whole wording is in the report)."""
    a, b = (dt.datetime.fromisoformat(w[k]) for k in ("start", "end"))
    return f"{a.day} {a:%b}{f' {a.year}' if a.year != b.year else ''} – {b.day} {b:%b %Y}"


HELD = {"held": "waits for the end of quiet hours", "off": "is off in your notification settings", "duplicate": "had gone out already"}


def delivered(ways, outcome):
    """What went out, as it went: "Delivered by Telegram and e-mail and kept in the app", and each way that did not, why.
    A way with no record (a delivery made before TSK-50) counts as it was said then."""
    names = {"telegram": "Telegram", "email": "e-mail"}
    went = [names[x] for x in ways if x in WAY and (outcome.get(x) or {"ok": True})["ok"]]
    out = f"Delivered by {' and '.join(went)} and kept in the app" if went else "Kept in the app"
    for x in (x for x in ways if x in WAY and outcome.get(x)):
        o = outcome[x]
        out += f"; the {WAY[x]} failed" if o["ok"] is False else f"; the {WAY[x]} {HELD.get(o.get('said'), o.get('said'))}" if o["ok"] is None else ""
    return out


# gb: the desk's container; a delivery
STEP_KINDS = {"desk-collect": {"run": run_desk_collect, "owners": ("desk",), "gb": 0.4, "fixed_plan": True},
              "desk-write": {"run": run_desk_write, "owners": ("desk",), "gb": 0.3, "fixed_plan": True},
              "desk-alert": {"run": run_desk_alert, "owners": ("desk",), "gb": 0.3, "fixed_plan": True},
              "deliver": {"run": run_deliver, "owners": ("desk",), "gb": 0.1, "fixed_plan": True}}

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
def briefing_plan(t, topic):
    """The plan of every occurrence of a briefing task, from its topic (topics/<slug>/TOPIC.md)."""
    qs = [str(q).strip() for q in topic.get("key_questions") or [] if str(q).strip()][:6] or [t["goal"]]   # cap: list (scouts per run)
    days = max(1, round(int(topic.get("window_hours") or 36) / 24))
    span = "the last day" if days <= 1 else f"the last {days} days"
    return [{"step": "Collect the news, feeds, filings, job openings and prices", "agent": "desk", "harness": "desk-collect", "after": [],
             "why": "the Topic Desk reads the brief's sources on its isolated network and keeps what is new and on topic"},
            {"step": f"Research {span}", "agent": "scout", "each": qs, "after": [1],
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


def desk_run(slug, mode, date, findings=None):
    """One step of the Topic Desk through ops/desk.sh -> its last line (collected: ..., filed: <path>)."""
    import conductor as CD
    if findings is not None:
        (CD.DESK / slug / "out").mkdir(parents=True, exist_ok=True)
        (CD.DESK / slug / "out/findings.json").write_text(json.dumps(findings, ensure_ascii=False))
    p = subprocess.run(["bash", str(CD.ROOT / "ops/desk.sh"), slug, "--date", date], capture_output=True, text=True, timeout=CD.STEP_TIMEOUT,
                       env=dict(os.environ, DESK_TELEGRAM="0", DESK_MODE=mode))
    lines = p.stdout.strip().splitlines()
    last = lines[-1] if lines else ""
    if p.returncode or not last or " failed: " in last or " NOT filed: " in last:
        raise RuntimeError(f"Topic Desk ({mode}): {last or TC.tail(p.stderr.strip(), 400) or 'no output'}")  # cap: preview
    return last


def run_desk_collect(c, t, s, prompt, card):
    import conductor as CD
    slug, date = t["spec"]["topic"], s["resume"].get("date") or dt.date.today().isoformat()
    desk_run(slug, "collect", date)
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
    m = re.search(r"filed: (\S+)", desk_run(t["spec"]["topic"], "write", date, findings))
    if not m:
        raise RuntimeError("Topic Desk (write): the report was not filed")
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
    if w["harness"] == "desk-alert":
        sent = M.X.deliver({"slug": slug, "title": t["title"], "deliver": ways}, w["resume"].get("title") or t["title"], w["resume"].get("short", ""),
                           rel, f"Alert · {(t.get('event') or {}).get('trigger', 'an event')}", text)
    else:
        head = re.search(r'^headline: "?(.*?)"?$', text, re.M)
        title = json.loads(f'"{head.group(1)}"') if head else t["title"]
        tg = CD.DESK / slug / "out" / f"{w['resume']['date']}.telegram.txt"
        sent = M.X.deliver({"slug": slug, "title": t["title"], "deliver": ways}, title, tg.read_text() if tg.exists() else "", rel,
                           f"{M.period({'schedule': t['rhythm'].get('schedule')})} briefing · {M.now():%d %b %Y}", text, empty=M.X.briefing_empty(text))
    pages = topic_wiki(t, slug, rel, text, card) if sent and w["harness"] != "desk-alert" else []
    how = " and ".join({"telegram": "Telegram", "email": "e-mail"}[x] for x in ways if x in ("telegram", "email"))
    body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S).strip()
    said = ("Nothing new was chosen: kept in the app, not sent" if not sent else
            f"Delivered by {how} and kept in the app" if how else "Kept in the app")
    wiki = f" Topic wiki pages updated: {', '.join(pages)}." if pages else ""
    return f"{said} ({rel}).{wiki}\n\n{body}"


# gb: the desk's container; a delivery
STEP_KINDS = {"desk-collect": {"run": run_desk_collect, "owners": ("desk",), "gb": 0.4, "fixed_plan": True},
              "desk-write": {"run": run_desk_write, "owners": ("desk",), "gb": 0.3, "fixed_plan": True},
              "desk-alert": {"run": run_desk_alert, "owners": ("desk",), "gb": 0.3, "fixed_plan": True},
              "deliver": {"run": run_deliver, "owners": ("desk",), "gb": 0.1, "fixed_plan": True}}

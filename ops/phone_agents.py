"""Standing work for the AI phone (crew agents; the phone itself is images/phone/phone.py).

  phone-cleanup  weekly: the cleanup analysis's facts (ops/cleanup.py: storage, apps, files by year) become concrete
                 steps, one per item: "delete WhatsApp Images from before 2025: 4.1 GB", "uninstall Audible (unused
                 since 2024): 5.8 GB", "trim all app caches: 1.2 GB". Each waits on the agent page for the owner's Approve
                 (refused from the AI phone itself). An approved step goes to /phone/cleanup/<item>-<n>.json; the phone
                 runs exactly that step once within 30 minutes, with the same block list and path checks as its tools,
                 and reports the space it freed (<item>-<n>.result.json). Nothing is deleted without that tap; a
                 dismissed step is not proposed again. "Approve all" (two taps) approves every open step at once: the
                 phone then runs them one after another (one at a time), each within the batch's window (30 min a step,
                 at most 4 hours).
  phone-check    weekly: battery, storage, Android security patch, connection and the screen state. A run fails
                 (a health alert) only on a real fault: not connected, battery low and not charging, storage nearly
                 full. The screen sleeps by design (2026-10-29), so its state is only reported. Old security patches are a note.

  python3 ops/crew.py phone-cleanup|phone-check         (crew-phone-cleanup / crew-phone-check units)
"""
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from textcap import tail                    # visible caps and input limits (AGENTS.md, truncation)

C = M = None                                         # ops/crew.py and ops/missions.py (set by crew.run / missions.main)
PHONE_DIR = Path(os.environ.get("PHONE_HOST_DIR", "/srv/ai/phone"))
ACTIONS = {"phone_cleanup_do", "phone_cleanup_do_all", "phone_cleanup_dismiss", "phone_cleanup_undo"}
MIN_DELETE, MIN_APP, MIN_CACHES = 200e6, 50e6, 300e6  # smaller steps are not worth a tap
MAX_APPS = 12
APPROVAL_S = 30 * 60
BATCH_MAX_S = 4 * 3600
UNUSED_DAYS = 90
NEVER_AREAS = ("Databases",)                          # WhatsApp's chat backups: the owner decides those himself
KEEP_APPS = ("com.android.chrome", "com.amazon.mShop", "com.tailscale", "org.telegram", "com.google.android.gms")  # the AI phone's own tools
ITEM = re.compile(r"^c-[0-9a-f]{10}$")


def gb(n):
    return f"{n / 1e9:.1f} GB" if n >= 1e8 else f"{n / 1e6:.0f} MB"


def cdir():
    d = PHONE_DIR / "cleanup"
    if not d.exists():
        d.mkdir(parents=True)
        d.chmod(0o1777)                                  # the phone container (another user) writes the results here
    return d


def item_id(*parts):
    return "c-" + hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


def area_name(area):
    return area.replace("Android/media/com.whatsapp/WhatsApp/Media/", "").replace("Android/media/com.whatsapp/WhatsApp/", "WhatsApp ")


# ---------- phone-cleanup: facts -> one step per item ----------
def steps_of(facts, today=None):
    """The cleanup facts -> concrete steps [{id, kind, title, why, size, args}], biggest first."""
    today = today or dt.date.today()
    out = []
    files = facts.get("files") or {}
    year = today.year - 1                                 # "before 2025" when it is 2026: a full year of grace
    cut_days = (today - dt.date(year, 1, 1)).days
    for a in files.get("areas") or []:
        if any(x in a["area"] for x in NEVER_AREAS):
            continue
        name = area_name(a["area"])
        stale = a["newest"] < (today - dt.timedelta(days=365)).isoformat()
        old = sum(v["size"] for y, v in a["by_year"].items() if y < str(year))
        n_old = sum(v["files"] for y, v in a["by_year"].items() if y < str(year))
        if stale and a["size"] >= MIN_DELETE:
            out.append({"id": item_id("delete", a["area"], 0), "kind": "delete", "size": a["size"],
                        "title": f"Delete {name} ({a['files']} files, nothing new since {a['newest']})",
                        "why": f"{a['oldest']} to {a['newest']}: old personal data from when this was the owner's own phone.",
                        "args": {"path": f"/sdcard/{a['area']}", "older_than_days": 0}})
        elif old >= MIN_DELETE:
            out.append({"id": item_id("delete", a["area"], year), "kind": "delete", "size": old,
                        "title": f"Delete {name} from before {year} ({n_old} files)",
                        "why": f"Files older than {cut_days} days; the newer ones ({a['files'] - n_old}) stay.",
                        "args": {"path": f"/sdcard/{a['area']}", "older_than_days": cut_days}})
    cutoff = (today - dt.timedelta(days=UNUSED_DAYS)).isoformat()
    unused = [x for x in facts.get("apps") or [] if not x["blocked"] and x["total"] >= MIN_APP and not x["package"].startswith(KEEP_APPS)
              and (not x["last_used"] or x["last_used"] < cutoff)]
    for x in sorted(unused, key=lambda x: -x["total"])[:MAX_APPS]:  # cap: list (the biggest unused apps, a few at a time)
        out.append({"id": item_id("uninstall", x["package"]), "kind": "uninstall", "size": x["total"],
                    "title": f"Uninstall {x['package']}",
                    "why": f"No recorded use {'since ' + x['last_used'] if x['last_used'] else 'in the last year'}; installed {x['installed'] or '?'}. Its data goes with it.",
                    "args": {"package": x["package"]}})
    cache = sum(x["cache"] for x in facts.get("apps") or [] if not x["blocked"])
    if cache >= MIN_CACHES:
        out.append({"id": item_id("trim_caches", today.isocalendar()[1]), "kind": "trim_caches", "size": cache,
                    "title": "Empty all app caches", "why": "Caches rebuild themselves; logins and data stay.", "args": {}})
    return sorted(out, key=lambda s: -s["size"])


def merge(old, new):
    """This run's steps with the last run's decisions: done, dismissed and running steps keep their state."""
    by = {s["id"]: s for s in old}
    out = []
    for s in new:
        prev = by.pop(s["id"], None)
        if prev and prev.get("status") in ("dismissed", "approved", "done"):
            out.append(prev)
        else:
            out.append({**s, "status": "open", **({"result": prev["result"], "attempt": prev.get("attempt", 0)} if prev and prev.get("status") == "failed" else {})})
    out += [s for s in by.values() if s.get("status") in ("approved", "done", "dismissed")]   # history stays
    # cap: rotate (the newest 20 done and 60 dismissed, so a dismissed one is not proposed again)
    keep = [s for s in out if s["status"] in ("open", "approved", "failed")] + [s for s in out if s["status"] == "done"][-20:] \
        + [s for s in out if s["status"] == "dismissed"][-60:]  # cap: rotate (the newest 20 done and 60 dismissed, so a dismissed one is not proposed again)
    return keep


def cleanup(c):
    import cleanup as CL
    CL.M = M
    facts = CL.phone_facts()
    st = steps_of(facts, M.now().date())
    cur = C.agent_file("phone-cleanup")
    actions = merge(cur.get("actions") or [], st)
    open_ = [s for s in actions if s["status"] == "open"]
    s = facts["storage"]
    res = (f"{gb(s['free'])} free of {gb(s['total'])}; {len(open_)} step{'s' if len(open_) != 1 else ''} to approve "
           f"({gb(sum(x['size'] for x in open_))})" if open_ else f"{gb(s['free'])} free of {gb(s['total'])}; nothing worth a step")
    C.save("phone-cleanup", result=res, actions=actions, findings=[], last=time.time(), free=s["free"], total=s["total"])
    import runtime as RTM
    if RTM.ref():
        for x in open_:
            RTM.emit(RTM.ref(), "propose", agent="crew:phone-cleanup", title=x["title"], detail=f"{gb(x['size'])} · {x['why']}")
    return len(open_)


def _approvable(req):
    if req.get("source") != "app":
        raise ValueError("cleanup steps are approved in Mission Control")
    if (PHONE_DIR / "STOP").exists():
        raise ValueError("the AI phone is switched off (Phone page → Stop); switch it on first")


def _hand_over(s, req, expires):
    """Write one approved step for the phone (it runs each file exactly once, one at a time)."""
    n = int(s.get("attempt", 0)) + 1
    name = f"{s['id']}-{n}"
    (cdir() / f"{name}.json").write_text(json.dumps({"id": name, "item": s["id"], "kind": s["kind"], "args": s["args"], "title": s["title"],
                                                      "approved": M.now().isoformat(timespec="seconds"), "by": req.get("by") or "owner",
                                                      "expires": expires}, ensure_ascii=False))
    s.update(status="approved", attempt=n, result="", approved=time.time(), expires=expires)


def approve(req):
    """The owner's Approve on one step (Mission Control; never from the AI phone): the phone runs it within 30 min."""
    _approvable(req)
    sid = str(req.get("id", ""))
    cur = C.agent_file("phone-cleanup")
    acts = cur.get("actions") or []
    s = next((x for x in acts if x["id"] == sid), None)
    if not ITEM.match(sid) or not s:
        raise ValueError("no such cleanup step")
    if s["status"] not in ("open", "failed"):
        raise ValueError(f"this step is {s['status']}")
    _hand_over(s, req, time.time() + BATCH_MAX_S)
    C.save("phone-cleanup", actions=acts)
    M.event("phone", "", f"Phone cleanup: approved “{s['title']}” ({gb(s['size'])}); it waits its turn on the AI phone", title="Crew")
    return {"approved": sid}


def approve_all(req):
    """The owner's Approve all: every step shown that is open or failed (not dismissed ones) at once; the phone runs them in
    turn. The app sends the ids it showed, so a step that appeared after the owner looked is never approved with them."""
    _approvable(req)
    acts = C.agent_file("phone-cleanup").get("actions") or []
    shown = {str(i) for i in req.get("ids") or []}
    todo = [s for s in acts if s["status"] in ("open", "failed") and s["id"] in shown]
    if not todo:
        raise ValueError("no open cleanup steps")
    expires = time.time() + BATCH_MAX_S
    for s in todo:
        _hand_over(s, req, expires)
    C.save("phone-cleanup", actions=acts)
    size = sum(s.get("size") or 0 for s in todo)
    M.event("phone", "", f"Phone cleanup: approved all {len(todo)} steps ({gb(size)}); the AI phone does them one after another", title="Crew")
    return {"approved": [s["id"] for s in todo], "bytes": size}


def undo(req):
    """The owner's Undo on an approved step the phone has not started: its hand-over file goes, so it never runs. Once the
    phone has started it (the marker it writes first), it is too late: an uninstall can't be taken back."""
    sid = str(req.get("id", ""))
    acts = C.agent_file("phone-cleanup").get("actions") or []
    s = next((x for x in acts if x["id"] == sid and x["status"] == "approved"), None)
    if not ITEM.match(sid) or not s:
        raise ValueError("this step is not waiting: nothing to undo")
    name = f"{sid}-{s.get('attempt', 1)}"
    if (cdir() / f"{name}.started").exists() or (cdir() / f"{name}.result.json").exists():
        raise ValueError("the AI phone has already started this step: it can't be undone")
    (cdir() / f"{name}.json").unlink(missing_ok=True)
    s.update(status="open", result="", started=False)
    C.save("phone-cleanup", actions=acts)
    M.event("phone", "", f"Phone cleanup: approval of “{s['title']}” undone; nothing ran", title="Crew")
    return {"undone": sid}


def dismiss(req):
    sid = str(req.get("id", ""))
    cur = C.agent_file("phone-cleanup")
    acts = cur.get("actions") or []
    s = next((x for x in acts if x["id"] == sid and x["status"] in ("open", "failed")), None)
    if not s:
        raise ValueError("no such open cleanup step")
    s["status"] = "dismissed"
    C.save("phone-cleanup", actions=acts)
    return {"dismissed": sid}


def handle(req, c=None):
    a = req.get("action")
    return approve(req) if a == "phone_cleanup_do" else approve_all(req) if a == "phone_cleanup_do_all" else undo(req) if a == "phone_cleanup_undo" else dismiss(req)


def sync():
    """The phone's results -> the steps (done with the space freed, or failed with why); approvals that expired unanswered fail."""
    cur = C.agent_file("phone-cleanup")
    acts = cur.get("actions") or []
    changed = False
    for s in acts:
        if s.get("status") != "approved":
            continue
        name = f"{s['id']}-{s.get('attempt', 1)}"
        rf = PHONE_DIR / "cleanup" / f"{name}.result.json"
        started = (PHONE_DIR / "cleanup" / f"{name}.started").exists()
        if started != bool(s.get("started")):       # "On the AI phone…", and no more Undo
            s["started"] = started
            changed = True
        if rf.exists():
            try:
                r = json.loads(rf.read_text())
            except ValueError:
                continue
            s.update(status="done" if r.get("ok") else "failed", result=r.get("text", ""), freed=r.get("freed", 0), ended=time.time())
            M.event("phone", "", f"Phone cleanup: {s['title']}: " + (f"done, {gb(r.get('freed') or 0)} freed" if r.get("ok") else f"not done ({r.get('text', '')})"),
                    push=not r.get("ok"), title="Crew")
            changed = True
        elif time.time() > s.get("expires", s.get("approved", time.time()) + APPROVAL_S) + 300:
            s.update(status="failed", result="The AI phone did not pick it up in time (switched off or not connected?). Approve again to retry.")
            changed = True
    if changed:
        freed = sum(x.get("freed") or 0 for x in acts if x.get("status") == "done")
        C.save("phone-cleanup", actions=acts, freed_total=freed)
    return changed


# ---------- phone-check: is the AI phone healthy? ----------
CHECK = ("import json, phone; phone.S['serial'] = json.load(open('/phone/state.json'))['serial']; a = lambda c: phone.adb('shell', c); "
         "print(json.dumps({'battery': a('dumpsys battery'), 'power': a('dumpsys power | grep -E \"mWakefulness=|mStayOn\"'), "
         "'df': a('df -k /data | tail -1'), 'patch': a('getprop ro.build.version.security_patch'), "
         "'android': a('getprop ro.build.version.release'), 'uptime': a('cat /proc/uptime')}))")


def battery_of(text):
    v = dict(re.findall(r"^\s*([A-Za-z ]+):\s*(\S+)\s*$", text or "", re.M))
    plugged = any(v.get(k) == "true" for k in ("AC powered", "USB powered", "Wireless powered", "Dock powered"))
    level = int(v["level"]) if v.get("level", "").isdigit() else None
    temp = int(v["temperature"]) / 10 if v.get("temperature", "").lstrip("-").isdigit() else None
    return {"level": level, "plugged": plugged, "charging": v.get("status") in ("2", "5"), "temp": temp,
            "health": {"2": "good", "3": "overheat", "4": "dead", "5": "over voltage", "7": "cold"}.get(v.get("health", ""), v.get("health", "?"))}


def judge(facts, state, today=None):
    """-> (faults, notes, summary). Faults are what needs the owner; notes are worth knowing."""
    today = today or dt.date.today()
    faults, notes = [], []
    if not state.get("connected"):
        faults.append("the AI phone is not connected (Phone page → Connect; wireless debugging may need re-pairing)")
        return faults, notes, "not connected"
    b = battery_of(facts.get("battery"))
    if b["level"] is not None and b["level"] < 20 and not b["plugged"]:
        faults.append(f"battery at {b['level']} % and not plugged in: plug the AI phone in")
    if b["temp"] and b["temp"] >= 45:
        faults.append(f"battery at {b['temp']:.0f} °C (too hot)")
    if b["health"] not in ("good", "?"):
        faults.append(f"battery health: {b['health']}")
    m = re.search(r"\s(\d+)\s+(\d+)\s+(\d+)\s+\d+%", facts.get("df") or "")
    free = int(m[3]) * 1024 if m else None
    if free is not None and free < 2e9:
        faults.append(f"storage nearly full ({gb(free)} free): approve the Phone cleanup's steps")
    awake = re.search(r"mWakefulness=(\w+)", facts.get("power") or "")     # reported only: the screen sleeps by design
    if state.get("error"):
        notes.append(f"last phone error: {state['error']}")
    patch = (facts.get("patch") or "").strip()
    try:
        age = (today - dt.date.fromisoformat(patch)).days
        if age > 180:
            notes.append(f"Android security patch {patch} ({age // 30} months old): check Settings → Software update on the phone")
    except ValueError:
        pass
    up = float((facts.get("uptime") or "0").split()[0] or 0)
    summary = (f"battery {b['level']} %{' charging' if b['charging'] else ' (plugged in)' if b['plugged'] else ''}"
               + (f", {b['temp']:.0f} °C" if b["temp"] else "") + (f"; {gb(free)} free" if free is not None else "")
               + f"; Android {facts.get('android', '').strip()} (patch {patch or '?'}); screen {awake[1].lower() if awake else '?'}; up {up / 86400:.1f} days")
    return faults, notes, summary


def check(c):
    st = json.loads((PHONE_DIR / "state.json").read_text()) if (PHONE_DIR / "state.json").exists() else {}
    if (PHONE_DIR / "STOP").exists():
        C.save("phone-check", result="The AI phone is switched off (Stop): nothing checked", findings=[], last=time.time())
        return 0
    facts = {}
    if st.get("connected"):
        p = subprocess.run(["docker", "exec", "-u", "phone", "-e", "HOME=/phone/home", "-e", "PHONE_DIR=/tmp/check", "-w", "/app",
                            "aistack-phone-1", "python", "-c", CHECK], capture_output=True, text=True, timeout=120)
        if p.returncode:
            raise RuntimeError(f"could not read the AI phone: {tail(p.stderr.strip(), 4000)}")  # cap: store
        facts = json.loads(p.stdout)
    faults, notes, summary = judge(facts, st, M.now().date())
    findings = [{"kind": "fault", "issue": f} for f in faults] + [{"kind": "note", "issue": n} for n in notes]
    C.save("phone-check", result=("; ".join(faults) if faults else "healthy: " + summary), summary=summary, findings=findings, last=time.time())
    if faults:                                         # a failed run is the health alert (only for real faults)
        raise RuntimeError("AI phone: " + "; ".join(faults))
    return 0

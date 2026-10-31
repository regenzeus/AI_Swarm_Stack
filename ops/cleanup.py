"""Cleanup missions (type "cleanup", run by ops/missions.py): where the space goes on the AI phone or the PC, and what
could go. Analysis only: a cleanup mission never deletes anything.

target "phone": read-only facts from the AI phone over ADB (images/phone/phone.py storage_report / apps_report, run
inside the phone container): storage categories, biggest folders, every installed app with size, cache, install date
and last recorded use. Block-listed apps (banking etc.) are only listed. Removing an app or trimming caches is a phone
tool that asks the owner for each action (phone_uninstall / phone_trim_caches in chat), never part of a mission run.
target "pc": a TreeSize-like scan of the Windows drives (ops/windows/disk-scan.ps1, started by the Windows host probe
when this runner drops /srv/ai/state/pcscan/request.json; result C:\\AI\\exports\\.host\\diskscan.json), plus Docker's
own usage inside WSL. Every finding carries safe / caution / never.

The report is built from the facts (no model needed, so it also works while ChatGPT is at its limit); the mission
agent's key only adds a short summary on top when it can.
"""
import datetime as dt
import json
import os
import re
import subprocess
import time
from pathlib import Path
from textcap import STORE, cut, tail                    # visible caps and input limits (AGENTS.md, truncation)

M = None                                    # ops/missions.py (set in its main)
PHONE = "aistack-phone-1"
SCAN = Path("/srv/win-exports/.host/diskscan.json")
REQUEST = Path("/srv/ai/state/pcscan/request.json")
UNUSED_DAYS = 90
PHONE_FACTS = ("import json, sys, phone; phone.S['serial'] = json.load(open('/phone/state.json'))['serial']; "
               "print(json.dumps({sys.argv[1]: getattr(phone, sys.argv[1] + '_report')()}))")
STEPS = None                                 # the run's step log (runs/<id>.events.jsonl), merged into its timeline


def step(kind, title, detail="", ms=None, **extra):
    """One thing the cleanup did or found, for the run's timeline (ops/telemetry.py reads runs/<id>.events.jsonl)."""
    if STEPS:
        with open(STEPS, "a") as f:
            f.write(json.dumps({"ts": time.time(), "agent": "cleanup", "kind": kind, "title": title, "detail": cut(detail, STORE), "ms": ms, **extra}) + "\n")  # cap: store
    import runtime as RTM                    # the live run view too; it also keeps a long wait (the Windows scan) from looking stalled
    if RTM.ref():
        RTM.emit(RTM.ref(), "say" if kind == "finding" else "stage", agent="cleanup", title=title, detail=cut(detail, STORE), ms=ms)  # cap: store


def gb(n):
    return f"{n / 1e9:.1f} GB" if n >= 1e8 else f"{n / 1e6:.0f} MB"


def target_of(m):
    t = str(m.get("target") or "").lower()
    if t in ("phone", "pc"):
        return t
    return "phone" if re.search(r"\bphone|handy|s22|android\b", f"{m.get('title', '')} {m.get('goal', '')}".lower()) else "pc"


# ---------- facts ----------
def phone_facts():
    if Path("/srv/ai/phone/STOP").exists():
        raise RuntimeError("the AI phone is switched off (Stop on the Phone page)")
    st = json.loads(Path("/srv/ai/phone/state.json").read_text())
    if not st.get("connected"):
        raise RuntimeError("the AI phone is not connected (Phone page → Connect)")
    out = {}
    for part, what in (("storage", "storage categories and biggest folders (du, dumpsys diskstats)"),
                       ("apps", "every installed app: size, data, cache, install date, last use (diskstats, usagestats, package)"),
                       ("files", "biggest files and old data by year per area (find + stat: names, sizes, dates)")):
        t0 = time.time()
        p = subprocess.run(["docker", "exec", "-u", "phone", "-e", "HOME=/phone/home", "-e", "PHONE_DIR=/tmp/cleanup", "-w", "/app", PHONE,
                            "python", "-c", PHONE_FACTS, part], capture_output=True, text=True, timeout=900)
        ms = int((time.time() - t0) * 1000)
        if p.returncode:
            step("error", f"phone · {part}", tail(p.stderr.strip(), 4000), ms)  # cap: store
            raise RuntimeError(f"could not read the phone ({part}): {tail(p.stderr.strip(), 4000)}")  # cap: store
        out.update(json.loads(p.stdout))
        step("scan", f"phone · {part}", f"Read {what}.", ms)
    s, f = out["storage"], out.get("files", {})
    step("finding", "Storage", f"{gb(s['total'] - s['free'])} used of {gb(s['total'])}, {gb(s['free'])} free; "
         + ", ".join(f"{k.replace(' Size', '')} {gb(v)}" for k, v in s["categories"].items() if v))
    step("finding", "Apps", f"{len(out['apps'])} installed by the owner; biggest: "
         + ", ".join(f"{a['package']} {gb(a['total'])}" for a in out["apps"][:8]))
    for a in f.get("areas", [])[:6]:
        step("finding", a["area"].split("/")[-1] if "whatsapp" not in a["area"] else "WhatsApp media",
             f"{a['files']} files, {gb(a['size'])}, {a['oldest']} to {a['newest']}; by year: "
             + ", ".join(f"{y} {gb(v['size'])}" for y, v in a["by_year"].items()))
    return out


def pc_facts(wait=1500):
    """Ask Windows for a fresh scan (the host probe picks the request up within a minute) and wait for it."""
    REQUEST.parent.mkdir(parents=True, exist_ok=True)
    asked = time.time()
    REQUEST.write_text(json.dumps({"at": M.now().isoformat(timespec="seconds")}))
    step("scan", "pc · scan requested", "Asked Windows for a disk scan (host probe → disk-scan.ps1, read-only, low priority).")
    # The scan takes 10-15 minutes and needs no model: park, so other missions run meanwhile (ops/missions.py park)
    fresh = M.park("the Windows disk scan", lambda: SCAN.exists() and SCAN.stat().st_mtime > asked, timeout=wait, every=15)
    for _ in range(1 if fresh else 0):
        try:
            if SCAN.stat().st_mtime > asked:
                time.sleep(2)
                scan = json.loads(SCAN.read_text(encoding="utf-8-sig"))
                import runtime as RTM
                RTM.touched(r"C:\AI\exports\.host\diskscan.json", note=f"the Windows disk scan, {SCAN.stat().st_size:,} bytes")
                step("scan", "pc · disk scan", f"{scan.get('files', 0):,} files on {', '.join(d['root'] for d in scan.get('drives', []))}, "
                     f"{scan.get('errors', 0)} folders unreadable (skipped)", int((time.time() - asked) * 1000))
                for d in scan.get("drives", []):
                    step("finding", f"Drive {d['root']}", f"{gib(d['total'] - d['free'])} used of {gib(d['total'])}, {gib(d['free'])} free")
                for c in scan.get("clutter", [])[:10]:
                    step("finding", c["label"], f"{gib(c['size'])} · {c['verdict']} · {c['path']} · {c['how']}")
                return scan, True
        except (OSError, ValueError):
            pass
    if SCAN.exists():                         # no fresh scan in time: the last one, marked as such
        return json.loads(SCAN.read_text(encoding="utf-8-sig")), False
    raise RuntimeError("Windows did not answer the scan request (is the 'ai-stack host probe' task running?)")


def docker_usage():
    t0 = time.time()
    p = subprocess.run(["docker", "system", "df", "--format", "{{json .}}"], capture_output=True, text=True, timeout=120)
    rows = [json.loads(x) for x in p.stdout.splitlines() if x.startswith("{")]
    step("scan", "wsl · docker system df", "; ".join(f"{x.get('Type')} {x.get('Size')} ({x.get('Reclaimable')} reclaimable)" for x in rows),
         int((time.time() - t0) * 1000))
    return rows


def gib(n):
    """Windows' own units (Explorer's "GB" are GiB), so the report matches what the owner sees."""
    return f"{n / 2**30:.1f} GB" if n >= 2**27 else f"{n / 2**20:.0f} MB"


# ---------- reports ----------
PHONE_FILES = {}


def phone_report(f, today=None):
    today = today or M.now().date()
    s, apps = f["storage"], f["apps"]
    PHONE_FILES.clear(); PHONE_FILES.update(f)
    cutoff = (today - dt.timedelta(days=UNUSED_DAYS)).isoformat()
    free = s["free"]
    unused = [a for a in apps if not a["blocked"] and (not a["last_used"] or a["last_used"] < cutoff)]
    big_unused = sorted(unused, key=lambda a: -a["total"])[:15]
    caches = sorted([a for a in apps if a["cache"] >= 50e6 and not a["blocked"]], key=lambda a: -a["cache"])[:8]
    wa = {x["path"].split("/")[-1]: x["size"] for x in s.get("whatsapp", [])}
    lines = [f"**{gb(s['total'] - free)} of {gb(s['total'])} used, {gb(free)} free** ({100 * free / max(s['total'], 1):.0f} % free).", "",
             "### Where the space goes", "", "| What | Size |", "|---|---|"]
    lines += [f"| {k.replace(' Size', '')} | {gb(v)} |" for k, v in sorted(s["categories"].items(), key=lambda x: -x[1]) if v]
    lines += ["", "### Biggest folders", "", "| Folder | Size | What to do | |", "|---|---|---|---|"]
    advice = {"Android": ("app data and app media (WhatsApp, Audible … below)", "caution"),
              "SdCardBackUp": ("an old backup folder: check its contents, copy to the NAS if needed, then delete", "caution"),
              "DCIM": ("camera photos and videos: move to Google Photos / the NAS, then delete", "caution"),
              "Pictures": ("pictures and screenshots: keep or move", "caution"),
              "Download": ("downloads: usually safe to delete after a look", "safe")}
    for x in s["folders"][:10]:
        name = x["path"].replace("/sdcard/", "")
        what, verdict = advice.get(name, ("", "caution"))
        lines.append(f"| {name} | {gb(x['size'])} | {what} | {verdict} |")
    if wa:
        lines += ["", f"### WhatsApp media: {gb(sum(wa.values()))}", "",
                  "Images, videos and voice notes received in chats. Biggest saver on most phones: WhatsApp → Settings → "
                  "Storage and data → Manage storage (largest files, forwarded many times), or delete media per chat.", ""]
        lines += [f"- {k}: {gb(v)}" for k, v in sorted(wa.items(), key=lambda x: -x[1])[:6]]
    lines += ["", f"### Apps without a recorded use for {UNUSED_DAYS}+ days ({len(unused)} apps, {gb(sum(a['total'] for a in unused))})", "",
              "Android keeps about a year of usage history, so \"no use recorded\" can also mean before that.", "",
              "| App | Size | Data | Installed | Last use |", "|---|---|---|---|---|"]
    lines += [f"| {a['package']} | {gb(a['total'])} | {gb(a['data'])} | {a['installed'] or '?'} | {a['last_used'] or 'none recorded'} |" for a in big_unused]
    if caches:
        lines += ["", f"### App caches ({gb(sum(a['cache'] for a in apps))} in total)", "",
                  "Caches rebuild themselves. Emptying them all at once is one approved action (phone_trim_caches); per-app "
                  "clearing needs the app's own settings.", ""]
        lines += [f"- {a['package']}: {gb(a['cache'])}" for a in caches]
    files = PHONE_FILES.get("files") or {}
    old_total = 0
    if files.get("areas"):
        lines += ["", "### Old personal data (this is no longer the owner's private phone)", "",
                  "By area and year. Deleting is one approved step per folder: Hermes shows what and how much, you tap.", "",
                  f"| Area | Files | Size | From → to | Before {today.year - 1} | Delete with |", "|---|---|---|---|---|---|"]
        year = str(today.year - 1)
        for a in files["areas"]:
            old = sum(v["size"] for y, v in a["by_year"].items() if y < year)
            old_total += old
            name = a["area"].replace("Android/media/com.whatsapp/WhatsApp/", "WhatsApp ")
            stale = a["newest"] < (today - dt.timedelta(days=365)).isoformat()     # nothing new in a year: the whole folder
            ask = (f"\"on the AI phone, delete /sdcard/{a['area']}\"" if stale or old >= a["size"] * 0.95
                   else f"\"on the AI phone, delete {name} files older than 365 days\"" if old >= 5e7
                   else "recent: look through it yourself")
            lines.append(f"| {name} | {a['files']} | {gb(a['size'])} | {a['oldest']} → {a['newest']} | {gb(old)} | {ask} |")
        lines += ["", "WhatsApp's `Databases` folder holds its chat backups: only delete it if the chats don't matter."]
    if files.get("biggest"):
        lines += ["", "### Biggest files", "", "| File | Size | Date |", "|---|---|---|"]
        lines += [f"| {x['path'].replace('/sdcard/', '')} | {gb(x['size'])} | {x['date']} |" for x in files["biggest"][:20]]
    for k, v in (files.get("contents") or {}).items():
        if v:
            lines += ["", f"In {k}: " + ", ".join(v[:30]) + ("…" if len(v) > 30 else "")]
    blocked = [a for a in apps if a["blocked"]]
    if blocked:
        lines += ["", f"Not looked at (block list: banking, payments, passwords): {', '.join(a['package'] for a in blocked)}."]
    potential = sum(a["total"] for a in big_unused) + old_total + sum(a["cache"] for a in apps)
    lines += ["", "### What it would bring", "",
              f"Removing the {len(big_unused)} biggest unused apps frees about {gb(sum(a['total'] for a in big_unused))}; "
              f"the caches about {gb(sum(a['cache'] for a in apps))}; files older than a year about {gb(old_total)}. Together that is "
              f"roughly {gb(potential)} more free space.", "",
              "To act: tell Hermes in Chat \"on the AI phone, uninstall …\" (each app asks you once) or \"trim the app caches\". "
              "Old files: \"on the AI phone, delete …\" (the table above has the exact words); every deletion shows what and "
              "how much and waits for your tap, also inside an allowance. Nothing is deleted by this analysis."]
    summary = (f"{gb(free)} free of {gb(s['total'])}; {len(unused)} apps unused for {UNUSED_DAYS}+ days "
               f"({gb(sum(a['total'] for a in unused))}); WhatsApp media {gb(sum(wa.values()))}")
    return "\n".join(lines), summary


VERDICT = {"safe": "✅ safe", "caution": "⚠️ caution", "never": "⛔ never"}


def pc_report(scan, fresh, docker=()):
    drives = scan.get("drives", [])
    lines = [f"Scan of {', '.join(d['root'] for d in drives)}: {scan.get('files', 0):,} files in {scan.get('seconds', 0) // 60} min"
             f"{'' if fresh else ' (the last scan: Windows did not answer a new request in time)'}.", "",
             "### Drives", "", "| Drive | Used | Free |", "|---|---|---|"]
    lines += [f"| {d['root']} {d.get('label') or ''} | {gib(d['total'] - d['free'])} of {gib(d['total'])} | **{gib(d['free'])}** "
              f"({100 * d['free'] / max(d['total'], 1):.0f} %) |" for d in drives]
    lines += ["", "### Easy wins", "", "| What | Size | Verdict | How |", "|---|---|---|---|"]
    for c in scan.get("clutter", []):
        if c["size"] >= 50e6:
            lines.append(f"| {c['label']} | {gib(c['size'])} | {VERDICT.get(c['verdict'], c['verdict'])} | {c['how']} |")
    old = scan.get("old_installers", [])
    if old:
        lines += ["", f"Old installers in Downloads (90+ days): {gib(sum(x['size'] for x in old))}: "
                  + ", ".join(f"{x['name']} ({gib(x['size'])})" for x in old[:8]) + "."]
    backups = [f for f in scan.get("top_files", []) if re.search(r"before-fsck|\.vhdx$|backup", f["path"], re.I) and "\\wsl\\" not in f["path"].lower()]
    if backups:
        lines += ["", "### Old backups and disk images", ""]
        lines += [f"- {f['path']}: {gib(f['size'])} (from {f['modified']}). ⚠️ caution: keep it only if you still need that state; "
                  "the stack's own backups are encrypted on the NAS and OneDrive." for f in backups[:5]]
    lines += ["", "### Biggest folders", "", "| Folder | Size |", "|---|---|"]
    shown = []
    for d in scan.get("dirs", []):
        if d["depth"] < 1 or any(d["path"].startswith(p + "\\") and d["size"] > 0.8 * s for p, s in shown):
            continue                                   # skip a folder that is most of its already-listed parent
        shown.append((d["path"], d["size"]))
        lines.append(f"| {d['path']} | {gib(d['size'])} |")
        if len(shown) >= 25:
            break
    games = scan.get("steam_games", [])
    if games:
        lines += ["", f"### Steam games on C: ({gib(sum(g['size'] for g in games))})", "",
                  "⚠️ caution: uninstall in Steam what you no longer play (you can always reinstall).", ""]
        lines += [f"- {g['name']}: {gib(g['size'])}" for g in games[:10]]
    lines += ["", "### Biggest files", ""] + [f"- {f['path']}: {gib(f['size'])} ({f['modified']})" for f in scan.get("top_files", [])[:12]]
    if docker:
        lines += ["", "### Docker inside WSL (the AI stack)", ""]
        lines += [f"- {x.get('Type')}: {x.get('Size')} ({x.get('Reclaimable')} reclaimable)" for x in docker]
        lines += ["", "⛔ never delete the WSL disk itself; unused Docker images can be pruned by the stack later (asks you first)."]
    lines += ["", "Nothing was deleted. ✅ safe items you can clear yourself (Disk Cleanup, the Recycle Bin, browser settings); "
              "⚠️ caution items need a look first; ⛔ never items are left alone."]
    c = next((d for d in drives if d["root"].startswith("C")), drives[0] if drives else {"free": 0, "total": 1})
    safe = sum(x["size"] for x in scan.get("clutter", []) if x["verdict"] == "safe")
    summary = f"C: {gib(c['free'])} free of {gib(c['total'])}; {gib(safe)} safe to clear right away"
    return "\n".join(lines), summary


def run(m, logf, ev=None):
    global STEPS
    STEPS = Path(logf).with_suffix(".events.jsonl")            # runs/<id>.events.jsonl, read by ops/telemetry.py
    STEPS.unlink(missing_ok=True)
    target = target_of(m)
    step("say", "Cleanup analysis", f"Target: {'the AI phone' if target == 'phone' else 'the PC'}. Read-only: nothing is deleted.")
    if target == "phone":
        body, summary = phone_report(phone_facts())
    else:
        scan, fresh = pc_facts()
        body, summary = pc_report(scan, fresh, docker_usage())
    note = ""
    key = os.environ.get("VK_MISSION", "")
    if key:                                    # a short take on top, when ChatGPT is available; the report stands without it
        try:
            t0 = time.time()
            note = M.ask_text("In 3 to 5 short bullet points in English, the most useful cleanup steps for the owner from this "
                              "report, biggest gain first, with the size; say which are safe and which need a look. No preamble.\n\n"
                              + body[:12000], key, model="gpt-sub-fast", timeout=120).strip()  # cap: prompt
            step("say", "First steps (gpt-sub-fast)", note, int((time.time() - t0) * 1000))
        except Exception as e:
            M.log(f"cleanup summary skipped: {type(e).__name__}")
            step("error", "First steps skipped", f"{type(e).__name__}: {str(e)} (the report stands without it)")
    step("say", "Result", summary)
    out = (f"## Result\n\n{('### First steps' + chr(10) + chr(10) + note + chr(10) + chr(10)) if note else ''}{body}\n\n"
           f"## Summary\n\n{summary}\n\n## Notes\n\nLast {target} cleanup analysis: {M.now():%d %b %Y %H:%M}: {summary}\n")
    Path(logf).write_text(out)
    return M.file_task_result(m, out, "cleanup analysis")

"""The stack's side of the Windows desk (PLT-31, DEC-43): WSL cannot start anything on Windows, so it leaves a question in a
folder that ops/windows/desk.ps1 fetches, and reads the answer from C:\\AI\\exports (read-only here). The app reads what this
publishes under /missions/windows; only the chat's tools can ask (images/mission-control/server.py)."""
import json
import os
import re
import time
import uuid
from pathlib import Path

M = None                                   # ops/missions.py, set by its main()
ACTIONS = {"windows_ask"}
INBOX = Path("/srv/ai/state/windesk/requests")
ANSWERS = Path("/srv/win-exports/.host/desk")
OUT = Path("/srv/ai/missions/windows")
QUESTION_MAX = 20000                       # cap: api: a question, not a document; the answer says so rather than cutting it
ALIVE_S = 60                               # the desk writes its status every 10 s
PICKUP_S = 120                             # it looks every 3 s: longer and it is not running
ANSWER_S = 1200                            # it stops Claude after 15 minutes
KEEP_S = 30 * 86400
IDS = re.compile(r"[a-f0-9]{12}")


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def alive():
    st = read(ANSWERS / "status.json")
    return bool(st and time.time() - st.get("ts", 0) < ALIVE_S)


def handle(req):
    if req.get("source") != "chat":
        return {"ok": False, "error": "asked only from a chat"}
    question = str(req.get("question") or "").strip()
    if not question:
        return {"ok": False, "error": "no question"}
    if len(question) > QUESTION_MAX:
        return {"ok": False, "error": f"the question is {len(question):,} characters; {QUESTION_MAX:,} at most"}
    if not alive():
        return {"ok": False, "error": "the Windows desk is not answering: the PC may be asleep, or it is not installed (ops/windows/desk-setup.ps1)"}
    rid, now = uuid.uuid4().hex[:12], int(time.time())   # cap: id
    folder = str(req.get("folder") or "").strip()
    save(OUT / f"{rid}.json", {"id": rid, "status": "queued", "question": question, "folder": folder, "at": now})
    save(INBOX / f"{rid}.json", {"question": question, "folder": folder, "at": now})
    return {"id": rid}


def step(now=None):
    """Publish the desk's status and carry each open question on."""
    now = now or time.time()
    st = read(ANSWERS / "status.json")
    if st:
        save(OUT / "status.json", st)
    for f in OUT.glob("*.json") if OUT.exists() else ():
        if not IDS.fullmatch(f.stem):
            continue
        t = read(f)
        if not t:
            continue
        if t["status"] in ("done", "failed"):
            if now - t.get("ended", now) > KEEP_S:
                f.unlink(missing_ok=True)
            continue
        got = read(ANSWERS / f.name)
        if got and got.get("status") in ("running", "done", "failed") and got["status"] != t["status"]:
            t.update(got)
            if got["status"] == "running":
                t["picked"] = int(now)
            save(f, t)
        elif t["status"] == "queued" and now - t["at"] > PICKUP_S:
            (INBOX / f.name).unlink(missing_ok=True)
            t.update(status="failed", ended=int(now), error="The Windows desk did not fetch the question within 2 minutes: the PC may be asleep.")
            save(f, t)
        elif t["status"] == "running" and now - t.get("picked", t["at"]) > ANSWER_S:
            t.update(status="failed", ended=int(now), error="No answer from the Windows desk after 20 minutes: the PC may have gone to sleep.")
            save(f, t)


def worker():
    while not M.stop.is_set():
        try:
            step()
        except Exception as e:
            M.log(f"windows desk: {type(e).__name__}: {e}")
        M.stop.wait(3)

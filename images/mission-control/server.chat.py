# A part of server.py (PLT-25): chats with their history, and what a chat made. It runs in server.py's namespace where it stood (_part); not a module of its own.
# ---------- chats (server-side history) ----------
def chat_path(cid):
    return CHATS / f"{cid}.json" if re.fullmatch(r"[a-z0-9]{6,24}", cid or "") else None


def load_chat(cid):
    p = chat_path(cid)
    try:
        return json.loads(p.read_text()) if p else None
    except FileNotFoundError:
        return None


RT.CHAT_TITLE = lambda cid: (load_chat(cid) or {}).get("title")      # run names: "Chat · <title>"


def save_chat(c, touch=True):
    """touch=False keeps the chat where it is in the list (what it made was looked up, nothing new was said)."""
    CHATS.mkdir(parents=True, exist_ok=True)
    if touch or not c.get("updated"):
        c["updated"] = time.time()
    tmp = CHATS / f".{c['id']}.tmp"
    tmp.write_text(json.dumps(c, ensure_ascii=False))
    tmp.rename(chat_path(c["id"]))


MODELS = [{"id": "gpt-sub", "name": "GPT-6.1 Sol", "note": "strongest, ChatGPT subscription"},
          {"id": "gpt-sub-fast", "name": "GPT-6 Luna", "note": "fast, ChatGPT subscription"}]
EFFORTS = ["low", "medium", "high", "xhigh"]
FILES = CHATS / "files"
DOC_EXT = (".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md", ".json", ".html", ".py", ".js", ".ts", ".yaml", ".yml", ".log")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")


async def api_models(request):
    """The chat's model choices and reasoning efforts, with the default."""
    return JSONResponse({"models": MODELS, "efforts": EFFORTS, "default": {"model": "gpt-sub", "effort": "medium"}})


def chat_summary(c):
    kinds = {}
    for x in c.get("made") or []:                                    # the chat list's icons: what each chat made
        if x.get("verb") in ("made", "exists", "pending", "sent"):
            kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    said = next((m.get("content") or "" for m in reversed(c.get("messages") or []) if not m.get("note")), "")
    last = chat_title(re.sub(r"[*_#`>|]+", "", "A picture or a file" if said == "(see attachment)" else said), 54)   # the list's line, ended on a whole word and marked; the chat holds it whole
    return {k: c.get(k) for k in ("id", "title", "mission", "updated", "pinned", "pending", "origin")} | {"count": len(c.get("messages", [])), "made": kinds, "last": last}


def origin_of(request):
    """Who started a chat: "owner" from your own devices (through tailscale serve, which adds your login and the
    device's address), "ai-phone", or "automation" (the stack's own checks and helper agents call the app directly)."""
    ip = client_ip(request)
    if ip == AI_PHONE_IP:
        return "ai-phone"
    return "owner" if ip and request.headers.get("tailscale-user-login") else "automation"


async def api_chats(request):
    """The owner's chats, newest first, optionally filtered by a search text."""
    q = request.query_params.get("q", "").strip().lower()
    out = []
    for p in CHATS.glob("*.json") if CHATS.exists() else []:
        try:
            c = json.loads(p.read_text())
        except Exception:
            continue
        if q and q not in (c.get("title") or "").lower() and not any(q in m.get("content", "").lower() for m in c.get("messages", [])):
            continue
        out.append(chat_summary(c))
    return JSONResponse(sorted(out, key=lambda c: (not c.get("pinned"), -c["updated"])))


async def api_chat_one(request):
    """One chat: GET reads it, PATCH renames or pins it, DELETE removes it with its attached files."""
    cid = request.path_params["cid"]
    c = load_chat(cid)
    if request.method == "DELETE":
        p = chat_path(cid)
        if p and p.exists():
            for a in (c or {}).get("files", []):
                for f in FILES.glob(f"{a}*"):
                    f.unlink(missing_ok=True)
            p.unlink()
        return JSONResponse({"ok": True})
    if not c:
        return JSONResponse({"error": "not found"}, status_code=404)
    if request.method == "GET":
        s = state()
        return JSONResponse(c | {"made": [made_view(x, s) for x in chat_made(c, s)]})
    if request.method == "PATCH":
        body = await request.json()
        c = load_chat(cid) or c                           # read after the await: an answer saved meanwhile stays (review APP-R20)
        if "title" in body:
            t = re.sub(r"\s+", " ", str(body["title"])).strip()
            if len(t) > 200:
                return JSONResponse({"ok": False, "error": f"the title is {len(t)} characters; the limit is 200"}, status_code=400)
            c["title"] = t or c.get("title")
        if "pinned" in body:
            c["pinned"] = bool(body["pinned"])
        updated = c.get("updated")
        save_chat(c)
        c["updated"] = updated
        return JSONResponse(chat_summary(c))
    return JSONResponse(c)


# ---------- what a chat made, reachable from the chat, and back (docs/CHAT-MADE.md, APP-39) ----------
# The run record has every tool result of every chat turn (runrecord.chat_made); the chat keeps what was resolved from
# them in c["made"] (a pending item's real id, whether its end was told), so it outlives the record's 90 days.
MADE_KEEP = ("key", "ts", "tool", "kind", "id", "verb", "title", "what", "rid", "told", "open_seen")
RID = re.compile(r"[0-9a-f]{16}")
RUN_STATE = {"ok": "done", "failed": "failed", "error": "failed", "stalled": "failed", "stopped": "failed"}
BUILD_STATE = {"review": "waits", "deployed": "done", "merged": "done", "failed": "failed", "rejected": "failed", "cancelled": "failed"}


def resolve_made(it, s):
    """A pending item (the runner was still at it when the tool answered) gets its real id: from the runner's answer
    while that is kept (an hour), else by its title (mission titles are unique: a second one is refused)."""
    rid = str(it.get("id") or "")[8:] if str(it.get("id") or "").startswith("request-") else ""
    if RID.fullmatch(rid):
        it["rid"] = rid
        try:
            r = json.loads((RESULTS / f"{rid}.json").read_text())
        except (OSError, ValueError):
            r = None
        if r is not None and not r.get("ok"):
            it.update(verb="failed", id=None, what=str(r.get("error") or "it could not be made"))
            return it
        got = (r or {}).get({"mission": "slug", "note": "path"}.get(it["kind"], "id"))
        if got:
            it.update(id=str(got), verb="exists" if r.get("duplicate") else "made")
            return it
    t = str(it.get("title") or "").strip().lower()
    pool = {"mission": s.get("missions"), "build": s.get("builds")}.get(it["kind"]) or []
    hit = next((x for x in pool if t and str(x.get("title") or "").strip().lower() == t), None)
    if hit:
        it.update(id=str(hit.get("slug") or hit.get("id")), verb="made")
    return it


def chat_made(c, s, fresh=None):
    """APP-39: what chat c made or changed, oldest first, with pending ones resolved; kept in the chat (saved when it
    changed, without moving the chat up the list). fresh: the run record's items for it (read here when not given)."""
    before = json.dumps(c.get("made") or [], sort_keys=True)
    have = {x["key"]: x for x in c.get("made") or []}
    if fresh is None:
        try:
            fresh = RT.chat_made(c["id"])
        except Exception as e:                                       # the record unreadable: what the chat kept still shows
            print(f"chat {c['id']}: what it made was not read: {type(e).__name__}: {e}", flush=True)
            fresh = []
    for it in fresh:
        have.setdefault(it["key"], {k: it[k] for k in MADE_KEEP if it.get(k) not in (None, "")})
    for it in have.values():
        if it.get("verb") == "pending":
            resolve_made(it, s)
    c["made"] = sorted(have.values(), key=lambda x: x["ts"])
    if json.dumps(c["made"], sort_keys=True) != before and chat_path(c["id"]):
        save_chat(c, touch=False)
    return c["made"]


def chat_title(text, n=60):
    """A chat's first title: its first message, whole words, the cut marked (the whole is the message itself)."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) <= n:
        return s
    return (s[:n].rsplit(" ", 1)[0] or s[:n]).rstrip(" ,.;:-") + "…"  # cap: id


def first_sentences(text, n=240):
    """A card's headline: the result's first sentence(s) up to n characters, the cut marked (the whole is on its page)."""
    s = re.sub(r"^[-*#>\s]+", "", re.sub(r"\s+", " ", str(text or ""))).strip()          # a summary's markdown bullet or heading
    if len(s) <= n:
        return s
    end = max(s.rfind(". ", 0, n), s.rfind("! ", 0, n), s.rfind("? ", 0, n))
    return s[:end + 1] + " (more on its page)" if end > n // 3 else TC.cut(s, n, "its page")  # cap: preview


def made_view(it, s):
    """One made item as the chat shows it: its name now, where it opens, its state (creating, queued, running, done,
    waits, failed, paused, sent, changed) and its result's headline."""
    k, i = it["kind"], str(it.get("id") or "")
    v = {x: it.get(x) for x in ("key", "ts", "kind", "id", "verb", "what", "tool")} | {"name": it.get("title") or "", "href": None,
                                                                                  "state": "", "line": "", "recurring": False}
    if it["verb"] == "failed":
        return v | {"state": "failed", "line": it.get("what") or ""}
    if it["verb"] == "pending":
        return v | {"state": "creating"}
    if k == "mission" and (m := next((x for x in s.get("missions") or [] if x["slug"] == i), None)):
        last = (m.get("runs") or [{}])[0]
        run = (s.get("running") or {}).get("slug") == i
        queued = any(q.get("slug") == i for q in s.get("queue") or [])
        fs = (((s.get("files") or {}).get("missions") or {}).get(i) or {}).get("files") or []     # MIS-23: what it made, before the report
        v["files"] = [{"name": f["name"], "href": f"#/file?m={urllib.parse.quote(i)}&n={urllib.parse.quote(f['name'])}"} for f in fs]
        v["files_missing"] = [a["name"] for a in m.get("files_asked") or [] if a["name"] not in {f["name"] for f in fs}]
        v.update(name=m["title"], href=f"#/mission/{urllib.parse.quote(i)}", line=first_sentences(last.get("summary")), ended=last.get("ended"),
                 recurring=m.get("schedule") != "manual" or bool(m.get("triggers")),
                 state="running" if run else "queued" if queued else RUN_STATE.get(last.get("status"), last.get("status") or "")
                 if last else "paused" if m["status"] == "paused" else "queued")
    elif k == "build" and (b := next((x for x in s.get("builds") or [] if str(x["id"]) == i), None)):
        v.update(name=f"Build #{i}: {b['title']}", href=f"#/build/{i}", line=first_sentences(b.get("summary") or b.get("error")),
                 state=BUILD_STATE.get(b["status"], "running"))
    elif k == "claude" and i:                                        # older ones leave the state; their run view stays
        t = next((x for x in s.get("claude_tasks") or [] if str(x["id"]) == i), None)
        v.update(name=f"Claude task #{i}", href=f"#/live/{urllib.parse.quote('claude-task:' + i)}", line=first_sentences((t or {}).get("question")),
                 state={"done": "done", "failed": "failed", "error": "failed"}.get(t["status"], "running") if t else "")
    elif k == "repo" and i:
        v.update(name=v["name"] or i, href=f"#/repo/{urllib.parse.quote(i)}", state="made")
    elif k == "note" and i:
        v.update(name=v["name"] or i.rsplit("/", 1)[-1], href=f"#/read?path={urllib.parse.quote(i)}", state="made")
    elif k == "email":
        v.update(state="sent")
    elif i:
        v.update(name=v["name"] or i, state="gone")                  # made here, no longer in the stack (removed)
    if it["verb"] == "changed":
        v["state"] = "changed"
    return v


MADE_IDX = {"t": 0, "v": {}}


def made_pass(now=None):
    """Every 30 s: what each chat made, kept in the chat; the reverse index for the "From a chat" link on an item's page;
    and a line in the chat when a one-off item it made ends (a mission run, a Claude task, a build waiting for review).
    An item already over when first seen is not announced: only an end this pass saw happen."""
    s, now = state(), now or time.time()
    try:
        fresh = {}
        for it in RT.chat_made():
            fresh.setdefault(it.pop("chat"), []).append(it)
    except Exception as e:
        print(f"made_pass: the run record was not read: {type(e).__name__}: {e}", flush=True)
        return MADE_IDX["v"]
    idx = {}
    for p in CHATS.glob("*.json") if CHATS.exists() else []:
        cid = p.stem
        try:
            c = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if cid not in fresh and not c.get("made"):
            continue
        items = chat_made(c, s, fresh.get(cid, []))
        told = []
        for it in items:
            if it.get("verb") in ("made", "exists") and it.get("id"):
                idx.setdefault(f"{it['kind']}:{it['id']}", {"chat": cid, "title": c.get("title") or "a chat", "ts": it["ts"], "key": it["key"]})
            if it.get("verb") != "made" or it.get("told") or it["kind"] not in ("mission", "claude", "build") or c.get("pending"):
                continue
            v = made_view(it, s)
            if v["recurring"]:
                continue                                             # a daily briefing does not write into the chat every day
            if v["state"] in ("done", "failed", "waits"):
                it["told"] = True
                if it.get("open_seen"):
                    told.append(v)
            elif v["state"] in ("queued", "running", "creating"):
                it["open_seen"] = True
        for v in told:
            say = {"done": "finished", "failed": "did not finish", "waits": "waits for your review"}[v["state"]]
            c["messages"].append({"role": "assistant", "ts": now, "note": True, "made_key": v["key"],
                                  "content": f"**{v['name']}** {say}: [open it]({v['href']})" + (f"\n\n{v['line']}" if v["line"] else "")})
        if json.dumps(c["made"], sort_keys=True) != json.dumps(json.loads(p.read_text()).get("made") or [], sort_keys=True) or told:
            save_chat(c, touch=bool(told))
    MADE_IDX.update(t=now, v=idx)
    return idx


async def made_watcher():
    while True:
        try:
            made_pass()
        except Exception as e:
            print(f"made_pass: {type(e).__name__}: {e}", flush=True)
        await asyncio.sleep(30)


def mission_context(slug):
    m = mission(slug)
    if not m:
        return ""
    d = {k: m.get(k) for k in ("title", "type", "status", "schedule_text", "goal", "depth", "triggers", "brief", "notes")}
    d["last_runs"] = [{k: r.get(k) for k in ("started", "status", "summary")} for r in (m.get("runs") or [])[:3]]  # cap: top
    return (f"This conversation is about the mission '{m['title']}' (slug '{slug}'). Help the owner tune its focus: discuss what "
            "it should track, then apply agreed changes with mission_update (briefings: key_questions, searches, watchlist, "
            "notes; tasks: goal) or mission_set_triggers, using this slug, and say exactly what you changed. To answer "
            "questions about its results, search the vault (its reports, alerts and wiki).\nCurrent mission:\n"
            + TC.cut(json.dumps(d, ensure_ascii=False), 6000))  # cap: prompt


def doc_text(path, name):
    """Readable text of an attached document (Hermes' API takes images, not files)."""
    n = name.lower()
    try:
        if n.endswith(".pdf"):
            from pypdf import PdfReader
            r = PdfReader(str(path))
            # limit: drops, PDF pages past 300 in an attachment; the text says how many it has
            return "\n\n".join(f"--- page {i} ---\n{(pg.extract_text() or '').strip()}" for i, pg in enumerate(r.pages[:300], 1)) + (f"\n\n(only the first 300 of {len(r.pages)} pages)" if len(r.pages) > 300 else "")  # cap: prompt
        if n.endswith(".docx"):
            import docx
            d = docx.Document(str(path))
            parts = [para.text for para in d.paragraphs]
            for t in d.tables:
                parts += [" | ".join(cell.text for cell in row.cells) for row in t.rows]
            return "\n".join(parts)
        if n.endswith(".xlsx"):
            import openpyxl
            wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
            out = []
            for ws in wb.worksheets[:10]:  # cap: list (the text says how many more)
                out.append(f"--- sheet {ws.title} ---")
                for row in ws.iter_rows(max_row=2000, values_only=True):
                    out.append(" | ".join("" if v is None else str(v) for v in row))
                if (ws.max_row or 0) > 2000:
                    out.append(f"(only the first 2,000 of {ws.max_row:,} rows of this sheet)")
            # limit: drops, sheets past 10 in an attachment; the text says how many it left out
            if len(wb.worksheets) > 10:
                out.append(f"(… and {len(wb.worksheets) - 10} more sheets, not read)")
            return "\n".join(out)
        return path.read_text(errors="replace")
    except Exception as e:
        return f"(could not read {name}: {type(e).__name__})"


ATTACH_MB, UPLOAD_MB = 30, 25        # limit: refuses (a chat attachment, a vault upload; the app has 256 MB, so a body is never read past these)


async def body_within(request, mb):
    """The request's body, refused past mb megabytes before it is in memory (review APP-R16: a large body was read whole,
    and the app, at 256 MB, was killed with every chat answer in progress). -> (bytes, None) or (None, the reason)."""
    n = mb * 1024 * 1024
    try:
        if int(request.headers.get("content-length") or 0) > n:
            return None, f"file too large ({mb} MB max)"
    except ValueError:
        return None, "invalid Content-Length"
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > n:
            return None, f"file too large ({mb} MB max)"
    return bytes(data), None


async def api_chat_upload(request):
    """An attachment for the next chat message: images go to Hermes as images, documents as extracted text."""
    if (no := not_from_ai_phone(request)):
        return no
    data, err = await body_within(request, ATTACH_MB)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    info, err = await store_attachment(request.headers.get("x-filename", "file"), data)
    return JSONResponse({"error": err}, status_code=400) if err else JSONResponse(info)


async def store_attachment(name, data):
    """Keep a file for a chat message (also what the phone shares); returns (info, None) or (None, error)."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name or "file")[-80:].lstrip(".-") or "file"  # cap: id
    low = name.lower()
    kind = "image" if low.endswith(IMG_EXT) else "doc" if low.endswith(DOC_EXT) else None
    if not kind:
        return None, "supported: images, PDF, Word, Excel, CSV, text and code files"
    if len(data) > (15 if kind == "image" else 30) * 1024 * 1024:
        return None, "file too large"
    FILES.mkdir(parents=True, exist_ok=True)
    fid = uuid.uuid4().hex[:16]
    path = FILES / f"{fid}-{name}"
    path.write_bytes(data)
    info = {"id": fid, "name": name, "kind": kind, "size": len(data)}
    if kind == "doc":
        text = await asyncio.to_thread(doc_text, path, name)
        (FILES / f"{fid}.txt").write_text(text)
        info["chars"] = len(text)
    return info, None

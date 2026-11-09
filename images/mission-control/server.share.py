# A part of server.py (PLT-25): the phone's Share menu. It runs in server.py's namespace where it stood (_part); not a module of its own.
# ---------- share target: the phone's Share menu -> Mission Control (manifest share_target) ----------
# Whatever is shared (a link, text, pictures, documents) is only kept here; the app then asks what to do with it.
# Nothing runs by itself, so a forged POST from another site can at most leave an item in this list.
SHARES = DATA / "shares"
SHARE_MB = 60                        # limit: refuses (one share: up to six pictures or files, said to the sharer)
URL_IN_TEXT = re.compile(r"https?://[^\s<>\"]+")


async def share(request):
    """The PWA share target: keeps what was shared (link, text, pictures, files) for 14 days and opens it in the app (APP-15)."""
    try:                                                 # review APP-R16: /share takes posts from anywhere; its size is checked first
        too_big = int(request.headers.get("content-length") or 0) > SHARE_MB * 1024 * 1024
    except ValueError:
        too_big = True
    if too_big:
        return PlainTextResponse(f"Too much to share at once: at most {SHARE_MB} MB.", status_code=413)
    form = await request.form(max_files=6, max_fields=10)
    rec = {"id": uuid.uuid4().hex[:16], "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "title": TC.cut(str(form.get("title") or ""), 300).strip(),  # cap: untrusted
           "text": cut(str(form.get("text") or "").strip(), 200000), "url": str(form.get("url") or "")[:2000].strip(),  # cap: api (a URL; a marker would break it)
           "files": [], "errors": []}
    if not rec["url"] and (m := URL_IN_TEXT.search(rec["text"])):     # Android apps usually put the link in the text
        rec["url"] = m.group(0).rstrip(").,;")
    if rec["url"] and not rec["url"].startswith(("http://", "https://")):
        rec["url"] = ""
    for f in form.getlist("files"):
        if hasattr(f, "read"):
            info, err = await store_attachment(f.filename or "shared", await f.read())
            rec["files"].append(info) if info else rec["errors"].append(f"{f.filename}: {err}")
    SHARES.mkdir(parents=True, exist_ok=True)
    for old in SHARES.glob("*.json"):                                   # keep two weeks
        if time.time() - old.stat().st_mtime > 14 * 86400:
            old.unlink(missing_ok=True)
    write_atomic(SHARES / f"{rec['id']}.json", json.dumps(rec, ensure_ascii=False))
    return RedirectResponse(f"/#/share/{rec['id']}", status_code=303)


def share_rec(sid):
    p = SHARES / f"{sid}.json"
    return json.loads(p.read_text()) if re.fullmatch(r"[a-f0-9]{16}", sid or "") and p.exists() else None


async def api_share(request):
    """One shared item, for its page with the one-tap choices."""
    rec = share_rec(request.path_params["sid"])
    return JSONResponse(rec) if rec else JSONResponse({"error": "not found"}, status_code=404)


async def api_share_save(request):
    """Save a shared item into the knowledge base: the link's page, the text, and every document or picture."""
    rec = share_rec(request.path_params["sid"])
    if not rec:
        return JSONResponse({"error": "not found"}, status_code=404)
    done = []
    if rec["url"]:
        done.append(await submit({"action": "vault_add", "title": rec["title"], "url": rec["url"], "source": "app"}, wait=20))
    elif rec["text"]:
        done.append(await submit({"action": "vault_add", "title": rec["title"] or rec["text"][:60], "text": rec["text"], "source": "app"}, wait=20))  # cap: id
    UPLOADS.mkdir(parents=True, exist_ok=True)
    for f in rec["files"]:
        src = file_of(f["id"])
        if src and f["name"].lower().endswith((".pdf", ".docx", ".md", ".txt", ".html", ".xlsx", ".csv", ".png", ".jpg")):
            name = f"{time.strftime('%Y%m%d-%H%M%S')}-{f['name']}"
            shutil.copyfile(src, UPLOADS / name)
            (UPLOADS / name).chmod(0o644)
            done.append(await submit({"action": "vault_add", "upload": name, "title": rec["title"], "source": "app"}, wait=20))
    ok = [d for d in done if d.get("ok", True) and not d.get("error")]
    return JSONResponse({"saved": len(ok), "of": len(done), "errors": [d.get("error") for d in done if d.get("error")]})


def file_of(fid):
    if not re.fullmatch(r"[a-f0-9]{16}", fid or ""):
        return None
    return next(iter(FILES.glob(f"{fid}-*")), None)


async def api_chat_file(request):
    """A file attached to a chat."""
    f = file_of(request.path_params["fid"])
    return FileResponse(f) if f else JSONResponse({"error": "not found"}, status_code=404)


def to_hermes(m, current):
    """One stored message as Hermes input: documents as text (recent turns), images only on the current turn."""
    if m["role"] != "user" or not m.get("attachments"):
        return {"role": m["role"], "content": m["content"]}
    text, images = m["content"], []
    for a in m["attachments"]:
        if a["kind"] == "doc":
            t = FILES / f"{a['id']}.txt"
            body = cut(t.read_text(), 120000, "the model reads the start of the document") if t.exists() else "(not readable)"  # cap: prompt
            text += f"\n\n[Attached document: {a['name']}]\n{body}\n[End of {a['name']}]"
        elif current and (f := file_of(a["id"])):
            mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif"}.get(f.suffix.lstrip(".").lower(), "png")
            images.append({"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{base64.b64encode(f.read_bytes()).decode()}"}})
        else:
            text += f"\n\n[Image attached earlier: {a['name']}]"
    return {"role": "user", "content": [{"type": "text", "text": text}] + images if images else text}


def build_request(c, model, effort):
    """Hermes request for the newest turn. Hermes keeps the conversation server-side (X-Hermes-Session-Id: its history,
    tool calls included, comes from Hermes' state.db, which also compresses long chats), so only the new message is
    sent: no re-sending of earlier turns, documents or pictures. A chat without a Hermes session yet (older chats) or
    one that was cut back (edit / regenerate) starts a new session, seeded once with the earlier turns as context."""
    system = [f"chat mission-control-{c['id']}"]
    if c.get("mission"):
        system.append(mission_context(c["mission"]))
    msgs = c["messages"]
    if not c.get("hsid"):
        c["hsid"] = f"mc-{c['id']}-{c.get('hrev', 0)}"
        earlier = msgs[:-1][-12:]
        if earlier:
            system.append("Earlier in this conversation (context; these turns are already answered):\n\n" +
                          "\n\n".join(f"{m['role']}: {TC.cut(m['content'], 4000)}" for m in earlier))  # cap: prompt
    payload = {"model": model, "provider": "custom", "model_options": {"reasoning_effort": effort}, "stream": True,
               "messages": [{"role": "system", "content": "\n\n".join(system)}, to_hermes(msgs[-1], True)]}
    return payload, {"X-Hermes-Session-Id": c["hsid"]}


LIVE = {}            # chat id -> answer in progress: text, reasoning, tools, done; the Hermes call is a background task
RUNNING = {}         # chat id -> asyncio task (for stop)
LIMITED = {}         # chat id -> when its message is tried again (AST-12: the subscription's usage limit)
LIMIT = re.compile(r"usage.?limit|rate.?limit|ratelimit|\b429\b|too many requests|hit your limit", re.I)
# limit: waits, a chat that met a usage limit is tried again this often (AST-12)
LIMIT_RETRY = 15 * 60                    # no reset time in the error: try again every 15 minutes
# limit: stops, a chat still limited after a day stops waiting and says so (AST-12)
LIMIT_GIVE_UP = 24 * 3600                # still limited after a day: stop and say so


def reset_in(text):
    """Seconds until the usage limit resets, from the provider's error (ChatGPT sends resets_at), or None."""
    m = re.search(r'resets?_in_seconds\W{0,3}(\d+)', text)
    if m:
        return int(m[1])
    m = re.search(r'resets?_at\W{0,3}(\d{10})', text)
    if m:
        return max(0, int(m[1]) - int(time.time()))
    m = re.search(r"(?:try again|resets?) in (?:about )?(\d+(?:\.\d+)?)\s*(s|sec|seconds?|m|min|minutes?|h|hours?)\b", text, re.I)
    return int(float(m[1]) * {"s": 1, "m": 60, "h": 3600}[m[2][0].lower()]) if m else None


def limit_of(status, text, tools=()):
    """AST-12: did the answer fail on the subscription's usage limit (not a real error)? -> (bool, seconds to reset).
    A normal answer that talks about rate limits is not one: it has to be a short error without any tool work."""
    t = text or ""
    hit = status == 429 or (status not in (None, 200) and LIMIT.search(t)) or (
        not tools and len(t) < 2000 and re.search(r"RateLimitError|usage_limit_reached|usage limit (?:has been |was )?reached|hit your limit", t, re.I))
    return (True, reset_in(t)) if hit else (False, None)


def tool_label(d):
    name = str(d.get("tool") or d.get("name") or d.get("tool_name") or "tool")
    name = re.sub(r"^mcp__\w+?__", "", name)
    return {"name": name, "status": str(d.get("status") or d.get("event") or d.get("phase") or ""),
            "detail": str(d.get("preview") or d.get("summary") or d.get("args_preview") or d.get("message") or "")}


async def run_chat(c, payload, headers=None, retry=False):
    """Talk to Hermes in the background: the answer is saved even if the phone drops the connection or sleeps. On the
    usage limit the message is kept and answered by itself after the reset (AST-12, limit_retrier)."""
    live = LIVE[c["id"]] = {"text": "", "reasoning": "", "tools": [], "done": False, "stopped": False, "status": None}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(1800, connect=10)) as h:
            async with h.stream("POST", HERMES, json=payload,
                                headers={"Authorization": f"Bearer {HERMES_KEY}", **(headers or {})}) as r:
                live["status"] = r.status_code
                if r.status_code != 200:
                    live["text"] = f"⚠ Hermes answered HTTP {r.status_code}: {cut((await r.aread()).decode(errors='replace'), 4000)}"  # cap: untrusted
                else:
                    ev = ""
                    async for line in r.aiter_lines():
                        if line.startswith("event:"):
                            ev = line[6:].strip()
                            continue
                        if not line.startswith("data: ") or line == "data: [DONE]":
                            if not line:
                                ev = ""
                            continue
                        try:
                            j = json.loads(line[6:])
                        except Exception:
                            continue
                        if ev == "hermes.tool.progress":
                            t = tool_label(j)
                            same = next((x for x in live["tools"] if x["name"] == t["name"] and x["status"] != "completed"), None)
                            if same and t["status"] in ("completed", "done", "finished", "error", "failed"):
                                same.update(status="completed" if t["status"] in ("completed", "done", "finished") else "failed")
                            elif not same or t["detail"] != same["detail"]:
                                live["tools"].append(t)
                            continue
                        ch = (j.get("choices") or [{}])[0]
                        delta = ch.get("delta", {})
                        live["text"] += delta.get("content") or ""
                        if ch.get("finish_reason") in ("length", "max_tokens"):
                            live["cut"] = True                # the model stopped at its output limit: said under the answer
                        live["reasoning"] += delta.get("reasoning_content") or delta.get("reasoning") or ""
    except asyncio.CancelledError:
        live["stopped"] = True
    except Exception as e:
        live["text"] += f"\n\n⚠ Hermes not reachable ({type(e).__name__})"
    finally:
        c = load_chat(c["id"]) or c
        limited, reset = (False, None) if live["stopped"] else limit_of(live["status"], live["text"], live["tools"])
        effort = (payload.get("model_options") or {}).get("reasoning_effort")
        if limited:
            now, prev = time.time(), c.get("limit") or {}
            at = now + (reset + 60 if reset is not None else LIMIT_RETRY)
            c["limit"] = {"retry_at": at, "since": prev.get("since", now), "tries": prev.get("tries", 0) + 1,
                          "model": payload.get("model"), "effort": effort, "reset_known": reset is not None}
            c["messages"].append({"role": "assistant", "ts": now, "limit": {"retry_at": at, "reset_known": reset is not None},
                                  "detail": live["text"], "model": payload.get("model"),
                                  "content": "⏳ **The ChatGPT subscription's usage limit is reached.** Your message is kept and is answered "
                                             "here by itself " + ("when the limit resets." if reset is not None else
                                                                  "as soon as the limit is over (it tries every 15 minutes).")
                                             + " You get a notification when the answer is ready."})
            LIMITED[c["id"]] = at
        else:
            c["messages"].append({"role": "assistant", "ts": time.time(),
                                  "content": (live["text"] or ("_(stopped)_" if live["stopped"] else "(no answer)")) + ("\n\n_(stopped)_" if live["stopped"] and live["text"] else "")
                                  + ("\n\n_(The answer stopped at the model's output limit. Ask it to go on.)_" if live.get("cut") else ""),
                                  "reasoning": tail(live["reasoning"], 200000), "tools": live["tools"][-400:],  # cap: list (the newest 400 tool calls; the run record keeps every one)
                                  "model": payload.get("model"), "effort": effort})
            if c.pop("limit", None) is not None:
                LIMITED.pop(c["id"], None)
                if retry and live["text"]:                # the owner may have left: tell them through the one path (OBS-16)
                    await submit({"action": "chat_ready", "chat": c["id"], "title": c.get("title", "")}, wait=0)
        c["pending"] = False
        save_chat(c)
        live["done"] = True
        RUNNING.pop(c["id"], None)
    await asyncio.sleep(120)
    LIVE.pop(c["id"], None)


async def api_chat(request):
    """Start a chat turn: stored at once, answered in the background; follow it with /api/chats/<id>/stream.
    Body: message, chat?, mission?, model?, effort?, attachments? [ids from /api/chat/upload], truncate? (edit/regenerate:
    drop messages from this index first)."""
    body = await request.json()
    text = str(body.get("message", "")).strip()
    if len(text) > 100000:
        return JSONResponse({"ok": False, "error": f"the message is {len(text):,} characters; the limit is 100,000: attach it as a document"}, status_code=400)
    atts = []
    for a in body.get("attachments") or []:
        f = file_of(a.get("id"))
        if f:
            atts.append({"id": a["id"], "name": f.name.split("-", 1)[1], "kind": "image" if f.name.lower().endswith(IMG_EXT) else "doc"})
    if not text and not atts:
        return JSONResponse({"error": "empty"}, status_code=400)
    c = load_chat(body.get("chat")) or {"id": uuid.uuid4().hex[:12], "created": time.time(), "messages": [],
                                        "mission": body.get("mission") if mission(body.get("mission") or "") else None,
                                        "origin": origin_of(request)}
    if c.get("pending") and c["id"] in LIVE and not LIVE[c["id"]]["done"]:
        return JSONResponse({"error": "still answering the last message"}, status_code=409)
    if isinstance(body.get("truncate"), int) and 0 <= body["truncate"] <= len(c["messages"]):
        c["messages"] = c["messages"][:body["truncate"]]
        c["hrev"] = c.get("hrev", 0) + 1          # Hermes' copy can't be cut back: continue in a fresh session
        c.pop("hsid", None)
    if not c["messages"]:
        c["title"] = (f"{mission(c['mission'])['title']}: " if c.get("mission") else "") + chat_title(text or atts[0]["name"])
    model = body.get("model") if body.get("model") in {m["id"] for m in MODELS} else "gpt-sub"
    effort = body.get("effort") if body.get("effort") in EFFORTS else "medium"
    c["messages"].append({"role": "user", "content": text or "(see attachment)", "ts": time.time(), "attachments": atts})
    if c.pop("limit", None) is not None:          # a new message replaces the one that waited for the usage limit
        LIMITED.pop(c["id"], None)
    c["files"] = sorted(set(c.get("files", []) + [a["id"] for a in atts]))
    c["pending"] = True
    payload, headers = build_request(c, model, effort)
    save_chat(c)
    t = asyncio.get_running_loop().create_task(run_chat(c, payload, headers))
    RUNNING[c["id"]] = t
    TASKS.add(t)
    t.add_done_callback(TASKS.discard)
    return JSONResponse({"chat": c["id"], "title": c["title"]})


async def api_chat_retry(request):
    """Try a message that waits for the usage limit now, instead of at its next try (AST-12)."""
    cid = request.path_params["cid"]
    c = load_chat(cid)
    if not c or not c.get("limit"):
        return JSONResponse({"ok": False, "error": "nothing waits for the usage limit in this chat"})
    LIMITED[cid] = time.time()
    return JSONResponse({"ok": True})


async def limit_retrier():
    """AST-12: a chat message that hit the usage limit is sent again at its retry time; after a day it stops and says so."""
    for p in CHATS.glob("*.json") if CHATS.exists() else []:        # waiting messages survive a restart of the app
        try:
            c = json.loads(p.read_text())
            if c.get("limit"):
                LIMITED[c["id"]] = c["limit"]["retry_at"]
        except (OSError, ValueError, KeyError) as e:
            print(f"chat {p.name}: its usage-limit wait was not read: {type(e).__name__}", flush=True)
    while True:
        await asyncio.sleep(20)
        retry_due()


def retry_due():
    """One pass: every waiting chat message whose time has come is sent to Hermes again."""
    for cid, at in list(LIMITED.items()):
        if at > time.time() or cid in RUNNING:
            continue
        LIMITED.pop(cid, None)
        c = load_chat(cid)
        if not c or not c.get("limit") or c.get("pending"):
            continue
        lim = c["limit"]
        while c["messages"] and c["messages"][-1].get("limit"):
            c["messages"].pop()                           # the waiting notice gives way to the answer
        if time.time() - lim["since"] > LIMIT_GIVE_UP or not c["messages"] or c["messages"][-1]["role"] != "user":
            c.pop("limit")
            c["messages"].append({"role": "assistant", "ts": time.time(), "content": "⚠ The usage limit did not end within a day, "
                                  "so this message was not answered. Send it again when the subscription works again."})
            save_chat(c)
            continue
        c["pending"] = True
        payload, headers = build_request(c, lim.get("model") or "gpt-sub", lim.get("effort") or "medium")
        save_chat(c)
        t = asyncio.get_running_loop().create_task(run_chat(c, payload, headers, retry=True))
        RUNNING[cid] = t
        TASKS.add(t)
        t.add_done_callback(TASKS.discard)


async def api_chat_stop(request):
    """Stops the answer that is being written in a chat."""
    t = RUNNING.get(request.path_params["cid"])
    if t and not t.done():
        t.cancel()
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "error": "nothing running"})


TASKS = set()


async def api_chat_stream(request):
    """SSE of the answer in progress: {text, reasoning, tools, done}; keep-alive pings; reconnectable."""
    cid = request.path_params["cid"]

    async def gen():
        yield "retry: 2000\n\n"
        last, t0 = None, time.time()
        while not await request.is_disconnected():
            live = LIVE.get(cid)
            if live:
                cur = {k: live[k] for k in ("text", "reasoning", "tools", "done", "stopped")}
            else:
                c = load_chat(cid) or {}
                done = not c.get("pending")
                m = (c.get("messages") or [{}])[-1] if done else {}
                cur = {"text": m.get("content", ""), "reasoning": m.get("reasoning", ""), "tools": m.get("tools", []), "done": done, "stopped": False}
            sig = json.dumps(cur, sort_keys=True)
            if sig != last:
                last = sig
                yield f"data: {sig}\n\n"
            if cur["done"]:
                return
            if time.time() - t0 > 10:
                yield ": ping\n\n"
                t0 = time.time()
            await asyncio.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


UPLOADS = DATA / "uploads"


async def api_upload(request):
    """A file from the phone for the vault inbox (PDF, Word, text, markdown); the runner files it."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", request.headers.get("x-filename", "upload"))[-80:].lstrip(".-") or "upload"  # cap: id
    if not name.lower().endswith((".pdf", ".docx", ".md", ".txt", ".html", ".pptx", ".xlsx", ".csv", ".png", ".jpg")):
        return JSONResponse({"ok": False, "error": "file type not supported"}, status_code=400)
    data, err = await body_within(request, UPLOAD_MB)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{name}"
    (UPLOADS / name).write_bytes(data)
    (UPLOADS / name).chmod(0o644)
    return JSONResponse(await submit({"action": "vault_add", "upload": name, "title": request.headers.get("x-title", ""), "source": "app"}, wait=20))

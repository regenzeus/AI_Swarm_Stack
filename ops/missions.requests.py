# A part of missions.py (PLT-25): the requests from the app and the chat. It runs in missions.py's namespace where it stood (_part); not a module of its own.
# ---------- requests (app, chat via MCP) ----------
def slugify(title, missions):
    s = unicodedata.normalize("NFKD", title.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss"))
    s = re.sub(r"[^a-z0-9]+", "-", s.encode("ascii", "ignore").decode()).strip("-")[:40] or "mission"  # cap: id
    base, n = s, 2
    while s in missions or (VAULT / "topics" / s).exists():
        s, n = f"{base}-{n}", n + 1
    return s


def words(t):
    return {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2}


def duplicate_of(title, missions):
    """A mission created in the last 30 minutes with a similar title (chat tools sometimes retry a slow create)."""
    w = words(title)
    for m in missions.values():
        if m.get("status") == "archived":
            continue
        try:
            age = now() - dt.datetime.fromisoformat(str(m.get("created")))
        except ValueError:
            continue
        o = words(m["title"])
        if age < dt.timedelta(minutes=30) and len(w & o) / max(len(w | o), 1) >= 0.4:
            return m
    return None


DRAFT = P.text("desk", "TOPIC_DRAFT")


def create_briefing(meta, req):
    example = (VAULT / "topics/copper/TOPIC.md").read_text()
    d = ask_json(DRAFT.format(example=example, title=req["title"], description=req.get("description", "")), os.environ["VK_DESK"])
    watch = TC.first([w for w in d.get("watchlist", []) if isinstance(w, dict) and w.get("name")], 15, "watchlist entries")  # cap: untrusted (a model's draft the owner reviews; as many as the owner may set)
    spec = {"symbols": [w["symbol"] for w in watch if w.get("symbol")], "feeds": d.get("feeds", []), "filings": d.get("filings", [])}
    chk = subprocess.run(["docker", "run", "--rm", "-i", "--network", "aistack_webonly", "-e", "SEC_CONTACT", "aistack/desk:1", "--check"],
                         input=json.dumps(spec), capture_output=True, text=True, timeout=300)
    if chk.returncode or not chk.stdout.strip():
        raise RuntimeError(f"source check failed: {(chk.stderr.strip().splitlines() or ['?'])[-1]}")
    ok = json.loads(chk.stdout)
    for w in watch:
        if w.get("symbol") not in ok["symbols"]:
            w.pop("symbol", None)
        for k in ("aliases", "proxy"):
            if not w.get(k) or w.get(k) == "null":
                w.pop(k, None)
    # cap: untrusted (a model's draft the owner reviews)
    sections = TC.first([s for s in d.get("sections", []) if isinstance(s, str)], 10, "report sections") or \
               ["Headline", "In 60 seconds", "Key developments", "What to watch", "Open questions"]
    topic = {"topic": d.get("topic") or req["title"], "slug": meta["slug"], "language": "en",
             "mission": d.get("mission", req.get("description", "")), "key_questions": TC.first(d.get("key_questions", []), 8, "key questions"),  # cap: untrusted (a model's draft the owner reviews)
             "watchlist": watch,
             "sources": {"feeds": ok["feeds"], "search": TC.first([q for q in d.get("search", []) if isinstance(q, str)], 10, "search queries"),  # cap: untrusted (a model's draft the owner reviews)
                         "jobs": [{"what": str(j["what"])[:120], "where": str(j.get("where") or "")[:80],   # cap: id
                                   "radius_km": min(max(int(j.get("radius_km") or 50), 0), 200)}
                                  for j in TC.first(d.get("jobs") or [], 6, "job searches") if isinstance(j, dict) and j.get("what")],  # cap: untrusted (a model's draft the owner reviews)
                         "gdelt": [], "filings": ok["filings"], "prefer": d.get("prefer", []), "avoid": d.get("avoid", [])},
             "report": {"sections": sections, "length": "2 minutes to read"}, "window_hours": window_hours(meta.get("schedule"))}
    write_front(VAULT / "topics" / meta["slug"] / "TOPIC.md", topic, d.get("notes", ""))
    dropped = len(spec["symbols"]) - len(ok["symbols"]) + len(spec["feeds"]) - len(ok["feeds"])
    return f"{len(topic['key_questions'])} key questions, {len(watch)} watched, {len(topic['sources']['search'])} searches" + \
           (f", {dropped} broken sources dropped" if dropped else "")


TOPIC_FIELDS = {"key_questions", "search", "feeds", "filings", "watchlist", "mission", "notes"}
DELIVER = ("telegram", "app", "email")


def handle(req, missions, c):
    a = req.get("action")
    slug = req.get("slug", "")
    m = missions.get(slug)
    if a == "create":
        typ = req.get("type")
        title = str(req.get("title", "")).strip()
        sched = req.get("schedule") or ("daily 06:30" if typ == "briefing" else "manual")
        if typ not in KEY_OF or not 3 <= len(title) <= 80 or not valid_schedule(sched):
            raise ValueError("type, title (3-80 characters) or schedule invalid")
        dup = duplicate_of(title, missions)
        if dup:
            return {"slug": dup["slug"], "detail": f"already exists as '{dup['title']}' (created {dup['created']}); nothing new created",
                    "duplicate": True}
        desc = limit(str(req.get("description", "")), 20000, "the description")
        s = slugify(title, missions)
        meta = {"slug": s, "title": title, "type": typ, "status": "active", "schedule": sched,
                "triggers": X.clean_triggers(req.get("triggers")), "depth": "deep" if req.get("depth") == "deep" and typ == "task" else None,
                "budget_usd_month": min(max(float(req.get("budget_usd_month", 0.10)), 0), 1.0),
                "deliver": [x for x in req.get("deliver", ["telegram", "app"]) if x in DELIVER],
                "created": now().isoformat(timespec="seconds"), "goal": desc or title, "once": bool(req.get("once"))}
        asked = FL.asked_of(req.get("files"))         # MIS-23: refused at once (with the reason) when the stack cannot make one
        if asked:
            meta["files_asked"] = asked
        needs = [n for n in (req.get("needs") or []) if n in CONN_SCOPES]      # app access the owner grants on the mission page
        if needs:
            meta["needs"] = needs
        if typ == "cleanup":                  # what to analyse: the AI phone or the PC (guessed from the words if not given)
            meta["target"] = req.get("target") if req.get("target") in ("phone", "pc") else CL.target_of(meta)
        if typ == "shopping":                 # price watch: later runs only report a drop of at least this many percent
            meta["watch_pct"] = min(max(float(req.get("watch_pct") or 0), 0), 50)
            if req.get("task"):               # TSK-21: a task holds it; the Conductor runs its checks
                meta["task"] = int(req["task"])
        if meta["once"]:
            meta["schedule"] = "manual"
        save_mission(meta)                    # first, so a retried create finds it as a duplicate
        if typ == "briefing":
            meta["topic"] = s
            meta["goal"] = f"{period(meta)} briefing: {title}. {desc}".strip() + f"\n\nContent, key questions and sources: topics/{s}/TOPIC.md"
            try:
                detail = create_briefing(meta, req)
            except Exception:
                (MISSIONS / s / "MISSION.md").unlink(missing_ok=True)
                raise
            save_mission(meta)
        else:
            detail = ("shopping agent created (it proposes; it never buys without your approval)" if typ == "shopping" else
                      f"cleanup analysis of the {'AI phone' if meta.get('target') == 'phone' else 'PC'} created (it never deletes)"
                      if typ == "cleanup" else "long-term task created")
        vault_commit([f"missions/{s}"] + ([f"topics/{s}"] if typ == "briefing" else []), f"mission: create {s}")
        reindex()
        if req.get("run_now", True):
            enqueue(c, s, "manual")
        event("created", s, f"New mission ({typ}, {schedule_text(sched)}"
              f"{', ' + str(len(meta['triggers'])) + ' event triggers' if meta['triggers'] else ''}): {detail}"
              + ("; first run starts now" if req.get("run_now", True) else ""), push=True, title=title)
        return {"slug": s, "detail": detail}
    if not m:
        raise ValueError(f"no mission '{slug}'")
    if a == "run":
        if m.get("status") == "archived":
            raise ValueError("mission is archived")
        if not enqueue(c, slug, "manual", mode="deep" if req.get("deep") and m["type"] == "task" else None):
            raise ValueError("already running or queued")
        event("queued", slug, "Run queued (on demand)" + (" · deep research" if req.get("deep") else ""), title=m["title"])
        return {"queued": True}
    if a in ("pause", "resume", "archive"):
        m["status"] = {"pause": "paused", "resume": "active", "archive": "archived"}[a]
        if a == "resume":
            m["created"] = now().isoformat(timespec="seconds")      # no catch-up of runs missed while paused
        save_mission(m)
        vault_commit([f"missions/{slug}"], f"mission: {a} {slug}")
        event(a, slug, {"pause": "paused", "resume": "resumed", "archive": "archived (files stay in the vault)"}[a], push=True, title=m["title"])
        return {"status": m["status"]}
    if a == "update":
        f = req.get("fields") or {}
        changed = []
        if "title" in f and 3 <= len(str(f["title"]).strip()) <= 80:
            m["title"] = str(f["title"]).strip(); changed.append("title")
        if "schedule" in f and f["schedule"] != m.get("schedule"):
            if not valid_schedule(f["schedule"]):
                raise ValueError(f"schedule '{f['schedule']}' invalid")
            import n8n_jobs as NJ
            import tasks as TK
            TK.table(c)
            tid = (c.execute("select id from tasks where door='mission' and ref=?", (slug,)).fetchone() or [None])[0]
            if tid and NJ.of("task", tid):                  # WFL-09: after its start the schedule is n8n's, changed on its canvas
                raise ValueError("its schedule is its workflow's in n8n now: open Workflows and change its schedule there")
            m["schedule"] = f["schedule"]; m["created"] = now().isoformat(timespec="seconds"); changed.append("schedule")
            if tid:                                        # its task gets the schedule, and with it its workflow (ops/n8n_jobs.py)
                c.execute("update tasks set rhythm=? where id=?", (json.dumps(TK.rhythm_of_mission({**m, **({"triggers": X.clean_triggers(f["triggers"])} if "triggers" in f else {})})), tid))
                c.commit()
        if "triggers" in f:
            m["triggers"] = X.clean_triggers(f["triggers"]); changed.append("event triggers")
        if "depth" in f and m["type"] == "task":
            m["depth"] = "deep" if f["depth"] == "deep" else None; changed.append("depth")
        if "budget_usd_month" in f:
            m["budget_usd_month"] = min(max(float(f["budget_usd_month"]), 0), 1.0); changed.append("budget")
        if "deliver" in f:
            m["deliver"] = [x for x in f["deliver"] if x in DELIVER]; changed.append("delivery")
        if "watch_pct" in f and m["type"] == "shopping":    # scheduled re-checks only report a drop of at least this much
            m["watch_pct"] = min(max(float(f["watch_pct"] or 0), 0), 50); changed.append("price watch")
        if "goal" in f and m["type"] in ("task", "shopping"):
            m["goal"] = limit(str(f["goal"]), 20000, "the goal"); changed.append("goal")
        paths = [f"missions/{slug}"]
        tf = {k: v for k, v in f.items() if k in TOPIC_FIELDS}
        if tf and m["type"] == "briefing":
            (meta, body), p = topic_of(m)
            for k, v in tf.items():
                if k == "mission":
                    meta["mission"] = limit(str(v), 4000, "the mission")
                elif k == "notes":
                    body = limit(str(v), 20000, "the notes")
                elif k == "key_questions":
                    meta["key_questions"] = [limit(str(x), 1000, "a key question") for x in limit_items(v, 20, "key questions")]
                elif k == "watchlist":
                    meta["watchlist"] = [{kk: vv for kk, vv in w.items() if kk in ("name", "symbol", "aliases", "proxy") and vv}
                                         for w in limit_items(v, 15, "watchlist entries") if isinstance(w, dict) and w.get("name")]
                else:
                    meta.setdefault("sources", {})[k] = [limit(str(x), 1000, "a source") for x in limit_items(v, 30, "sources")]
            write_front(p, meta, body)
            paths.append(f"topics/{m.get('topic', slug)}")
            changed.append("briefing focus")
        if "schedule" in f and m["type"] == "briefing":     # the news window follows the schedule (weekly: a week)
            (meta, body), p = topic_of(m)
            if meta.get("window_hours") != window_hours(m["schedule"]):
                meta["window_hours"] = window_hours(m["schedule"])
                write_front(p, meta, body)
                paths.append(f"topics/{m.get('topic', slug)}")
        save_mission(m)
        vault_commit(paths, f"mission: update {slug} ({', '.join(changed)})")
        event("updated", slug, "changed: " + (", ".join(changed) or "nothing"), title=m["title"])
        return {"changed": changed}
    raise ValueError(f"unknown action '{a}'")




def handle_stack(req):
    """Actions on the rest of the stack: e-mail to the owner, add to the vault, analyse a repo, search / forget memory."""
    a = req["action"]
    if a == "email":
        if not X.email_ready():
            raise ValueError("e-mail is not set up (make email-setup)")
        subject, body = limit(str(req.get("subject", "")).strip(), 300, "the subject"), limit(str(req.get("markdown", "")), 200000, "the e-mail")
        if not subject or not body.strip():
            raise ValueError("subject and text needed")
        if not X.email(subject, body, f"From your assistant · {now():%d %b %Y}", X.APP):
            raise RuntimeError("sending failed")
        event("email", "", f"E-mail sent: {subject}")
        return {"sent": True}
    if a == "vault_add":
        title = limit(re.sub(r"\s+", " ", str(req.get("title", ""))).strip(), 200, "the title")
        inbox = VAULT / "raw" / "_inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        stamp = f"{now():%Y-%m-%d-%H%M%S}"
        if req.get("upload"):
            name = Path(str(req["upload"])).name
            src = HOME / "app" / "uploads" / name
            if not src.is_file():
                raise ValueError("upload not found")
            dst = inbox / name
            dst.write_bytes(src.read_bytes())
        else:
            text, url = limit(str(req.get("text", "")), 200000, "the text"), str(req.get("url", "")).strip()
            if url:
                if not re.match(r"^https?://", url):
                    raise ValueError("not a web address")
                p_ = subprocess.run(["docker", "run", "--rm", "-i", "--network", "aistack_webonly", "aistack/desk:1", "--fetch"],
                                    input=json.dumps({"url": url}), capture_output=True, text=True, timeout=180)
                if p_.returncode or not p_.stdout.strip():
                    raise ValueError(f"page not readable: {(p_.stderr.strip().splitlines() or ['?'])[-1]}")
                d = json.loads(p_.stdout)
                title, text = title or d.get("title") or url, d["text"]
            if len(text.strip()) < 20:
                raise ValueError("nothing to add")
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50] or "note"  # cap: id
            dst = inbox / f"{stamp}-{slug}.md"
            write_front(dst, {"title": title or slug, "source": url or "Mission Control", "added": now().isoformat(timespec="minutes")},
                        f"# {title}\n\n{text}")
        rel = str(dst.relative_to(VAULT))
        event("vault_add", "", f"Added to the vault inbox: {title or dst.name} (wiki pages follow in a few minutes)")
        return {"path": rel}
    if a == "understand":
        r = O.start(req.get("repo"), str(req.get("source") or "app"), kind=req.get("kind") or None, step=req.get("step") or None, update=bool(req.get("update")))   # BLD-26: one job, the whole package, or the reason why not; DEC-48: a kind, one step again
        if not r["already"]:
            event("understand", "", f"Onboarding {r['repo']}: code graph, code map, explanations, search and a written analysis", title="Code")
        return r
    if a == "card_edit":                                   # DEC-49: pin, strike, add or remove a line of a repository's card
        import repocard as RC
        name = str(req.get("repo") or "")
        if not name or not (O.CODE / name).is_dir():
            raise ValueError("no such repository")
        e = RC.edit(name, str(req.get("act") or ""), lid=req.get("id"), text=req.get("text"), kind=str(req.get("kind") or "rule"))
        event("card", "", f"The card of {name}: the owner's {req.get('act')}", title="Code")
        return {"edits": e}
    if a == "forget":
        text = str(req.get("text", "")).strip()
        if not 3 <= len(text) <= 200:
            raise ValueError("give 3-200 characters to forget")
        out = sh("python3", str(OPS / "hindsight_forget.py"), text, timeout=300)
        event("forget", "", f"Long-term memory: forgot conversations containing “{text}”")
        return {"output": tailcut(out.strip(), 4000)}  # cap: store
    if a == "memory_search":
        q = limit(str(req.get("q", "")).strip(), 500, "the search").replace("'", "''")
        if len(q) < 2:
            return {"facts": []}
        rows = sh("docker", "exec", "aistack-hindsight-db-1", "psql", "-U", "hindsight", "-d", "hindsight", "-tAF", "\t", "-c",
                  f"select fact_type, to_char(created_at, 'YYYY-MM-DD'), coalesce(metadata->>'chat_id', ''), replace(replace(text, E'\\t', ' '), E'\\n', ' ') from memory_units "
                  f"where bank_id = 'owner' and text ilike '%{q}%' order by created_at desc limit 40").splitlines()  # cap: list (the 40 newest matches; a narrower search finds the rest)
        return {"facts": [dict(zip(("type", "date", "chat", "text"), r.split("\t"))) for r in rows if r.count("\t") == 3]}
    if a == "memory_browse":
        return memory_browse()
    if a == "memory_move":
        return memory_move([str(x) for x in req.get("ids") or []], [str(x) for x in req.get("keep") or []])
    raise ValueError("unknown action")


FACTS_SQL = ("select u.id, u.fact_type, to_char(u.created_at, 'YYYY-MM-DD'), coalesce(u.metadata->>'chat_id', ''), coalesce(u.metadata->>'source', ''), "
             "replace(replace(u.text, E'\\t', ' '), E'\\n', ' '), coalesce((select string_agg(e.canonical_name, '|') from unit_entities ue join entities e on e.id = ue.entity_id where ue.unit_id = u.id), '') "
             "from memory_units u where u.bank_id = 'owner' order by u.created_at desc")    # the owner's bank only: a trial has its own
MOVE_LIST = Path(os.environ.get("MEMORY_MOVE", "/srv/ai/state/memory-move.json"))     # what is not about the owner, for his eyes (APP-50)


def long_term_facts():
    rows = sh("docker", "exec", "aistack-hindsight-db-1", "psql", "-U", "hindsight", "-d", "hindsight", "-tAF", "\t", "-c", FACTS_SQL).splitlines()
    out = []
    for r in rows:
        x = r.split("\t")
        if len(x) == 7:
            out.append({"id": x[0], "type": x[1], "date": x[2], "chat": x[3], "source": x[4], "text": x[5], "entities": [e for e in x[6].split("|") if e]})
    return out


def memory_browse():
    """The Memory tab's Long-term: the owner's profile, every fact whole, and what waits for his eyes because it is not about him."""
    facts = long_term_facts()
    try:
        move = json.loads(MOVE_LIST.read_text())
    except (OSError, ValueError):
        move = []
    live = {f["id"]: f for f in facts}
    move = [{**m, "text": live[m["id"]]["text"]} for m in move if m["id"] in live and not m.get("kept")]
    prof = sh("docker", "exec", HERMES, "sh", "-c", "cat /opt/data/memories/USER.md /opt/data/memories/MEMORY.md 2>/dev/null").replace("\n§\n", "\n").strip()
    return {"facts": facts, "profile": prof, "move": move}


def memory_move(ids, keep):
    """The move list applied (the memory agent's nightly pass, DEC-44, or the owner's tap): each fact goes to a wiki as a filed source,
    naming the chat it came from and the long-term fact's id (MEM-48), and is retired softly with its Undo."""
    import keeper as K
    K.M = sys.modules[__name__]
    facts = {f["id"]: f for f in long_term_facts()}
    try:
        items = json.loads(MOVE_LIST.read_text())
    except (OSError, ValueError):
        items = []
    want = [m for m in items if m["id"] in ids and m["id"] in facts]
    gone = [i for i in ids if i not in facts]           # Hindsight re-made it (an observation gets a new id) or it was forgotten already
    by_topic = {}
    for m in want:
        if m.get("file", True):                           # what an agent did needs no wiki: its journal and the run record hold it
            by_topic.setdefault(m.get("topic") or "Other", []).append(facts[m["id"]])
    day = now().strftime("%Y-%m-%d")
    for topic, fs in by_topic.items():
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
        body = "\n".join(f"- {f['text']} (kept {f['date']}" + (f", chat {f['chat']}" if f["chat"] else "") + f"; long-term fact {f['id']})" for f in fs)
        (VAULT / "raw/_inbox" / f"{day}-long-term-{slug}.md").write_text(f"# {topic}: facts moved from long-term memory\n\nExtracted by a model from chats, not checked.\n\n{body}\n")
    done = K.apply([{"id": m["id"], "class": "moved_to_wiki", "why": f"not about the owner: filed for the wikis under {m.get('topic') or 'Other'}"} for m in want], list(facts.values()))
    for m in items:
        if m["id"] in keep:
            m["kept"] = True
    MOVE_LIST.write_text(json.dumps([m for m in items if m["id"] not in ids]))
    event("memory", "", f"Long-term memory: {len(done)} facts that are not about you moved to the wikis (each has its Undo)"
          + (f"; {len(gone)} on the list were no longer in long-term memory" if gone else ""), title="Crew")
    return {"moved": len(done), "gone": len(gone)}


def handle_memory(req):
    pid, decision = str(req.get("id", "")), req.get("decision")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", pid) or decision not in ("approve", "reject"):
        raise ValueError("invalid approval")
    out = sh("docker", "exec", "-u", "hermes", HERMES, "hermes", "-z", f"/memory {decision} {pid}", timeout=180)
    with open("/srv/ai/state/approvals.jsonl", "a") as f:
        f.write(json.dumps({"ts": int(time.time()), "kind": "memory", "item_id": pid, "rule": "user",
                            "decision": "approved" if decision == "approve" else "rejected", "actor": "app"}) + "\n")
    event("memory", "", f"Memory {pid} {'saved' if decision == 'approve' else 'discarded'}")
    return {"output": tailcut(out.strip(), 4000)}  # cap: store


STACK_ACTIONS = {"email", "vault_add", "understand", "card_edit", "forget", "memory_search", "memory_browse", "memory_move"}
BUILD_ACTIONS = {"build_assign", "build_revise", "build_approve", "build_approve_all", "build_reject", "build_recheck", "build_revert",
                 "build_switch_engine"}
IMPROVE_ACTIONS = {"improve_scan", "proposal_accept", "proposal_dismiss"}
REPO_ACTIONS = {"codemap", "repo_create", "repo_buildable", "repo_remove"}
# crew_schedule answers only with where a schedule is changed now (n8n's canvas, WFL-09), until the app drops its form
CREW_ACTIONS = {"crew_run", "crew_memory_forget", "crew_memory_undo", "crew_schedule", "health_ack", "phone_cleanup_do", "phone_cleanup_do_all", "phone_cleanup_dismiss", "phone_cleanup_undo"}
creating = threading.Lock()            # one new mission at a time (drafting takes a minute or two)


def handle_forgejo_connect(req):
    """The owner's Forgejo token from the app: check it with Forgejo, store it encrypted (sops), restart to load it.
    The token is never logged, echoed or put on a command line."""
    tok = str(req.get("token", "")).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", tok):
        raise ValueError("not a Forgejo token")
    def get(path):
        r = urllib.request.Request(B.FORGEJO + path, headers={"Authorization": f"token {tok}"})
        with urllib.request.urlopen(r, timeout=15) as resp:
            return json.load(resp)
    try:
        user = get("/user")["login"]
        get("/user/repos?limit=1")
    except urllib.error.HTTPError as e:
        raise ValueError("Forgejo refused this token (check its permissions: repository read+write, user read)"
                         if e.code in (401, 403) else f"Forgejo answered {e.code}") from None
    except OSError:
        raise ValueError("Forgejo is not reachable from the PC right now (is the NAS on?)") from None
    store_secret("FORGEJO_TOKEN", tok, f"secrets: Forgejo token for {user} (encrypted, set from Mission Control)")
    event("system", "", f"Forgejo connected as {user}", push=True, title="Code")
    subprocess.Popen(["systemd-run", "--user", "--on-active=3", "--quiet", "systemctl", "--user", "restart", "missions.service"])
    return {"user": user}


def store_secret(name, value, msg):
    """Put one secret into secrets/secrets.enc.yaml (sops, value over stdin: never on a command line or in a log)
    and commit the encrypted file at once: a dirty live checkout stops every later build deploy."""
    p = subprocess.run(["sops", "set", "--value-stdin", "secrets/secrets.enc.yaml", f'["{name}"]'], cwd=str(STACK_REPO),
                       input=json.dumps(value), capture_output=True, text=True, timeout=60)
    if p.returncode:
        raise ValueError("could not save it encrypted (sops); nothing changed")
    for cmd in (["git", "add", "secrets/secrets.enc.yaml"], ["git", "commit", "-q", "-m", msg], ["git", "push", "-q", "origin", "HEAD"]):
        subprocess.run(cmd, cwd=str(STACK_REPO), capture_output=True, timeout=120)


def notify_task(tid, title, what):
    """A task that waits for the owner (a question, its plan's OK), through the one notification path."""
    N.send(f"Task #{tid} {what}: {title}", "result", by="conductor", title="Tasks", buttons=[[("🔍 Open the task", f"{X.APP}/#/task/{tid}")]],
           push_on=True, event_kind="task")


def handle_notify(req):
    """The owner's notification preferences (OBS-16), and the app's word that a chat which waited for the usage limit
    is answered (AST-12): the owner may have left the app, so it goes out through the one path."""
    if req["action"] == "notify_prefs":
        return {"prefs": N.set_prefs(req.get("prefs") or {})}
    cid = str(req.get("chat", ""))
    if not re.fullmatch(r"[a-z0-9]{6,24}", cid):
        raise ValueError("no such chat")
    N.send(f"The answer that waited for the usage limit is ready: {req.get('title') or 'your chat'}", "result", by="main", title="Chat",
           buttons=[[("💬 Open the chat", f"{X.APP}/#/chat?c={cid}")]], push_on=True, event_kind="chat")
    return {}


def respond(rid, req):
    c = db()
    try:
        a = req.get("action")
        res = (__import__("flows").answer(req) if a == "flow_answer" else __import__("domain.packs", fromlist=["handle"]).handle(req) if a in ("pack_approve", "pack_refuse") else __import__("domain.trackers", fromlist=["handle"]).handle(req) if a in ("tracker_shadow_approve", "tracker_shadow_reject", "tracker_live") else __import__("domain.places", fromlist=["handle"]).handle(req) if a == "command_approve" else CHG.handle(req, c) if a in CHG.ACTIONS else CT.handle(req, c) if a == "claude_task" else CT.cancel(c, req.get("id")) if a == "claude_cancel" else handle_forgejo_connect(req) if a == "forgejo_connect" else handle_memory(req) if a == "memory" else handle_stack(req) if a in STACK_ACTIONS
               else B.handle(req, c) if a in BUILD_ACTIONS else I.handle(req, c) if a in IMPROVE_ACTIONS
               else R.handle(req, c) if a in REPO_ACTIONS else CR.handle(req, c) if a in CREW_ACTIONS else J.handle(req) if a in J.ACTIONS
               else WD.handle(req) if a in WD.ACTIONS else SH.handle(req, c) if a in SH.ACTIONS else W.handle(req) if a in W.ACTIONS else H.handle(req) if a in H.ACTIONS
               else SW.handle(req, c) if a in SW.ACTIONS else FL.handle(req) if a in FL.ACTIONS else handle_notify(req) if a in ("notify_prefs", "chat_ready") else TK.handle(req, c) if a in TK.ACTIONS else EV.handle(req, c) if a in EV.ACTIONS else A2.handle(req) if a in A2.ACTIONS
               else DQ.handle(req) if a in DQ.ACTIONS else MS.handle(req) if a in MS.ACTIONS else handle(req, load_missions(), c))
        res = {"ok": True, **res}
    except Exception as e:
        res = {"ok": False, "error": str(e)}
        log(f"request {rid} failed: {e}")
        if req.get("action") == "create":
            event("error", "", f"Mission could not be created: {str(e)}", push=True, title=req.get("title", ""))
    finally:
        c.close()
    (PUBLIC / "results").mkdir(exist_ok=True)
    tmp = PUBLIC / "results" / f".{rid}.tmp"               # the app polls for this file: it never sees half of it
    tmp.write_text(json.dumps(res, ensure_ascii=False))
    tmp.replace(PUBLIC / "results" / f"{rid}.json")


def process_inbox():
    for f in sorted(INBOX.glob("*.json")):
        rid = f.stem
        try:
            req = json.loads(f.read_text())
            f.unlink()
        except Exception:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", rid) or not isinstance(req, dict):
            continue
        if req.get("action") in ("create", "memory", "email", "vault_add", "forget", "build_reject", "codemap", "repo_create", "repo_buildable", "repo_remove", "crew_memory_forget", "crew_memory_undo"):     # slow ones run in a thread
            def slow(rid=rid, req=req):
                with creating:
                    respond(rid, req)
            threading.Thread(target=slow, daemon=True).start()
        elif req.get("action") in MS.ACTIONS:             # an agent's memory call: its own thread, never in the inbox's way (MEM-28)
            threading.Thread(target=respond, args=(rid, req), daemon=True).start()
        else:
            respond(rid, req)
    (PUBLIC / "results").mkdir(exist_ok=True)
    for old in (PUBLIC / "results").glob("*.json"):
        if time.time() - old.stat().st_mtime > 3600:
            old.unlink()

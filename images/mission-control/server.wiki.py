# A part of server.py (PLT-25): the wiki views. It runs in server.py's namespace where it stood (_part); not a module of its own.
# ---------- wiki (Obsidian-style views of the vault wiki and the mission wikis) ----------
LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")


def wiki_roots():
    """Every wiki: the vault's, then each mission's, an archived mission's last (its files stay; FND-61)."""
    roots = [{"root": "wiki", "title": "Vault wiki", "mission": None, "archived": False}]
    st = state()
    for m in st["missions"]:
        if m.get("wiki") and (VAULT / m["wiki"]).exists():
            roots.append({"root": m["wiki"], "title": m["title"], "mission": m["slug"], "archived": m.get("status") == "archived"})
    for t in st.get("tasks") or []:                      # a briefing task's topic without a mission of its own (TSK-22)
        r = f"topics/{t['topic']}/wiki" if t.get("topic") else None
        if r and (VAULT / r).exists() and r not in {x["root"] for x in roots}:
            roots.append({"root": r, "title": t["title"], "mission": None, "task": t["id"], "archived": t.get("status") == "cancelled"})
    for d in sorted((VAULT / "repos").glob("*/wiki")) if (VAULT / "repos").is_dir() else ():     # APP-50: under Memory's Code part, not on the wikis' list or map
        roots.append({"root": f"repos/{d.parent.name}/wiki", "title": d.parent.name, "mission": None, "repo": d.parent.name, "archived": False})
    return sorted(roots, key=lambda r: r["archived"])


def front(text):
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if not m:
        return {}, text
    try:
        return yaml.safe_load(m.group(1)) or {}, m.group(2)
    except Exception:
        return {}, m.group(2)


_wiki_cache = {}


def wiki(root):
    """Pages, a resolver for [[links]], forward links and backlinks of one wiki root (cached by mtime)."""
    base = VAULT / root
    files = sorted(base.rglob("*.md"))
    sig = (len(files), max((f.stat().st_mtime for f in files), default=0))
    if _wiki_cache.get(root, {}).get("sig") == sig:
        return _wiki_cache[root]
    pages = {}
    for f in files:
        with f.open(encoding="utf-8", errors="replace", newline="") as source:
            markdown = source.read()
        # Keep the copy source intact; parsing/rendering still uses normalized newlines.
        meta, body = front(markdown.replace("\r\n", "\n").replace("\r", "\n"))
        pid = str(f.relative_to(base))[:-3]
        pages[pid] = {"id": pid, "title": str(meta.get("title") or f.stem.replace("-", " ").title()), "type": meta.get("type", ""),
                      "summary": str(meta.get("summary", "")), "folder": pid.split("/")[0] if "/" in pid else "",
                      "aliases": meta.get("aliases") or [], "body": body, "meta": meta, "markdown": markdown}
    names = {}
    for p in pages.values():
        for n in [p["id"], p["id"].split("/")[-1], p["title"], *p["aliases"]]:
            names.setdefault(str(n).lower(), p["id"])

    def resolve(target):
        t = target.strip().lower().removesuffix(".md")
        for cand in (t, t.removeprefix(root.lower() + "/"), t.split("/")[-1]):
            if cand in names:
                return ("page", names[cand])
        if (VAULT / f"{target.strip()}.md").is_file():
            return ("file", f"{target.strip()}.md")
        return (None, None)
    links, back = {}, {}
    for p in pages.values():
        out = set()
        for mm in LINK.finditer(p["body"]):
            kind, ref = resolve(mm.group(1))
            if kind == "page" and ref != p["id"]:
                out.add(ref)
                back.setdefault(ref, set()).add(p["id"])
        links[p["id"]] = out
    w = {"sig": sig, "pages": pages, "resolve": resolve, "links": links, "back": back}
    _wiki_cache[root] = w
    return w


def root_ok(root):
    return root in {r["root"] for r in wiki_roots()}


def skills_file():
    try:
        return json.loads((M / "public/skills.json").read_text())
    except (OSError, ValueError):
        return {"skills": [], "error": "The list comes within the hour, once the runner has read them."}


async def api_skills(request):
    """Every skill Hermes can look up, without its instructions (APP-48)."""
    d = skills_file()
    return JSONResponse({**d, "skills": [{k: v for k, v in x.items() if k != "body"} for x in d.get("skills") or []]})


async def api_skill(request):
    """One skill with its whole instructions."""
    want = request.query_params.get("path", "")
    x = next((x for x in skills_file().get("skills") or [] if x["path"] == want), None)
    return JSONResponse(x) if x else JSONResponse({"error": "not found"}, status_code=404)


MEMDIR = M / "memory"                                 # the memory stack's records (ops/memstack.py DIR)


def read_json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


async def api_memory_catalogue(request):
    """MEM-45: every collection by sector, with what the stack measured of its use, and the stack's status (given and used, the gate)."""
    cat = read_json(M / "public/memory-catalogue.json", None)
    if cat is None:
        return JSONResponse({"collections": [], "error": "The catalogue comes within the hour, once the runner has measured the stores."})
    return JSONResponse({**cat, "status": read_json(M / "public/memory-stack.json", {})})


LESSON_RE = re.compile(r"^- (?P<text>.+?) \(evidence: (?P<ev>.*?); tally (?P<tally>-?\d+); id (?P<id>L-[0-9a-f]{8})(?:; since (?P<since>[\d-]+))?\)$")


async def api_memory_lessons(request):
    """MEM-38: each role's playbook: its lessons with their evidence and tally, and how many are retired."""
    out = []
    for f in sorted((VAULT / "howto" / "lessons").glob("*.md")) if (VAULT / "howto" / "lessons").is_dir() else []:
        text = f.read_text(errors="replace")
        live, _, retired = text.partition("\n## Retired")
        rows = [m.groupdict() for m in (LESSON_RE.match(ln.strip()) for ln in live.splitlines()) if m]
        out.append({"role": f.stem, "lessons": rows, "retired": sum(1 for ln in retired.splitlines() if ln.startswith("- "))})
    return JSONResponse(out)


def run_slug(run):
    return re.sub(r"[^a-z0-9]+", "-", str(run).lower()).strip("-")[:120] or "run"  # cap: id (= ops/memstack.py slug)


async def api_memory_run(request):
    """MEM-46: what memory a run was given, which items it used, and what it yielded with each outcome."""
    run = request.query_params.get("run", "")
    given = read_json(MEMDIR / "given" / f"{run_slug(run)}.json", [])
    used = None
    try:
        for ln in (MEMDIR / "runs.jsonl").read_text().splitlines()[::-1]:
            if f'"run": {json.dumps(run)}' in ln:
                used = json.loads(ln)
                break
    except OSError:
        pass
    writes = []
    try:
        for ln in (MEMDIR / "writes.jsonl").read_text().splitlines():
            if f'"run": {json.dumps(run)}' in ln:
                writes.append(json.loads(ln))
    except OSError:
        pass
    return JSONResponse({"run": run, "given": given, "used": used, "yielded": writes})


async def api_journals(request):
    """APP-50: each agent's journal: who, how big, when written, its newest entry; with q, those that hold the words."""
    q = request.query_params.get("q", "").strip().lower()
    out = []
    for f in sorted((VAULT / "agents").glob("*/MEMORY.md")):
        try:
            txt = f.read_text(errors="replace")
        except OSError:
            continue
        hit = next((ln.strip() for ln in txt.splitlines() if q in ln.lower()), None) if q else None
        if q and hit is None:
            continue
        heads = re.findall(r"^### (.+)$", txt, re.M)
        out.append({"id": f.parent.name, "name": f.parent.name.replace("crew-", "").replace("mission-", "").replace("-", " ").capitalize(), "bytes": f.stat().st_size,
                    "at": f.stat().st_mtime, "entries": len(heads), "last": heads[-1] if heads else "", "hit": hit})
    return JSONResponse(sorted(out, key=lambda x: -x["at"]))


async def api_sources(request):
    """APP-50: the filed sources the vault's wiki is compiled from, newest first."""
    raw = VAULT / "raw"
    out = []
    for f in raw.rglob("*.md") if raw.is_dir() else []:
        rel = str(f.relative_to(VAULT))
        name = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", f.stem).replace("-", " ")
        out.append({"path": rel, "kind": f.parent.name.strip("_"), "title": name.capitalize(), "date": dt.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d"), "at": f.stat().st_mtime})
    return JSONResponse(sorted(out, key=lambda x: -x["at"]))


async def api_wiki_roots(request):
    """Every wiki (the vault's and each mission's) with pages, links, summary and whether its mission is archived."""
    out = []
    try:
        summaries = json.loads((M / "public/wiki-summaries.json").read_text())     # ops/wikis.py
    except Exception:
        summaries = {}
    for r in wiki_roots():
        w = wiki(r["root"])
        out.append(r | {"summary": (summaries.get(r["root"]) or {}).get("summary", ""), "pages": len([p for p in w["pages"] if p != "index"]), "links": sum(len(v) for v in w["links"].values())})
    return JSONResponse(out)


SUBJECT_STOP = {"index", "overview", "sources", "log", "summary"}


def subject(title):
    """A page title as a subject two wikis can share: lower case, without a parenthesis or punctuation."""
    t = re.sub(r"\([^)]*\)", " ", str(title).lower())
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return t if len(t) >= 4 and t not in SUBJECT_STOP else ""


async def api_telemetry(request):
    """TSK-25: the daily telemetry history per agent, model, harness and kind (a year), and the price table (ops/history.py)."""
    f = TELEMETRY
    if not f.exists():
        return JSONResponse({"rows": [], "prices": {}, "error": "No history yet: the runner writes it within the hour."})
    return PlainTextResponse(f.read_text(), media_type="application/json")

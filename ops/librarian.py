"""The Librarian (MEM-08, MEM-12, KNW-14, DEC-32): the memory curator's weekly tidy of every agent wiki, the hub pages
that join the wikis, and the search index. It changes only what the vault's history restores (one commit per pass),
adds no fact of its own and forgets nothing: forgetting stays the owner's (KNW-08).

lint     every agent wiki, without a model: broken links, orphans, a wiki over its limit, the same subject on two pages,
         contradictions already marked, and pages not confirmed for STALE_DAYS, which it marks stale (MEM-12).
judge    one model call per wiki with something to judge: which candidate pairs are one subject (merged into one page with
         every fact, source and superseded line of both; the other page becomes a stub that points to it) and which claims
         on the pages it has not read yet contradict each other (a > [!contradiction] callout, trust: contested). A merge
         that would lose or add a link is refused; a contradiction whose source is not on the page is dropped.
hubs     a subject two or more wikis share (the map's rule, MEM-09) gets a hub page in the vault wiki (wiki/hubs/) linking
         each wiki's page on it: the top layer that joins the wikis, written from their pages alone and listed under
         "## Hubs" in the vault's index.md, its own section there.
index    qmd cleanup drops the chunks of files that are gone (FND-43), then the index is updated.
report   public/librarian.json: each wiki's lint, what changed and the commit (Stack → Memory, and the run's record).
The commit holds exactly the files the pass wrote (WROTE), also when a step fails halfway.
The vault wiki itself keeps its own curator (ops/vault-lint.sh); the Librarian only writes its hubs/ folder.
"""
import datetime as dt
import textcap as TC                              # visible caps (AGENTS.md, truncation)
import difflib
import fcntl
import json
import os
import re
import subprocess
import time
from pathlib import Path
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md

M = None                                       # ops/missions.py (set by crew.run)
STALE_DAYS = 90                                # MEM-12: an agent wiki's facts are news; unconfirmed this long, a page is stale
# limit: paces, a wiki over this is flagged as an issue; nothing is removed
LIMIT = 200                                    # pages per agent wiki (= ops/memory.py STORES agent-wikis)
SAME = 0.85                                    # two page names this similar in one folder are a duplicate candidate
PAIRS = 6                                      # duplicate candidates judged per wiki and pass; the rest wait  # cap: prompt
PAGE_CHARS = 6000                              # one page's text in the judge's prompt  # cap: prompt
READ_CHARS = 40000                             # page text one judge call reads; the other pages wait for the next pass  # cap: prompt
LOCK = Path(os.environ.get("VAULT_LOCK", "/srv/ai/state/vault-ingest.lock"))   # the vault's ingest and lint take it too
HUBS = "wiki/hubs"
WROTE = []                                     # the files this pass wrote or removed: its commit holds exactly these
SUBJECT_STOP = {"index", "overview", "sources", "log", "summary"}            # = images/mission-control/server.py
LINK = re.compile(r"\[\[([^\]|#]+)(#[^\]|]*)?(\|[^\]]*)?\]\]")

JUDGE = P.text("memory", "WIKI_JUDGE")


# ---------- reading a wiki ----------
def subject(title):
    """A page title as a subject two wikis can share (the map's rule): lower case, without a parenthesis or punctuation."""
    t = re.sub(r"\([^)]*\)", " ", str(title).lower())
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return t if len(t) >= 4 and t not in SUBJECT_STOP else ""


def pages(root):
    """Every page of a wiki (path without .md, its file, front matter and body); a merged page's stub is marked."""
    out = []
    for f in sorted((M.VAULT / root).rglob("*.md")):
        if f.name == "index.md":
            continue
        meta, body = M.split_front(f.read_text(errors="replace"))
        meta = meta if isinstance(meta, dict) else {}
        out.append({"path": str(f.relative_to(M.VAULT / root))[:-3], "file": f, "meta": meta, "body": body, "mtime": f.stat().st_mtime,
                    "title": str(meta.get("title") or f.stem), "aliases": [str(a) for a in meta.get("aliases") or []],
                    "stub": bool(meta.get("merged_into"))})
    return out


def targets(text):
    return [m.group(1).strip().removesuffix(".md") for m in LINK.finditer(text)]


def resolves(root, t):
    return any(p.exists() for p in (M.VAULT / root / f"{t}.md", M.VAULT / f"{t}.md", M.VAULT / t))


def subjects(p):
    return {subject(x) for x in [p["title"], *p["aliases"]]} - {""}


def candidates(ps, apart=frozenset()):
    """Pairs of pages that may be one subject: a shared title or alias, or names this similar in one folder; not a pair
    already judged two subjects whose pages have not changed since (`apart`)."""
    live, out = [p for p in ps if not p["stub"]], []
    for i, a in enumerate(live):
        fa, na = a["path"].split("/", 1) if "/" in a["path"] else ("", a["path"])
        for b in live[i + 1:]:
            fb, nb = b["path"].split("/", 1) if "/" in b["path"] else ("", b["path"])
            if frozenset((a["path"], b["path"])) in apart:
                continue
            if subjects(a) & subjects(b) or (fa == fb and difflib.SequenceMatcher(None, na, nb).ratio() >= SAME):
                out.append((a, b))
    return out


def kept_apart(apart, ps):
    """The pairs judged two subjects before ([a, b, mtime a, mtime b]) whose pages have not changed since."""
    mt = {p["path"]: p["mtime"] for p in ps}
    return {frozenset((a, b)) for a, b, ma, mb in apart if mt.get(a) == ma and mt.get(b) == mb}


def confirmed(p):
    try:
        return dt.date.fromisoformat(str(p["meta"].get("last_validated")))
    except ValueError:
        return None


def lint(root, ps, today, apart=frozenset()):
    """The mechanical checks of one agent wiki, without a model: [{kind, page, detail}]."""
    live = [p for p in ps if not p["stub"]]
    issues, inbound = [], {p["path"]: 0 for p in live}
    for p in live:
        for t in targets(p["body"]):
            if t in inbound:
                inbound[t] += t != p["path"]
            elif not resolves(root, t):
                issues.append({"kind": "broken-link", "page": p["path"], "detail": f"[[{t}]] has no page"})
    issues += [{"kind": "orphan", "page": k, "detail": "no other page links here"} for k, n in inbound.items() if n == 0]
    if len(live) > LIMIT:
        issues.append({"kind": "over-limit", "page": "", "detail": f"{len(live)} pages, over {LIMIT}"})
    issues += [{"kind": "duplicate", "page": a["path"], "detail": f"may be the same subject as {b['path']}"} for a, b in candidates(ps, apart)]
    for p in live:
        n = p["body"].count("[!contradiction]")
        if n:
            issues.append({"kind": "contradiction", "page": p["path"], "detail": f"{n} marked, unresolved"})
        d = confirmed(p)
        if d and (today - d).days > STALE_DAYS:
            issues.append({"kind": "stale", "page": p["path"], "detail": f"last confirmed {d.isoformat()}"})
    return issues


# ---------- changing a wiki (only what the vault's history restores) ----------
def write(p, meta, body, root):
    """Write one page unless it changed since it was read (its writer compiled it meanwhile); True if written."""
    if p["file"].exists() and p["file"].stat().st_mtime != p["mtime"]:
        return False
    M.write_front(p["file"], meta, body)
    WROTE.append(p["file"])
    p.update(meta=meta, body=body, mtime=p["file"].stat().st_mtime)
    M.RTM.touched(f"{root}/{p['path']}.md", changed=True, note="tidied by the Librarian")      # MEM-10: the access map sees it
    return True


def mark_stale(root, p, today):
    d = confirmed(p)
    if p["stub"] or not d or (today - d).days <= STALE_DAYS or p["meta"].get("trust") == "stale":
        return False
    return write(p, {**p["meta"], "trust": "stale", "stale_since": today.isoformat()}, p["body"], root)


def merge(root, ps, keep, drop, body, today):
    """One merge, if it keeps every link of both pages and adds none; '' when done, else why it was refused."""
    pair = {keep["path"], drop["path"]}
    want, got = (set(targets(keep["body"])) | set(targets(drop["body"]))) - pair, set(targets(body)) - pair
    if want - got:
        return f"it would lose {len(want - got)} link{'s' if len(want - got) > 1 else ''} ({', '.join(sorted(want - got)[:3])})"  # cap: top
    if got - want:
        return f"it would add {len(got - want)} link{'s' if len(got - want) > 1 else ''} neither page had"
    body = M.X.keep_superseded(keep["body"] + "\n\n" + drop["body"], body)
    km, dm = keep["meta"], drop["meta"]
    meta = {**km, "aliases": sorted({*map(str, km.get("aliases") or []), *map(str, dm.get("aliases") or []), drop["title"]} - {keep["title"]})[:12],  # cap: top (store)
            "sources": sorted({*(km.get("sources") or []), *(dm.get("sources") or [])}),
            "created": min(str(km.get("created") or today), str(dm.get("created") or today)),
            "last_validated": max(str(km.get("last_validated") or ""), str(dm.get("last_validated") or "")) or today.isoformat()}
    if keep["file"].stat().st_mtime != keep["mtime"] or drop["file"].stat().st_mtime != drop["mtime"]:
        return "a page changed while the Librarian read it"
    write(keep, meta, body, root)
    write(drop, {"title": drop["title"], "type": dm.get("type", ""), "merged_into": keep["path"], "merged": today.isoformat(), "trust": "merged"},
          f"Merged into [[{keep['path']}]] by the Librarian on {today.isoformat()}: both pages were about the same subject. "
          "This page's earlier text is in the vault's history.", root)
    old = re.compile(r"\[\[" + re.escape(drop["path"]) + r"(?=[\]|#])")
    for p in ps:
        if not p["stub"] and p is not drop and old.search(p["body"]):
            write(p, p["meta"], old.sub("[[" + keep["path"], p["body"]), root)
    return ""


def mark_contradiction(root, by_path, c, today):
    """A > [!contradiction] callout on the page (trust: contested), if both sources are links on their pages; True if marked."""
    p, q = by_path.get(str(c.get("page", ""))), by_path.get(str(c.get("other_page") or c.get("page", "")))
    if not p or not q or p["stub"] or q["stub"]:
        return False
    src, osrc = (t[0] if (t := targets(str(c.get(k, "")))) else "" for k in ("source", "other_source"))
    if src not in targets(p["body"]) or osrc not in targets(q["body"]):
        return False                                       # an invented source: no callout
    claim, other = (TC.cut(re.sub(r"\s+", " ", str(c.get(k, ""))).strip().rstrip("."), 300) for k in ("claim", "other"))  # cap: untrusted
    if not claim or not other or claim in p["body"]:
        return False
    where = "" if q is p else f" on [[{q['path']}]]"
    line = (f"> [!contradiction] {claim} ([[{src}]]); {other} ([[{osrc}]]{where}). "
            f"Unresolved: marked by the Librarian on {today.isoformat()}.")
    body = p["body"]
    if re.search(r"^## Contradictions\s*$", body, re.M):
        body = re.sub(r"^(## Contradictions\s*\n)", lambda m: m.group(1) + line + "\n", body, count=1, flags=re.M)
    elif re.search(r"^## Open questions\s*$", body, re.M):
        body = re.sub(r"^(## Open questions\s*$)", lambda m: "## Contradictions\n" + line + "\n\n" + m.group(1), body, count=1, flags=re.M)
    else:
        body = body.rstrip() + "\n\n## Contradictions\n" + line + "\n"
    return write(p, {**p["meta"], "trust": "contested"}, body, root)


def judge(root, title, ps, pairs, fresh):
    def page(p):
        return f"=== {p['path']} ({p['title']})\n{TC.cut(p['body'], PAGE_CHARS, 'the page goes on')}"  # cap: prompt
    return M.ask_json(JUDGE.format(title=title, pairs="\n\n".join(f"--- pair {i + 1}\n{page(a)}\n{page(b)}" for i, (a, b) in enumerate(pairs)) or "(no pairs this time)",
                                   pages="\n\n".join(page(p) for p in fresh) or "(no pages this time)"),
                      os.environ["VK_MEMORY"], model="gpt-sub-fast", timeout=600)


def tidy(root, title, today, read, apart=()):
    """One agent wiki: lint, mark stale, judge, apply. `read` maps the pages read last time to their mtime; `apart` lists
    the pairs judged two subjects before. The pairs still apart come back in out["apart"]."""
    ps = pages(root)
    skip = kept_apart(apart, ps)
    out = {"root": root, "title": title, "pages": sum(not p["stub"] for p in ps), "issues": lint(root, ps, today, skip), "stale": [],
           "merged": [], "refused": [], "distinct": [], "contradictions": [], "waits": 0, "changed": False}
    for p in ps:
        if mark_stale(root, p, today):
            out["stale"].append(p["path"])
    pairs = candidates(ps, skip)
    out["waits"] = max(0, len(pairs) - PAIRS)
    pairs = pairs[:PAIRS]  # cap: list (waits counts the pairs left for the next pass)
    unread = sorted((p for p in ps if not p["stub"] and read.get(p["path"]) != p["mtime"]), key=lambda p: -p["mtime"])
    fresh, size = [], 0
    for p in unread:
        if size + min(len(p["body"]), PAGE_CHARS) > READ_CHARS:
            break
        fresh.append(p)
        size += min(len(p["body"]), PAGE_CHARS)
    out["waits"] += len(unread) - len(fresh)
    if pairs or fresh:
        try:
            r = judge(root, title, ps, pairs, fresh)
        except Exception as e:
            out["not_judged"] = "ChatGPT usage limit" if M.paused(str(e)) else f"{type(e).__name__}: {str(e)}"
            r = {}
        by_path = {p["path"]: p for p in ps}
        asked = {frozenset((a["path"], b["path"])) for a, b in pairs}
        for mg in r.get("merges") or []:
            k, d = str(mg.get("keep", "")), str(mg.get("drop", ""))
            if frozenset((k, d)) not in asked or k == d or not str(mg.get("body", "")).strip() or by_path[k]["stub"] or by_path[d]["stub"]:
                continue
            why = merge(root, ps, by_path[k], by_path[d], str(mg["body"]), today)
            (out["refused"] if why else out["merged"]).append({"keep": k, "drop": d, "why": why or TC.cut(str(mg.get("why", "")), 300)})  # cap: untrusted
            if not why:
                by_path[d]["stub"] = True
        for x in r.get("distinct") or []:
            if frozenset((str(x.get("a", "")), str(x.get("b", "")))) in asked:
                out["distinct"].append({"a": str(x["a"]), "b": str(x["b"]), "why": TC.cut(str(x.get("why", "")), 300)})  # cap: untrusted
        for c in r.get("contradictions") or []:
            if mark_contradiction(root, by_path, c, today):
                out["contradictions"].append(str(c["page"]))
        if "not_judged" not in out:
            read.update({p["path"]: p["mtime"] for p in fresh})
    mt = {p["path"]: p["mtime"] for p in ps if not p["stub"]}
    out["apart"] = [[a, b, mt[a], mt[b]] for a, b in sorted(tuple(sorted(k)) for k in skip | {frozenset((x["a"], x["b"])) for x in out["distinct"]})
                    if a in mt and b in mt]               # not asked again while both pages stay as they are
    out["changed"] = bool(out["stale"] or out["merged"] or out["contradictions"])
    if out["merged"]:                                      # a merged page leaves the wiki's index
        M.X.write_index(root, title)
        WROTE.append(M.VAULT / root / "index.md")
    return out


# ---------- hubs: the top layer joining the wikis ----------
def slug(t):
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:60] or "subject"  # cap: id


def hubs(roots, today):
    """A hub page in the vault wiki for each set of pages two or more wikis share a subject on; the Librarian's hubs
    whose subject is no longer shared go (the vault's history keeps them). {written, removed, hubs}."""
    where = {}
    names = dict(roots)
    for root, _ in roots:
        for p in pages(root):
            if p["stub"] or (root == "wiki" and p["path"].startswith("hubs/")):
                continue
            for n in subjects(p):
                where.setdefault(n, {}).setdefault(root, p)
    groups = {}
    for n, v in sorted(where.items()):
        if len(v) > 1:
            groups.setdefault(tuple(sorted((r, p["path"]) for r, p in v.items())), v)
    d = M.VAULT / HUBS
    want, written = {}, []
    for key, v in groups.items():
        first = v.get("wiki") or v[sorted(v)[0]]
        name = slug(first["title"])
        while name in want:
            name += "-2"
        rows = [f"- **{names.get(r, r)}**: [[{r}/{p['path']}|{p['title']}]]" + (f" — {p['meta']['summary']}" if p["meta"].get("summary") else "")
                + (f" (last confirmed {p['meta']['last_validated']})" if p["meta"].get("last_validated") else "") for r, p in sorted(v.items())]
        body = (f"# {first['title']}\n\n{len(v)} wikis have a page on this subject. Each page, with its own summary:\n\n" + "\n".join(rows)
                + "\n\n_Written by the Librarian from the wikis' pages; it adds nothing of its own. Each page holds its facts and sources._")
        want[name] = (body, sorted(f"{r}/{p['path']}" for r, p in v.items()))
    for name, (body, sources) in want.items():
        f = d / f"{name}.md"
        old = M.split_front(f.read_text(errors="replace")) if f.exists() else ({}, "")
        created = (old[0] or {}).get("created")
        if old[1].strip() == body.strip() and isinstance(created, dt.date):
            continue
        day = lambda d: dt.date.fromisoformat(str(d))     # noqa: E731  # bare dates the vault check reads, each its own object (no YAML anchors)
        meta = {"title": body.splitlines()[0][2:], "type": "hub", "sources": sources, "created": day(created or today),
                "last_validated": day(today), "trust": "untrusted-source", "librarian": True,
                "qmd": {"metadata": {"type": "hub", "tier": "t1", "last_validated": day(today), "trust": "untrusted-source"}}}
        M.write_front(f, meta, body)
        WROTE.append(f)
        M.RTM.touched(f"{HUBS}/{name}.md", changed=True, note="hub page written by the Librarian")
        written.append(name)
    removed = []
    for f in sorted(d.glob("*.md")) if d.exists() else []:
        if f.stem not in want and (M.split_front(f.read_text(errors="replace"))[0] or {}).get("librarian"):
            f.unlink()
            WROTE.append(f)
            removed.append(f.stem)
    index_hubs({n: b.splitlines()[0][2:] for n, (b, _) in want.items()})
    return {"written": written, "removed": removed, "hubs": len(want)}


def index_hubs(titles):
    """The vault's index.md lists the hubs under '## Hubs', the Librarian's own section of it (the curator keeps the rest)."""
    f = M.VAULT / "index.md"
    if not f.exists():
        return
    text = f.read_text(errors="replace")
    if not titles and "## Hubs" not in text:
        return
    rest = re.sub(r"\n*^## Hubs\n(?:- [^\n]*(?:\n|$))*", "\n", text, flags=re.M).rstrip("\n") + "\n"
    new = rest + ("\n## Hubs\n" + "".join(f"- [[{HUBS}/{n}]] — {t}\n" for n, t in sorted(titles.items())) if titles else "")
    if new != text:
        f.write_text(new)
        WROTE.append(f)


# ---------- the search index ----------
def clean_index():
    """qmd cleanup (FND-43): the chunks of files that are gone, before and after."""
    import memory as MEM
    before = MEM.measure("qmd", time.time())
    subprocess.run(["docker", "exec", "aistack-qmd-1", "qmd", "cleanup"], capture_output=True, text=True, timeout=900, check=True)
    M.reindex()
    after = MEM.measure("qmd", time.time())
    keep = ("count", "orphaned", "orphaned_share", "bytes")
    return {"before": {k: before.get(k) for k in keep}, "after": {k: after.get(k) for k in keep}}


# ---------- one pass ----------
def store():
    return M.PUBLIC / "librarian.json"


def load():
    try:
        return json.loads(store().read_text())
    except (FileNotFoundError, ValueError):
        return {}


def run(now=None, index=True):
    """One pass over every wiki and the search index; the report is also public/librarian.json."""
    import wikis as W
    W.M = M
    if getattr(M.X, "M", None) is None:
        M.X.M = M                                          # outside the runner (the crew job) the compile module is not set up
    WROTE.clear()
    t0 = time.time()
    today = dt.date.fromtimestamp(now or t0)
    prev = load()
    read, apart = prev.get("read") or {}, {}
    roots = W.roots()
    rep = {"started": t0, "wikis": [], "hubs": {}, "index": None, "commit": None}
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)                     # never alongside a vault ingest or lint
        for root, title in roots:
            if root == "wiki":
                continue                                   # the vault wiki has its own curator (ops/vault-lint.sh)
            r = read.setdefault(root, {})
            try:
                w = tidy(root, title, today, r, (prev.get("apart") or {}).get(root) or [])
                apart[root] = w.pop("apart")
                rep["wikis"].append(w)
            except Exception as e:
                rep["wikis"].append({"root": root, "title": title, "error": f"{type(e).__name__}: {str(e)}", "changed": False, "issues": []})
        try:
            rep["hubs"] = hubs(roots, today)
        except Exception as e:
            rep["hubs"] = {"error": f"{type(e).__name__}: {str(e)}", "written": [], "removed": [], "hubs": 0}
        paths = sorted({str(Path(f).relative_to(M.VAULT)) for f in WROTE})     # what it wrote, even before a failure, and nothing else
        if paths:
            subprocess.run(["git", "add", "-A", "--", *paths], cwd=M.VAULT, capture_output=True)
            M.vault_commit(paths, f"librarian: {today.isoformat()} · {summary(rep)}")
            rep["commit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=M.VAULT, capture_output=True, text=True).stdout.strip()
            rep["files"] = paths
    if index:
        try:
            rep["index"] = clean_index()
        except Exception as e:
            rep["index"] = {"error": f"{type(e).__name__}: {str(e)}"}
    rep.update(at=time.time(), seconds=round(time.time() - t0), read={k: v for k, v in read.items() if k in dict(roots)}, apart=apart)
    store().write_text(json.dumps(rep, default=str))
    return rep


def summary(rep):
    """The pass in one line."""
    ws = rep["wikis"]
    parts = [f"{len(ws)} wikis checked"]
    for k, one, many in (("merged", "duplicate merged", "duplicates merged"), ("contradictions", "contradiction marked", "contradictions marked"),
                         ("stale", "page marked stale", "pages marked stale")):
        n = sum(len(w.get(k) or []) for w in ws)
        if n:
            parts.append(f"{n} {one if n == 1 else many}")
    h = rep.get("hubs") or {}
    if h.get("hubs"):
        parts.append(f"{h['hubs']} hub page{'s' if h['hubs'] > 1 else ''}")
    ix = rep.get("index") or {}
    if ix.get("before"):
        parts.append(f"search index: {ix['before']['orphaned']} → {ix['after']['orphaned']} orphaned chunks")
    for key, word in (("error", "failed"), ("not_judged", "not judged")):
        bad = [w["root"] for w in ws if key in w]
        if bad:
            parts.append(f"{word}: {', '.join(bad)}")
    return ", ".join(parts)

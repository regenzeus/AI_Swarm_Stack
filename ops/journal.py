"""Agent journals (design "Agents in Mission Control", phase 2): every agent remembers its own past runs.

One file per agent in the vault, agents/<agent-id>/MEMORY.md, git-committed like the rest of the vault:
  # Memory: <title>
  ## Standing notes      lines that hold until changed: the agent's agent_note, the curator's folds, the owner's edits
  - ...
  ## Journal             one entry per run, newest last
  ### 2026-10-28 19:13 · run 19 · done
  - Did: ...  - Found: ...  - Failed: ... (what and why)  - Open: ... (questions, the next step)
Agent ids are the runtime record's agent with ":" → "-": mission:ram-upgrade → mission-ram-upgrade, crew:memory → crew-memory.

Read at a run's start (begin + take): one opening in a fixed order within OPEN_CHARS (MEM-05): 1 what the swarm has for
the agent's card (standing instructions, the owner's messages, requests, help it got, lessons), 2 its state (the working
state, standing notes and the last ENTRIES entries), 3 its knowledge (the wikis its card names, its own first: MEM-04),
4 the owner's facts that match the task (Hindsight), 5 its team. It goes in front of the run's first prompt
(missions.hermes_z / ask_text); the run's log shows each read. A mission's working state (its "## Notes") lives here under
"## Working state", not in a second file. Written at its end (record): the run's runtime record is condensed into an entry by one
gpt-sub-fast call, or deterministically when the model is limited or the run had no steps. The weekly memory curator
(crew) folds entries older than the last KEEP into standing notes (curate); folded entries move to ARCHIVE.md.
Edits from the app (journal_note, journal_edit) and agent_note (Mission Control's MCP tool) come through the inbox.

Long-term memory (Hindsight, bank "owner") holds the owner's own facts; journal entries are not copied there (MEM-06: what
an agent found is in its wiki and its journal, which the chat finds through the vault search). A run's opening adds the
top recall for its task, at most RECALL_CHARS. Hindsight is reachable only on memnet: the calls run in Hermes' container.
"""
import datetime as dt
import textcap as TC                              # visible caps (AGENTS.md, truncation)
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md

M = None                                         # ops/missions.py (set by missions.main)
VAULT = Path(os.environ.get("JOURNAL_VAULT", "/srv/vault"))
ENTRIES, CAP_CHARS, KEEP, FOLD_AT = 5, 6000, 8, 14
OPEN_CHARS = 12000           # the whole opening (MEM-05): the swarm, the state, the knowledge, the facts, the team
RECALL_CHARS, BANK, HERMES = 900, "owner", "aistack-hermes-1"
VIEW = os.environ.get("RUNTIME_VIEW_HOST", "http://127.0.0.1:8093/view/")
ID = re.compile(r"^(mission|crew)-[a-z0-9][a-z0-9-]{0,120}$")
ACTIONS = {"journal_note", "journal_edit"}
CO = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
_lock = threading.Lock()
_run = threading.local()                         # the brief waiting for the current run's first prompt


def aid(agent):
    a = str(agent or "").strip().lower().replace(":", "-", 1)
    if not ID.match(a):
        raise ValueError(f"not an agent id: {agent!r}")
    return a


def rel(agent):
    return f"agents/{aid(agent)}/MEMORY.md"


def parse(text):
    doc, sec = {"title": "", "state": [], "notes": [], "entries": []}, None
    for ln in text.splitlines():
        if ln.startswith("# ") and not doc["title"]:
            doc["title"] = ln[2:].removeprefix("Memory:").strip()
        elif ln.startswith("## "):
            low = ln.lower()
            sec = "state" if "working state" in low else "notes" if "standing" in low else "journal" if "journal" in low else None
        elif sec == "state" and ln.strip() and not ln.startswith("_"):
            doc["state"].append(ln.rstrip())
        elif ln.startswith("### ") and sec == "journal":
            doc["entries"].append({"head": ln[4:].strip(), "lines": []})
        elif ln.startswith("- ") and ln[2:].strip():
            if sec == "notes":
                doc["notes"].append(ln[2:].strip())
            elif sec == "journal" and doc["entries"]:
                doc["entries"][-1]["lines"].append(ln[2:].strip())
    return doc


def render(doc, a):
    out = [f"# Memory: {doc.get('title') or a}", "",
           "_This agent's own memory (ops/journal.py): read at the start of every run, an entry added at its end. "
           "Edit it in Mission Control (Agents → this agent → Memory) or here; keep lines short._", ""]
    if doc.get("state"):
        out += ["## Working state", "", "_Replaced by every run: where the work stands, what is open, the next step._", "", *doc["state"], ""]
    out += ["## Standing notes", ""]
    out += [f"- {n}" for n in doc["notes"]] or ["(none yet)"]
    out += ["", "## Journal", ""]
    for e in doc["entries"]:
        out += [f"### {e['head']}", *[f"- {x}" for x in e["lines"]], ""]
    return "\n".join(out).rstrip() + "\n"


def load(agent):
    p = VAULT / rel(agent)
    return parse(p.read_text()) if p.exists() else {"title": "", "state": [], "notes": [], "entries": []}


def set_state(agent, text, title="", extra=()):
    """A run's new working state replaces the old one (MEM-05); extra: paths the same commit stages (the old NOTES.md)."""
    doc = load(agent)
    doc["title"] = doc["title"] or title
    doc["state"] = [ln.rstrip() for ln in str(text or "").splitlines() if ln.strip()]
    save(agent, doc, f"journal: {aid(agent)} working state", extra)


def state_text(agent):
    return "\n".join(load(agent).get("state") or [])


def commit(paths, msg):
    """Commit only these paths (other agents' staged work stays theirs); retry once when another commit holds the index."""
    with _lock:
        for _ in range(3):
            subprocess.run(["git", "add", "--", *paths], cwd=VAULT, capture_output=True)
            r = subprocess.run(["git", "commit", "-qm", msg, "-m", CO, "--", *paths], cwd=VAULT, capture_output=True, text=True)
            if r.returncode == 0 or "nothing" in (r.stdout + r.stderr):
                break
            time.sleep(2)
    threading.Thread(target=lambda: subprocess.run(["git", "push", "-q"], cwd=VAULT, capture_output=True, timeout=60), daemon=True).start()


def save(agent, doc, msg, extra=()):
    a, p = aid(agent), VAULT / rel(agent)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(render(doc, a))
    tmp.replace(p)
    commit([rel(a), *extra], msg)


def clip(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


# ---------- read: the brief at a run's start ----------
VAULT_SCOPE = ["qmd://vault-wiki/", "qmd://vault-raw/"]     # the vault wiki and the owner's own notes


def _qmd(root):
    return f"qmd://{root}/" if root.startswith(("missions/", "topics/")) else "qmd://vault-wiki/" if root == "wiki" else ""


def _titles(root):
    out = set()
    for f in (VAULT / root).rglob("*.md"):
        m = re.search(r"^title:\s*(.+)$", f.read_text(errors="replace")[:600], re.M)  # cap: parse: the title is in the front matter
        t = re.sub(r"[^a-z0-9]+", " ", re.sub(r"\([^)]*\)", " ", (m.group(1) if m else f.stem).lower())).strip()
        if len(t) >= 4 and t not in ("index", "overview", "sources"):
            out.add(t)
    return out


def card_wikis(card):
    """The wikis an agent's card says it reads (config/agents.yaml memory.wikis): own, vault, related."""
    try:
        import registry as REG
        c = next((x for x in REG.load().get("agents") or [] if x.get("id") == card), {})
        return list((c.get("memory") or {}).get("wikis") or ["vault"])
    except Exception:
        return ["vault"]


def wiki_scope(card, own=None):
    """MEM-04: the qmd prefixes a run may read, in order: its own wiki first, then the vault (its wiki and your notes),
    then the wikis that share a subject with its own; never another mission's private wiki (one built from your mail)."""
    want, out = card_wikis(card), []
    if "own" in want and own and _qmd(own):
        out.append(_qmd(own))
    if "vault" in want:
        out += VAULT_SCOPE
    if "related" in want and own and (VAULT / own).is_dir():
        mine = _titles(own)
        private = set(M.private_wikis()) if M and hasattr(M, "private_wikis") else set()
        for d in sorted([*(VAULT / "missions").glob("*/wiki"), *(VAULT / "topics").glob("*/wiki")]):
            r = str(d.relative_to(VAULT))
            if r != own and r not in private and mine & _titles(r):
                out.append(_qmd(r))
    return out


def wiki_matches(query, n=3, scope=None):
    """The top pages for this task from the wikis in scope (wiki_scope; default the vault), its own wiki's first:
    [{path, title, snippet}]. BM25, no model."""
    scope = scope if scope is not None else VAULT_SCOPE
    q = clip(re.sub(r"[^\w\s.-]", " ", query or ""), 120)
    if not q or not scope:
        return []
    try:
        p = subprocess.run(["docker", "exec", "aistack-qmd-1", "qmd", "search", q, "-n", "30", "--json"], capture_output=True, text=True, timeout=30)
        hits = json.loads(p.stdout or "[]")
    except Exception:
        return []
    found = []
    for rank, h in enumerate(hits):
        f = str(h.get("file", ""))
        at = next((i for i, pre in enumerate(scope) if f.startswith(pre)), None)
        if at is None:
            continue                             # outside what its card names: mail, chats, specs, other missions' work
        snip = re.sub(r"^@@.*?@@[^\n]*\n", "", str(h.get("snippet", "")))
        found.append((0 if at == 0 and scope[0] not in VAULT_SCOPE else 1, rank, {"path": f, "title": h.get("title", ""), "snippet": clip(snip, 240)}))
    return [x[2] for x in sorted(found, key=lambda x: (x[0], x[1]))[:n]]


def hindsight(path, body, timeout=30):
    """POST to Hindsight (only on memnet: through Hermes' container) -> the JSON answer, or None. Never raises."""
    code = ("import json,sys,urllib.request as u\n"
            "r=u.Request('http://hindsight:8888/v1/default/banks/'+sys.argv[1], data=sys.argv[2].encode(), headers={'Content-Type':'application/json'})\n"
            "print(u.urlopen(r,timeout=int(sys.argv[3])).read().decode())")
    try:
        p = subprocess.run(["docker", "exec", HERMES, "/opt/hermes/.venv/bin/python", "-c", code, f"{BANK}/{path}", json.dumps(body), str(timeout)],
                           capture_output=True, text=True, timeout=timeout + 15)
        return json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else None
    except Exception:
        return None


def recall(agent, query, n=4):
    """The top long-term facts for this task: this agent's (tagged) and the owner's untagged ones -> [text]."""
    q = clip(query, 300)
    if not q:
        return []
    r = hindsight("memories/recall", {"query": q, "budget": "mid", "max_tokens": 400, "tags": [f"agent:{aid(agent)}"], "tags_match": "any"})
    out, used = [], 0
    for x in (r or {}).get("results") or []:
        t = clip(x.get("text") or "", 300)
        if t and t not in out and used + len(t) <= RECALL_CHARS:
            out.append(t)
            used += len(t)
        if len(out) >= n:
            break
    return out


def memory_text(doc, cap=None):
    cap = cap or CAP_CHARS
    entries = doc["entries"][-ENTRIES:]  # cap: list (the opening says how many earlier runs are in the journal)
    def build(es):
        parts = []
        if doc.get("state"):
            parts.append("Working state (from your last run):\n" + "\n".join(doc["state"]))
        if doc["notes"]:
            parts.append("Standing notes:\n" + "\n".join(f"- {n}" for n in doc["notes"]))
        if es:
            older = len(doc["entries"]) - len(es)
            parts.append(f"Your last {len(es)} runs (oldest first" + (f"; {older} earlier ones are in your journal" if older else "") + "):\n" + "\n\n".join(e["head"] + "\n" + "\n".join(f"- {x}" for x in e["lines"]) for e in es))
        return "\n\n".join(parts)
    text = build(entries)
    while len(text) > cap and entries:
        entries = entries[1:]
        text = build(entries)
    return (text[:cap] + " …" if len(text) > cap else text), len(entries)


def _emit_read(run, agent, title, args, result, chars):
    if not run:
        return
    try:
        import runtime as RTM
        cid = f"journal-{time.time_ns()}"
        RTM.emit(run, "call", agent=agent, title=title, detail=json.dumps(args), data={"call_id": cid})
        RTM.emit(run, "result", agent=agent, title=title, detail=result, status="success", data={"call_id": cid, "chars": chars})
    except Exception:
        pass


def brief(agent, title="", query="", run=None, tools=True, card=None, wiki=None):
    """MEM-05: a run's opening, in a fixed order within OPEN_CHARS: 1 the swarm's pack for its card, 2 its state, 3 its
    knowledge (the wikis its card names, its own first), 4 the owner's facts for the task, 5 its team. The run's log gets
    a READ line for each part; the oldest journal entries make room when it is full."""
    a = aid(agent)
    doc = load(a)
    import swarm_client as SW
    pack = SW.pack(card) if card else {}
    swarm = SW.pack_text(pack, card, parts=("instructions", "owner", "requests", "help", "lessons")) if pack else ""
    team = SW.pack_text(pack, card, parts=("team",)) if pack else ""
    if card:
        _emit_read(run, agent, "swarm_context", {"card": card}, swarm or "nothing new from the swarm", len(swarm))
    facts = recall(agent, query or title)
    if facts:
        _emit_read(run, agent, "memory_recall", {"query": clip(query or title, 120)}, "\n".join(facts), sum(map(len, facts)))
    scope = wiki_scope(card, wiki) if card else VAULT_SCOPE
    pages = wiki_matches(query or title, scope=scope)
    if pages or query or title:
        _emit_read(run, agent, "wiki_search", {"query": clip(query or title, 120), "scope": scope},
                   "\n".join(f"{w['path']}: {w['snippet']}" for w in pages) or "no matching pages", sum(len(w["snippet"]) for w in pages))
    know = "\n".join(f"- {w['path']} ({w['title']}): {w['snippet']}" for w in pages) or "(none)"
    fixed = len(swarm) + len(team) + len(know) + sum(len(f) + 3 for f in facts) + 1500
    text, n = memory_text(doc, max(1500, OPEN_CHARS - fixed))
    _emit_read(run, agent, "read_file", {"path": rel(a)}, f"{len(doc.get('state') or [])} lines of working state, {len(doc['notes'])} standing notes, "
               f"{n} of {len(doc['entries'])} journal entries\n\n{text}", len(text))
    note = (f'To keep a lesson for all your future runs (for example "check the board manual first"), call the agent_note tool '
            f'with agent="{a}" and one short line. ') if tools else ""
    return ("## 1 · From the swarm (your card's standing instructions, the owner's messages, requests, help others gave, lessons)\n"
            f"{swarm or '(nothing new)'}\n\n"
            f"## 2 · Your state ({rel(a)}: your working state, standing notes and last runs)\n"
            f"{text or '(empty: this is your first run with a memory)'}"
            + (f"\n({len(doc['entries']) - n} older runs are in the file)" if n < min(ENTRIES, len(doc['entries'])) else "") + "\n\n"
            "## 3 · Your knowledge (the wikis your card names, your own first)\n" + know + "\n\n"
            "## 4 · The owner's facts that match this task (long-term memory)\n" + ("\n".join(f"- {f}" for f in facts) or "(none)") + "\n\n"
            "## 5 · Your team\n" + (team or "(not available)") + "\n\n"
            + ("This opening already holds what swarm_context would give you: do not call it in this run. " if card else "")
            + f"Build on what you found before and say in your result what changed since your last run. {note}\n\n---\n\n")

def begin(agent, title="", query="", run=None, tools=True, card=None, wiki=None):
    """At a run's start: the opening waits for the run's first prompt (take); card: its agent card (the swarm's pack, the
    wikis it reads), wiki: its own wiki's root. Never fails a run."""
    try:
        _run.brief = {"agent": agent, "title": title, "query": query, "run": run, "tools": tools, "card": card, "wiki": wiki}
    except Exception:
        _run.brief = None


def take(prompt, tools=True):
    """The run's first prompt gets the memory in front (once per run); later prompts go as they are."""
    b = getattr(_run, "brief", None)
    _run.brief = None
    if not b:
        return prompt
    try:
        return brief(b["agent"], b["title"], b["query"], b["run"], tools=tools and b["tools"], card=b.get("card"), wiki=b.get("wiki")) + prompt
    except Exception as e:
        _log(f"journal brief {b['agent']}: {type(e).__name__}: {e}")
        return prompt


def end():
    _run.brief = None


def _log(msg):
    (M.log if M else print)(msg)


# ---------- write: an entry at a run's end ----------
def run_view(run):
    try:
        req = urllib.request.Request(VIEW + urllib.request.quote(run, safe=""), headers={"Authorization": f"Bearer {os.environ.get('API_SERVER_KEY', '')}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except Exception:
        return None


def _arg(detail):
    try:
        a = json.loads(detail or "{}")
    except ValueError:
        return clip(detail, 100)
    if not isinstance(a, dict):
        return ""
    for k in ("command", "file_path", "path", "url", "question", "query", "q", "pattern", "subject", "title", "text"):
        if a.get(k):
            return clip(a[k], 100)
    return ""


def digest(v):
    """The run's steps, errors and problems in a few lines (from the runtime view)."""
    steps, errors = [], []
    for e in (v or {}).get("events", []):
        t = str(e.get("title") or "").split("__")[-1]
        if e["kind"] == "call" and t not in ("read_file", "wiki_search", "journal_write"):
            steps.append(f"{t}({_arg(e.get('detail'))})")
        elif e["kind"] == "error" or (e["kind"] == "result" and e.get("status") in ("error", "failure")):
            errors.append(f"{t}: {clip(e.get('detail'), 140)}")
        elif e["kind"] == "stage":
            steps.append(clip(f"{e.get('title')}: {e.get('detail') or ''}", 140))
    probs = [p.get("text", p.get("kind", "")) for p in (v or {}).get("problems", [])]
    return steps, errors, probs


def deterministic(v, state, summary):
    steps, errors, probs = digest(v)
    k = (v or {}).get("stats", {})
    calls = (k.get("model") or {}).get("calls", 0)
    tools = {}
    for s in steps:
        name = s.split("(", 1)[0]
        tools[name] = tools.get(name, 0) + 1
    did = f"{calls} model calls, {len(steps)} steps" + (": " + ", ".join(f"{t} ×{n}" for t, n in sorted(tools.items(), key=lambda x: -x[1])[:5]) if tools else "")
    lines = [f"Did: {did}", f"Found: {clip(summary, 300)}" if summary else ""]
    if state != "done" or errors or probs:
        lines.append("Failed: " + clip("; ".join(([state] if state != "done" else []) + errors[:2] + probs[:2]) or state, 300))
    return [x for x in lines if x]


ENTRY_PROMPT = P.text("journal", "ENTRY")


def condense(v, title, run, state, summary, seconds, result):
    steps, errors, probs = digest(v)
    if os.environ.get("JOURNAL_MODEL", "1") == "0" or (not steps and not result) or (M and M.paused(summary)):
        return None                              # nothing to condense, or the model is limited: deterministic
    prompt = ENTRY_PROMPT.format(title=title, run=run, state=state, seconds=f"{round(seconds or 0)} s", summary=clip(summary, 600),
                                 n=len(steps), steps="\n".join(TC.more(steps, 40, "more steps")) or "(none)", errors="; ".join(TC.more(errors, 5, "more errors") + TC.more(probs, 5, "more problems")) or "none",  # cap: prompt
                                 result=TC.cut(str(result or ""), 3000) or "(none)")  # cap: prompt
    P.record(prompt)                                  # MEM-11: the run records the prompt's version
    try:
        out = M.ask_text(prompt, os.environ["VK_JOURNAL"], model="gpt-sub-fast", timeout=90)
    except Exception as e:
        _log(f"journal: the model condense was skipped ({type(e).__name__}): deterministic entry")
        return None
    lines = [clip(ln.strip("-* \t"), 260) for ln in out.splitlines() if re.match(r"^\W*(Did|Found|Failed|Open):", ln.strip())]
    return [re.sub(r"^\W*", "", ln) for ln in lines][:4] or None


def record(agent, title, run, state, summary="", seconds=None, result=""):
    """At a run's end: one entry from its runtime record; the run's log shows the write. → the entry's lines."""
    a = aid(agent)
    v = run_view(run) if run else None
    lines = condense(v, title, run, state, summary, seconds, result) or deterministic(v, state, summary)
    t = (M.now() if M else dt.datetime.now())
    label = f"run {run.split(':')[1]}" if run and run.startswith("mission-run:") else "run"
    head = f"{t:%Y-%m-%d %H:%M} · {label} · {state}" + (f" · {round(seconds / 60)} min" if seconds and seconds >= 90 else "")
    with _lock:
        doc = load(a)
    doc["title"] = doc["title"] or title
    doc["entries"].append({"head": head, "lines": lines})
    save(a, doc, f"journal: {a} {head}")
    if run:
        _emit_read(run, agent, "journal_write", {"path": rel(a), "content": f"### {head}\n" + "\n".join(f"- {x}" for x in lines)},
                   "journal entry written", sum(map(len, lines)))
    return lines


def after_run(m, rid, status, summary, output, seconds):
    """The mission runner's hook (missions.execute): its entry. Never fails the run."""
    end()
    try:
        state = "limit" if status == "failed" and M.paused(summary) else {"ok": "done"}.get(status, status)
        res = (VAULT / output).read_text(errors="replace") if output and (VAULT / output).is_file() else ""
        record(f"mission:{m['slug']}", m["title"], f"mission-run:{rid}", state, summary, seconds, res)
    except Exception as e:
        _log(f"journal {m.get('slug')}: {type(e).__name__}: {e}")


# ---------- the app and the agents change it: notes, edits, forgetting ----------
def note(agent, text, by="agent"):
    t = clip(text, 300)
    if not t:
        raise ValueError("an empty note")
    with _lock:
        doc = load(agent)
    if t in doc["notes"]:
        return {"notes": len(doc["notes"])}
    doc["notes"].append(t)
    doc["title"] = doc["title"] or aid(agent)
    save(agent, doc, f"journal: {aid(agent)} standing note ({by})")
    return {"notes": len(doc["notes"])}


def edit(agent, section, old, text):
    """Change one line (text) or forget it (text empty), by its exact old text."""
    old, new = str(old or "").strip(), clip(text, 400)
    with _lock:
        doc = load(agent)
    hits = [lst for lst in ([doc["notes"]] if section == "notes" else [e["lines"] for e in doc["entries"]]) if old in lst]
    if not hits:
        raise ValueError("that line is not in the memory any more (reload)")
    lst = hits[-1]
    i = lst.index(old)
    if new:
        lst[i] = new
    else:
        lst.pop(i)
    doc["entries"] = [e for e in doc["entries"] if e["lines"]]
    save(agent, doc, f"journal: {aid(agent)} {'line edited' if new else 'line forgotten'} by the owner")
    return {"changed": True}


def handle(req):
    a = req.get("action")
    if a == "journal_note":
        return note(req.get("agent"), req.get("text"), by="The owner" if req.get("by") == "you" else "agent")
    if a == "journal_edit":
        return edit(req.get("agent"), "notes" if req.get("section") == "notes" else "journal", req.get("old"), req.get("text", ""))
    raise ValueError("unknown journal action")


# ---------- the memory curator: old entries fold into standing notes ----------
FOLD_PROMPT = P.text("journal", "FOLD")


def curate():
    """Fold each long journal's old entries into its standing notes; they move to ARCHIVE.md. → journals tidied."""
    root, n = VAULT / "agents", 0
    for p in sorted(root.glob("*/MEMORY.md")) if root.exists() else []:
        a = p.parent.name
        doc = load(a)
        if len(doc["entries"]) < FOLD_AT:
            continue
        old, keep = doc["entries"][:-KEEP], doc["entries"][-KEEP:]  # cap: rotate (the older ones fold into standing notes)
        try:
            d = M.ask_json(FOLD_PROMPT.format(title=doc["title"], notes="\n".join(f"- {x}" for x in doc["notes"]) or "(none)",
                                              entries=TC.cut("\n\n".join(e["head"] + "\n" + "\n".join(f"- {x}" for x in e["lines"]) for e in old), 12000)),  # cap: prompt
                           os.environ["VK_JOURNAL"], model="gpt-sub-fast", timeout=180)
            notes = [clip(x, 220) for x in d.get("notes") or [] if str(x).strip()][:12]
        except Exception as e:
            _log(f"journal curate {a}: skipped ({type(e).__name__})")
            continue
        if not notes and doc["notes"]:
            continue                             # an empty answer never wipes the notes
        arch = p.parent / "ARCHIVE.md"
        prev = arch.read_text() if arch.exists() else f"# Journal archive: {doc['title'] or a}\n\n_Entries folded into the standing notes by the memory curator._\n"
        arch.write_text(prev.rstrip() + "\n\n" + "\n\n".join(f"### {e['head']}\n" + "\n".join(f"- {x}" for x in e["lines"]) for e in old) + "\n")
        doc["notes"], doc["entries"] = notes, keep
        save(a, doc, f"journal: {a} {len(old)} old entries folded into standing notes (memory curator)", extra=[f"agents/{a}/ARCHIVE.md"])
        n += 1
    return n

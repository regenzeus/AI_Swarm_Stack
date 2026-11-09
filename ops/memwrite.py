#!/usr/bin/env python3
"""What enters memory, and how (docs/MEMORY-STACK.md "Writing", MEM-35 to MEM-38, MEM-48, MEM-49).

A run's note (the memory tool's note) and a run's result are candidates. A candidate enters memory only through reconcile:
  1 the rubric: evidence named; not about the agent's own run; durable; for code, not a restatement of the code. The cheap
    checks are code; the judgement is one call of prompts/memory.md RUBRIC (none when the model is limited: the code checks decide)
  2 its sector: a lesson -> its role's playbook (vault/howto/lessons/<role>.md); a fact about the world -> a filed source
    for the vault wiki's curator (raw/_inbox); a failure -> its repository wiki's Fragile areas; a fact about the owner ->
    long-term memory's retain (whose mission keeps only facts about him); a skill idea -> the Distiller's queue
  3 inside the sector: add, confirm (a repeat: the lesson's tally rises, the date is added), skip; never a blind overwrite
Every outcome goes to /srv/ai/missions/memory/writes.jsonl with what it was, where it went and how to undo it (undo(id)).

  python3 ops/memwrite.py undo <id> | log [n]"""
import datetime as dt
import hashlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md
import textcap as TC                              # visible caps (AGENTS.md, truncation)

M = None                                          # ops/missions.py when the runner loaded this module
VAULT = Path(os.environ.get("MEMORY_VAULT", "/srv/vault"))
DIR = Path(os.environ.get("MEMSTACK_DIR", "/srv/ai/missions/memory"))
LOG = DIR / "writes.jsonl"
KINDS = ("lesson", "fact", "failure", "owner", "skill")
OWN_RUN = re.compile(r"\b(this run|my run|in this task|i (ran|called|tried|started|finished|searched|opened)|the run (took|ended|failed))\b", re.I)
UNTRUSTED = re.compile(r"https?://|\bmail\b|\be-?mail\b|\bnewsletter\b|\bweb ?page\b", re.I)
RUBRIC = P.text("memory", "RUBRIC")
SAME = 0.6                                        # word overlap at which a lesson or fact is the same as one already held


def now_iso():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def words(s):
    return {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", str(s or ""))} - {"the", "and", "for", "with", "that", "this", "from"}


def overlap(a, b):
    """How much of the shorter text the longer one holds (a fact inside a page's snippet)."""
    wa, wb = words(a), words(b)
    return len(wa & wb) / max(1, min(len(wa), len(wb))) if wa and wb else 0.0


NEGATION = re.compile(r"\b(never|not|no|don'?t|do not|avoid|without|nicht|nie|kein\w*)\b", re.I)


def numbers(s):
    """The numbers and dates a text names, written the same way ("25,000" and "25000" are one)."""
    return {re.sub(r"[.,\s]", "", n) for n in re.findall(r"\d[\d.,]*\d|\d", str(s or ""))}


def same_lesson(a, b):
    """Two lessons say the same: most of both texts' words shared (symmetric, so a short lesson never counts as a longer
    one it shares three words with), the same numbers, and neither says never where the other does not (review MEM-R10)."""
    wa, wb = words(a), words(b)
    if not wa or not wb or 2 * len(wa & wb) / (len(wa) + len(wb)) < SAME:
        return False
    return numbers(a) == numbers(b) and bool(NEGATION.search(a)) == bool(NEGATION.search(b))


def same_fact(held, text):
    """A page or note already holds this fact: its words, and every number and date it names. A fact for another year or
    with another figure is a newer fact, never "already held" (review MEM-R10: 2026's guidance was skipped as 2025's)."""
    return overlap(held, text) >= SAME and numbers(text) <= numbers(held)


def log(entry):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def writes(n=None):
    """The log's writes, each marked undone or not (an undo record is {"undo": "<write id>"}; a write's own "undo" is how)."""
    try:
        rows = [json.loads(ln) for ln in LOG.read_text().splitlines() if ln.strip()]
    except OSError:
        return []
    undone = {r["undo"] for r in rows if isinstance(r.get("undo"), str)}
    out = [r | {"undone": r["id"] in undone} for r in rows if not isinstance(r.get("undo"), str)]
    return out if n is None else out[-n:]  # cap: list (the caller says how many in all)


def commit(paths, msg):
    import journal as J
    J.commit(paths, msg)


def role_of(agent):
    """The playbook a lesson of this agent goes to: its card's first role (crew-builder -> builder's card -> code)."""
    import memstack as MS
    a = MS.agent_id(agent)
    reg = MS.registry()
    cards = [a, a.removeprefix("crew-")] + (["mission"] if a.startswith("mission-") else [])
    for cid in cards:
        roles = (reg.get(cid) or {}).get("roles") or []
        if roles:
            return roles[0]
    return "default"


# ---------- the rubric (MEM-35) ----------
def checks(c):
    """The rubric's checks that need no model -> the reason it fails, or ''."""
    if c["kind"] not in KINDS:
        return f"the kind is {c['kind']!r}, not one of {', '.join(KINDS)}"
    if len(c["text"]) < 12:
        return "too short to hold a fact"
    if c["kind"] != "skill" and len(c["evidence"]) < 4:
        return "no evidence: name the file, page, URL, commit, run or chat it comes from"
    if OWN_RUN.search(c["text"]) and c["kind"] != "failure":
        return "it is about the agent's own run: the journal and the run record keep that"
    if c["kind"] == "failure" and not c.get("repo"):
        return "a failure belongs to a repository: name it"
    return ""


def judge(c, ask=None):
    """The rubric's judgement (durable; for code not a restatement of the code) -> (keep, why). Without a model: keep."""
    if c["kind"] in ("owner", "skill"):
        return True, "decided by its sector (the retain mission, the Distiller)"
    ask = ask or (lambda p: M.ask_json(p, os.environ.get("VK_MEMORY", ""), model="gpt-sub-fast", timeout=120) if M else None)
    try:
        prompt = RUBRIC.format(kind=c["kind"], text=c["text"], evidence=c["evidence"], repo=c.get("repo") or "(none)")
        P.record(prompt)
        d = ask(prompt)
    except Exception as e:
        return True, f"kept on the checks alone: the rubric's model could not be asked ({type(e).__name__})"
    if not isinstance(d, dict):
        return True, "kept on the checks alone: no model"
    return bool(d.get("keep")), TC.cut(str(d.get("why") or ""), 300)  # cap: untrusted (a model's reason)


# ---------- the sectors ----------
def playbook_path(role):
    return VAULT / "howto" / "lessons" / f"{role}.md"


PLAYBOOK_HEAD = ("_What runs in this role learned. Each lesson names its evidence. Its tally rises by one when a run that was given "
                 "it ends done and falls by one when such a run fails; at 0 it moves under Retired. Written by the memory agent "
                 "(ops/memwrite.py, ops/distiller.py); edit or delete a line here and it stays so._")


def read_playbook(role):
    import memstack as MS
    f = playbook_path(role)
    if not f.is_file():
        return {"title": f"Lessons for {role}", "type": "playbook", "role": role}, [], []
    meta, body = MS.split_front(f.read_text(errors="replace"))
    live, _, retired = body.partition("\n## Retired")
    return meta, [ln for ln in live.splitlines() if ln.startswith("- ")], [ln for ln in retired.splitlines() if ln.startswith("- ")]


def write_playbook(role, meta, live, retired):
    f = playbook_path(role)
    f.parent.mkdir(parents=True, exist_ok=True)
    import yaml
    body = (f"---\n{yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)}---\n# Lessons for {role}\n\n{PLAYBOOK_HEAD}\n\n"
            + "\n".join(live) + "\n\n## Retired\n\n" + "\n".join(retired) + "\n")
    f.write_text(body)


def lesson_line(text, evidence, tally, lid, since):
    clean = lambda s: re.sub(r"[()\n]+", " ", str(s)).strip()
    return f"- {clean(text)} (evidence: {clean(evidence)}; tally {tally}; id {lid}; since {since})"


PLAYBOOKS = threading.Lock()                      # a note's thread and a run's tallies never write one playbook at once


def add_lesson(role, text, evidence, start=1):
    """-> (outcome, lesson id, the line before when it was confirmed)."""
    import memstack as MS
    with PLAYBOOKS:
        meta, live, retired = read_playbook(role)
        for i, ln in enumerate(live):
            m = MS.LESSON.match(ln)
            if m and same_lesson(m["text"], text):
                before = ln
                # the first evidence and the newest one (review MEM-R10: a repeat's evidence was dropped); the newest
                # confirmation only, so a line does not grow with each
                first = re.sub(r", confirmed \d{4}-\d{2}-\d{2}$", "", m["ev"]).split("; latest: ")[0]
                ev = first if not evidence or str(evidence).strip() in first else f"{first}; latest: {evidence}"
                live[i] = lesson_line(m["text"], f"{ev}, confirmed {dt.date.today().isoformat()}", int(m["tally"]) + 1, m["id"], m["since"] or "")
                write_playbook(role, meta, live, retired)
                return "confirm", m["id"], before
        lid = "L-" + hashlib.sha1(f"{role}:{text}".encode()).hexdigest()[:8]
        live.append(lesson_line(text, evidence, start, lid, dt.date.today().isoformat()))
        write_playbook(role, meta, live, retired)
        return "add", lid, None


def file_fact(c, untrusted):
    """A fact about the world, filed for the vault wiki's curator, naming the agent, its evidence and the entry it came from."""
    import yaml
    d = VAULT / "raw" / "_inbox"
    d.mkdir(parents=True, exist_ok=True)
    name = f"{dt.date.today().isoformat()}-note-{c['id']}.md"
    meta = {"title": TC.cut(c["text"], 80, "the note holds it whole"), "source": f"agent {c['agent'] or 'unknown'}", "evidence": c["evidence"],  # cap: id
            "from": c.get("from") or c["id"], "filed": now_iso(), **({"untrusted": True} if untrusted else {})}
    (d / name).write_text(f"---\n{yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)}---\n{c['text']}\n\nEvidence: {c['evidence']}\n")
    return f"raw/_inbox/{name}"


def held_fact(text):
    """A page or filed note that already says this (the vault search, then the words) -> its path, or ''."""
    import memstack as MS
    try:
        hits = MS.qmd_search(text, 8)
    except Exception as e:                               # no search: the fact is filed, and the curator's compile reconciles it
        print(f"memwrite: the vault search did not answer ({type(e).__name__}: {e}): filed without the check", flush=True)
        return ""
    for h in hits:
        if same_fact(h["snippet"], text):
            return h["path"]
    return ""


def retain_owner(c):
    """A fact about the owner through long-term memory's own retain (its mission keeps only facts about him)."""
    import journal as J
    body = {"items": [{"content": c["text"], "context": f"noted by the agent {c['agent'] or 'unknown'}; evidence: {c['evidence']}",
                       "tags": [f"source:agent:{c['agent'] or 'unknown'}"], "metadata": {"candidate": c["id"]}}], "async": True}
    r = J.hindsight("memories", body, timeout=60)
    if r is None:
        raise RuntimeError("Hindsight did not take it")
    return r


def reconcile(c, ask=None):
    """One candidate into its sector -> its log entry (MEM-35, MEM-36)."""
    why = checks(c)
    base = {"id": "W-" + c["id"][2:], "at": now_iso(), "candidate": c}
    if why:
        return log({**base, "outcome": "reject", "why": why})
    keep, why = judge(c, ask)
    if not keep:
        return log({**base, "outcome": "reject", "why": why})
    untrusted = bool(UNTRUSTED.search(c["evidence"]))
    k = c["kind"]
    if k == "lesson":
        role = c.get("role") or role_of(c["agent"])
        outcome, lid, before = add_lesson(role, c["text"], c["evidence"])
        rel = f"howto/lessons/{role}.md"
        commit([rel], f"memory: lesson {lid} {outcome} for {role}")
        return log({**base, "outcome": outcome, "where": rel, "ref": f"lesson:{role}:{lid}", "why": why,
                    "undo": {"kind": "lesson", "role": role, "lesson": lid, "before": before}})
    if k == "fact":
        have = held_fact(c["text"])
        if have:
            return log({**base, "outcome": "skip", "where": have, "why": f"already held in {have}"})
        rel = file_fact(c, untrusted)
        commit([rel], f"memory: a fact filed from {c['agent'] or 'an agent'}")
        return log({**base, "outcome": "add", "where": rel, "why": why, "untrusted": untrusted, "undo": {"kind": "file", "path": rel}})
    if k == "failure":
        import repowiki as RW
        rel = RW.note(c["repo"], "fragile", c["text"], c["evidence"], by=c["agent"] or "agent")
        if rel is None:
            return log({**base, "outcome": "reject", "why": f"{c['repo']} has no wiki yet"})
        if rel == "":
            return log({**base, "outcome": "skip", "where": f"repos/{c['repo']}/wiki/fragile.md", "why": "the page already says it"})
        return log({**base, "outcome": "add", "where": rel, "why": why, "undo": {"kind": "line", "path": rel, "text": c["text"]}})
    if k == "owner":
        retain_owner(c)
        return log({**base, "outcome": "add", "where": "owner:facts", "why": "retained: long-term memory keeps it only if it is about the owner",
                    "undo": {"kind": "owner", "candidate": c["id"]}})
    DIR.mkdir(parents=True, exist_ok=True)
    with (DIR / "skill-ideas.jsonl").open("a") as f:
        f.write(json.dumps(c) + "\n")
    return log({**base, "outcome": "queue", "where": "the Distiller's skill ideas", "why": "a skill is written only by the Distiller"})


def candidate(kind, text, evidence, agent="", run=None, repo=None, source="note", role=None, ask=None, **extra):
    """A note or a yielded result -> a sentence for the agent: what happened to it (MEM-35)."""
    text = TC.limit(re.sub(r"\s+", " ", str(text or "")).strip(), 2000, "the note")
    evidence = TC.limit(re.sub(r"\s+", " ", str(evidence or "")).strip(), 500, "the evidence")
    cid = "C-" + hashlib.sha1(f"{kind}:{text}:{time.time_ns()}".encode()).hexdigest()[:10]
    c = {"id": cid, "kind": str(kind or "").strip().lower(), "text": text, "evidence": evidence, "agent": str(agent or ""), "run": run,
         "repo": repo or None, "source": source, **({"role": role} if role else {}), **extra}
    try:
        e = reconcile(c, ask)
    except Exception as ex:
        e = log({"id": "W-" + cid[2:], "at": now_iso(), "candidate": c, "outcome": "error", "why": f"{type(ex).__name__}: {ex}"})
    words_ = {"add": "Kept", "confirm": "Already known; confirmed", "skip": "Already held", "queue": "Queued for the Distiller",
              "reject": "Not kept", "error": "Could not be written"}
    return f"{words_.get(e['outcome'], e['outcome'])}: {e.get('where') or ''} {('(' + e['why'] + ')') if e.get('why') else ''}".strip() + f" [{e['id']}]"


# ---------- results yield (MEM-37) ----------
def yield_answer(repo, question, answer, task_id, ask=None):
    """A Claude task's answer about a repository: when the rubric finds durable facts in it the code does not state, the Scribe
    folds it into the repository's wiki (its one writer). -> the log entry."""
    import repowiki as RW
    c = {"id": "C-" + hashlib.sha1(f"answer:{task_id}".encode()).hexdigest()[:10], "kind": "fact", "text": TC.cut(answer, 6000, "the task keeps the whole answer"),  # cap: prompt
         "evidence": f"Claude task #{task_id}: {question}", "agent": "claude-task", "repo": repo, "source": "result", "run": f"claude-task:{task_id}"}
    base = {"id": "W-" + c["id"][2:], "at": now_iso(), "candidate": {**c, "text": TC.cut(c["text"], 600, "the task keeps it")}}  # cap: store (the task keeps the answer)
    if not RW.exists(repo):
        return log({**base, "outcome": "reject", "why": f"{repo} has no wiki yet"})
    keep, why = judge(c, ask)
    if not keep:
        return log({**base, "outcome": "reject", "why": why})
    rel = f"repos/{repo}/sources/claude-task-{task_id}.md"
    p = VAULT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# Claude task #{task_id}\n\nQuestion: {question}\n\n{answer}\n")
    written = RW.fold(repo, f"A Claude task's answer about the repository. Question: {question}\n\n{answer}", rel)
    commit([rel, f"repos/{repo}/wiki"], f"memory: Claude task #{task_id} folded into {repo}'s wiki")
    return log({**base, "outcome": "add" if written else "skip", "where": f"repos/{repo}/wiki: {', '.join(written) or 'nothing new'}", "why": why,
                "undo": {"kind": "git", "paths": [rel] + [f"repos/{repo}/wiki/{w}.md" for w in written]}})


# ---------- undo ----------
def undo_lesson(e, u):
    """Undo exactly what this write did to a lesson and nothing that came after it (review MEM-R11): a confirmation takes
    one off the tally (and its evidence, unless a later confirmation stands on it); a retirement brings the lesson back;
    an addition takes the lesson out wherever it is now. A lesson that has moved since is refused, with where it is."""
    import memstack as MS
    with PLAYBOOKS:
        meta, live, retired = read_playbook(u["role"])
        is_it = lambda ln: bool(MS.LESSON.match(ln)) and MS.LESSON.match(ln)["id"] == u["lesson"]
        in_live, in_retired = [ln for ln in live if is_it(ln)], [ln for ln in retired if is_it(ln)]
        if e.get("outcome") == "retire":
            if not in_retired:
                raise ValueError(f"lesson {u['lesson']} is not retired any more: nothing to bring back")
            retired = [ln for ln in retired if not is_it(ln)]
            live.append(u["before"])
        elif e.get("outcome") == "confirm":
            if not in_live:
                raise ValueError(f"lesson {u['lesson']} was retired since this confirmation: undo the retirement first")
            m, b = MS.LESSON.match(in_live[0]), MS.LESSON.match(u["before"] or "")
            later = any(w["ref"] == e.get("ref") and w.get("at", "") > e.get("at", "") and w.get("outcome") == "confirm" and not w.get("undone")
                        for w in writes() if w.get("id") != e["id"] and w.get("ref"))
            ev = b["ev"] if b and not later else m["ev"]
            line = lesson_line(m["text"], ev, int(m["tally"]) - 1, m["id"], m["since"] or "")
            live = [line if is_it(ln) else ln for ln in live]
        else:                                            # an addition: the lesson goes, live or retired
            live, retired = [ln for ln in live if not is_it(ln)], [ln for ln in retired if not is_it(ln)]
        write_playbook(u["role"], meta, live, retired)


def undo(wid):
    e = next((r for r in writes() if r["id"] == wid), None)
    if not e:
        raise ValueError(f"no write {wid} in the memory's log")
    if e["undone"]:
        raise ValueError(f"write {wid} is already undone")
    u = e.get("undo") or {}
    if u.get("kind") == "lesson":
        undo_lesson(e, u)
        commit([f"howto/lessons/{u['role']}.md"], f"memory: undo {wid}")
    elif u.get("kind") == "file":
        p = VAULT / u["path"]
        if not p.exists():                               # vault-ingest moves a filed note on within a minute (review MEM-R6)
            raise ValueError(f"write {wid} was already taken in: {u['path']} went to raw/articles and into the wiki it was "
                             "compiled into. Undo it in the vault's history (git revert of the ingest commit).")
        gone = p.with_name(p.name + ".undone")
        p.rename(gone)
        commit([u["path"], str(gone.relative_to(VAULT))], f"memory: undo {wid}")
    elif u.get("kind") == "line":
        p = VAULT / u["path"]
        if not p.exists():
            raise ValueError(f"write {wid} cannot be undone here: {u['path']} is gone")
        p.write_text("\n".join(ln for ln in p.read_text().splitlines() if u["text"] not in ln) + "\n")
        commit([u["path"]], f"memory: undo {wid}")
    elif u.get("kind") == "git":
        raise ValueError("a wiki fold is undone in the vault's history (git revert of its commit)")
    elif u.get("kind") == "owner":
        raise ValueError("a fact in long-term memory is forgotten on the Memory tab (Long-term, Forget)")
    else:
        raise ValueError(f"write {wid} has nothing to undo ({e['outcome']})")
    log({"id": "U-" + wid[2:], "at": now_iso(), "undo": wid})
    return {"undone": wid}


def main(argv):
    if len(argv) == 3 and argv[1] == "undo":
        print(json.dumps(undo(argv[2])))
        return 0
    if len(argv) >= 2 and argv[1] == "log":
        for r in writes(int(argv[2]) if len(argv) > 2 else 20):
            print(json.dumps(r, ensure_ascii=False))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

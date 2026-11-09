#!/usr/bin/env python3
"""The Distiller (docs/MEMORY-STACK.md, MEM-38, MEM-39): the memory agent's job that turns runs into how-to.

  tally(refs, state)   at a run's end (ops/memstack.py after_run): each lesson the run was given gains 1 when it ended done
                       and loses 1 when it failed; a lesson at 0 moves under its playbook's Retired section
  sequences(...)       the assistant's tool sequences of three or more steps that ended done in skill_runs runs on
                       skill_titles different titles within skill_days (config/memory.yaml), not covered by a skill
  propose(...)         at most skills_per_week a week: the best sequence becomes a skill draft (prompts/memory.md
                       DISTILL_SKILL), refused when it holds a dangerous command, published only through the skills
                       benchmark gate (ops/curate.py --apply), which rolls it back when the gate fails
  run(...)             the weekly pass (ops/crew.py memory, Wednesdays)

  python3 ops/distiller.py sequences | run [--dry]"""
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md
import textcap as TC                              # visible caps (AGENTS.md, truncation)

ROOT = Path(__file__).resolve().parent.parent
M = None                                          # ops/missions.py when the runner or the crew set it
DIR = Path(os.environ.get("MEMSTACK_DIR", "/srv/ai/missions/memory"))
RUNTIME_DB = Path(os.environ.get("RUNTIME_DB_HOST", "/srv/ai/missions/app/runtime.db"))
DISTILL = P.text("memory", "DISTILL_SKILL")
DANGEROUS = re.compile(r"rm\s+-rf|curl[^\n|]*\|\s*(ba)?sh|wget[^\n|]*\|\s*(ba)?sh|chmod\s+777|\bsudo\b|/etc/(passwd|shadow)|BEGIN [A-Z ]*PRIVATE KEY"
                       r"|\b(api[_-]?key|password|passwd|secret)\s*[:=]|\bmkfs\b|\bdd\s+if=|:\(\)\s*\{", re.I)
NOISE = re.compile(r"memory_opening|journal_write|swarm_context|swarm_finish|todo|skill_view|skills_list|memory_recall|wiki_search|read_file$")


def now_iso():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


# ---------- lessons (MEM-38) ----------
def tally(refs, state):
    """+1 for each lesson a run that ended done was given, -1 for one that failed; at 0 under Retired. -> {lesson id: tally}."""
    if state not in ("done", "failed") or not refs:
        return {}
    import memstack as MS
    import memwrite as MW
    by_role = {}
    for r in refs:
        parts = r.split(":")
        if len(parts) == 3 and parts[0] == "lesson":
            by_role.setdefault(parts[1], set()).add(parts[2])
    out, touched = {}, []
    for role, ids in by_role.items():
        with MW.PLAYBOOKS:
            meta, live, retired = MW.read_playbook(role)
            keep = []
            for ln in live:
                m = MS.LESSON.match(ln)
                if not m or m["id"] not in ids:
                    keep.append(ln)
                    continue
                t = int(m["tally"]) + (1 if state == "done" else -1)
                line = MW.lesson_line(m["text"], m["ev"], t, m["id"], m["since"] or "")
                out[m["id"]] = t
                if t <= 0:
                    retired.append(line)
                    MW.log({"id": "W-" + hashlib.sha1(f"retire:{m['id']}:{time.time()}".encode()).hexdigest()[:10], "at": now_iso(), "outcome": "retire",
                            "where": f"howto/lessons/{role}.md", "ref": f"lesson:{role}:{m['id']}", "why": f"its tally fell to {t}: runs given it failed",
                            "undo": {"kind": "lesson", "role": role, "lesson": m["id"], "before": ln}, "candidate": {"kind": "lesson", "text": m["text"]}})
                else:
                    keep.append(line)
            MW.write_playbook(role, meta, keep, retired)
        touched.append(f"howto/lessons/{role}.md")
    if touched:
        MW.commit(touched, f"memory: lesson tallies after a run that {'ended done' if state == 'done' else 'failed'}")
    return out


# ---------- skills (MEM-39) ----------
def lim(name, default):
    import memstack as MS
    return int(MS.limit(name, default))


def sequences(days=None, runs_needed=None, titles_needed=None, db=RUNTIME_DB, now=None, agent="main", covered=None):
    """[{sequence, runs, titles, examples}] of tool sequences (3 to 6 calls) that ended done in enough runs on enough titles."""
    days = days or lim("skill_days", 30)
    runs_needed = runs_needed or lim("skill_runs", 3)
    titles_needed = titles_needed or lim("skill_titles", 3)
    now = now or time.time()
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    runs = c.execute("select run, title from runs where agent=? and end_state='done' and started>=?", (agent, now - days * 86400)).fetchall()
    seen = {}
    for run, title in runs:
        if not str(title or "").strip():
            continue                                      # a run without a title cannot count as a different task
        raw = [t for (t,) in c.execute("select title from events where run=? and kind='call' order by ts", (run,)) if t and not NOISE.search(t)]
        calls = [t for i, t in enumerate(raw) if not i or t != raw[i - 1]]   # a call repeated at once is one step
        grams = set()
        for n in range(3, 7):
            for i in range(len(calls) - n + 1):
                g = tuple(calls[i:i + n])
                if len(set(g)) == n:                       # every step a different tool: a look-tap-look loop is not a procedure
                    grams.add(g)
        for g in grams:
            s = seen.setdefault(g, {"runs": set(), "titles": set(), "examples": []})
            s["runs"].add(run)
            s["titles"].add(re.sub(r"\s+", " ", str(title or ""))[:120])  # cap: id (the run's title is in its record)
            if len(s["examples"]) < 3:
                s["examples"].append({"run": run, "title": title})
    covered = covered if covered is not None else covered_by_skills()
    out = []
    for g, s in seen.items():
        if len(s["runs"]) >= runs_needed and len(s["titles"]) >= titles_needed and not covered(g):
            out.append({"sequence": list(g), "runs": len(s["runs"]), "titles": len(s["titles"]), "examples": s["examples"]})
    longest = {}
    for x in sorted(out, key=lambda x: (-len(x["sequence"]), -x["runs"])):  # a longer sequence holds its shorter parts
        key = " ".join(x["sequence"])
        if not any(key in k for k in longest):
            longest[key] = x
    return sorted(longest.values(), key=lambda x: (-x["runs"], -len(x["sequence"])))


def covered_by_skills():
    """A sequence is covered when a skill (or an earlier proposal) names every tool of it."""
    import memstack as MS
    try:
        bodies = [s.get("body", "") for s in json.loads((MS.PUBLIC / "skills.json").read_text()).get("skills") or []]
    except (OSError, ValueError):
        bodies = []
    try:
        bodies += [json.loads(ln).get("sequence_text", "") for ln in (DIR / "skills.jsonl").read_text().splitlines() if ln.strip()]
    except OSError:
        pass
    short = lambda t: t.split("__")[-1]
    return lambda g: any(all(short(t) in b for t in g) for b in bodies)


def name_of(seq):
    tail = [re.sub(r"[^a-z0-9]+", "-", t.split("__")[-1].lower()).strip("-") for t in seq]
    return ("distilled-" + "-".join(dict.fromkeys(tail)))[:60].strip("-")  # cap: id (the sequence is kept whole in the proposal)


def dangerous(text):
    m = DANGEROUS.search(text or "")
    return m.group(0) if m else ""


def install_script(name, draft):
    """The command the benchmark gate applies: the draft copied into Hermes' skills (distilled/<name>/SKILL.md)."""
    if not re.fullmatch(r"[a-z0-9-]{3,60}", name):
        raise ValueError(f"not a skill name: {name!r}")
    return (f"docker exec -i -u hermes aistack-hermes-1 sh -c 'mkdir -p /opt/data/skills/distilled/{name} && "
            f"cat > /opt/data/skills/distilled/{name}/SKILL.md' < {draft}")


def propose(ask=None, gate=None, dry=False, candidates=None):
    """At most one skill a pass: the best uncovered sequence -> a draft -> the danger check -> the benchmark gate. -> the record."""
    cands = candidates if candidates is not None else sequences()
    if not cands:
        return {"proposed": None, "why": "no tool sequence ended done often enough on enough different tasks"}
    x = cands[0]
    name = name_of(x["sequence"])
    ask = ask or (lambda p: M.ask_json(p, os.environ.get("VK_MEMORY", ""), model="gpt-sub-fast", timeout=300))   # the memory agent's key (ops/keys.sh)
    runs = "\n".join(f"- run {e['run']}: {e['title']}" for e in x["examples"])
    prompt = DISTILL.format(name=name, sequence=" → ".join(x["sequence"]), runs=runs)
    P.record(prompt)
    d = ask(prompt)
    body = str(d.get("body") or "")
    desc = TC.cut(str(d.get("description") or "").strip(), 300)  # cap: untrusted (a model's answer)
    rec = {"at": now_iso(), "name": name, "sequence": x["sequence"], "sequence_text": " ".join(t.split("__")[-1] for t in x["sequence"]),
           "runs": x["runs"], "titles": x["titles"], "description": desc}
    bad = dangerous(body) or dangerous(desc)
    if not body.strip() or bad:
        rec.update(decision="refused", why=f"a dangerous command in the draft: {bad}" if bad else "the draft was empty")
        return record(rec)
    draft = DIR / "skill-drafts" / name / "SKILL.md"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(f"---\nname: {name}\ndescription: {json.dumps(desc)}\nauthor: the memory agent's Distiller\n---\n{body.strip()}\n")
    os.chmod(draft, 0o644)
    if dry:
        rec.update(decision="drafted", draft=str(draft))
        return record(rec)
    gate = gate or (lambda cmd: subprocess.run([sys.executable, str(ROOT / "ops/curate.py"), "--apply", cmd, "--no-lint"], capture_output=True, text=True,
                                                timeout=7200, cwd=ROOT).returncode)
    rc = gate(install_script(name, draft))
    rec.update(decision="published" if rc == 0 else "rolled back", why="the skills benchmark kept it" if rc == 0 else "the skills benchmark did not keep it")
    return record(rec)


def record(rec):
    DIR.mkdir(parents=True, exist_ok=True)
    with (DIR / "skills.jsonl").open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    import memwrite as MW
    MW.log({"id": "W-" + hashlib.sha1(f"skill:{rec['name']}:{rec['at']}".encode()).hexdigest()[:10], "at": rec["at"],
            "outcome": {"published": "add", "drafted": "queue"}.get(rec["decision"], "reject"), "where": f"howto:skills ({rec['name']})",
            "why": rec.get("why") or rec["decision"], "candidate": {"kind": "skill", "text": rec["sequence_text"]}})
    return rec


def proposed_this_week(now=None):
    now = now or time.time()
    try:
        rows = [json.loads(ln) for ln in (DIR / "skills.jsonl").read_text().splitlines() if ln.strip()]
    except OSError:
        return 0
    week = dt.datetime.fromtimestamp(now - 7 * 86400).astimezone().isoformat()
    return sum(1 for r in rows if r.get("at", "") >= week and r.get("decision") in ("published", "rolled back"))


def run(dry=False, ask=None, gate=None, now=None):
    """The weekly pass: a skill proposal while the week's quota allows it and the memory trials pass (MEM-47)."""
    import memtrials as MT
    rep = {"at": now_iso()}
    open_, why = MT.gate()
    rep["gate"] = {"open": open_, "why": why}
    if not open_:
        rep["skill"] = {"proposed": None, "why": f"waits: {why}"}
        return rep
    if proposed_this_week(now) >= lim("skills_per_week", 1):
        rep["skill"] = {"proposed": None, "why": "this week's skill was proposed already"}
        return rep
    try:
        rep["skill"] = propose(ask=ask, gate=gate, dry=dry)
    except Exception as e:
        rep["skill"] = {"error": f"{type(e).__name__}: {e}"}
    return rep


def main(argv):
    global M
    import missions
    M = missions
    if len(argv) >= 2 and argv[1] == "sequences":
        print(json.dumps(sequences()[:10], indent=1))  # cap: top (the ten with the most runs)
        return 0
    if len(argv) >= 2 and argv[1] == "run":
        print(json.dumps(run(dry="--dry" in argv), indent=1, default=str))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

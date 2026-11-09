#!/usr/bin/env python3
"""The Memory Keeper (MEM-17, MEM-18, MEM-20, MEM-21, DEC-40): the one agent that looks after every memory store, every
night (its judgement parts on Wednesdays). docs/MEMORY.md, "The Memory Keeper", has the design; its rules:

  1. Nothing is deleted: a long-term fact is soft-retired (reversible) or rewritten with its old text kept; a wiki fact
     moves under Superseded; the vault's history keeps every version.
  2. Every change is in the change log (LOG) with what was there, what is there now, why and how to undo it.
  3. The world is corrected only from sources: a disputed or outdated wiki fact gets a refinement task (TSK-34) whose
     research the wiki's own writer folds in. The Keeper never writes a fact.
  4. The owner's facts stay his: in long-term memory only hygiene (duplicates, test noise, agents' runs, English, end
     dates); two of his facts that disagree become a question for him.
  5. The automatic changes run only while the memory trial on the current prompt passes (PRECISION, RECALL).
  6. Bounded: AUTO_MAX changes, DISPUTES and RECHECKS tasks a pass.

  python3 ops/keeper.py trial          the memory trial: eval/trials/memory.yaml through the Keeper's own judgement
  python3 ops/keeper.py undo <change>  undo one change of the log
  python3 ops/keeper.py pass [--dry]   one pass by hand (the crew-memory unit runs it every night)
Run with secrets: sops exec-env secrets/agent-keys.enc.yaml '...' (VK_MEMORY)."""
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md
import textcap as TC                              # visible caps (AGENTS.md, truncation)

ROOT = Path(__file__).resolve().parent.parent
M = None                                          # ops/missions.py (set by crew)
LOG = Path(os.environ.get("KEEPER_LOG", "/srv/ai/state/keeper.jsonl"))
TRIAL = Path(os.environ.get("KEEPER_TRIAL", "/srv/ai/trials/memory/result.json"))
FIXTURE = ROOT / "eval/trials/memory.yaml"
VAULT = Path(os.environ.get("MEMORY_VAULT", "/srv/vault"))
HERMES = "aistack-hermes-1"
BANK = "owner"
# limit: paces, automatic memory changes a pass; the rest are listed and follow
AUTO_MAX = 40          # automatic changes in long-term memory a pass; the rest are listed
DISPUTES = 2           # refinement tasks a pass for contradictions open DISPUTE_DAYS
RECHECKS = 1           # refinement tasks a pass for stale pages agents still read
DISPUTE_DAYS = 14
CROSS_HUBS = 4         # subjects shared by two or more wikis checked a week
PRECISION, RECALL = 0.95, 0.6
TRIAL_RUNS = 3         # the gate reads the worst of the last runs on the current prompt
AUTO = {"duplicate", "test_noise", "agent_run", "not_english", "passing_state", "superseded"}
OWNER_ONLY = {"contradiction", "stale", "other"}   # what the model may name; a contradiction becomes "superseded" (DEC-44), the rest stay notes
KEEPER = P.text("memory", "KEEPER_FACTS")
CROSS = P.text("memory", "CROSS_CHECK")


def now_iso():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def ask_json(prompt, key=None):
    return M.ask_json(prompt, key or os.environ["VK_MEMORY"], model="gpt-sub-fast", timeout=600)


# ---------- long-term memory (Hindsight) ----------
def facts():
    """The bank's world and experience facts (observations are Hindsight's own consolidation of them)."""
    q = ("select id, fact_type, to_char(created_at, 'YYYY-MM-DD'), coalesce(to_char(occurred_end, 'YYYY-MM-DD'), ''), "
         "replace(replace(text, chr(10), ' '), '|', '/') from memory_units "
         f"where bank_id = '{BANK}' and fact_type in ('world', 'experience') order by created_at")
    out = subprocess.run(["docker", "exec", "aistack-hindsight-db-1", "psql", "-U", "hindsight", "-d", "hindsight", "-tAF", "|", "-c", q],
                         capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise RuntimeError(f"Hindsight's database: {out.stderr.strip()}")
    rows = []
    for ln in out.stdout.splitlines():
        p = ln.split("|", 4)
        if len(p) == 5:
            rows.append({"id": p[0], "type": p[1], "date": p[2], "end": p[3], "text": p[4]})
    return rows


def hindsight(ops):
    """PATCH memory units in one call through Hermes (Hindsight is reachable only on memnet): [(id, body)] -> [ok]."""
    if not ops:
        return []
    code = ("import json,sys,urllib.request as u\nout=[]\n"
            "for i,b in json.loads(sys.argv[1]):\n"
            f"  r=u.Request('http://hindsight:8888/v1/default/banks/{BANK}/memories/'+i, method='PATCH', data=json.dumps(b).encode(), "
            "headers={'Content-Type':'application/json'})\n"
            "  try:\n    u.urlopen(r,timeout=120); out.append(True)\n  except Exception as e:\n    print('fail',i,e,file=sys.stderr); out.append(False)\n"
            "print(json.dumps(out))")
    p = subprocess.run(["docker", "exec", HERMES, "/opt/hermes/.venv/bin/python", "-c", code, json.dumps(ops)],
                       capture_output=True, text=True, timeout=120 + 120 * len(ops))
    if p.returncode:
        raise RuntimeError(f"Hindsight: {p.stderr.strip()}")
    return json.loads(p.stdout.strip().splitlines()[-1])


def words(s):
    return {w for w in re.findall(r"[a-z0-9äöüß]+", s.lower()) if len(w) > 2}


def overlap(a, b):
    wa, wb = words(a), words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def english(s):
    """Mostly English: no German or Spanish marker words and letters a-z (the multilingual embedding still finds it)."""
    low = f" {s.lower()} "
    return not re.search(r" (der|die|das|und|nicht|ist|ein|eine|mit|für|el|la|los|las|para|que|una|del|owner prefiere) ", low)


NUMBER = re.compile(r"\d+(?:[.,:]\d+)*")


def merge_ok(t, older, newer):
    """MEM-50: a merged fact keeps every number and date of both, is English, and is no longer than both together."""
    nums = set(NUMBER.findall(older)) | set(NUMBER.findall(newer))
    return english(t) and len(t) <= len(older) + len(newer) + 40 and nums <= set(NUMBER.findall(t))


def classify(fs, ask=ask_json):
    """Each fact the Keeper would change, with its class: [{id, class, of?, text?, end?, why}]. Exact duplicates are
    found without the model; the rest is the model's judgement (KEEPER_FACTS), checked here before it counts."""
    by = {f["id"]: f for f in fs}
    out, seen, merged = [], set(), set()
    norm = {}
    for f in fs:                                        # oldest first: the older one stays
        k = re.sub(r"[^a-z0-9äöüß]+", " ", f["text"].lower()).strip()   # every word and number: "at 06:30" is not "at 07:15"
        if k and k in norm:
            out.append({"id": f["id"], "class": "duplicate", "of": norm[k], "why": "the same words as an older fact"})
            seen.add(f["id"])
        else:
            norm.setdefault(k, f["id"])
    rest = [f for f in fs if f["id"] not in seen]
    if not rest:
        return out
    lines = "\n".join(f"{f['id']} | {f['type']} | {f['date']}{' to ' + f['end'] if f['end'] else ''} | {f['text']}" for f in rest[-400:])  # cap: list (the header says how many)
    head = "" if len(rest) <= 400 else f"(the newest 400 of {len(rest)} facts)\n"
    d = ask(KEEPER.format(today=dt.date.today().isoformat(), facts=head + TC.cut(lines, 60000, "the rest waits for the next pass")))  # cap: prompt
    for x in d.get("findings") or []:
        fid, cls = str(x.get("id", "")), str(x.get("class", ""))
        f = by.get(fid)
        if not f or fid in seen or cls not in AUTO | OWNER_ONLY:
            continue
        item = {"id": fid, "class": cls, "why": TC.cut(str(x.get("why") or ""), 300)}  # cap: untrusted
        if cls in ("duplicate", "contradiction"):
            other = by.get(str(x.get("of", "")))
            if not other or other["id"] == fid:
                continue
            if cls == "duplicate":
                if overlap(f["text"], other["text"]) < 0.25:  # the model says "the same", the words barely meet: a note instead
                    item["class"], item["why"] = "other", "maybe the same as " + other["id"][:8] + ": " + item["why"]
                else:
                    if fs.index(other) > fs.index(f):         # facts come oldest first: the older one stays (KNW-08)
                        fid, other = other["id"], f
                        item["id"] = fid
                    if fid in seen:
                        continue                              # the newer is handled already this pass
                    t = re.sub(r"\s+", " ", str(x.get("text") or "")).strip()
                    if t and t != other["text"]:              # MEM-50: the newer adds a detail: the older is rewritten to hold both
                        if other["id"] in merged or not merge_ok(t, other["text"], by[fid]["text"]):
                            continue                          # one merge into a fact a pass; a merge that loses a number waits
                        item["merge"] = t
                        merged.add(other["id"])
            else:                                           # DEC-44: two of the owner's facts disagree: the newer holds, the older is dated
                older, newer = (f, other) if fs.index(f) < fs.index(other) else (other, f)
                if older["id"] in seen or older["end"]:
                    continue
                fid = older["id"]
                item = {"id": fid, "class": "superseded", "end": newer["date"], "why": f"the newer fact {newer['id'][:8]} says otherwise: {item['why']}"}
                other = newer
            item["of"] = other["id"]
        if cls == "not_english":
            t = re.sub(r"\s+", " ", str(x.get("text") or "")).strip()
            if not t or t == f["text"] or not english(t) or len(t) > 3 * len(f["text"]) + 40:
                continue
            item["text"] = t
        if cls == "passing_state":
            end = str(x.get("end") or "")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end) or end > dt.date.today().isoformat() or f["end"]:   # it may have ended before it was stored
                continue
            item["end"] = end
        seen.add(item["id"])
        out.append(item)
    return out


def gate():
    """-> (open, why): the automatic classes run only while the trial of the current KEEPER_FACTS text passes."""
    try:
        runs = [r for r in json.loads(TRIAL.read_text()).get("runs") or [] if r.get("prompt") == KEEPER.ref]
    except (OSError, ValueError):
        runs = []
    if len(runs) < TRIAL_RUNS:
        return False, f"the memory trial has {len(runs)} of {TRIAL_RUNS} runs on the current {KEEPER.ref}: every finding is a suggestion"
    last = runs[-TRIAL_RUNS:]  # cap: parse (the gate reads the last runs on this prompt)
    p, r = min(x["precision"] for x in last), min(x["recall"] for x in last)   # the worst of its last runs: a model varies
    if p < PRECISION or r < RECALL:
        return False, f"the memory trial's worst of {TRIAL_RUNS} runs scored precision {p} and recall {r} (needs {PRECISION} and {RECALL})"
    return True, f"its trial passed {TRIAL_RUNS} times on the current prompt (worst: precision {p}, recall {r}; last {last[-1]['at'][:10]})"


def plan(found, open_gate, budget=AUTO_MAX):
    """-> (changes to make, suggestions for the owner)."""
    auto, sug = [], []
    for x in found:
        if open_gate and x["class"] in AUTO and len(auto) < budget:
            auto.append(x)
        else:
            sug.append(x)
    return auto, sug


def log(entry):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def changes(n=None):
    try:
        rows = [json.loads(ln) for ln in LOG.read_text().splitlines() if ln.strip()]
    except OSError:
        return []
    undone = {r["undo"] for r in rows if r.get("undo")}
    out = [r | {"undone": r["id"] in undone} for r in rows if not r.get("undo")]
    return out if n is None else out[-n:]  # cap: list (the caller says how many in all)


def apply(auto, fs, send=None, dry=False):
    """Make the automatic changes; each is logged with its undo. -> the log entries."""
    by = {f["id"]: f for f in fs}
    ops, entries = [], []
    for x in auto:
        f = by[x["id"]]
        cid = hashlib.sha1(f"{x['id']}:{x['class']}:{time.time()}".encode()).hexdigest()[:12]
        if x["class"] in ("duplicate", "test_noise", "agent_run", "moved_to_wiki"):
            body, before, after = {"state": "invalidated", "reason": f"Memory Keeper: {x['class'].replace('_', ' ')}: {x['why']}"}, {"state": "valid"}, {"state": "invalidated"}
        elif x["class"] == "not_english":
            body, before, after = {"text": x["text"]}, {"text": f["text"]}, {"text": x["text"]}
        else:                                          # passing_state, superseded: the date it stopped holding
            body, before, after = {"occurred_end": x["end"]}, {"occurred_end": ""}, {"occurred_end": x["end"]}
        ops.append((x["id"], body))
        entries.append({"id": cid, "at": now_iso(), "store": "hindsight", "target": x["id"], "class": x["class"], "fact": f["text"],
                        "before": before, "after": after, "why": x["why"], **({"of": x["of"]} if x.get("of") else {})})
        if x.get("merge") and x.get("of") in by:       # MEM-50: the older now holds the newer's details; its own entry, its own Undo
            o = by[x["of"]]
            ops.append((o["id"], {"text": x["merge"]}))
            entries.append({"id": hashlib.sha1(f"{o['id']}:merged:{time.time()}".encode()).hexdigest()[:12], "at": now_iso(), "store": "hindsight",
                            "target": o["id"], "class": "merged", "fact": o["text"], "before": {"text": o["text"]}, "after": {"text": x["merge"]},
                            "why": f"it now holds the details of the newer copy {x['id'][:8]}", "of": x["id"]})
    if dry or not ops:
        return entries
    ok = (send or hindsight)(ops)
    done = []
    for e, good in zip(entries, ok):
        if good:
            log(e)
            done.append(e)
    return done


def undo(cid, send=None):
    """Reverse one change of the log (the owner's Undo on its page, Agents → Memory Keeper)."""
    e = next((r for r in changes() if r["id"] == cid), None)
    if not e:
        raise ValueError(f"no change {cid} in the Memory Keeper's log")
    if e["undone"]:
        raise ValueError(f"change {cid} is already undone")
    if e["store"] == "hindsight":
        body = {"state": "valid"} if e["after"].get("state") == "invalidated" else dict(e["before"])
        if not (send or hindsight)([(e["target"], body)])[0]:
            raise RuntimeError("Hindsight did not take the undo")
    else:
        raise ValueError(f"a {e['store']} change is undone in its own history (the vault's git)")
    log({"id": hashlib.sha1(f"undo:{cid}".encode()).hexdigest()[:12], "at": now_iso(), "undo": cid, "store": e["store"]})
    return {"undone": cid, "fact": e.get("fact", "")}


# ---------- the wikis: disputes, re-checks, the same subject across wikis ----------
def callouts(root):
    """Every contradiction mark on an agent wiki's pages: [(page path, its title, the line)]."""
    import mission_extras as X
    return [(p["path"], p["title"], ln.strip()) for p in X.wiki_pages(root) for ln in p["body"].splitlines() if "[!contradiction]" in ln]


def dispute_key(root, page, line):
    return f"dispute:{root}:{page}:{hashlib.sha1(line.encode()).hexdigest()[:10]}"


def disputes(c, roots, send, create, today=None, budget=DISPUTES):
    """MEM-17: each mark a Ledger item owned by its wiki's writer; open DISPUTE_DAYS, a refinement researches it; gone
    from the page (moved under Superseded), it is settled; still there DISPUTE_DAYS after its task, the owner is asked."""
    import swarm_client as SW
    today = today or time.time()
    out = {"open": 0, "new": 0, "tasks": [], "settled": 0, "asked": 0}
    have = {}
    for a in send("find", {"kind": "memory_issue", "limit": 500}, "system").get("result") or []:
        have[a["key"]] = a
    marked = set()
    for root, title in roots:
        for page, ptitle, line in callouts(root):
            key = dispute_key(root, page, line)
            marked.add(key)
            if key in have:
                continue
            r = send("upsert", {"idem": key, "kind": "memory_issue", "key": key, "title": f"Contradiction on “{ptitle}” ({title})",
                                "body": line, "owner": SW.wiki_owner(root), "guard": False}, "system")
            if r.get("ok"):
                out["new"] += 1
                have[key] = {"id": (r.get("result") or {}).get("id"), "key": key, "state": "draft", "created": today, "updated": today}
    started = 0
    for key, a in have.items():
        if not key.startswith("dispute:"):
            continue
        _, root, page, _ = key.split(":", 3)
        state = a.get("state")
        if state == "draft":                              # the Ledger makes every new item a draft: registered, it is open
            send("transition", {"idem": f"open:{key}", "id": a["id"], "to": "open", "reason": "registered by the Memory Keeper"}, "system")
            state = a["state"] = "open"
        if key not in marked and state in ("open", "active", "blocked"):
            send("transition", {"idem": f"settled:{key}", "id": a["id"], "to": "done",
                                "reason": "settled: the mark is gone from the page (the claim that no longer holds moved under Superseded)"}, "system")
            out["settled"] += 1
            continue
        if state == "open":
            out["open"] += 1
            if started < budget and today - float(a.get("created") or today) >= DISPUTE_DAYS * 86400:
                line = (send("get", {"id": a["id"]}, "system").get("result") or {}).get("body") or ""
                tid = create({"text": f"Settle this contradiction on the wiki page: {re.sub(r'^> \[!contradiction\]\s*', '', line)} "
                                      "Find which claim holds now, each with a current source, and correct the page.",
                              "wiki": {"root": root, "page": page}, "source": "keeper", "autonomy": "auto"}, c)
                send("transition", {"idem": f"task:{key}", "id": a["id"], "to": "active", "reason": f"researched by task #{tid}",
                                    "evidence": [{"text": f"refinement task #{tid}", "ref": f"task:{tid}"}]}, "system")
                out["tasks"].append(tid)
                started += 1
        elif state == "active" and today - float(a.get("updated") or today) >= DISPUTE_DAYS * 86400:
            send("transition", {"idem": f"ask:{key}", "id": a["id"], "to": "blocked",      # DEC-44: nobody is asked; both claims stay marked
                                "reason": "its research did not settle it: both claims stay marked on the page, each with its source"}, "system")
            out["asked"] += 1
    return out


def rechecks(c, roots, create, read_recently, budget=RECHECKS):
    """A page marked stale (not confirmed for 90 days) that agents still read gets a refinement that checks it."""
    import mission_extras as X
    tids = []
    for root, _ in roots:
        for p in X.wiki_pages(root):
            if len(tids) >= budget:
                return tids
            if p["meta"].get("trust") == "stale" and not p["meta"].get("recheck") and f"{root}/{p['path']}.md" in read_recently:
                tids.append(create({"text": f"Check whether the wiki page “{p['title']}” still holds today: confirm each key fact "
                                            "with a current source and correct what is outdated.",
                                    "wiki": {"root": root, "page": p["path"]}, "source": "keeper", "autonomy": "auto"}, c))
                M.write_front(VAULT / root / f"{p['path']}.md", {**p["meta"], "recheck": f"task #{tids[-1]}"}, p["body"])
    return tids


def hub_pages():
    """The vault wiki's hub pages: each subject two or more wikis share, with the pages it links -> [(subject, [rel])]."""
    out = []
    for f in sorted((VAULT / "wiki" / "hubs").glob("*.md")):
        links = re.findall(r"\[\[((?:missions|topics)/[^\]|]+)", f.read_text(errors="replace"))
        rels = [ln for ln in dict.fromkeys(links) if (VAULT / f"{ln}.md").is_file()]
        if len(rels) >= 2:
            out.append((f.stem, rels))
    return out


def cross_check(ask=ask_json, hubs=None, budget=CROSS_HUBS, dry=False):
    """The same subject in two wikis: claims that cannot both hold get a mark on both pages, each with both sources
    (which makes them disputes). A claim whose source is not on its page is dropped. -> the pages marked."""
    marked = []
    for subject, rels in (hubs if hubs is not None else hub_pages())[:budget]:  # cap: list (the rest next week; the hubs keep them)
        pages = {r: M.split_front((VAULT / f"{r}.md").read_text(errors="replace"))[1] for r in rels}
        d = ask(CROSS.format(subject=subject, pages="\n\n".join(f"=== {r}\n{TC.cut(b, 6000, 'the page goes on')}" for r, b in pages.items())))  # cap: prompt
        for x in d.get("contradictions") or []:
            a, b = str(x.get("page", "")), str(x.get("other_page", ""))
            sa, sb = str(x.get("source", "")).strip("[] "), str(x.get("other_source", "")).strip("[] ")
            if a not in pages or b not in pages or a == b or f"[[{sa}" not in pages[a] or f"[[{sb}" not in pages[b]:
                continue
            ca, cb = TC.cut(str(x.get("claim", "")), 300), TC.cut(str(x.get("other", "")), 300)  # cap: untrusted
            if dry:
                marked.append({"a": a, "claim": ca, "b": b, "other": cb})
                continue
            for me, other, mine, theirs, msrc, osrc in ((a, b, ca, cb, sa, sb), (b, a, cb, ca, sb, sa)):
                f = VAULT / f"{me}.md"
                meta, body = M.split_front(f.read_text(errors="replace"))
                line = f"> [!contradiction] {mine} ([[{msrc}]]); the wiki page [[{other}]] says: {theirs} ([[{osrc}]])"
                if line in body:
                    continue
                body = (re.sub(r"^(## Contradictions\s*\n)", lambda m: m.group(1) + line + "\n", body, count=1, flags=re.M)
                        if re.search(r"^## Contradictions\s*$", body, re.M) else body.rstrip() + "\n\n## Contradictions\n" + line + "\n")
                M.write_front(f, {**meta, "trust": "contested"}, body)
                marked.append(me)
    if marked and not dry:
        M.vault_commit([f"{m}.md" for m in marked], f"Memory Keeper: {len(marked)} contradiction marks across wikis")
    return marked


# ---------- the memory trial (MEM-20) ----------
def trial(ask=ask_json, fixture=FIXTURE, out=TRIAL):
    """The planted facts of eval/trials/memory.yaml through classify(): the automatic changes it would make, scored
    against each fact's label. Precision: of the changes it would make, the right ones (a true fact touched is wrong);
    recall: of the planted faults it may fix itself, the ones it found."""
    import yaml
    fx = yaml.safe_load(Path(fixture).read_text())
    fs = [{"id": f["id"], "type": f.get("type", "world"), "date": str(f["date"]), "end": "", "text": f["text"]} for f in fx["facts"]]
    label = {f["id"]: f["label"] for f in fx["facts"]}
    found = classify(fs, ask)
    auto, sug = plan(found, True, budget=len(fs))
    def settles(x):                                       # DEC-44: a contradiction is settled by date; either fact of the pair may carry its label
        return x["class"] == "superseded" and (label[x["id"]].startswith("contradiction") or label.get(x.get("of"), "") == f"contradiction:{x['id']}")
    right = [x for x in auto if label[x["id"]].split(":")[0] == x["class"] or settles(x)]
    wrong = [x for x in auto if x not in right]
    faults = [i for i, lab in label.items() if lab.split(":")[0] in AUTO]
    found_faults = {x["id"] for x in right if label[x["id"]].split(":")[0] in AUTO}
    res = {"at": now_iso(), "prompt": KEEPER.ref, "facts": len(fs), "faults": len(faults), "changes": len(auto),
           "precision": round(len(right) / len(auto), 3) if auto else 0.0, "recall": round(len(found_faults) / len(faults), 3) if faults else 0.0,
           "wrong": [{"id": x["id"], "class": x["class"], "label": label[x["id"]], "why": x["why"]} for x in wrong],
           "missed": [i for i in faults if i not in found_faults],
           "contradictions_settled": sorted(x["id"] for x in right if settles(x)),
           "merged": sorted(f"{x['of']}<-{x['id']}" for x in auto if x.get("merge"))}
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        runs = json.loads(out.read_text()).get("runs") or []
    except (OSError, ValueError):
        runs = []
    out.write_text(json.dumps({**res, "runs": (runs + [res])[-10:]}, indent=1, ensure_ascii=False))  # cap: rotate (the last 10 runs)
    return res


# ---------- one pass ----------
def run_pass(c, dry=False, deep=None, create=None, send=None, read_recently=None):
    """The night's pass. -> its report (crew memory.json): the facts, the gate, the changes, the suggestions, disputes."""
    import swarm_client as SW
    import tasks as T
    if deep is None:                                      # Wednesdays; KEEPER_DEEP=1 for a pass by hand (crew.py memory)
        deep = dt.date.today().weekday() == 2 or os.environ.get("KEEPER_DEEP") == "1"
    send = send or SW.call
    create = create or (lambda req, cc: T.create(req, cc)["task"])
    rep = {"at": now_iso(), "deep": deep}
    fs = facts()
    open_gate, why = gate()
    rep["gate"] = {"open": open_gate, "why": why}
    found = classify(fs) if deep else classify(fs, ask=lambda p: {"findings": []})   # nightly: exact duplicates only
    auto, sug = plan(found, open_gate)
    rep["facts"] = len(fs)
    rep["changed"] = apply(auto, fs, dry=dry)
    by = {f["id"]: f for f in fs}
    rep["suggestions"] = [{"id": x["id"], "text": by[x["id"]]["text"], "why": x["class"].replace("_", " ") + (f" of {x['of'][:8]}" if x.get("of") else "") + f": {x['why']}",
                           "note": by[x["of"]]["text"] if x.get("of") else (x.get("text") or "")} for x in sug]
    import mission_extras as X
    import wikis as W
    W.M, X.M = W.M or M, X.M or M                         # set by the runner; a pass by hand sets them here
    roots = [(r, t) for r, t in W.roots() if r != "wiki"]
    if not dry:
        try:
            rep["disputes"] = disputes(c, roots, send, create)
        except Exception as e:
            rep["disputes"] = {"error": f"{type(e).__name__}: {e}"}
        try:
            rep["rechecks"] = rechecks(c, roots, create, read_recently if read_recently is not None else recently_read())
        except Exception as e:
            rep["rechecks"] = {"error": f"{type(e).__name__}: {e}"}
        if deep:
            try:
                rep["cross"] = cross_check()
            except Exception as e:
                rep["cross"] = {"error": f"{type(e).__name__}: {e}"}
    return rep


def recently_read(days=30):
    """The wiki pages agents read in the last days (the run record's file reads, MEM-10). A database error reaches the
    pass, which reports it (QA-26): a record that cannot be read is not a record of nothing read."""
    import sqlite3
    db = Path(os.environ.get("RUNTIME_DB_HOST", "/srv/ai/missions/app/runtime.db"))
    cc = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = cc.execute("select detail from events where kind in ('read', 'call') and ts > ? and detail like '%/wiki/%'",
                      (time.time() - days * 86400,)).fetchall()
    return {m.group(1) for (d,) in rows for m in re.finditer(r"((?:missions|topics)/[a-z0-9-]+/wiki/[a-z0-9/_-]+\.md)", d or "")}


UNKNOWN = {"pass": "The Memory Keeper's pass", "disputes": "The check of the wikis' disputes", "rechecks": "The check of stale pages agents still read",
           "cross": "The check across wikis"}


def unknown(rep):
    """QA-26: the parts of a pass that could not run, as sentences for the health board."""
    return [f"{name} could not run ({rep[k]['error']}), so what it would have found is not known"
            for k, name in UNKNOWN.items() if isinstance(rep.get(k), dict) and rep[k].get("error")]


def summary(rep):
    ch = rep.get("changed") or []
    kinds = {}
    for e in ch:
        kinds[e["class"]] = kinds.get(e["class"], 0) + 1
    d = rep.get("disputes") or {}
    parts = [f"{rep.get('facts', 0)} facts"]
    parts.append(", ".join(f"{n} {k.replace('_', ' ')}" for k, n in kinds.items()) + " fixed" if ch else "no automatic change"
                 + ("" if rep["gate"]["open"] else " (gate closed)"))
    parts.append(f"{len(rep.get('suggestions') or [])} for you to look at")
    if isinstance(d, dict) and "open" in d:
        parts.append(f"{d['open']} open disputes, {len(d['tasks'])} researched, {d['settled']} settled")
    if unknown(rep):
        parts.append(f"{len(unknown(rep))} part{'s' if len(unknown(rep)) != 1 else ''} could not run")
    return " · ".join(parts)


def main(argv):
    global M
    import missions
    M = missions
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "trial":
        print(json.dumps(trial(), indent=1, ensure_ascii=False))
        return 0
    if cmd == "undo" and len(argv) > 2:
        print(json.dumps(undo(argv[2]), ensure_ascii=False))
        return 0
    if cmd == "pass":
        c = M.db()
        print(json.dumps(run_pass(c, dry="--dry" in argv, deep=True), indent=1, ensure_ascii=False, default=str))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

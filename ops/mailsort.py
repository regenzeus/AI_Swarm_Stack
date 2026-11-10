"""The mail sorter (crew job mail-sort; CNX-10 to CNX-13): worthless bulk mail under one label and out of the inbox, only
for the senders the owner approved, one by one, on Your mail. Headers only, no model, nothing trashed or deleted.

  1. The look (ops/mailsort_nas.py, run on the NAS over ssh, read-only, as the Postmaster reads the copy): the senders
     whose mail is bulk with high confidence or likely, why, and what each per-mail guard kept. It goes to
     OUT/proposal.json for the app, with three sample subjects per sender, cut and marked. Nothing moves.
  2. The owner decides on Your mail (#/mail), once per sender: a tick (high confidence ticked, likely not), "Keep this
     sender" for good, and one button that sorts out the ticked ones (mailsort_go). Their word is OUT/decisions.json.
  3. The move, here only and only after that tap: the approved senders' mail that passed every guard goes through the
     mail connector's organize scope (mail_sort_out: the label LABEL, and out of the inbox; the connector leaves bank and
     security mail alone again), in batches of at most BATCH, paced. Each batch is recorded in OUT/batches/ (ids, sender,
     subject, whether it was in the inbox); Undo (mailsort_undo) takes the label off and puts back into the inbox what was
     there, and the run's senders are no longer approved.
  4. It keeps sorting: weekly from its n8n workflow, new mail of approved senders is sorted the same way with the same
     guards; new candidates join the proposal and Needs you; a sender the owner has not approved never moves. A run says
     what it did in one line on Home, without a push.
Deleting what is under the label is the owner's own act in Gmail, later; the NAS keeps every mail whatever happens.

  python3 ops/crew.py mail-sort        (crew-mail-sort.service: weekly from n8n, and at once after the owner's tap)
  python3 ops/mailsort.py look         the proposal now, as counts (read-only: it moves nothing and writes nothing)
"""
import base64
import collections
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import textcap as TC                              # visible caps (AGENTS.md, truncation)

C = M = None                                      # ops/crew.py and ops/missions.py (set by crew.run)
OUT = Path(os.environ.get("MAILSORT_OUT", "/srv/ai/missions/mail/sort"))
NAS_SCRIPT = Path(__file__).resolve().parent / "mailsort_nas.py"
SSH_HOST = "synology"                             # the NAS's ssh name, as ops/postmaster.py reads the copy
# The one place the label's name is set: the proposal carries it to the app, each batch to its undo.
LABEL = os.environ.get("MAIL_SORT_LABEL") or "AI Stack/Deletable"
JOB = "mail-sort"
ACTIONS = {"mailsort_go", "mailsort_keep", "mailsort_undo"}
# limit: paces, the mail connector takes at most 200 mails a call (its MAX_BATCH); the rest goes in the next batch
BATCH = 200
# limit: paces, a pause between batches keeps the sorter well under Gmail's IMAP allowance, which the NAS's copy shares
PAUSE_S = 15
SAMPLE = 140                                      # characters of a sample subject on Your mail (the whole one is in Gmail)
TOOL_OUT, TOOL_BACK = "mail-mail_sort_out", "mail-mail_sort_back"
CATEGORY = {"promotions": "Promotions", "social": "Social", "updates": "Updates", "forums": "Forums"}


class Unread(Exception):
    """The NAS could not be read: the sentence for the run's line and the health board (QA-26)."""


# ---------- files under /srv/ai (the owner's decisions and the batches; never in git) ----------
def _read(name, default):
    try:
        return json.loads((OUT / name).read_text())
    except (OSError, ValueError):
        return default


def _write(name, doc):
    """Whole or not at all, readable by the app (another user)."""
    p = OUT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    for d in {OUT, p.parent}:
        d.chmod(0o755)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False))
    tmp.chmod(0o644)
    tmp.replace(p)


def decisions():
    """The owner's word per sender, {addr: when}: approved (sorted out, now and weekly), kept (never proposed again), seen
    (looked at and left unticked: no new Needs you card for them)."""
    d = _read("decisions.json", {})
    return {k: dict(d.get(k) or {}) for k in ("approved", "kept", "seen")}


def batches():
    out = []
    for f in sorted((OUT / "batches").glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    return out


def sorted_ids():
    """The ids already sorted out (in a batch nobody undid): a mail never goes twice."""
    return {i["id"] for b in batches() if not b.get("undone") for i in b.get("items") or []}


def runs():
    return _read("runs.json", [])


def save_run(entry):
    _write("runs.json", [entry] + [r for r in runs() if r["run"] != entry["run"]])


# ---------- the look, on the NAS ----------
def nas(args, ssh=None):
    """ops/mailsort_nas.py on the NAS's python3, over ssh, with nothing written there -> its JSON."""
    code = base64.b64encode(json.dumps(args).encode()).decode()
    try:
        p = (ssh or subprocess.run)(["ssh", "-o", "ConnectTimeout=20", SSH_HOST, f"python3 - {code}"], input=NAS_SCRIPT.read_text(),
                                    capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        raise Unread("the NAS took the connection, but its look at the mail copy did not finish in 15 minutes")
    except OSError as e:
        raise Unread(f"ssh could not start: {type(e).__name__}")
    if p.returncode:
        err = " ".join((p.stderr or "").split())
        if p.returncode == 255 and re.search(r"timed out|no route to host|host is down", err, re.I):
            raise Unread("the NAS did not answer (asleep or off), so the mail copy could not be looked at")
        raise Unread(f"the look at the mail copy on the NAS failed: {err or f'exit code {p.returncode}'}")
    try:
        return json.loads(p.stdout)
    except ValueError:
        raise Unread("the NAS's answer was not whole (no JSON), so the mail copy could not be looked at")


def look(d, ssh=None, now=None):
    """The proposal from the copy's index, with the owner's decisions in it. -> the NAS's document."""
    return nas({"me": os.environ.get("GMAIL_ADDRESS", "").lower(), "label": LABEL, "kept": sorted(d["kept"]),
                "approve": sorted(set(d["approved"]) - set(d["kept"])), "now": int(now or time.time())}, ssh)


def why(s):
    """Why a sender counts as worthless, in plain words, from its headers."""
    out = []
    share = s["list"] / s["n"] if s["n"] else 0
    if share >= 0.5:
        out.append(f"a mailing list ({round(100 * share)} % of its mail has an unsubscribe link)")
    if s.get("category") in CATEGORY:
        out.append(f"Gmail files it under {CATEGORY[s['category']]}")
    out.append("you never wrote to them and never starred one")
    out.append("no attachments" if not s["attach"] else f"{s['attach']} of {s['n']} with attachments")
    if s.get("relays"):
        out.append("but it passes on messages from people" + (f" ({s['relayed']} of {s['n']} subjects say so; they stay)" if s.get("relayed") else "")
                   + ": look before you tick")
    return out


def restate(doc, d):
    """The owner's decisions in the published proposal (after a tap, before the next look)."""
    for s in doc.get("senders") or []:
        s["approved"] = s["addr"] in d["approved"]
        s["new"] = not any(s["addr"] in d[k] for k in ("approved", "kept", "seen"))
    doc.update(approved=len(d["approved"]), kept=len(d["kept"]))
    _write("proposal.json", doc)
    return doc


def publish(p, d):
    """The proposal for the app (OUT/proposal.json): every sender with its numbers, why, three sample subjects cut and
    marked, and what the guards kept; no ids."""
    senders = [{**{k: v for k, v in s.items() if k != "samples"}, "why": why(s),
                "samples": [TC.cut(x, SAMPLE, "the whole subject is in Gmail") for x in s["samples"]]}  # cap: preview
               for s in p["senders"]]
    doc = {k: p.get(k) for k in ("at", "label", "mails", "senders_all", "left", "guards", "gone")}
    doc["senders"] = senders
    return restate(doc, d)


def pending():
    """The senders no decision has seen yet (Needs you, CNX-11): -> [sender]."""
    d = decisions()
    return [s for s in _read("proposal.json", {}).get("senders") or []
            if not any(s["addr"] in d[k] for k in ("approved", "kept", "seen"))]


# ---------- the owner's taps (the app's requests, validated by the runner) ----------
def start(why_, run=None):
    """The sorter's unit, now, as crew Run now starts one; its cause says it was the owner."""
    import crew as CR
    CR.set_cause(JOB, "you", why=why_)
    p = (run or subprocess.run)(["systemctl", "--user", "start", "--no-block", f"{CR.BY_ID[JOB]['unit']}.service"],
                                capture_output=True, text=True)
    if p.returncode:
        raise ValueError(f"the sorter could not start ({p.stderr.strip()}); your choice is kept, and its weekly run sorts it out")


def handle(req, run=None, now=None):
    a, now = req.get("action"), now or time.time()
    d, p = decisions(), _read("proposal.json", {})
    known = {s["addr"]: s for s in p.get("senders") or []}
    if a == "mailsort_keep":
        addr = str(req.get("addr", "")).strip().lower()
        if addr not in known and addr not in d["approved"]:
            raise ValueError("this sender is not in the proposal: open Your mail again")
        d["kept"][addr] = now
        d["approved"].pop(addr, None)
        _write("decisions.json", d)
        if p:
            restate({**p, "senders": [s for s in p.get("senders") or [] if s["addr"] != addr]}, d)
        return {"kept": addr}
    if a == "mailsort_go":
        if not p or req.get("at") != p.get("at"):
            raise ValueError("the proposal changed while you looked at it: open Your mail again and choose")
        out, add = {str(x).lower() for x in req.get("except") or []}, {str(x).lower() for x in req.get("also") or []}
        if (out | add) - set(known):
            raise ValueError(f"{len((out | add) - set(known))} of the chosen senders are not in the proposal: open Your mail again")
        chosen = ({x for x, s in known.items() if s["tier"] == "high" or x in d["approved"]} - out | add) - set(d["kept"])
        for x in known:
            d["seen"][x] = now
        for x in out:
            d["approved"].pop(x, None)
        for x in chosen:
            d["approved"].setdefault(x, now)
        _write("decisions.json", d)
        restate(p, d)
        if chosen:
            start("Sort out", run)
        return {"approved": len(chosen), "mails": sum(known[x]["movable"] for x in chosen)}
    if a == "mailsort_undo":
        rid = str(req.get("run", ""))
        r = next((x for x in runs() if x.get("run") == rid), None)
        if not r or not re.fullmatch(r"[0-9a-z-]{1,40}", rid):
            raise ValueError("no such sorting run")
        if r.get("undone"):
            raise ValueError("this sorting run is undone already")
        _write(f"undo/{rid}.json", {"run": rid, "at": now})
        start("Undo", run)
        return {"undo": rid}
    raise ValueError("unknown mail sorter action")


# ---------- the move and its undo (the crew job) ----------
def answer(text):
    """The connector's JSON line (mail_sort_out, mail_sort_back) -> dict; anything else (no grant) is raised as said."""
    last = (text or "").strip().splitlines()[-1:] or [""]
    try:
        d = json.loads(last[0])
    except ValueError:
        d = None
    if not isinstance(d, dict) or "done" not in d:
        raise RuntimeError(f"the mail connector said: {text}")
    return d


def new_run_id(now=None):
    """A run's id: its time, and a number after it when a run of the same second exists (its batches keep their names)."""
    base = time.strftime("%Y%m%d-%H%M%S", time.localtime(now or time.time()))
    taken = {r.get("run", "") for r in runs()}
    taken |= {b.get("run", "") for b in batches()}
    rid, n = base, 1
    while rid in taken or any(t.startswith(rid + "-") for t in taken):
        n += 1
        rid = f"{base}-n{n}"
    return rid


def move(c, p, d, tool, rid, now=None):
    """The approved senders' mails that passed every guard, in batches, each recorded. -> the run's entry."""
    done = sorted_ids()
    todo = [(addr, i, subject) for addr, ms in sorted((p.get("moves") or {}).items())
            if addr in d["approved"] and addr not in d["kept"] for i, _, subject in ms if i not in done]
    names = {s["addr"]: s["name"] for s in p.get("senders") or []}
    entry = {"run": rid, "at": now or time.time(), "label": LABEL, "mails": 0, "inbox": 0, "senders": [], "batches": 0,
             "protected": 0, "missing": 0, "undone": None}
    senders = collections.Counter()
    for k in range(0, len(todo), BATCH):
        if k and M.rest(c, JOB, PAUSE_S):                # the runner stops: the rest waits for the next run
            break
        part = todo[k:k + BATCH]
        res = answer(tool(TOOL_OUT, {"ids": [x[1] for x in part], "label": LABEL}))
        ok, was_in = set(res.get("done") or []), set(res.get("inbox") or [])
        items = [{"id": i, "sender": f"{names.get(addr) or ''} <{addr}>", "subject": subject, "inbox": i in was_in}
                 for addr, i, subject in part if i in ok]
        entry["batches"] += 1
        bid = f"{rid}-{entry['batches']:04d}"
        _write(f"batches/{bid}.json", {"id": bid, "run": rid, "at": time.time(), "label": LABEL, "items": items,
                                       "protected": res.get("protected") or [], "missing": res.get("missing") or [], "undone": None})
        senders.update(addr for addr, i, _ in part if i in ok)
        entry.update(mails=entry["mails"] + len(items), inbox=entry["inbox"] + sum(x["inbox"] for x in items), senders=sorted(senders),
                     protected=entry["protected"] + len(res.get("protected") or []), missing=entry["missing"] + len(res.get("missing") or []))
        save_run(entry)
    return entry


def undo(tool, now=None):
    """Every undo the owner asked for: each batch of that run gets the label off, and what was in the inbox goes back
    there; the run's senders are no longer approved (they stay in the proposal, unticked). -> how many mails."""
    n = 0
    for f in sorted((OUT / "undo").glob("*.json")):
        rid = f.stem
        for b in batches():
            if b.get("run") != rid or b.get("undone"):
                continue
            answer(tool(TOOL_BACK, {"ids": [i["id"] for i in b["items"]], "label": b["label"],
                                    "to_inbox": [i["id"] for i in b["items"] if i["inbox"]]}))
            b["undone"] = now or time.time()
            _write(f"batches/{b['id']}.json", b)
            n += len(b["items"])
        r = next((x for x in runs() if x["run"] == rid), None)
        if r:
            d = decisions()
            for addr in r.get("senders") or []:
                d["approved"].pop(addr, None)
            _write("decisions.json", d)
            save_run({**r, "undone": now or time.time()})
        f.unlink()
    return n


def line(entries, undone, p, waiting):
    """The run's one line on Home."""
    mails, said = sum(e["mails"] for e in entries), []
    if undone:
        said.append(f"{undone:,} mails put back, as you asked")
    if mails:
        senders = len({a for e in entries for a in e["senders"]})
        said.append(f"{mails:,} mails of {senders} sender{'s' if senders != 1 else ''} sorted out under {LABEL} "
                    f"({sum(e['inbox'] for e in entries):,} of them were in the inbox)")
    elif p is not None:
        said.append("nothing new to sort out")
    if p is not None and p.get("guards"):
        said.append(f"the guards kept {sum(p['guards'].values()):,} mails of the proposed senders")
    if waiting:
        said.append(f"{len(waiting)} sender{'s' if len(waiting) != 1 else ''} wait for your look on Your mail")
    return "; ".join(said)


def run(c, tool=None, ssh=None, granted=None):
    """The crew job: undo what the owner asked to undo, look again, sort out the approved senders' new mail; again while
    the owner's word changed during the run (a tap while it worked)."""
    import inbox as IN
    tool = tool or (lambda name, args: IN.mcp(name, args, key=os.environ["VK_POSTMASTER"]))
    can = (granted or IN.granted)("organize")
    entries, unknown, undone, p = [], [], 0, None
    rid = new_run_id()
    if not can:
        unknown.append("Gmail organize is not granted, so nothing was sorted out or put back (Stack, Connections)")
    while True:
        d = decisions()
        if can:
            undone += undo(tool)
            d = decisions()
        try:
            p = look(d, ssh)
        except Unread as e:
            unknown.append(str(e))
            break
        publish(p, d)
        if can and p.get("moves"):
            e = move(c, p, d, tool, f"{rid}-{len(entries) + 1}" if entries else rid)
            if e["batches"]:
                entries.append(e)
        if decisions() == d and not (can and list((OUT / "undo").glob("*.json"))):
            break
    res = "; ".join(x for x in [line(entries, undone, p, pending() if p is not None else []), *unknown] if x)
    C.save(JOB, result=res, last=time.time(), unknown=unknown)
    return 0                                          # no push: the line on Home is enough (CNX-12)


def summary(p):
    """The look as counts, for the terminal: no subjects."""
    rows = [f"{p['mails']:,} mails from {p['senders_all']:,} senders in the copy"]
    for t in ("high", "likely"):
        ss = [s for s in p["senders"] if s["tier"] == t]
        rows.append(f"{t}: {len(ss)} senders, {sum(s['movable'] for s in ss):,} mails would go ({sum(s['inbox'] for s in ss):,} in the inbox)")
    rows.append("kept by the guards: " + ", ".join(f"{k} {v:,}" for k, v in sorted(p["guards"].items(), key=lambda x: -x[1])))
    rows.append("never proposed: " + ", ".join(f"{k} {v:,}" for k, v in sorted(p["left"].items(), key=lambda x: -x[1])))
    return "\n".join(rows)


if __name__ == "__main__":
    if sys.argv[1:] == ["look"]:
        print(summary(look(decisions())))
    else:
        sys.exit(__doc__)

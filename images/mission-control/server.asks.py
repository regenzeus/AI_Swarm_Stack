# part of server.py (PLT-25; ASK-12, ASK-13, docs/ASKS.md): the Asks only the app sees and the answers that wait for the
# runner. It runs in server.py's namespace where it stood (_part); not a module of its own.
#
# The runner owns the Ask store (ops/asks.py) and publishes the Asks in state.json. Three waits only this app sees (the
# AI phone's approval requests, Gmail's Trash batch, a mission whose access is not granted) are Asks too: their id is
# the same hash of their source key the runner uses, so Dismiss and Later on them go through the runner's inbox like
# every answer, and the runner's list of hidden ones ("asks_hidden") keeps them out until they wake.
#
# An answer goes into the runner's inbox and waits there while the runner is down; queued_answers() lists those not taken
# yet, so the app shows them as kept and the card does not come back meanwhile. The runner applies each once, by its
# answer id.


def app_ask_id(source):
    """= ops/asks.py ask_id: an Ask's id from its source key."""
    return hashlib.sha1(str(source).encode()).hexdigest()[:16]   # cap: id


def app_asks(items, hidden):
    """The app's own waits as Asks: each with its id and source key; a dismissed or put-off one is left out. The
    runner's items are Asks already (they carry theirs) and pass as they are."""
    out = []
    for d in items:
        if d.get("ask") or d.get("id") is None:
            out.append(d)
            continue
        src = f"srv:{d['id']}"
        aid = app_ask_id(src)
        if aid not in set(hidden or ()):
            out.append({**d, "ask": aid, "source_key": src})
    return out


ASK_ACTIONS = ("ask_answer", "ask_undo", "ask_dismiss", "ask_later", "ask_group")


def queued_answers(inbox=None):
    """ASK-13: the answers in the runner's inbox it has not taken yet (it is restarting, or busy): kept, sent once."""
    out = []
    for f in sorted((inbox or INBOX).glob("*.json")):
        try:
            r = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(r, dict) and r.get("action") in ASK_ACTIONS:
            out.append({"id": r.get("id"), "action": r["action"], "answer_id": r.get("answer_id"), "outcome": r.get("outcome"),
                        "words": r.get("words") or "", "kind": r.get("kind"), "at": f.stat().st_mtime})
    return out

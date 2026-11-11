"""ASK-11: answers in your own words, read by the interpreter (docs/ASKS.md).

A person may answer every Ask but a gate in words ("Single, as always", "23 km, on 180 days", "ask me again in
January"). The words wait in the store ("reading"); this reader hands them, with the Ask's question, its allowed answers
and its values schema, to one model call without tools (prompts/intake.md INTERPRET, gpt-sub-fast on the subscription,
through the intake agent's key, whose prompts file holds it) and gets JSON back: one allowed outcome with its values, or one short question back.
clean() keeps only what the Ask allows: an outcome it does not offer, a value it does not take, or a reading under
CONFIDENT becomes a question back in the card; it never guesses silently. A sure reading is held with "Understood as"
and the one-tap undo (ops/asks.py understood). At a gate the reading only suggests a chip, which the person still taps.

A reading that fails (the model away, its answer not JSON) is tried again on the next pass; after TRIES the card asks
the person to tap an answer or say it another way, and the words stay in the Ask's history.

    python3 ops/asks_words.py "<the Ask's id>" "<words>"     one reading, printed, nothing kept
"""
import datetime as dt
import json
import os
import sys
import time

import asks as AK
import prompts as P
import textcap as TC

CONFIDENT = 0.7          # a reading under this asks back in the card instead of being held
TRIES = 3                # limit: stops, a reading that fails three times asks the person to tap or say it another way
MODEL = "gpt-sub-fast"
TIMEOUT_S = 60           # limit: stops, one reading waits a minute for the model; then it is tried again
UNDERSTOOD_CHARS = 300   # of the model's "understood" line shown in the card
_tries = {}              # answer id -> failed readings so far (a restart starts the count again, never loses the words)


def prompt(a, words, now=None):
    """The interpreter's prompt for one Ask and one answer in words."""
    outs = [o for o in a.get("choices") or [] if not o.get("href")]
    when = dt.datetime.fromtimestamp(now or time.time()).astimezone().strftime("%A %Y-%m-%d %H:%M")
    return P.text("intake", "INTERPRET").format(
        question=a["question"], why=a.get("why") or "-", facts="; ".join(f"{f['k']}: {f['v']}" for f in a.get("facts") or []) or "-",
        outcomes=", ".join(f"{o['id']}: {o['label']}" for o in outs), values=", ".join(f"{k}: {v}" for k, v in (a.get("values") or {}).items()) or "none",
        gate="yes" if a.get("gate") else "no", now=when, words=str(words).replace("WORDS>>>", "WORDS> > >"))


def _number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).replace(",", ".").split()[0])
    except (ValueError, IndexError):
        return None


def clean(raw, a, now=None):
    """The model's answer, kept to what the Ask allows. -> {outcome, values, confidence, understood, ask_back,
    instruction}; a doubt becomes ask_back."""
    raw = raw if isinstance(raw, dict) else {}
    ids = {o["id"]: o["label"] for o in a.get("choices") or [] if not o.get("href")}
    outcome = raw.get("outcome") if raw.get("outcome") in ids else None
    schema = a.get("values") or {}
    values = {}
    for k, v in (raw.get("values") or {}).items() if isinstance(raw.get("values"), dict) else []:
        if k not in schema:
            continue
        kind = schema[k]
        v = _number(v) if kind == "number" else bool(v) if kind == "yes-no" else str(v)
        if v is not None:
            values[k] = v
    try:
        conf = max(0.0, min(1.0, float(raw.get("confidence"))))
    except (TypeError, ValueError):
        conf = 0.0
    understood = TC.cut(str(raw.get("understood") or ""), UNDERSTOOD_CHARS)   # cap: untrusted (a model's line for a card)
    ask_back = str(raw.get("ask_back") or "").strip() or None
    ins = raw.get("instruction") if isinstance(raw.get("instruction"), dict) else {}
    kind = ins.get("kind") if ins.get("kind") in ("snooze", "rule", "note") else None
    instruction = None
    if kind == "snooze":
        until = AK.when(str(ins.get("until") or ""), now)
        instruction = {"kind": "snooze", "until": until} if until else None
        if not until:
            ask_back = ask_back or "Until when should it wait?"
    elif kind == "rule" and not a.get("gate") and outcome:
        instruction = {"kind": "rule"}
    elif kind == "note":
        instruction = {"kind": "note", "text": TC.limit(str(ins.get("text") or ""), AK.WORDS_MAX, "the note")}
    if raw.get("outcome") not in (None, "", "null") and outcome is None:
        ask_back = ask_back or f"Which of its answers do you mean: {', '.join(ids.values())}?"
    if outcome and conf < CONFIDENT and not a.get("gate"):
        ask_back = ask_back or f"So: {understood or ids[outcome]}?"
    if outcome and ask_back is not None and not a.get("gate"):
        outcome = None                               # unsure: nothing is held, the card asks
    if not outcome and not instruction and not ask_back:
        ask_back = f"Which of its answers do you mean: {', '.join(ids.values())}?"
    return {"outcome": outcome, "values": values, "confidence": conf, "understood": understood or (ids.get(outcome) or ""),
            "ask_back": ask_back, "instruction": instruction}


def interpret(a, words, ask, now=None):
    """One reading: the prompt to the model (ask(prompt) -> its JSON as a dict), cleaned."""
    return clean(ask(prompt(a, words, now)), a, now)


def model_ask(m):
    """The runner's model call for the interpreter: the intake agent's key, no tools, gpt-sub-fast."""
    return lambda text: m.ask_json(text, os.environ.get("VK_INTAKE", ""), MODEL, timeout=TIMEOUT_S)


def work(ask, now=None, log=print):
    """One pass: every answer in words that waits (and every gate comment) is read once. -> how many were read."""
    n = 0
    for ans in AK.reading():
        a = AK.get(ans["ask_id"])
        if not a or a["status"] not in AK.WAITING:
            continue
        try:
            r = interpret(a, ans["words"], ask, now)
        except Exception as e:                          # the model away or no JSON: tried again next pass, TRIES in all
            k = ans["answer_id"]
            _tries[k] = _tries.get(k, 0) + 1
            log(f"asks: reading {k}: {type(e).__name__}: {e} (try {_tries[k]} of {TRIES})")
            if _tries[k] >= TRIES:
                r = {"outcome": None, "ask_back": f"Your words could not be read just now ({type(e).__name__}). Tap one of its answers, "
                                                  "or say it another way.", "understood": "", "instruction": None}
            else:
                continue
        AK.understood(a["id"], ans["answer_id"], r, now=now)
        _tries.pop(ans["answer_id"], None)
        n += 1
    return n


if __name__ == "__main__":
    import missions as M
    x = AK.get(sys.argv[1])
    print(json.dumps(interpret(x, sys.argv[2], model_ask(M)), indent=1, ensure_ascii=False))

"""Text caps that show themselves, and refusals for input that is too long (the truncation rules in AGENTS.md).

Nothing the owner reads or types is cut silently. A cap is allowed only for a reason ops/truncation.py knows (it is
named on the line: `cap: <reason>`), and when it hits, the text says how much is missing and, where it helps, where
the whole text is. The owner's own input is never cut: over a limit it is refused with the limit named.

Every image that imports it has a copy of this file next to its code (images/*/textcap.py: an image cannot import
ops/); tests/test_truncation.py keeps them identical and checks each Dockerfile copies it. Stdlib only.
"""
import json
import sys

STORE = 20000          # the smallest cap on stored text the owner may read (logs, step details, outputs)


def cut(text, n, where=""):
    """The first n characters, then a marker with how many are missing (and where the whole text is)."""
    s = str(text if text is not None else "")
    if len(s) <= n:
        return s
    return s[:n] + f" [… {len(s) - n:,} more characters cut{': ' + where if where else ''}]"


def fit(text, n, where=""):
    """At most n characters in all, the marker included: for an outside hard limit (a Telegram message, a push, a
    subject line) where the marked text must still fit."""
    s = str(text if text is not None else "")
    if len(s) <= n:
        return s
    mark = f" [… {len(s):,} characters in all{': ' + where if where else ''}]"
    return s[:max(0, n - len(mark))] + mark if n > len(mark) else s[:n]


class Cut(RuntimeError):
    """A model's answer stopped at its output limit: never used as if it were whole."""


def answer(res, who="the model"):
    """The text of a chat-completions answer, refused when the model stopped at its output limit (finish_reason
    "length"): a cut answer parses into half a plan or stores half a result without a sign of it."""
    ch = (res.get("choices") or [{}])[0]
    if ch.get("finish_reason") in ("length", "max_tokens"):
        n = (res.get("usage") or {}).get("completion_tokens")
        raise Cut(f"{who}'s answer stopped at its output limit{f' ({n:,} tokens)' if n else ''}; it was not used")
    return (ch.get("message") or {}).get("content") or ""


def tail(text, n, where=""):
    """The last n characters, after a marker with how many earlier ones are missing."""
    s = str(text if text is not None else "")
    if len(s) <= n:
        return s
    return f"[{len(s) - n:,} earlier characters cut{': ' + where if where else ''} …] " + s[-n:]


def limit(text, n, what="this text"):
    """Input someone typed: never cut. Over the limit -> ValueError naming it, which the app shows as the reason."""
    s = str(text if text is not None else "")
    if len(s) > n:
        raise ValueError(f"{what} is {len(s):,} characters; the limit is {n:,}. Shorten it or split it.")
    return s


def limit_items(items, n, what="items"):
    """A list someone sent: never dropped silently. Over the limit -> ValueError naming it."""
    items = list(items or [])
    if len(items) > n:
        raise ValueError(f"{len(items)} {what}; at most {n}.")
    return items


def more(items, n, what="more"):
    """A list of lines for a text a person or a model reads: the first n, then one line that says how many follow."""
    items = list(items or [])
    return items if len(items) <= n else items[:n] + [f"(… and {len(items) - n:,} {what})"]


def first(items, n, what="items"):
    """A list another program, agent or model sent, bounded by the limit its prompt or contract names: the first n, and
    what was left out is said on stderr (the service's log), never dropped without a word."""
    items = list(items or [])
    if len(items) > n:
        print(f"cap: kept the first {n} of {len(items)} {what}", file=sys.stderr, flush=True)
    return items[:n]


def bounded_json(obj, n):
    """JSON of at most about n characters that still parses: a too-long value is stored as a cut text, marked."""
    s = json.dumps(obj, ensure_ascii=False, default=str)
    return s if len(s) <= n else json.dumps({"cut": True, "chars": len(s), "text": cut(s, n)}, ensure_ascii=False)

#!/usr/bin/env python3
"""The agent registry, config/agents.yaml (SWM-01, SWM-22 to SWM-24, SWM-29): load it, check it, hash a card.

  python3 ops/registry.py check      every rule below; exit 1 with the problems (run by ops/check.sh)
  python3 ops/registry.py cards      one line per agent: id, harness, model, key, card hash

Rules: every card has every field with known values; ids are unique; a key belongs to exactly one card or one
service; every key in ops/keys.sh is accounted for, and a card's model and MCP tools equal its key's models and
grants there (least privilege, SWM-24); models are subscription or local only (SWM-29); every job names an
existing systemd unit (ops/systemd/<job>.service); a card's optional standing instructions are a short list of
sentences (they change only through an agent change, SWM-18). Reads only the repository. Stdlib and PyYAML only.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REG = "config/agents.yaml"
FIELDS = ("id", "purpose", "responsibilities", "owns", "harness", "model", "key", "jobs", "schedule", "roles", "rooms",
          "contact", "wake", "budgets", "tools", "autonomy")
BUDGETS = ("wakes_per_day", "messages_per_hour")
WIKIS = ("own", "vault", "related")           # MEM-04: what a card's memory.wikis may name
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")


def load(root=ROOT):
    return yaml.safe_load((root / REG).read_text()) or {}


def keys_table(root=ROOT):
    """{alias: (models, mcp servers)} from the KEYS table in ops/keys.sh."""
    rows = re.findall(r'^\s*"(vk-[a-z-]+)\|([^|]*)\|[0-9.]+\|([^"]*)"', (root / "ops/keys.sh").read_text(), re.M)
    return {a: (set(m.split(",")) - {""}, set(c.split(",")) - {""}) for a, m, c in rows}


def card_hash(card, root=ROOT):
    """A run records this (SWM-25): it changes with any field of the card and with its prompts file (MEM-11)."""
    f = root / str(card.get("prompts") or "")
    text = f.read_text() if card.get("prompts") and f.is_file() else ""
    return hashlib.sha256((json.dumps(card, sort_keys=True, ensure_ascii=False) + text).encode()).hexdigest()[:12]


def hash_of(agent_id, root=ROOT):
    """The card hash of one agent for its run manifest (SWM-25), or None when it has no card."""
    try:
        card = next((c for c in load(root).get("agents") or [] if c.get("id") == agent_id), None)
    except (OSError, ValueError):
        return None
    return card_hash(card, root) if card else None


def check(root=ROOT):
    reg, out = load(root), []
    lists = {k: set(reg.get(k) or []) for k in ("harnesses", "models", "kinds", "roles", "rooms", "wake")}
    services = reg.get("services") or {}
    table = keys_table(root)
    owner_of = {}
    seen = set()
    for c in reg.get("agents") or []:
        cid = str(c.get("id", "?"))
        where = f"agent {cid}"
        for f in FIELDS:
            if f not in c:
                out.append(f"{where}: no {f}")
        bad = [w for w in ((c.get("memory") or {}).get("wikis") or []) if w not in WIKIS]
        if bad:
            out.append(f"{where}: memory.wikis may name {', '.join(WIKIS)}, not {', '.join(map(str, bad))}")
        if not ID_RE.match(cid):
            out.append(f"{where}: id must be lower-case letters, digits and dashes")
        if cid in seen:
            out.append(f"{where}: duplicate id")
        seen.add(cid)
        for f, known in (("harness", "harnesses"), ("wake", "wake")):
            if c.get(f) not in lists[known]:
                out.append(f"{where}: unknown {f} {c.get(f)!r}")
        model = str(c.get("model"))
        if model not in lists["models"] and not model.startswith("ollama:"):
            out.append(f"{where}: model {model!r} is not a subscription or local model (CST-02)")
        for f, known in (("roles", "roles"), ("rooms", "rooms")):
            for v in c.get(f) or []:
                if v not in lists[known]:
                    out.append(f"{where}: unknown {f[:-1]} {v!r}")
        for k in (c.get("owns") or {}):
            if k not in lists["kinds"]:
                out.append(f"{where}: owns unknown kind {k!r}")
        for k, done in (c.get("owns") or {}).items():
            if not str(done or "").strip():
                out.append(f"{where}: owns {k} without a definition of done")
        b = c.get("budgets") or {}
        for f in BUDGETS:
            if not isinstance(b.get(f), int) or b[f] < 0:
                out.append(f"{where}: budgets.{f} must be a whole number of 0 or more")
        ins = c.get("instructions", [])                  # optional: standing instructions, changed only by agent changes (SWM-18)
        if not isinstance(ins, list) or len(ins) > 20 or any(not isinstance(x, str) or not x.strip() or len(x) > 300 for x in ins):
            out.append(f"{where}: instructions must be a list of at most 20 sentences of up to 300 characters")
        pf = c.get("prompts")                            # MEM-11: its prompts file, named after the card
        if pf is not None and (pf != f"prompts/{cid}.md" or not (root / pf).is_file()):
            out.append(f"{where}: prompts must be prompts/{cid}.md, an existing file")
        for j in c.get("jobs") or []:
            if not (root / "ops/systemd" / f"{j}.service").exists():
                out.append(f"{where}: job {j} has no unit ops/systemd/{j}.service")
        key = c.get("key")
        if key and key != "none":
            if key in owner_of:
                out.append(f"{where}: key {key} is also {owner_of[key]}'s (SWM-23: one key per agent)")
            owner_of[key] = f"agent {cid}"
            if key not in table:
                out.append(f"{where}: key {key} is not in ops/keys.sh")
            else:
                models, grants = table[key]
                if model in lists["models"] - {"none", "claude-subscription"} and model not in models:
                    out.append(f"{where}: model {model} is not among {key}'s models {sorted(models)}")
                if set(c.get("tools") or []) != grants:
                    out.append(f"{where}: tools {sorted(c.get('tools') or [])} differ from {key}'s MCP grants "
                               f"{sorted(grants)} in ops/keys.sh (SWM-24)")
        elif c.get("tools"):
            out.append(f"{where}: tools without a gateway key")
    for s in services:
        if s in owner_of:
            out.append(f"service key {s} is also {owner_of[s]}'s")
        owner_of.setdefault(s, f"service {s}")
        if s not in table:
            out.append(f"service key {s} is not in ops/keys.sh")
    for k in sorted(set(table) - set(owner_of)):
        out.append(f"key {k} in ops/keys.sh belongs to no agent card and no service")
    named = {c.get("prompts") for c in reg.get("agents") or []} | {f"prompts/{s.removeprefix('vk-')}.md" for s in services} | {"prompts/shared.md"}
    for f in sorted((root / "prompts").glob("*.md")) if (root / "prompts").is_dir() else []:
        if f.stem != "AGENTS" and f"prompts/{f.name}" not in named:
            out.append(f"prompts/{f.name} is named by no card's prompts field and is no service's (MEM-11)")
    return out


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "cards":
        for c in load().get("agents") or []:
            print(f"{c['id']:16} {c['harness']:12} {c['model']:20} {c['key']:12} {card_hash(c)}")
        return 0
    if cmd == "check":
        problems = check()
        for p in problems:
            print(f"   {p}")
        print(f"   {len(load().get('agents') or [])} agent cards, {len(problems)} problem{'s' if len(problems) != 1 else ''}")
        return 1 if problems else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

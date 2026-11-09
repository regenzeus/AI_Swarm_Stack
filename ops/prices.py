"""What tokens would cost if paid (TSK-27): the provider's list price of the model behind each name the stack uses.

The subscriptions cost $0 per call, so the point is comparison and waste detection, not billing. The prices come from
the gateway's own price table (LiteLLM's model cost map): each gateway alias (config/litellm/config.yaml, e.g.
gpt-sub → chatgpt/gpt-6.1-sol) is priced as the provider's API model (gpt-6.1-sol), and the Claude models Claude Code
reports by name. config/prices.json holds the result with its date; `refresh` writes it again (monthly, with the
upgrade check, or after a model change); a name not in it has no price and says so.

  python3 ops/prices.py refresh     the table from the running gateway (docker exec into LiteLLM)
"""
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "config/prices.json"
CLAUDE = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1")   # what Claude Code reports by name


def load(path=None):
    try:
        return json.loads((path or TABLE).read_text())
    except (OSError, ValueError):
        return {"models": {}}


def cost(model, tokens, table=None):
    """USD at list price for {in, out, cached} tokens of a model (cached tokens are part of in), or None without a price."""
    p = (table or load())["models"].get(model or "")
    if not p:
        return None
    tin, tout, cached = (int((tokens or {}).get(k) or 0) for k in ("in", "out", "cached"))
    return round((tin - cached) * p["in"] + cached * (p.get("cached") if p.get("cached") is not None else p["in"]) + tout * p["out"], 6)


def total(usage, table=None):
    """{model: tokens} -> (USD at list price of the priced models, the models without a price)."""
    table = table or load()
    usd, missing = 0.0, []
    for m, tok in (usage or {}).items():
        c = cost(m, tok, table)
        if c is None:
            missing.append(m)
        else:
            usd += c
    return round(usd, 6), missing


def aliases():
    """{gateway name: provider model} from the gateway's config, and the Claude models by their own name."""
    cfg = yaml.safe_load((ROOT / "config/litellm/config.yaml").read_text())
    out = {m["model_name"]: str(m["litellm_params"]["model"]).split("/", 1)[-1] for m in cfg.get("model_list") or []
           if not str(m["litellm_params"]["model"]).startswith("ollama")}
    return {**out, **{c: c for c in CLAUDE}}


def refresh():
    names = aliases()
    code = ("import json, litellm, sys; names = json.loads(sys.argv[1]); mc = litellm.model_cost; "
            "from importlib.metadata import version; print(json.dumps({'version': version('litellm'), 'models': {n: {k: mc.get(m, {}).get(k) for k in "
            "('input_cost_per_token', 'output_cost_per_token', 'cache_read_input_token_cost')} for n, m in names.items()}}))")
    box = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()
    lite = next(b for b in box if "litellm" in b)
    out = json.loads(subprocess.run(["docker", "exec", lite, "python3", "-c", code, json.dumps(names)], capture_output=True, text=True, check=True).stdout)
    models = {n: {"model": names[n], "in": p["input_cost_per_token"], "out": p["output_cost_per_token"], "cached": p["cache_read_input_token_cost"]}
              for n, p in out["models"].items() if p["input_cost_per_token"] is not None and p["output_cost_per_token"] is not None}
    TABLE.write_text(json.dumps({"source": "the gateway's price table (LiteLLM model_cost)", "litellm": str(out.get("version") or ""),
                                 "date": dt.date.today().isoformat(), "unit": "USD per token, list price if paid",
                                 "models": models, "unpriced": sorted(set(names) - set(models))}, indent=1) + "\n")
    print(f"{len(models)} models priced, {TABLE.relative_to(ROOT)}" + (f"; no price for {', '.join(sorted(set(names) - set(models)))}" if set(names) - set(models) else ""))


if __name__ == "__main__":
    if sys.argv[1:] == ["refresh"]:
        refresh()
    else:
        sys.exit(__doc__)

#!/usr/bin/env python3
"""The deployment's model policy (GEN-05, DEC-45): which kind of model access it allows and what serves each alias.

    python3 ops/modelpolicy.py check      the policy is whole and allowed; exit 1 with the problems
    python3 ops/modelpolicy.py litellm    write the gateway's LiteLLM configuration of a gateway_only deployment

Cards (config/agents.yaml) and keys (ops/keys.sh) name aliases: gpt-sub, gpt-sub-fast and claude-subscription (the Claude
CLI roles). deployments/<name>/models.yaml maps each to what serves it:

  subscription_only (home, CST-02)   chatgpt-subscription (LiteLLM's device login) and claude-oauth (the Claude CLI's
                                     OAuth token); no metered key anywhere
  gateway_only (work)                gateway (an OpenAI-compatible endpoint, through LiteLLM) and gateway-anthropic (an
                                     Anthropic-compatible endpoint the Claude CLI talks to); no subscription model

A gateway deployment's LiteLLM serves the gateway's models under the aliases and nothing else, so a request for any other
model is refused by LiteLLM itself. Its token is a secret (sops), named in the policy, never written in it."""
import os
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deployment as DEPLOY  # noqa: E402

ROOT = DEPLOY.ROOT
SERVED_BY = {"subscription_only": {"chatgpt-subscription", "claude-oauth"}, "gateway_only": {"gateway", "gateway-anthropic"}}
CLAUDE_ALIAS = "claude-subscription"          # the alias of the roles that run the Claude CLI


def load(folder=None):
    f = Path(folder or DEPLOY.FOLDER) / "models.yaml"
    if not f.is_file():
        raise SystemExit(f"{f} does not exist: every deployment says its model policy (docs/PLATFORM.md §4)")
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


def card_aliases(root=ROOT):
    """The aliases the cards may name (config/agents.yaml's models, without none)."""
    reg = yaml.safe_load((root / "config/agents.yaml").read_text(encoding="utf-8"))
    return set(reg.get("models") or []) - {"none"}


def problems(p, root=ROOT):
    """-> what is wrong with a policy, each said with what to change; [] when it is whole and allowed."""
    out = []
    kind = p.get("policy")
    if kind not in SERVED_BY:
        return [f"policy is {kind!r}: one of {', '.join(sorted(SERVED_BY))}"]
    aliases = p.get("aliases") or {}
    missing = sorted(card_aliases(root) - set(aliases))
    if missing:
        out.append(f"no alias for {', '.join(missing)}: every model a card may name needs one (config/agents.yaml)")
    for name, a in sorted(aliases.items()):
        by = (a or {}).get("served_by")
        if by not in SERVED_BY[kind]:
            out.append(f"{name} is served by {by!r}, which {kind} does not allow ({', '.join(sorted(SERVED_BY[kind]))})")
        if kind == "gateway_only" and not (a or {}).get("model"):
            out.append(f"{name} names no gateway model")
        if (name == CLAUDE_ALIAS) != (by in ("claude-oauth", "gateway-anthropic")):
            out.append(f"{name}: the Claude CLI's alias is served by claude-oauth or gateway-anthropic, and no other alias is")
    if kind == "gateway_only":
        g = p.get("gateway") or {}
        for k in ("openai_base", "anthropic_base"):
            if not str(g.get(k) or "").startswith("https://"):
                out.append(f"gateway.{k} is {g.get(k)!r}: an https:// address")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]+", str(g.get("token") or "")):
            out.append("gateway.token names no secret (the sops name of the gateway's token, e.g. GATEWAY_TOKEN)")
        if not isinstance(g.get("max_budget_usd_30d"), (int, float)):
            out.append("gateway.max_budget_usd_30d is missing: a metered gateway has a cap the owner chose")
    return out


def claude_args(p=None, environ=os.environ):
    """The `docker exec -e` arguments that give the Claude CLI its access under the policy, setting what they pass in the
    environment first. Home: the OAuth token, as before. A gateway: its Anthropic address, its token and its model, and
    never the OAuth token, even when one is set."""
    p = p or POLICY
    if p.get("policy") == "subscription_only":
        return ["-e", "CLAUDE_CODE_OAUTH_TOKEN"]
    g, a = p["gateway"], p["aliases"][CLAUDE_ALIAS]
    environ["ANTHROPIC_BASE_URL"] = g["anthropic_base"]
    environ["ANTHROPIC_AUTH_TOKEN"] = environ.get(g["token"], "")
    environ["ANTHROPIC_MODEL"] = a["model"]
    return ["-e", "ANTHROPIC_BASE_URL", "-e", "ANTHROPIC_AUTH_TOKEN", "-e", "ANTHROPIC_MODEL"]


def claude_ready(p=None, environ=os.environ):
    """Whether the Claude CLI roles can run: their token is in the environment."""
    p = p or POLICY
    name = "CLAUDE_CODE_OAUTH_TOKEN" if p.get("policy") == "subscription_only" else p["gateway"]["token"]
    return bool(environ.get(name))


# Which feature each of the gateway's tool servers belongs to. A deployment's gateway lists a server only when its feature
# is on, and never one that sends data out when the deployment holds customer data (a work site, 9 Nov 2026: its gateway
# listed home's jobs, mail, phone, house, fetch, research and browser). A server missing here stops the writer.
SERVER_FEATURE = {"qmd": "memory", "memory": "memory", "memorypublic": "memory", "missions": "mission-control", "files": "mission-control", "stack": "mission-control",
                  "claude": "builder", "graphify": "builder", "fetch": "web", "jobs": "web", "research": "web", "browser": "web",
                  "mail": "mail", "phone": "phone", "house": "home"}
# The gateway container reads the token under this one name; make fills it from the secret models.yaml names (a work site,
# 9 Nov 2026: the token named there never reached the container, which gets only the variables compose passes it).
TOKEN_IN_GATEWAY = "AISTACK_GATEWAY_TOKEN"
SENDS_OUT = {"fetch", "jobs", "research", "browser", "mail", "phone", "house"}


def servers_for(servers, on, customer):
    """The tool servers a deployment's gateway lists: those whose feature is on, none that sends data out for customer data."""
    odd = sorted(set(servers) - set(SERVER_FEATURE))
    if odd:
        raise SystemExit(f"tool servers {', '.join(odd)} belong to no feature: name theirs in ops/modelpolicy.py SERVER_FEATURE")
    return {k: v for k, v in servers.items() if SERVER_FEATURE[k] in on and not (customer and k in SENDS_OUT)}


def litellm(p, home_config, folder=None):
    """A gateway deployment's LiteLLM configuration: home's settings and the tool servers of its features, its models
    replaced by the gateway's under the aliases (and the smoke rig), its budget the policy's."""
    import dataguard as DG
    folder = Path(folder or DEPLOY.FOLDER)
    on = DEPLOY.features(DEPLOY.load(folder / "deployment.env", env={}))
    cfg = yaml.safe_load(home_config)
    cfg["mcp_servers"] = servers_for(cfg.get("mcp_servers") or {}, on, DG.customer(DG.load(folder)))
    g = p["gateway"]
    models = [{"model_name": name, "litellm_params": {"model": a["model"], "api_base": g["openai_base"], "api_key": f"os.environ/{TOKEN_IN_GATEWAY}"}}
              for name, a in sorted(p["aliases"].items()) if a["served_by"] == "gateway"]
    models += [m for m in cfg["model_list"] if m["model_name"] == "smoke"]          # the smoke rig: local, wiring only
    cfg["model_list"] = models
    cfg["litellm_settings"]["max_budget"] = g["max_budget_usd_30d"]
    cfg["litellm_settings"]["callbacks"] = [c for c in cfg["litellm_settings"].get("callbacks", []) if c == "otel"]  # cache_affinity is ChatGPT's
    head = ("# Written by ops/modelpolicy.py litellm from config/litellm/config.yaml and this deployment's models.yaml: do not edit.\n"
            "# Gateway only: the aliases are the gateway's models, and LiteLLM refuses any other model.\n")
    return head + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=10**6)   # no folding: the public copy swaps names, not line breaks


POLICY = load()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["check"]:
        bad = problems(POLICY)
        print("\n".join(bad) or f"   the model policy is whole: {POLICY['policy']}, {len(POLICY.get('aliases') or {})} aliases")
        sys.exit(1 if bad else 0)
    if args == ["token-name"]:                     # make: the secret whose value the gateway container gets (none at home)
        print(POLICY["gateway"]["token"] if POLICY.get("policy") == "gateway_only" and POLICY.get("gateway") else "")
        sys.exit(0)
    if args == ["litellm"]:
        if POLICY.get("policy") != "gateway_only":
            sys.exit("only a gateway_only deployment has a LiteLLM configuration of its own; home's is config/litellm/config.yaml")
        bad = problems(POLICY)
        if bad:
            sys.exit("\n".join(bad))
        out = DEPLOY.FOLDER / "litellm.yaml"
        out.write_text(litellm(POLICY, (ROOT / "config/litellm/config.yaml").read_text(encoding="utf-8"), DEPLOY.FOLDER), encoding="utf-8")
        print(f"wrote {out}")
        sys.exit(0)
    sys.exit(__doc__)

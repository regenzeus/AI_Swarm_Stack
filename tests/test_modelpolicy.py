"""The model policy (GEN-05): home stays subscriptions only and unchanged; a gateway deployment serves only the gateway's
models under the aliases, and the Claude CLI gets the gateway, never the OAuth token."""
import copy
import subprocess
import sys
from pathlib import Path

import yaml

import modelpolicy as MP

ROOT = Path(__file__).resolve().parents[1]
HOME = MP.load(ROOT / "deployments/home")
WORK = MP.load(ROOT / "deployments/example-work")


def test_home_is_subscriptions_only_and_its_claude_calls_are_as_before():
    assert HOME["policy"] == "subscription_only" and MP.problems(HOME) == []
    assert MP.claude_args(HOME, environ={}) == ["-e", "CLAUDE_CODE_OAUTH_TOKEN"]
    assert MP.claude_ready(HOME, environ={"CLAUDE_CODE_OAUTH_TOKEN": "x"}) and not MP.claude_ready(HOME, environ={})
    served = {m["model_name"] for m in yaml.safe_load((ROOT / "config/litellm/config.yaml").read_text())["model_list"]}
    assert {a for a, v in HOME["aliases"].items() if v["served_by"] == "chatgpt-subscription"} <= served | {"gpt-sub", "gpt-sub-fast"}


def test_a_gateway_deployment_serves_only_the_gateways_models_and_refuses_any_other():
    assert MP.problems(WORK) == []
    cfg = yaml.safe_load(MP.litellm(WORK, (ROOT / "config/litellm/config.yaml").read_text(), ROOT / "deployments/example-work"))
    names = {m["model_name"] for m in cfg["model_list"]}
    assert names == {"gpt-sub", "gpt-sub-fast", "smoke"}                 # LiteLLM knows no other name: any other is refused
    for m in cfg["model_list"]:
        params = m["litellm_params"]
        assert not params["model"].startswith("chatgpt/")
        if m["model_name"] != "smoke":
            assert params["api_base"] == WORK["gateway"]["openai_base"] and params["api_key"] == "os.environ/AISTACK_GATEWAY_TOKEN"
    assert cfg["litellm_settings"]["max_budget"] == 50 and "cache_affinity" not in str(cfg["litellm_settings"]["callbacks"])
    assert set(cfg["mcp_servers"]) == {"qmd", "memory", "memorypublic", "missions", "files", "claude", "graphify", "stack"}   # its features' only
    committed = (ROOT / "deployments/example-work/litellm.yaml").read_text()
    assert committed == MP.litellm(WORK, (ROOT / "config/litellm/config.yaml").read_text(), ROOT / "deployments/example-work"), \
        "run AISTACK_DEPLOYMENT=example-work python3 ops/modelpolicy.py litellm"


def test_a_gateway_lists_only_its_features_tool_servers_and_none_that_sends_out_customer_data():
    """A work site, 9 Nov 2026: its gateway listed home's jobs, mail, phone, house, fetch, research and browser. Every tool
    server has a feature; one without stops the writer; customer data never meets one that sends data out."""
    home = yaml.safe_load((ROOT / "config/litellm/config.yaml").read_text())["mcp_servers"]
    assert set(home) <= set(MP.SERVER_FEATURE), "a new tool server needs its feature in SERVER_FEATURE"
    every = set(MP.SERVER_FEATURE.values()) | {"core"}
    assert set(MP.servers_for(home, every, customer=False)) == set(home)
    kept = MP.servers_for(home, every, customer=True)
    assert not set(kept) & {"fetch", "jobs", "research", "browser", "mail", "phone", "house"} and "memory" in kept
    import pytest
    with pytest.raises(SystemExit, match="belong to no feature"):
        MP.servers_for({**home, "newtool": {}}, every, customer=False)


def test_the_claude_cli_under_a_gateway_gets_the_gateway_and_never_the_oauth_token():
    env = {"GATEWAY_TOKEN": "t", "CLAUDE_CODE_OAUTH_TOKEN": "home-token"}
    args = MP.claude_args(WORK, environ=env)
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in args and args == ["-e", "ANTHROPIC_BASE_URL", "-e", "ANTHROPIC_AUTH_TOKEN", "-e", "ANTHROPIC_MODEL"]
    assert env["ANTHROPIC_BASE_URL"] == WORK["gateway"]["anthropic_base"] and env["ANTHROPIC_AUTH_TOKEN"] == "t"
    assert env["ANTHROPIC_MODEL"] == "example-claude" and MP.claude_ready(WORK, environ={"GATEWAY_TOKEN": "t"})


def test_a_policy_that_mixes_or_leaves_out_is_refused_with_what_to_change():
    bad = copy.deepcopy(WORK)
    bad["aliases"]["gpt-sub"] = {"served_by": "chatgpt-subscription"}
    bad["gateway"]["openai_base"] = "http://gateway"
    del bad["gateway"]["max_budget_usd_30d"]
    del bad["aliases"]["gpt-sub-fast"]
    said = "\n".join(MP.problems(bad))
    assert "gpt-sub is served by 'chatgpt-subscription', which gateway_only does not allow" in said
    assert "no alias for gpt-sub-fast" in said and "https://" in said and "max_budget_usd_30d" in said
    home = copy.deepcopy(HOME)
    home["aliases"]["gpt-sub"] = {"served_by": "gateway", "model": "x"}
    assert any("subscription_only does not allow" in p for p in MP.problems(home))


def test_no_claude_call_passes_the_oauth_token_itself_and_the_checks_run_the_policy():
    hits = subprocess.run(["git", "grep", "-n", "CLAUDE_CODE_OAUTH_TOKEN", "--", "ops/*.py"], cwd=ROOT, capture_output=True, text=True).stdout
    assert all(h.startswith("ops/modelpolicy.py:") for h in hits.splitlines()), hits
    assert "python3 ops/modelpolicy.py check" in (ROOT / "ops/check.sh").read_text()
    assert "${LITELLM_CONFIG:-../config/litellm/config.yaml}:/app/config.yaml:ro" in (ROOT / "compose/core.yaml").read_text()
    work = subprocess.run([sys.executable, "ops/modelpolicy.py", "check"], cwd=ROOT, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "AISTACK_DEPLOYMENT": "example-work"})
    assert work.returncode == 0 and "gateway_only" in work.stdout


def test_the_gateway_token_reaches_the_gateway_container_under_one_name():
    """A work site, 9 Nov 2026: the gateway's configuration read the token under the name models.yaml gives, but compose
    passes the gateway container only its own variables, so the token never arrived. The configuration reads one fixed
    name, compose passes it, and make fills it from the secret models.yaml names, in the shell that has both secret files."""
    assert MP.TOKEN_IN_GATEWAY == "AISTACK_GATEWAY_TOKEN"
    assert "AISTACK_GATEWAY_TOKEN: ${AISTACK_GATEWAY_TOKEN:-}" in (ROOT / "compose/core.yaml").read_text()
    make = (ROOT / "Makefile").read_text()
    assert "GATEWAY_TOKEN_NAME ?= $(shell python3 ops/modelpolicy.py token-name)" in make
    assert "AISTACK_GATEWAY_TOKEN=\\$$$(GATEWAY_TOKEN_NAME)" in make and '"$(GW)$(COMPOSE) $(1)"' in make
    r = subprocess.run([sys.executable, str(ROOT / "ops/modelpolicy.py"), "token-name"], capture_output=True, text=True,
                       env={"AISTACK_DEPLOYMENT": "example-work", "PATH": "/usr/bin:/bin"})
    assert r.stdout.strip() == "GATEWAY_TOKEN"
    r = subprocess.run([sys.executable, str(ROOT / "ops/modelpolicy.py"), "token-name"], capture_output=True, text=True,
                       env={"AISTACK_DEPLOYMENT": "home", "PATH": "/usr/bin:/bin"})
    assert r.stdout.strip() == ""


"""SEC-29: the core's Phoenix keeps traces on the site: no external resources, no agent assistant or its tools, no hosted
sandboxes, and the playground only towards OpenAI-compatible endpoints."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_phoenix_runs_without_its_agent_assistant_external_requests_or_hosted_sandboxes():
    env = yaml.safe_load((ROOT / "compose/core.yaml").read_text().replace("!reset ", "").replace("!override ", ""))["services"]["phoenix"]["environment"]
    want = {"PHOENIX_TELEMETRY_ENABLED": "false", "PHOENIX_ALLOW_EXTERNAL_RESOURCES": "false",
            "PHOENIX_DISABLE_AGENT_ASSISTANT": "true", "PHOENIX_AGENTS_DISABLE_WEB_ACCESS": "true",
            "PHOENIX_AGENTS_DISABLE_BASH": "true", "PHOENIX_AGENTS_DISABLE_GITHUB": "true",
            "PHOENIX_ALLOWED_SANDBOX_PROVIDERS": "NONE", "PHOENIX_ALLOWED_PROVIDERS": "OPENAI"}
    assert {k: str(env.get(k)) for k in want} == want
    assert not {"PHOENIX_COLLECTOR_ENDPOINT", "PHOENIX_AGENTS_COLLECTOR_ENDPOINT"} & set(env)    # no remote export

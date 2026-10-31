"""Keep the new-PC procedure and rehearsal checklist complete; run with pytest alongside the docs tests.
Only read documentation and public configuration: never load secrets or contact the live stack.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PROCEDURE = "NEW-MACHINE.md"
REHEARSAL = "ops/windows/rehearse-new-pc.ps1"
TOPICS = {
    "Dashboard access": (
        "tailscale serve --bg --https=8448 http://127.0.0.1:9119",
        "tailscale serve status", "gate-hermes-dashboard", "Tailscale-User-Login", "no Funnel",
    ),
    "Windows resources": (
        "host-probe.ps1", "ai-stack host probe", "Start-ScheduledTask",
        r"C:\AI\exports\.host\host.json", "30", "Stack page",
    ),
    "Builder image": (
        "ARG HERMES_IMAGE=", "default", "versions.env",
        '--build-arg HERMES_IMAGE="$HERMES_IMAGE"', "Hermes first",
    ),
    "Profiles": (
        "configure-mission.sh", 'LITELLM_MISSION_KEY="$VK_MISSION"', "sops exec-env",
        "docker exec aistack-builder-1 sh /config/configure-builder.sh",
        "LITELLM_BUILDER_KEY", "VK_BUILDER", "hermes profile list",
    ),
    "Dashboard API-key synchronization": (
        "configure.sh", "API_SERVER_KEY", "/opt/data/.env", "Compose environment",
        "docker restart aistack-hermes-1", "make smoke", "Mission Control", "Open WebUI",
    ),
}


def checklist():
    text = (ROOT / REHEARSAL).read_text()
    header = text.split('$ErrorActionPreference = "Stop"', 1)[0]
    return dict(re.findall(r"^# \[ \] ([^:\n]+): (.*?)(?=^# \[ \] |\Z)", header, re.M | re.S))


@pytest.mark.parametrize("topic", TOPICS)
@pytest.mark.parametrize("document", [PROCEDURE, REHEARSAL])
def test_required_setup_topics(document, topic):
    if document == REHEARSAL:
        items = checklist()
        assert topic in items, f"{document}: missing checklist item {topic}"
        text = items[topic]
    else:
        text = (ROOT / document).read_text()
    text = " ".join(text.replace("\n#", "\n").split())
    missing = [term for term in TOPICS[topic] if term not in text]
    assert not missing, f"{document}: {topic} needs {missing}"


def test_documented_builder_default_matches_configuration():
    dockerfile = (ROOT / "images/builder/Dockerfile").read_text()
    default = re.search(r"^ARG HERMES_IMAGE=(\S+)$", dockerfile, re.M)[1]
    pins = (ROOT / "versions.env").read_text()
    pin = re.search(r"^HERMES_IMAGE=(\S+)$", pins, re.M)[1]
    assert default == pin, "builder default changed: review the new-PC build instructions"
    for document in (PROCEDURE, REHEARSAL):
        assert f"ARG HERMES_IMAGE={default}" in (ROOT / document).read_text(), document


def test_rehearsal_checklist_keeps_manual_steps_isolated():
    text = (ROOT / REHEARSAL).read_text().split('$ErrorActionPreference = "Stop"', 1)[0]
    assert "replacement PC only" in text
    assert "NOT these newer integrations" in text
    assert "Do not enable them in" in text and "airehearsal" in text
    assert "compose/rehearsal.yaml" in text

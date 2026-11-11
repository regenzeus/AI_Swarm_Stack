"""Subscription-only policy for the KEYS table in ops/keys.sh (docs/SECURITY.md).

Scope: guards the repository's own workflows (the table as committed, and every script in ops/ that could
rewrite it). It cannot stop a future manual edit; CI running this test is what catches that.
The one non-subscription model is the `smoke` rig, which only vk-smoke may hold (the deploy smoke test
probes forbidden models on purpose and expects 403: those probes must stay)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUBSCRIPTION = {"gpt-sub", "gpt-sub-fast"}
SMOKE_ONLY = {"smoke": "vk-smoke"}


def keys_table():
    rows = re.findall(r'^\s*"(vk-[a-z-]+)\|([^|]*)\|([0-9.]+)\|([^"]*)"', (ROOT / "ops/keys.sh").read_text(), re.M)
    assert rows
    return rows


def test_every_key_holds_only_subscription_models():
    for alias, models, _budget, _mcp in keys_table():
        for m in models.split(","):
            allowed = m in SUBSCRIPTION or SMOKE_ONLY.get(m) == alias
            assert allowed, f"{alias} holds non-subscription model {m!r}"


def test_models_are_served_by_the_gateway():
    cfg = (ROOT / "config/litellm/config.yaml").read_text() + (ROOT / "config/litellm/chatgpt-models.yaml").read_text()
    served = set(re.findall(r"model_name:\s*(\S+)", cfg))
    for _alias, models, _b, _m in keys_table():
        assert set(models.split(",")) <= served | SUBSCRIPTION


def test_budget_mode_is_retired():
    assert not (ROOT / "ops/budget-mode.py").exists()
    assert "budget-mode" not in (ROOT / "Makefile").read_text()


def test_only_the_creation_script_writes_the_keys_table():
    """No script other than ops/keys.sh itself may write ops/keys.sh (the old budget-mode.py did)."""
    for p in list((ROOT / "ops").rglob("*.py")) + list((ROOT / "ops").rglob("*.sh")) + [ROOT / "Makefile"]:
        if p.name == "keys.sh":
            continue
        text = p.read_text()
        if "keys.sh" in text:
            assert not re.search(r"keys\.sh.{0,80}(write|open\([^)]*[\"']w)|(>>?|sed -i|tee)\s*\S*keys\.sh", text, re.S), \
                f"{p.relative_to(ROOT)} appears to write ops/keys.sh"


def test_update_keys_only_reads_the_table():
    src = (ROOT / "ops/update-keys.py").read_text()
    assert 'KEYS.read_text()' in src and "write" not in src.replace("urllib", "")



def test_deploy_never_prints_a_key():
    src = (Path(__file__).resolve().parent.parent / "ops/deploy.py").read_text()
    assert not re.search(r'f"[A-Z_]*KEY=\{', src)          # run() prints every command: keys go by name (-e NAME), never as NAME=value


def test_background_jobs_use_their_own_keys():
    """Only mission runs (and what runs inside them) use vk-mission; every VK_* the ops code reads is in the table."""
    allowed = {"missions.py", "mission_extras.py", "cleanup.py", "wiki_rebuild.py", "deploy.py"}
    table = {alias.replace("-", "_").upper() for alias, *_ in keys_table()}
    for f in sorted((ROOT / "ops").glob("*.py")):
        text = f.read_text()
        if f.name not in allowed:
            assert 'environ["VK_MISSION"]' not in text and "environ.get(\"VK_MISSION\"" not in text, f.name
        for name in re.findall(r'environ(?:\.get\(|\[)["\'](VK_[A-Z_]+)', text):
            assert name in table, (f.name, name)

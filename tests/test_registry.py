"""ops/registry.py: the agent cards in config/agents.yaml (SWM-01, SWM-22 to SWM-24, SWM-29)."""
import copy

import yaml

import registry as R


def write(tmp_path, reg, keys):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "ops/systemd").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ops/systemd/crew-x.service").write_text("[Service]\n")
    (tmp_path / "prompts").mkdir(exist_ok=True)
    (tmp_path / "prompts/inbox.md").write_text("<!-- prompt: PICK -->\nx\n<!-- end -->\n")
    (tmp_path / "config/agents.yaml").write_text(yaml.safe_dump(reg))
    (tmp_path / "ops/keys.sh").write_text("KEYS=(\n" + "".join(f'  "{k}"\n' for k in keys) + ")\n")
    return tmp_path


BASE = R.load()


def small():
    reg = copy.deepcopy(BASE)
    card = copy.deepcopy(next(c for c in reg["agents"] if c["id"] == "inbox"))
    card["jobs"] = ["crew-x"]
    reg["agents"], reg["services"] = [card], {"vk-smoke": "smoke"}
    return reg, ["vk-inbox|gpt-sub-fast|0.02|mail", "vk-smoke|smoke|0.001|"]


def test_the_repo_cards_pass_the_registry_check():
    assert R.check() == []


def test_a_card_names_its_own_prompts_file_and_every_prompts_file_has_an_owner(tmp_path):
    reg, keys = small()
    root = write(tmp_path, reg, keys)
    h = R.hash_of("inbox", root)
    (root / "prompts/inbox.md").write_text("<!-- prompt: PICK -->\ny\n<!-- end -->\n")
    assert R.hash_of("inbox", root) != h                                        # the card hash follows its prompts (MEM-11)
    reg["agents"][0]["prompts"] = "prompts/other.md"
    assert "agent inbox: prompts must be prompts/inbox.md, an existing file" in R.check(write(tmp_path, reg, keys))
    reg["agents"][0]["prompts"] = "prompts/inbox.md"
    (root / "prompts/stray.md").write_text("x")
    assert "prompts/stray.md is named by no card's prompts field and is no service's (MEM-11)" in R.check(write(tmp_path, reg, keys))


def test_a_card_missing_a_field_or_naming_unknown_values_is_refused(tmp_path):
    reg, keys = small()
    assert R.check(write(tmp_path, reg, keys)) == []
    for field in R.FIELDS:
        bad = copy.deepcopy(reg)
        del bad["agents"][0][field]
        assert f"no {field}" in "\n".join(R.check(write(tmp_path, bad, keys))), field
    for field, value, want in (("harness", "langchain", "unknown harness"), ("wake", "sometimes", "unknown wake"),
                               ("roles", ["boss"], "unknown role"), ("rooms", ["secret"], "unknown room"),
                               ("owns", {"poem": "done"}, "unknown kind"), ("owns", {"idea": ""}, "without a definition of done"),
                               ("jobs", ["crew-none"], "has no unit"), ("budgets", {"wakes_per_day": -1, "messages_per_hour": 2}, "whole number")):
        bad = copy.deepcopy(reg)
        bad["agents"][0][field] = value
        assert want in "\n".join(R.check(write(tmp_path, bad, keys))), field


def test_a_shared_key_and_extra_grants_are_refused(tmp_path):
    reg, keys = small()
    twin = copy.deepcopy(reg["agents"][0])
    twin["id"] = "inbox-two"
    reg2 = {**reg, "agents": reg["agents"] + [twin]}
    assert "also agent inbox's (SWM-23" in "\n".join(R.check(write(tmp_path, reg2, keys)))
    wide = ["vk-inbox|gpt-sub-fast|0.02|mail,phone", keys[1]]
    assert "differ from vk-inbox's MCP grants" in "\n".join(R.check(write(tmp_path, reg, wide)))
    extra = keys + ["vk-orphan|gpt-sub|0.01|"]
    assert "vk-orphan in ops/keys.sh belongs to no agent card" in "\n".join(R.check(write(tmp_path, reg, extra)))


def test_paid_models_are_refused(tmp_path):
    reg, keys = small()
    reg["agents"][0]["model"] = "gpt-5-api"
    assert "is not an alias of the deployment's model policy, nor a local model" in "\n".join(R.check(write(tmp_path, reg, keys)))
    reg["agents"][0]["model"] = "ollama:qwen3:0.6b"
    assert not any("model" in p for p in R.check(write(tmp_path, reg, keys)))


def test_the_card_hash_changes_with_any_field():
    card = copy.deepcopy(BASE["agents"][0])
    h = R.card_hash(card)
    card["rooms"] = card["rooms"] + ["ops"]
    assert R.card_hash(card) != h and len(h) == 12


def test_a_run_names_its_card_and_the_next_run_shows_a_change():
    import sqlite3

    import runrecord as RR
    assert R.hash_of("doctor") == R.card_hash(next(c for c in BASE["agents"] if c["id"] == "doctor")) and R.hash_of("nobody") is None
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("create table runs(run text, agent text, started real, manifest text)")
    c.execute("insert into runs values ('r1', 'crew:doctor', 1, ?)", ('{"agent": "crew:doctor", "card": "aaaaaaaaaaaa"}',))
    assert RR.drift(c, "r2", "crew:doctor", {"agent": "crew:doctor", "card": "bbbbbbbbbbbb"}) == ["agent card changed (aaaaaaaaaaaa → bbbbbbbbbbbb)"]
    assert RR.drift(c, "r2", "crew:doctor", {"agent": "crew:doctor", "card": "aaaaaaaaaaaa"}) == []

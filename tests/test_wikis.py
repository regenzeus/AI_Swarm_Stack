"""ops/wikis.py: a summary for every wiki (one small model call when its pages change) and deleting a mission's wiki
(one vault commit, restorable; the mission stops compiling one). A temporary git vault; the model is a fake."""
import json
import re
import subprocess
import threading
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def page(vault, rel, title, summary=""):
    p = vault / f"{rel}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\ntitle: {title}\nsummary: {summary}\n---\nBody of {title}.\n")


def split_front(text):
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    import yaml
    return (yaml.safe_load(m.group(1)) or {}, m.group(2)) if m else ({}, text)


@pytest.fixture
def W(tmp_path, monkeypatch):
    import wikis
    vault, public = tmp_path / "vault", tmp_path / "public"
    vault.mkdir(); public.mkdir()
    git = lambda *a: subprocess.run(["git", *a], cwd=vault, check=True, capture_output=True)
    git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    page(vault, "wiki/concepts/ddr4", "DDR4", "memory standard")
    page(vault, "missions/ram/wiki/entities/corsair", "Corsair", "RAM maker")
    page(vault, "missions/ram/wiki/index", "RAM: wiki")
    (vault / "missions/ram/MISSION.md").write_text("---\nslug: ram\n---\n")
    git("add", "-A"); git("commit", "-qm", "seed")
    missions = {"ram": {"slug": "ram", "title": "RAM upgrade", "type": "task"}}
    saved, events, calls = [], [], []

    def ask_text(prompt, key, model="gpt-sub", timeout=300):
        calls.append((prompt, model))
        return "**The wiki** covers DDR4 kits.\n Corsair leads."

    def vault_commit(paths, msg):
        subprocess.run(["git", "add", *paths], cwd=vault, capture_output=True)
        subprocess.run(["git", "commit", "-qm", msg], cwd=vault, capture_output=True)

    wikis.M = types.SimpleNamespace(
        VAULT=vault, PUBLIC=public, load_missions=lambda: missions, split_front=split_front, ask_text=ask_text,
        X=types.SimpleNamespace(wiki_root=lambda m: f"missions/{m['slug']}/wiki"), J=types.SimpleNamespace(CO="Co-Authored-By: t"),
        save_mission=lambda m: saved.append(dict(m)), vault_commit=vault_commit, reindex=lambda: None, log=lambda *a: None,
        event=lambda *a, **k: events.append(a), stop=threading.Event())
    monkeypatch.setenv("VK_WIKIS", "vk-test")
    wikis.calls, wikis.saved, wikis.events, wikis.missions = calls, saved, events, missions
    yield wikis
    wikis.M = None


def test_every_wiki_gets_a_plain_summary_once_until_its_pages_change(W):
    assert sorted(W.sweep(now=1000)) == ["missions/ram/wiki", "wiki"]
    s = json.loads((W.M.PUBLIC / "wiki-summaries.json").read_text())
    assert s["missions/ram/wiki"]["summary"] == "The wiki covers DDR4 kits. Corsair leads."      # no markdown
    assert s["missions/ram/wiki"]["pages"] == 1                                                     # index.md is not a page
    assert all(m == "gpt-sub-fast" for _, m in W.calls) and "Corsair: RAM maker" in W.calls[-1][0]
    n = len(W.calls)
    assert W.sweep(now=2000) == [] and len(W.calls) == n                                            # nothing changed: no call
    page(W.M.VAULT, "missions/ram/wiki/entities/gskill", "G.Skill", "RAM maker")
    assert W.sweep(now=3000) == []                                                                  # changed, but < 6 h ago
    assert W.sweep(now=1000 + W.EVERY + 1) == ["missions/ram/wiki"]


def test_a_page_without_a_summary_field_is_described_by_its_text_and_a_meta_answer_is_not_stored(W):
    p = W.M.VAULT / "wiki/howto/backup.md"
    p.parent.mkdir(parents=True)
    p.write_text("---\ntitle: Backups\n---\n# Backups\nNightly at 03:30 to the [[entities/nas|NAS]], age-encrypted.\n")
    pages, _ = W.pages_of("wiki")
    assert ("Backups", "Nightly at 03:30 to the NAS, age-encrypted.") in pages
    W.M.ask_text = lambda *a, **k: "I can't access the page contents from the titles alone. Please provide the pages."
    assert W.sweep(now=1000) == []                                                                  # nothing stored
    assert "wiki" not in json.loads((W.M.PUBLIC / "wiki-summaries.json").read_text())


def test_delete_removes_a_mission_wiki_in_one_restorable_commit_and_stops_it_growing(W):
    W.sweep(now=1000)
    out = W.handle({"action": "wiki_delete", "root": "missions/ram/wiki"})
    vault = W.M.VAULT
    assert out["pages"] == 1 and not (vault / "missions/ram/wiki").exists()
    assert W.saved[-1]["wiki_off"] is True                                                          # no wiki grows back
    log = subprocess.run(["git", "log", "--format=%s"], cwd=vault, capture_output=True, text=True).stdout
    assert "wiki: delete missions/ram/wiki" in log
    restored = subprocess.run(["git", "show", "HEAD~1:missions/ram/wiki/entities/corsair.md"], cwd=vault, capture_output=True, text=True)
    assert "Corsair" in restored.stdout                                                             # restorable from history
    assert "missions/ram/wiki" not in json.loads((W.M.PUBLIC / "wiki-summaries.json").read_text())


def test_the_vault_wiki_and_paths_outside_wikis_cannot_be_deleted(W):
    for bad in ("wiki", "missions/ram", "missions/../wiki", "topics/x/wiki/../..", "agents/crew-doctor"):
        with pytest.raises(ValueError):
            W.handle({"action": "wiki_delete", "root": bad})
    assert (W.M.VAULT / "wiki/concepts/ddr4.md").exists()


def test_a_deleted_wiki_is_not_compiled_again():
    src = (ROOT / "ops/mission_extras.py").read_text()
    assert 'if m.get("wiki_off"):' in src.split("def compile_wiki", 1)[1][:200]


def test_wiki_delete_is_wired_for_the_app_only():
    runner = (ROOT / "ops/missions.py").read_text()
    server = (ROOT / "images/mission-control/server.py").read_text()
    assert "W.handle(req) if a in W.ACTIONS" in runner and "target=W.worker" in runner
    assert 'body.get("action") == "wiki_delete" and from_ai_phone(request)' in server            # never from the AI phone
    assert server.count("wiki_delete") == 1                                                        # and no MCP tool sends it


def test_mission_wikis_and_agent_journals_are_searchable():
    start = (ROOT / "images/qmd/start.sh").read_text()
    assert "--name missions" in start and "--name agents" in start
    j = (ROOT / "ops/journal.py").read_text()                                   # a run reads what its card names (MEM-04)
    assert 'VAULT_SCOPE = ["qmd://vault-wiki/", "qmd://vault-raw/"]' in j and "def wiki_scope(card, own=None):" in j


def test_a_page_with_invalid_front_matter_is_skipped_and_does_not_stop_the_summary(W):
    bad = W.M.VAULT / "wiki/concepts/bad.md"
    bad.write_text("---\ntitle: Bad: really: bad\nsummary: a: b: c\n---\nBody.\n")
    logs = []
    W.M.log = lambda *a: logs.append(a)
    pages, _ = W.pages_of("wiki")
    assert [t for t, _ in pages] == ["DDR4"]
    assert any("bad.md" in str(x) for x in logs)
    assert "wiki" in W.sweep(now=1000)
    assert "wiki" in json.loads((W.M.PUBLIC / "wiki-summaries.json").read_text())


def test_the_real_split_front_reads_broken_front_matter_as_plain_text():
    """The fixture above stubs split_front; this checks ops/missions.py's own (FND-11)."""
    import missions
    text = "---\ntitle: Bad: really: bad\n---\nBody.\n"
    assert missions.split_front(text) == ({}, text.strip())
    assert missions.split_front("---\ntitle: Good\n---\nBody.\n") == ({"title": "Good"}, "Body.")

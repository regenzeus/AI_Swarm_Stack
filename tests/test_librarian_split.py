"""Keeping memory in check (MEM-40, MEM-41): a wiki over its limit splits into parts by its links, a subscription to it gives the
parts that match, a split is logged with its undo; a page nobody read or confirmed for the archive days is archived, never before the
read record covers them."""
import datetime as dt
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def LIB(tmp_path, monkeypatch):
    import librarian
    import mission_extras as X
    import memwrite
    import memstack
    vault = tmp_path / "vault"
    root = vault / "topics/big/wiki"
    for group, n in (("company", 6), ("price", 5), ("mine", 2)):
        for i in range(n):
            links = " ".join(f"[[entities/{group}-{j}]]" for j in range(n) if j != i)
            (root / "entities").mkdir(parents=True, exist_ok=True)
            (root / "entities" / f"{group}-{i}.md").write_text(f"---\ntitle: {group.title()} {i}\nlast_validated: '2026-01-01'\n---\n## Key facts\n- {group} fact {links}\n")
    M = types.SimpleNamespace(VAULT=vault, split_front=memstack.split_front, write_front=lambda f, meta, body: _write(f, meta, body),
                              RTM=types.SimpleNamespace(touched=lambda *a, **k: None), X=X)
    X.M = M
    librarian.M = M
    monkeypatch.setattr(memwrite, "LOG", tmp_path / "mem" / "writes.jsonl")
    monkeypatch.setattr(memwrite, "DIR", tmp_path / "mem")
    monkeypatch.setattr(memstack, "VAULT", vault)
    librarian.WROTE.clear()
    yield librarian
    X.M = None


def _write(f, meta, body):
    import yaml
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f"---\n{yaml.safe_dump(meta, sort_keys=False)}---\n{body}")


def test_a_wiki_over_the_limit_splits_into_parts_with_hubs(LIB):
    ps = LIB.pages("topics/big/wiki")
    assert LIB.split("topics/big/wiki", "Big", ps, dt.date(2026, 11, 7), split_pages=20, merge_pages=3) is None   # under the limit: nothing
    r = LIB.split("topics/big/wiki", "Big", ps, dt.date(2026, 11, 7), split_pages=10, merge_pages=3)
    assert r == {"parts": 2, "changed": True}                                                 # the two-page group joined another part
    parts = sorted((LIB.M.VAULT / "topics/big/wiki/parts").glob("*.md"))
    assert len(parts) == 2 and all("type: part" in p.read_text() for p in parts)
    index = (LIB.M.VAULT / "topics/big/wiki/index.md").read_text()
    assert "## Parts" in index and "[[parts/" in index
    again = LIB.split("topics/big/wiki", "Big", LIB.pages("topics/big/wiki"), dt.date(2026, 11, 8), split_pages=10, merge_pages=3)
    assert again == {"parts": 2, "changed": False}                                            # the same split twice changes nothing
    import memwrite as MW
    assert MW.writes()[-1]["outcome"] == "split" and MW.writes()[-1]["undo"]["kind"] == "git"


def test_a_subscription_to_a_split_wiki_gives_its_matching_parts(LIB, monkeypatch, tmp_path):
    LIB.split("topics/big/wiki", "Big", LIB.pages("topics/big/wiki"), dt.date(2026, 11, 7), split_pages=10, merge_pages=3)
    import memstack as MS
    import memtrials
    monkeypatch.setattr(MS, "qmd_search", memtrials.local_search(LIB.M.VAULT))
    monkeypatch.setattr(MS, "DIR", tmp_path / "mem")
    monkeypatch.setattr(MS, "PUBLIC", tmp_path / "pub")
    import runtime
    monkeypatch.setattr(runtime, "emit", lambda *a, **k: None)
    text = MS.opening("mission:big", kind="mission", task="price fact", subs=["world:topics/big/wiki"], own="topics/big/wiki", tools=False)
    assert "Its parts" in text and "world:topics/big/wiki#" in text and "price-0" in text


def test_a_split_is_undone():
    """Its undo is the vault's history: the log names the files; git restores them."""
    src = (ROOT / "ops/librarian.py").read_text()
    assert '"undo": {"kind": "git", "paths": [f"{root}/parts", f"{root}/index.md"]}' in src


def test_an_unread_page_is_archived_and_kept_out_of_openings(LIB):
    today = dt.date(2026, 11, 7)
    ok = lambda: (True, "ok")
    rep = LIB.structure([("topics/big/wiki", "Big")], today, gate=ok, reads=(set(), 10.0))
    assert rep["archived"] == {} and "covers 10 of 90 days" in rep["archive_waits"]           # too short a record: nothing archived
    read = {"topics/big/wiki/entities/company-0.md"}
    rep = LIB.structure([("topics/big/wiki", "Big")], today, gate=ok, reads=(read, 120.0))
    arch = rep["archived"]["topics/big/wiki"]
    assert "entities/company-0" not in arch and "entities/price-1" in arch
    assert "archived: '2026-11-07'" in (LIB.M.VAULT / "topics/big/wiki/entities/price-1.md").read_text()
    assert LIB.structure([("topics/big/wiki", "Big")], today, gate=lambda: (False, "a trial failed"))["waits"] == "a trial failed"
    import memstack as MS
    assert all(not p["meta"].get("archived") or False for p in MS.pages_of("topics/big/wiki") if p["path"] == "entities/company-0")

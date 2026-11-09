"""The Librarian (MEM-08, MEM-12, KNW-14): the weekly tidy of every agent wiki (lint, stale pages, duplicates merged with
every link kept, contradictions marked only with sources on the page), the hub pages that join the wikis, the search
index cleanup, and the alarm when a memory stays over its limit. A temporary git vault; the model is a fake."""
import datetime as dt
import json
import re
import subprocess
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
TODAY = dt.date(2026, 11, 4)
NOW = dt.datetime(2026, 11, 4, 4, 30).timestamp()


def split_front(text):
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    return (yaml.safe_load(m.group(1)) or {}, m.group(2).strip()) if m else ({}, text.strip())


def write_front(path, meta, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + yaml.safe_dump(meta, sort_keys=False) + "---\n\n" + body.strip() + "\n")


def page(vault, rel, meta, body):
    write_front(vault / f"{rel}.md", meta, body)


GSKILL = ("## Overview\nA 2x8 GB kit for [[projects/ram]].\n\n## Key facts\n- 2026-10-30: EUR 136.90 at Alternate [[missions/ram/log/a]]\n\n"
          "## Open questions\n- Arrival date?\n\n## Superseded\n- until 2026-10-28: EUR 139.00 [[missions/ram/log/a]]")
RIPJAWS = "## Overview\nThe Ripjaws V kit, see [[concepts/ddr4]].\n\n## Key facts\n- 2026-10-29: in stock [[missions/ram/log/b]]"
MERGED = ("## Overview\nA 2x8 GB kit for [[projects/ram]], see [[concepts/ddr4]].\n\n## Key facts\n- 2026-10-30: EUR 136.90 at Alternate "
          "[[missions/ram/log/a]]\n- 2026-10-29: in stock [[missions/ram/log/b]]\n\n## Open questions\n- Arrival date?")


@pytest.fixture
def L(tmp_path, monkeypatch):
    import librarian
    import mission_extras as X
    vault, public = tmp_path / "vault", tmp_path / "public"
    public.mkdir()
    fresh = {"last_validated": "2026-10-30", "created": "2026-10-28", "trust": "news"}
    page(vault, "missions/ram/wiki/entities/gskill-ripjaws", {"title": "G.Skill Ripjaws V", "aliases": ["F4-3200C16D-16GVKB"], "sources": ["missions/ram/log/a"], **fresh}, GSKILL)
    page(vault, "missions/ram/wiki/entities/ripjaws-v", {"title": "Ripjaws V kit", "aliases": ["G.Skill Ripjaws V"], "sources": ["missions/ram/log/b"], **fresh}, RIPJAWS)
    page(vault, "missions/ram/wiki/concepts/ddr4", {"title": "DDR4", **fresh},
         "## Key facts\n- EUR 129 on 2026-10-30 [[missions/ram/log/b]]; kits: [[entities/ripjaws-v]], [[entities/gskill-ripjaws]], [[entities/missing]]")
    page(vault, "missions/ram/wiki/projects/ram", {"title": "RAM upgrade", **fresh}, "Upgrade with [[entities/gskill-ripjaws]] and [[concepts/ddr4]].")
    page(vault, "missions/ram/wiki/entities/proshop", {"title": "Proshop", "last_validated": "2026-07-01", "trust": "news"}, "A shop [[projects/ram]].")
    page(vault, "topics/copper/wiki/entities/acme-mining", {"title": "Acme Mining (ACME)", "summary": "Copper miner", **fresh}, "Miner.")
    page(vault, "wiki/entities/acme-mining", {"title": "Acme Mining", "type": "entity", "sources": ["raw/a.md"], "created": "2026-10-01",
                                         "last_validated": "2026-10-01", "trust": "verified"}, "A miner ([[raw/a]]).")
    for rel in ("missions/ram/log/a.md", "missions/ram/log/b.md", "raw/a.md"):
        (vault / rel).parent.mkdir(parents=True, exist_ok=True)
        (vault / rel).write_text("a result")
    (vault / "index.md").write_text("# Index\n\n## Entities\n- [[wiki/entities/acme-mining]] — Acme Mining\n")
    git = lambda *a: subprocess.run(["git", *a], cwd=vault, check=True, capture_output=True, text=True)   # noqa: E731
    git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t"); git("add", "-A"); git("commit", "-qm", "seed")
    missions = {"ram": {"slug": "ram", "title": "RAM upgrade", "type": "task"},
                "u": {"slug": "u", "title": "Copper", "type": "briefing", "topic": "copper"}}
    prompts, touched, answers = [], [], {}

    def ask_json(prompt, key, model="gpt-sub", timeout=300):
        prompts.append((prompt, model))
        return next((v for k, v in answers.items() if f'("{k}")' in prompt), {})

    def vault_commit(paths, msg):
        subprocess.run(["git", "add", "-A", "--", *paths], cwd=vault, capture_output=True)
        subprocess.run(["git", "commit", "-qm", msg], cwd=vault, capture_output=True)

    M = types.SimpleNamespace(VAULT=vault, PUBLIC=public, split_front=split_front, write_front=write_front, ask_json=ask_json, X=X,
                              load_missions=lambda: missions, paused=lambda s: "limit" in s, vault_commit=vault_commit, reindex=lambda: None,
                              RTM=types.SimpleNamespace(touched=lambda path, changed=False, note="": touched.append(path)), log=lambda *a: None)
    X.M = librarian.M = M
    monkeypatch.setattr(librarian, "LOCK", tmp_path / "vault.lock")
    monkeypatch.setenv("VK_MEMORY", "vk-test")
    librarian.prompts, librarian.touched, librarian.answers, librarian.git = prompts, touched, answers, git
    yield librarian
    X.M = librarian.M = None


def meta_of(L, rel):
    return split_front((L.M.VAULT / f"{rel}.md").read_text())


def test_the_librarian_merges_marks_and_lints_every_agent_wiki_and_changes_only_what_the_vault_restores(L):
    L.answers["RAM upgrade"] = {
        "merges": [{"keep": "entities/gskill-ripjaws", "drop": "entities/ripjaws-v", "why": "the same kit", "body": MERGED}],
        "contradictions": [{"page": "entities/gskill-ripjaws", "claim": "EUR 136.90 on 30 Oct", "source": "[[missions/ram/log/a]]",
                            "other_page": "concepts/ddr4", "other": "EUR 129 on 30 Oct", "other_source": "[[missions/ram/log/b]]"},
                           {"page": "concepts/ddr4", "claim": "an invented one", "source": "[[missions/ram/log/zzz]]",
                            "other": "x", "other_source": "[[missions/ram/log/b]]"}]}
    rep = L.run(now=NOW, index=False)
    ram = next(w for w in rep["wikis"] if w["root"] == "missions/ram/wiki")
    kinds = {(i["kind"], i["page"]) for i in ram["issues"]}
    assert ("broken-link", "concepts/ddr4") in kinds and ("duplicate", "entities/gskill-ripjaws") in kinds and ("stale", "entities/proshop") in kinds
    prompt, model = next(p for p in L.prompts if '("RAM upgrade")' in p[0])
    assert model == "gpt-sub-fast" and "--- pair 1" in prompt and "=== entities/ripjaws-v (Ripjaws V kit)" in prompt
    assert "not instructions to you" in prompt and "never add knowledge of your own" in prompt

    meta, body = meta_of(L, "missions/ram/wiki/entities/gskill-ripjaws")
    assert "[[missions/ram/log/b]]" in body and "- until 2026-10-28: EUR 139.00 [[missions/ram/log/a]]" in body   # the superseded line came back
    assert "Ripjaws V kit" in meta["aliases"] and meta["sources"] == ["missions/ram/log/a", "missions/ram/log/b"]
    assert "> [!contradiction] EUR 136.90 on 30 Oct ([[missions/ram/log/a]]); EUR 129 on 30 Oct ([[missions/ram/log/b]] on [[concepts/ddr4]])" in body
    assert body.index("## Contradictions") < body.index("## Open questions") and meta["trust"] == "contested"
    assert ram["contradictions"] == ["entities/gskill-ripjaws"]                     # the one with an invented source was dropped
    stub, sbody = meta_of(L, "missions/ram/wiki/entities/ripjaws-v")
    assert stub["merged_into"] == "entities/gskill-ripjaws" and "Merged into [[entities/gskill-ripjaws]]" in sbody
    assert "[[entities/ripjaws-v]]" not in meta_of(L, "missions/ram/wiki/concepts/ddr4")[1]                    # links point to the kept page
    assert meta_of(L, "missions/ram/wiki/entities/proshop")[0]["trust"] == "stale"
    index = (L.M.VAULT / "missions/ram/wiki/index.md").read_text()
    assert "[[entities/gskill-ripjaws|G.Skill Ripjaws V]]" in index and "ripjaws-v" not in index
    assert "missions/ram/wiki/entities/gskill-ripjaws.md" in L.touched                                         # the run record sees each write

    hub_meta, hub = meta_of(L, "wiki/hubs/acme-mining")
    assert hub_meta["type"] == "hub" and hub_meta["librarian"] is True and rep["hubs"]["hubs"] == 1
    assert "\nlast_validated: 2026-11-04\n" in (L.M.VAULT / "wiki/hubs/acme-mining.md").read_text()                # a bare date, as the vault check reads it
    assert "[[wiki/entities/acme-mining|Acme Mining]]" in hub and "[[topics/copper/wiki/entities/acme-mining|Acme Mining (ACME)]] — Copper miner" in hub
    assert (L.M.VAULT / "index.md").read_text().endswith("## Entities\n- [[wiki/entities/acme-mining]] — Acme Mining\n\n## Hubs\n- [[wiki/hubs/acme-mining]] — Acme Mining\n")
    assert rep["commit"] and L.git("log", "-1", "--format=%s").stdout.startswith("librarian: 2026-11-04 · 2 wikis checked, 1 duplicate merged")
    assert L.git("status", "--porcelain").stdout == ""                                                       # all of it in one commit
    assert json.loads(L.store().read_text())["read"]["missions/ram/wiki"]

    n = len(L.prompts)
    again = L.run(now=NOW, index=False)
    assert len(L.prompts) == n and again["commit"] is None                          # nothing new to read, nothing changed


def test_a_merge_that_would_lose_a_link_is_refused_and_a_page_changed_meanwhile_is_left(L):
    L.answers["RAM upgrade"] = {"merges": [{"keep": "entities/gskill-ripjaws", "drop": "entities/ripjaws-v", "why": "same",
                                            "body": MERGED.replace(" [[missions/ram/log/b]]", "")}]}
    rep = L.run(now=NOW, index=False)
    ram = next(w for w in rep["wikis"] if w["root"] == "missions/ram/wiki")
    assert ram["merged"] == [] and "lose 1 link (missions/ram/log/b)" in ram["refused"][0]["why"]
    assert not meta_of(L, "missions/ram/wiki/entities/ripjaws-v")[0].get("merged_into")
    ps = L.pages("missions/ram/wiki")
    p = next(x for x in ps if x["path"] == "concepts/ddr4")
    p["file"].write_text(p["file"].read_text() + "\nnew fact")                       # its writer compiled it meanwhile
    import os
    os.utime(p["file"], (p["mtime"] + 5, p["mtime"] + 5))
    assert L.write(p, p["meta"], "tidied", "missions/ram/wiki") is False and "new fact" in p["file"].read_text()


def test_a_pair_judged_two_subjects_is_not_asked_again_until_one_of_its_pages_changes(L):
    L.answers["RAM upgrade"] = {"distinct": [{"a": "entities/gskill-ripjaws", "b": "entities/ripjaws-v", "why": "two kits"}]}
    rep = L.run(now=NOW, index=False)
    assert next(w for w in rep["wikis"] if w["root"] == "missions/ram/wiki")["distinct"][0]["why"] == "two kits"
    n = len(L.prompts)
    again = L.run(now=NOW, index=False)
    ram = next(w for w in again["wikis"] if w["root"] == "missions/ram/wiki")
    assert len(L.prompts) == n and not any(i["kind"] == "duplicate" for i in ram["issues"])      # no call, no "possible duplicate"
    f = L.M.VAULT / "missions/ram/wiki/entities/ripjaws-v.md"
    f.write_text(f.read_text() + "\n- 2026-11-03: a new fact [[missions/ram/log/b]]\n")                    # its writer compiled it again
    L.run(now=NOW, index=False)
    assert "--- pair 1" in L.prompts[-1][0] and "entities/ripjaws-v" in L.prompts[-1][0]


def test_what_a_pass_wrote_before_a_step_failed_is_still_in_its_commit_and_nothing_else_is(L, monkeypatch):
    L.answers["RAM upgrade"] = {"merges": [{"keep": "entities/gskill-ripjaws", "drop": "entities/ripjaws-v", "why": "same", "body": MERGED}]}

    def halfway(root, ps, keep, drop, body, today):
        L.write(keep, keep["meta"], keep["body"] + "\n- a tidied line", root)
        raise RuntimeError("halfway")
    monkeypatch.setattr(L, "merge", halfway)
    (L.M.VAULT / "missions/ram/wiki/entities/proshop.md").write_text("---\ntitle: Proshop\n---\nits writer's change, not committed yet")
    rep = L.run(now=NOW, index=False)
    ram = next(w for w in rep["wikis"] if w["root"] == "missions/ram/wiki")
    assert ram["error"] == "RuntimeError: halfway" and "failed: missions/ram/wiki" in L.git("log", "-1", "--format=%s").stdout
    assert "missions/ram/wiki/entities/gskill-ripjaws.md" in rep["files"] and "- a tidied line" in L.git("show", "HEAD:missions/ram/wiki/entities/gskill-ripjaws.md").stdout
    assert L.git("status", "--porcelain").stdout == " M missions/ram/wiki/entities/proshop.md\n"             # another writer's file stays its own


def test_a_compile_keeps_superseded_lines_and_a_contested_page_and_skips_merged_stubs(L, monkeypatch):
    import mission_extras as X
    import swarm_client as SW
    monkeypatch.setattr(SW, "wiki_helps", lambda root, title="", send=None: [])
    assert X.keep_superseded(GSKILL, "## Key facts\n- new") == "## Key facts\n- new\n\n## Superseded\n- until 2026-10-28: EUR 139.00 [[missions/ram/log/a]]\n"
    assert X.keep_superseded(GSKILL, GSKILL) == GSKILL
    page(L.M.VAULT, "missions/ram/wiki/entities/old", {"title": "Old", "merged_into": "entities/gskill-ripjaws"}, "Merged into …")
    assert "entities/old" not in [p["path"] for p in X.wiki_pages("missions/ram/wiki")]
    L.M.ask_json = lambda p, key, timeout=0: {"pages": [{"path": "entities/gskill-ripjaws", "title": "G.Skill Ripjaws V",
                                                         "body": "## Key facts\n- EUR 130 [[missions/ram/log/c]]\n\n## Contradictions\n> [!contradiction] a; b"}]}
    X.compile_wiki({"slug": "ram", "type": "task", "title": "RAM upgrade"}, "missions/ram/log/c.md", "a result", "k")
    meta, body = meta_of(L, "missions/ram/wiki/entities/gskill-ripjaws")
    assert meta["trust"] == "contested" and "- until 2026-10-28: EUR 139.00" in body
    src = str(X.WIKI)                                                              # prompts/mission.md WIKI
    assert 'move the\nold fact to a "Superseded" section' in src and 'Keep a\n"Contradictions" section as it is' in src


def test_a_compile_sees_a_long_page_whole_and_keeps_the_lines_it_was_not_shown(L, monkeypatch):
    """FND-103: the compile showed each page's first 3,000 characters with no mark and wrote the model's text over the
    whole page, so the oldest Timeline lines and the Open questions of a long page were lost at each compile. Now the
    page goes whole (marked past PAGE_SEEN), and a list line past what the model saw comes back to its own section."""
    import mission_extras as X
    import swarm_client as SW
    monkeypatch.setattr(SW, "wiki_helps", lambda root, title="", send=None: [])
    old = [f"- {dt.date(2026, 10, 30) - dt.timedelta(days=i)}: price check {i} [[missions/ram/log/a]]" for i in range(80)]   # past 3,000
    body = ("## Overview\nThe RAM upgrade.\n\n## Key facts\n- 2026-10-30: wait [[missions/ram/log/a]]\n\n## Timeline\n" + "\n".join(old)
            + "\n\n## Open questions\n- Will the November sales bring an offer under EUR 150?")
    page(L.M.VAULT, "missions/ram/wiki/projects/ram", {"title": "RAM upgrade", "last_validated": "2026-10-30"}, body)
    asked = []
    new = "## Overview\nThe RAM upgrade.\n\n## Key facts\n- 2026-11-01: still wait [[missions/ram/log/c]]\n\n## Timeline\n- 2026-11-01: price check [[missions/ram/log/c]]"
    L.M.ask_json = lambda p, key, timeout=0: asked.append(p) or {"pages": [{"path": "projects/ram", "title": "RAM upgrade", "body": new}]}
    X.compile_wiki({"slug": "ram", "type": "task", "title": "RAM upgrade"}, "missions/ram/log/c.md", "RAM upgrade: still wait", "k")
    assert len(body) > 3000 and body in asked[0] and "more characters cut" not in asked[0]   # under PAGE_SEEN the model reads all of it
    assert X.keep_unseen(body, new, X.PAGE_SEEN) == new                         # and may drop what it saw
    seen = 200                                                                  # a page longer than the window: shown in part
    out = X.keep_unseen(body, new, seen)
    kept = [ln for ln in old if body.index(ln) >= seen]
    assert kept and all(ln in out for ln in kept) and "- 2026-10-30: price check 0 " not in out   # seen and dropped stays dropped
    tl = out.split("## Timeline\n")[1].split("\n\n")[0].splitlines()
    assert tl == ["- 2026-11-01: price check [[missions/ram/log/c]]", *kept]    # back under Timeline, oldest last
    assert out.rstrip().endswith("## Open questions\n- Will the November sales bring an offer under EUR 150?")
    big = {"path": "projects/ram", "body": body}
    monkeypatch.setattr(X, "PAGE_SEEN", seen)
    monkeypatch.setattr(X, "wiki_pages", lambda root: [{**big, "title": "RAM upgrade", "summary": "", "aliases": [], "meta": {"created": "2026-10-28"}}])
    monkeypatch.setattr(X, "write_index", lambda root, title: None)
    X.compile_into("missions/ram/wiki", "RAM upgrade", "missions/ram/log/c.md", "RAM upgrade: still wait", "k")
    assert "more characters cut: the compile keeps the lines it did not see]" in asked[1]
    meta, written = meta_of(L, "missions/ram/wiki/projects/ram")
    assert all(ln in written for ln in kept) and "Will the November sales" in written
    assert meta["created"] == "2026-10-28"                                      # FND-110: a compiled page keeps the day it was made


def test_the_search_index_cleanup_is_measured_before_and_after(L, monkeypatch):
    import memory as MEM
    ran = []
    nums = iter([{"count": 500, "orphaned": 750, "orphaned_share": 0.44, "bytes": 13600000}, {"count": 500, "orphaned": 0, "orphaned_share": 0.0, "bytes": 9000000}])
    monkeypatch.setattr(MEM, "measure", lambda sid, now: next(nums))
    monkeypatch.setattr(L.subprocess, "run", lambda cmd, **k: ran.append(cmd) or types.SimpleNamespace(returncode=0, stdout=""))
    assert L.clean_index() == {"before": {"count": 500, "orphaned": 750, "orphaned_share": 0.44, "bytes": 13600000},
                               "after": {"count": 500, "orphaned": 0, "orphaned_share": 0.0, "bytes": 9000000}}
    assert ran == [["docker", "exec", "aistack-qmd-1", "qmd", "cleanup"]]
    assert L.summary({"wikis": [], "hubs": {}, "index": {"before": {"orphaned": 750}, "after": {"orphaned": 0}}}).endswith("search index: 750 → 0 orphaned chunks")


def test_the_librarian_and_the_map_share_one_rule_for_a_subject():
    import librarian
    import server as S
    assert librarian.SUBJECT_STOP == S.SUBJECT_STOP
    for t in ("Acme Mining (ACME)", "Index", "G.Skill Ripjaws V", "DDR4", "Centrus Energy (LEU)"):
        assert librarian.subject(t) == S.subject(t)


def test_a_memory_over_its_limit_for_eight_days_alerts_its_curator(monkeypatch):
    import crew
    import memory as MEM
    store = {"id": "qmd", "name": "Search index (qmd)", "curator": "memory", "limit": [0.10, "orphaned share"]}
    assert MEM.over(store, {"orphaned_share": 0.44}) and not MEM.over(store, {"orphaned_share": 0.05})
    assert not MEM.over({"id": "mission-notes", "limit": [0, "files"]}, {"count": 6})
    inv = {"stores": [{**store, "over_since": NOW - 9 * 86400, "problems": ["750 embedding chunks (44%) belong to files that are gone"]},
                      {"id": "journals", "name": "Agent journals", "curator": "memory", "over_since": NOW - 86400, "problems": ["big"]}]}
    assert [s["id"] for s, _ in MEM.alarms(inv, NOW)] == ["qmd"]                      # one day over is no alarm yet
    crew.M = types.SimpleNamespace(log=lambda *a: None)
    items = [{"kind": "crew", "id": "memory", "name": "Librarian", "issues": []}]
    crew.memory_alarms(items, inv, NOW)
    crew.memory_alarms(items, inv, NOW)
    assert items[0]["issues"] == [{"kind": "over-limit", "at": NOW - 9 * 86400,
                                   "text": "Search index (qmd) has been over its limit since 2026-10-26: 750 embedding chunks (44%) belong to files that are gone"}]
    assert "over-limit" in crew.ALERTS
    crew.M = None


def test_a_refinement_writes_the_pages_it_is_given_in_the_wiki_s_own_folders_and_leaves_the_vault_index(L, monkeypatch):
    """TSK-34: compile_into takes the pages a refinement names (in groups) and the folders that wiki has (the vault
    wiki's howto, answers ...); the vault wiki's index stays its curator's; a folder the wiki has not is refused."""
    import mission_extras as X
    import swarm_client as SW
    monkeypatch.setattr(SW, "wiki_helps", lambda root, title="", send=None: [])
    page(L.M.VAULT, "wiki/howto/flash-bios", {"title": "Flash the BIOS", "summary": "how"}, "## Steps\n- old step")
    page(L.M.VAULT, "wiki/howto/other", {"title": "Other", "summary": "x"}, "## Steps\n- other")
    (L.M.VAULT / "wiki/index.md").write_text("the curator's index")
    seen = []
    L.M.ask_json = lambda p, key, timeout=0: seen.append(p) or {"pages": [
        {"path": "howto/flash-bios", "title": "Flash the BIOS", "body": "## Steps\n- new step [[tasks/1-wiki-findings-1]]"},
        {"path": "zzz/elsewhere", "title": "No", "body": "x"}]}
    out = X.compile_into("wiki", "Vault wiki", "tasks/1-wiki-findings-1.md", "Fix the BIOS steps", "k", touched=["howto/flash-bios"])
    assert out == ["howto/flash-bios"] and "=== howto/flash-bios" in seen[0] and "=== howto/other" not in seen[0]
    meta, body = meta_of(L, "wiki/howto/flash-bios")
    assert "- new step" in body and "tasks/1-wiki-findings-1" in meta["sources"]
    assert (L.M.VAULT / "wiki/index.md").read_text() == "the curator's index"

def test_a_line_written_while_the_compile_waited_stays(L, monkeypatch):
    """Review MEM-R12: the compile wrote its snapshot back over a line an agent noted while the model worked."""
    import mission_extras as X
    import swarm_client as SW
    monkeypatch.setattr(SW, "wiki_helps", lambda root, title="", send=None: [])
    monkeypatch.setattr(X, "write_index", lambda root, title: None)
    f = L.M.VAULT / "missions/ram/wiki/projects/ram.md"

    def model(p, key, timeout=0):
        meta, body = L.M.split_front(f.read_text())
        L.M.write_front(f, meta, body.rstrip() + "\n\n## Fragile areas\n- Noted by crew:builder: the shop's API times out [[missions/ram/log/d]]\n")
        return {"pages": [{"path": "projects/ram", "title": "RAM upgrade", "body": "Upgrade with [[entities/gskill-ripjaws]] now."}]}
    L.M.ask_json = model
    X.compile_into("missions/ram/wiki", "RAM upgrade", "missions/ram/log/c.md", "RAM upgrade", "k", touched=["projects/ram"])
    text = f.read_text()
    assert "Upgrade with [[entities/gskill-ripjaws]] now." in text and "the shop's API times out" in text
    assert "and [[concepts/ddr4]]" not in text                      # what the model saw and rewrote stays rewritten

"""The memory stack (docs/MEMORY-STACK.md, MEM-22 to MEM-34, MEM-44): the catalogue, subscriptions by role, the opening chosen for
the task within a budget, access classes, what a run was given and what it used."""
import pysrc
import webjs
import json
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def MS(tmp_path, monkeypatch):
    import memstack
    import journal
    vault = tmp_path / "vault"
    fx = yaml.safe_load((ROOT / "eval/trials/memstack.yaml").read_text())
    import memtrials
    memtrials.build_fixture(fx, vault)
    monkeypatch.setattr(memstack, "VAULT", vault)
    monkeypatch.setattr(journal, "VAULT", vault)
    monkeypatch.setattr(memstack, "DIR", tmp_path / "mem")
    monkeypatch.setattr(memstack, "PUBLIC", tmp_path / "public")
    monkeypatch.setattr(memstack, "RUNTIME_DB", tmp_path / "runtime.db")
    monkeypatch.setattr(memstack, "qmd_search", memtrials.local_search(vault))
    monkeypatch.setattr(memstack, "private_roots", lambda: {"missions/mail-digest/wiki"})
    monkeypatch.setattr(journal, "hindsight", lambda path, body, timeout=30: {"results": [{"id": "f1", "text": "The owner prefers short answers."}]})
    import runtime
    monkeypatch.setattr(runtime, "emit", lambda *a, **k: None)
    return memstack


def test_budgets_come_from_one_file_and_a_trial_arm_can_override_them(MS):
    conf = yaml.safe_load((ROOT / "config/memory.yaml").read_text())
    assert set(conf["budgets"]) >= {"code", "review", "mission", "crew", "task"} and all(v >= 8000 for v in conf["budgets"].values())
    assert MS.budget_of("code") == conf["budgets"]["code"] and MS.budget_of("code", 5000) == 5000          # the arm's override wins
    rec = json.loads(json.dumps(MS.record_given(None, "a", "code", 5000, [], [], [], [], [], 0.1)))
    assert rec["budget"] == 5000                                                                              # each run records its budget


def test_every_card_resolves_to_subscriptions_by_its_roles(MS):
    reg = yaml.safe_load((ROOT / "config/agents.yaml").read_text())["agents"]
    for c in reg:
        if c.get("model") in (None, "none"):
            continue                                      # a script runs no model: it has no opening
        subs = MS.subscriptions(c["id"], f"crew:{c['id']}", repo="ai-stack", own="topics/x/wiki")
        assert subs, f"{c['id']} resolves to no subscription"
    assert MS.subscriptions("mission", "mission:ram", own="missions/ram/wiki") == [
        "agent:mission-ram", "work:ledger", "world:missions/ram/wiki", "world:*", "owner:facts", "howto:lessons/missions"]
    assert "world:{own}" not in str(MS.subscriptions("mission", "mission:ram"))                            # an unfilled placeholder drops


def test_a_coding_run_is_subscribed_to_its_repository(MS):
    assert MS.subscriptions("builder", "crew:builder", repo="click")[:2] == ["code:click", "howto:lessons/code"]
    assert "owner:facts" not in MS.subscriptions("builder", "crew:builder", repo="click")
    assert MS.subscriptions("builder", "crew:builder") == ["howto:lessons/code", "agent:crew-builder"]       # no repository: no code sector


def test_must_items_come_first_and_the_rest_fill_by_rank(MS):
    it = lambda ref, n, m, must=False, trust="compiled": MS.item("c", ref, ref, "x" * n, trust, None, m, must=must)
    items = [it("low", 300, 0.2), it("state", 200, 1.0, must=True), it("high", 300, 0.9), it("extracted", 300, 0.9, trust="extracted")]
    given, pointers = MS.fill(items, 2000)
    assert [x["ref"] for x in given] == ["state", "high", "extracted", "low"] and not pointers
    given, pointers = MS.fill(items, 950)
    assert given[0]["ref"] == "state" and given[1]["ref"] == "high" and [p["ref"] for p in pointers][-1] == "low"


def test_what_does_not_fit_is_a_pointer_not_a_silent_cut(MS):
    text = MS.opening("mission:copper-test", kind="mission", task="Kazatomprom guidance cut", subs=["agent:mission-copper-test", "world:topics/copper/wiki"],
                      budget=1400, own="topics/copper/wiki", tools=False)
    assert "### Also in memory for this task, not given" in text and "vault:topics/copper/wiki/concepts/spot-price.md" in text
    assert "1,400 characters" in text
    big = MS.opening("mission:copper-test", kind="mission", task="Kazatomprom guidance cut", subs=["world:topics/copper/wiki"], budget=1100,
                     own="topics/copper/wiki", tools=False)
    if "characters cut" in big or "more characters" in big:
        assert "the whole is vault:" in big                                                 # a cut names where the whole is


def test_the_opening_offers_matching_collections_it_did_not_give(MS):
    MS.PUBLIC.mkdir(parents=True, exist_ok=True)
    (MS.PUBLIC / "memory-catalogue.json").write_text(json.dumps({"collections": [
        {"id": "world:topics/copper/wiki", "title": "Copper", "answers": "What has the stack found out about Copper?", "size": 3, "unit": "pages"},
        {"id": "code:click", "title": "click", "answers": "How does click work?", "size": 9, "unit": "wiki pages"}]}))
    text = MS.opening("mission:ram", kind="mission", task="copper supply", subs=["agent:mission-ram"], tools=True)
    assert "### Other memory that may help (memory subscribe <id>)" in text and "world:topics/copper/wiki" in text and "code:click" not in text
    assert "Memory tools: search" in text and "Your agent id for them: mission-ram" in text


def test_access_classes_are_enforced_in_search_open_and_the_opening(MS):
    ok = MS.access_check("all", "mission:ram")
    assert not ok("agent:mission-other") and ok("agent:mission-ram") and not ok("world:missions/mail-digest/wiki") and ok("world:topics/copper/wiki")
    assert MS.access_check("all", "mission:mail-digest")("world:missions/mail-digest/wiki")          # its own mission reads it
    pub = MS.access_check("public", "scout")
    assert not pub("owner:facts") and not pub("agent:scout") and not pub("world:missions/mail-digest/wiki") and pub("code:click") and pub("howto:skills")
    assert "Not yours to read" in MS.open_ref("vault:agents/mission-other/MEMORY.md", "all", "mission:ram")
    assert "Not yours to read" in MS.open_ref("owner:0123abcd-0000", "public", "scout")
    assert "Kazatomprom" in MS.open_ref("vault:topics/copper/wiki/entities/kazatomprom.md", "public", "scout")
    text = MS.opening("mission:ram", kind="mission", task="Kazatomprom copper mail", subs=["agent:mission-other", "world:*", "world:missions/mail-digest/wiki"], tools=False)
    assert "Secret working state" not in text and "private mail" not in text and "kazatomprom.md" in text
    code = MS.opening("crew:builder", kind="code", task="copper", subs=["owner:facts", "world:*"], tools=False)
    assert "The owner prefers" not in code                                                         # a coder's opening never holds the owner's facts
    assert MS.access_check("public", "crew:builder", own=True)("agent:crew-builder")          # but its own journal, which the runner vouches for
    assert not MS.access_check("public", "crew:builder")("agent:crew-builder")                # through memorypublic the caller only says who it is


def test_a_caller_s_own_word_for_who_it_is_never_opens_private_memory(MS, monkeypatch):
    """Review MEM-R1, R2, R14 (7 Nov 2026): through memorypublic the scout said it was "memory" and read the mail wiki."""
    MS.PUBLIC.mkdir(parents=True, exist_ok=True)
    (MS.PUBLIC / "memory-catalogue.json").write_text(json.dumps({"collections": []}))
    for agent in ("memory", "crew-memory", "mission:mail-digest", "scout"):
        assert "private mail" not in MS.subscribe("world:*", agent=agent, task="Kazatomprom mail", access="public"), agent
    log = MS.VAULT / "missions/mail-digest/log/2026/11/07-result.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("the private mail result")
    ref = "vault:missions/mail-digest/log/2026/11/07-result.md"
    assert "Not yours to read" in MS.open_ref(ref, "public", "scout")            # a mission's results take its wiki's access
    assert "Not yours to read" in MS.open_ref(ref, "all", "mission:ram")
    assert "the private mail result" in MS.open_ref(ref, "all", "mission:mail-digest")
    (MS.VAULT / "notes.md").write_text("loose note")
    assert "Not yours to read" in MS.open_ref("vault:notes.md", "public", "scout")   # outside every sector: the all class only
    assert "missions/any/wiki" in MS._AllPrivate() and "wiki" not in MS._AllPrivate()
    monkeypatch.setattr(MS, "private_roots", lambda: MS._AllPrivate())            # the private list could not be read
    assert not MS.access_check("public", "scout")("world:topics/copper/wiki")    # fails closed


def test_an_untrusted_item_is_marked_in_the_opening(MS):
    p = MS.VAULT / "topics/copper/wiki/entities/kazatomprom.md"
    p.write_text(p.read_text().replace("title: Kazatomprom", "title: Kazatomprom\nuntrusted: true"))
    text = MS.opening("mission:copper-test", kind="mission", task="Kazatomprom guidance", subs=["world:topics/copper/wiki"], tools=False)
    assert "#### Kazatomprom [UNTRUSTED: from the web or mail]" in text
    p.write_text(p.read_text().replace("untrusted: true", "trust: untrusted-source"))      # the vault's own mark (61 pages live)
    text = MS.opening("mission:copper-test", kind="mission", task="Kazatomprom guidance", subs=["world:topics/copper/wiki"], tools=False)
    assert "#### Kazatomprom [UNTRUSTED: from the web or mail]" in text
    import datetime as dt
    assert MS.age_days(dt.date.today()) < 1.1 and MS.age_days(dt.date(2000, 1, 1)) > 9000   # a bare YAML date ages too


def test_an_unreachable_store_is_named_and_the_run_goes_on(MS, monkeypatch):
    def down(*a, **k):
        raise RuntimeError("qmd is not running")
    monkeypatch.setattr(MS, "qmd_search", down)
    text = MS.opening("mission:copper-test", kind="mission", task="Kazatomprom", subs=["agent:mission-copper-test", "world:topics/copper/wiki"], tools=False)
    assert "### Could not be read this time" in text and "world:topics/copper/wiki (RuntimeError: qmd is not running)" in text
    assert "Working state" in text                                                            # the rest is still given


def test_an_opening_records_what_it_gave(MS):
    MS.opening("mission:copper-test", kind="mission", task="Kazatomprom guidance", subs=["agent:mission-copper-test", "world:topics/copper/wiki"],
               run="mission-run:7", own="topics/copper/wiki", tools=False)
    rec = MS.given_of("mission-run:7")[0]
    assert rec["kind"] == "mission" and rec["budget"] == MS.budget_of("mission") and rec["chars"] > 0
    assert {x["coll"] for x in rec["items"]} == {"agent:mission-copper-test", "world:topics/copper/wiki"}
    assert any("entities/kazatomprom" in k for x in rec["items"] for k in x["keys"])


def test_used_items_are_found_in_the_run_s_later_events(MS, monkeypatch):
    MS.opening("mission:copper-test", kind="mission", task="Kazatomprom guidance", subs=["world:topics/copper/wiki"], run="mission-run:8",
               own="topics/copper/wiki", tools=False)
    monkeypatch.setattr(MS, "run_events", lambda run, since=0: "read_file topics/copper/wiki/entities/kazatomprom.md and wrote the report")
    out = MS.after_run("mission-run:8", "done")
    used = {x["ref"]: x["used"] for x in out["items"]}
    assert used["vault:topics/copper/wiki/entities/kazatomprom.md"] is True and out["used_chars"] > 0 and out["outcome"] == "done"
    assert any(not v for v in used.values())                                                 # the other pages it did not use
    assert MS.runs_log(30)[-1]["run"] == "mission-run:8"
    src = (ROOT / "ops/runtime.py").read_text()
    assert "threading.Thread(target=measure, daemon=False)" in src                              # a crew job's process waits for its measurement


def test_an_entry_without_a_path_counts_as_used_when_the_run_says_what_only_it_held(MS, monkeypatch):
    """Commissioning, 8 Nov 2026: the Centrus proof mission resolved its last run's open question, yet its journal entries
    counted as unmeasurable: memory without a file path could never count as used."""
    import journal as J
    J.record("mission:centrus", "Centrus", None, "done", "Sept. 17 Antares multi-year HALEU contract; Westerman acquisition completed")
    J.record("mission:centrus", "Centrus", None, "done", "Centrus reported >1,900 kg HALEU produced, restart unconfirmed")
    MS.opening("mission:centrus", kind="mission", task="Memory proof: Centrus LEU enrichment", run="mission-run:9", tools=False)
    monkeypatch.setattr(MS, "run_events", lambda run, since=0: "the prompt with the whole opening: antares westerman 1,900 haleu")
    monkeypatch.setattr(MS, "run_output", lambda run, since=0: "answer: after the antares contract and the westerman deal, haleu output resumed")
    out = MS.after_run("mission-run:9", "done")
    entries = [x for x in out["items"] if "#" in x["ref"]]       # a mission's entries are all given, whatever words they share
    assert len(entries) == 2 and all(x["measurable"] for x in entries)
    assert [x["used"] for x in entries].count(True) == 1               # the Antares entry; the 1,900 one shares only HALEU
    assert MS.marks_of("Found: >1,900 kg on Oct. 16 at Piketon", "") == ["1,900", "piketon"]


def test_a_coding_step_s_use_is_read_from_the_engine_runs_inside_its_builds(MS):
    """Commissioning, 8 Nov 2026: the measurement read the step's build runs, not the Claude Code runs inside them that do
    the reading and editing (their ref is the build), so coding steps measured 0 % used; the whole chain read 85 %."""
    import sqlite3
    c = sqlite3.connect(MS.RUNTIME_DB)
    c.execute("create table if not exists runs (run text primary key, ref text)")
    c.execute("create table if not exists events (run text, ts real, kind text, title text, detail text)")
    c.executemany("insert into runs values (?, ?)", [("task:5:step:4", None), ("build:9:0:queued", "task:5:step:4"),
                                                    ("claude:builder:abc", "build:9:0:queued")])
    c.execute("insert into events values ('claude:builder:abc', ?, 'call', 'Bash', 'sed -n 1,80p src/click/_utils.py')", (time.time() + 5,))
    c.commit()
    assert MS.family(c, "task:5:step:4") == ["task:5:step:4", "build:9:0:queued", "claude:builder:abc"]
    assert "src/click/_utils.py" in MS.run_events("task:5:step:4", 0) and "src/click/_utils.py" in MS.run_output("task:5:step:4", 0)


def test_health_shows_given_and_used_per_run_kind(MS):
    MS.DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    rows = [{"run": "a", "kind": "code", "at": now, "chars": 10000, "measurable_chars": 8000, "used_chars": 2000, "outcome": "done", "items": []},
            {"run": "b", "kind": "code", "at": now, "chars": 6000, "measurable_chars": 2000, "used_chars": 1000, "outcome": "failed", "items": []},
            {"run": "c", "kind": "mission", "at": now - 40 * 86400, "chars": 1, "measurable_chars": 1, "used_chars": 1, "outcome": "done", "items": []}]
    (MS.DIR / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    h = MS.health(30, now)
    assert h == {"code": {"runs": 2, "given_per_run": 8000, "used_share": 0.3, "done_share": 0.5, "budget": MS.budget_of("code")}}
    app = webjs.app_js()
    assert "function memStatusHtml(st)" in app and "${memStatusHtml(st)}" in app and "of it used" in app   # Memory's first page (DEC-53: no longer twice, on Stack too)


def test_the_catalogue_lists_every_collection_with_its_card(MS, monkeypatch):
    import memory as MEMI
    monkeypatch.setattr(MEMI, "last", lambda: {"stores": [{"id": "hindsight", "count": 39}, {"id": "skills", "count": 63}]})
    cat = MS.catalogue()
    ids = {c["id"] for c in cat["collections"]}
    assert {"owner:facts", "owner:profile", "world:topics/copper/wiki", "world:missions/mail-digest/wiki", "world:sources", "howto:skills",
            "agent:mission-copper-test", "work:ledger"} <= ids
    for c in cat["collections"]:
        assert {"id", "sector", "title", "answers", "trust", "access", "writer", "methods"} <= set(c), c["id"]
        assert c["trust"] in ("exact", "compiled", "extracted") and c["access"] in MS.ACCESS
    by = {c["id"]: c for c in cat["collections"]}
    assert by["world:missions/mail-digest/wiki"]["access"] == "private" and by["owner:facts"]["access"] == "owner" and by["owner:facts"]["size"] == 39
    assert by["agent:mission-other"]["access"] == "own"


def test_a_split_wiki_s_parts_are_collections_with_their_parent(MS, monkeypatch):
    import memory as MEMI
    monkeypatch.setattr(MEMI, "last", lambda: {"stores": []})
    d = MS.VAULT / "topics/copper/wiki/parts"
    d.mkdir(parents=True)
    (d / "companies.md").write_text("---\ntitle: Companies\nsummary: 1 page\npages: [entities/kazatomprom]\n---\nbody")
    by = {c["id"]: c for c in MS.catalogue()["collections"]}
    assert by["world:topics/copper/wiki#companies"]["parent"] == "world:topics/copper/wiki"
    text = MS.opening("mission:copper-test", kind="mission", task="spot price", subs=["world:topics/copper/wiki"], own="topics/copper/wiki", tools=False)
    assert "Its parts" in text and "world:topics/copper/wiki#companies" in text                # the hub of parts, then matching pages
    part = MS.opening("mission:copper-test", kind="mission", task="Kazatomprom", subs=["world:topics/copper/wiki#companies"], tools=False)
    assert "kazatomprom.md" in part and "spot-price.md" not in part


def test_a_coding_opening_is_built_from_its_task_not_the_whole_wiki(MS, monkeypatch):
    import repofacts as RF
    seen = {}

    def brief(name, request, files=None, budget=0, code=None, at=None):
        seen.update(name=name, request=request, files=files, code=code, at=at)
        return ("## What the stack knows for this task\nMeasured from git.\n\n### Files: the files the specification names\n- ops/x.py: changed in 4 of 9 commits\n\n"
                "### Commands that work\nAll tests: pytest\n\n### What failed here before, on these files\n- build #3 failed: x\n")
    monkeypatch.setattr(RF, "brief", brief)
    text = MS.opening("crew:builder", kind="code", task="Fix the parser in ops/x.py", card="builder", files=["ops/x.py"], repo="trial-click", wiki_of="click",
                      at="abc123", tools=False)
    assert seen == {"name": "click", "request": "Fix the parser in ops/x.py", "files": ["ops/x.py"], "code": "trial-click", "at": "abc123"}
    assert "Commands that work" in text and "ops/x.py: changed in 4 of 9 commits" in text and "build #3 failed" in text
    changes = (ROOT / "ops/changes.py").read_text()
    assert 'arm in ("stack", "stack+notes", "knowledge")' in changes and "MS.opening(f\"crew:{role}\"" in changes            # a change's steps use it


def test_a_step_s_opening_is_built_from_its_inputs(MS, monkeypatch):
    import changes as CH
    got = {}
    monkeypatch.setattr(MS, "opening", lambda agent, **k: got.update(agent=agent, **k) or "MEMORY")
    out = CH.memory_of({"files": ["a.py"], "wiki_of": "click"}, "trial-click", "tester", request="Make the help names unique.\n- C1: names shall be unique",
                       files=["tests/test_help.py"], run="task:9:step:3")
    assert out == "MEMORY" and got["agent"] == "crew:tester" and got["files"] == ["tests/test_help.py"] and got["run"] == "task:9:step:3"
    assert "C1: names shall be unique" in got["task"] and got["kind"] == "code"
    assert CH.memory_of({"no_wiki": True}, "r", "builder") == "" or "MEMORY" not in CH.memory_of({"no_wiki": True}, "r", "builder")   # the "swarm" arm: no memory


def test_the_build_prepares_notes_for_its_repository(MS, monkeypatch, tmp_path):
    import builds as B
    calls = []
    monkeypatch.setattr(MS, "write_notes", lambda name, dest, code=None, files=None: calls.append((name, dest.name, code)) or 3)
    assert hasattr(B.NOTES_DIR, "joinpath") and isinstance(B.NOTES, tuple)   # two names: the folder was once shadowed by the tuple
    monkeypatch.setattr(B, "NOTES_DIR", tmp_path / "notes")
    b = {"id": 41, "source": "", "task": None}
    assert B.memory_notes(b, "click", None).name == "build-41.json" and calls[-1] == ("click", "build-41.json", "click")
    monkeypatch.setattr(MS, "write_notes", lambda *a, **k: 0)
    assert B.memory_notes(b, "click", None) is None                                           # none could be made: no hook file
    src = pysrc.builds()
    assert 'AISTACK_MEMNOTES=/work/.memory/{notes.name}' in src and '"memory": {"type": "http"' in src and "graphify" not in src.split("SERENA_FOR_CLAUDE")[1][:400]


def test_a_generic_task_step_gets_its_memory_from_its_inputs(MS, monkeypatch):
    import conductor as CD
    got = {}
    monkeypatch.setattr(MS, "opening", lambda agent, **k: got.update(agent=agent, **k) or "## Memory for this run\nA kept fact.")
    t = {"id": 12, "goal": "Compare two RAM kits", "done": ["a verdict"], "spec": {"repo": None}}
    prev = {"idx": 1, "title": "Find kits", "agent": "scout", "output": "G.Skill Aegis 32 GB at 89 EUR", "after": []}
    s = {"idx": 2, "title": "Pick one", "agent": "analyst", "after": [1], "harness": "claude-code", "occ": 1}
    p = str(CD.prompt_of(t, s, [prev, s], {}))
    assert p.endswith("## Memory for this run\nA kept fact.") and got["agent"] == "crew:analyst" and got["run"] == "task:12:step:2"
    assert "G.Skill Aegis" in got["task"] and "Pick one" in got["task"] and got["kind"] == "task"
    assert "A kept fact." not in str(CD.prompt_of(t, s, [prev, s], {}, memory=False))
    src = (ROOT / "ops/changes.py").read_text()
    assert 'wiki=memory_of(ch, repo, "intake", request=t["text"], run=run)' in src            # the change's intake too (MEM-31)


def test_a_card_that_holds_memorypublic_never_gets_the_owner_s_facts(MS):
    text = MS.opening("crew:scout", kind="task", task="copper Kazatomprom", card="scout", subs=["owner:facts", "world:*"], tools=False)
    assert "The owner prefers" not in text and "kazatomprom.md" in text                         # MEM-30: the card's grant decides
    mission = MS.opening("mission:copper-test", kind="mission", task="copper", card="mission", subs=["owner:facts"], tools=False)
    assert "The owner prefers short answers." in mission


def test_a_coding_run_reads_its_repository_whatever_its_card_s_roles(MS, monkeypatch):
    got = []
    monkeypatch.setattr(MS, "items_for", lambda s, ctx: got.append(s) or [])
    MS.opening("crew:intake", kind="review", task="Fix the help names", card="intake", repo="click", tools=False)
    assert got[0] == "code:click" and "owner:facts" not in got                  # a missions-role card still gets click, never the owner's facts


def test_a_run_that_ends_twice_is_measured_once_per_opening(MS, monkeypatch):
    monkeypatch.setattr(MS, "run_events", lambda run, since=0: "kazatomprom.md")
    MS.opening("crew:builder", kind="mission", task="Kazatomprom guidance", subs=["world:topics/copper/wiki"], run="task:9:step:4", tools=False)
    first = MS.after_run("task:9:step:4", "done")
    assert MS.after_run("task:9:step:4", "done") is None                     # nothing new: not counted again
    MS.opening("crew:builder", kind="mission", task="Kazatomprom guidance", subs=["world:topics/copper/wiki"], run="task:9:step:4", tools=False)
    second = MS.after_run("task:9:step:4", "done")                            # the fix round's own opening only
    assert second["chars"] == first["chars"] and len(MS.runs_log(30)) == 2

def test_a_scope_word_means_its_collections_and_a_subscription_counts_for_the_run(MS, monkeypatch):
    """Review MEM-R16: scope "agents" never matched agent:<id>, a lesson scope returned every role's, and a subscription was
    recorded for no run."""
    assert MS.scope_of("agents") == "agent" and MS.scope_of("lessons") == "howto:lessons" and MS.scope_of("world:*") == "world"
    assert MS.in_scope("agent:mission-ram", "agent") and not MS.in_scope("agents-x:y", "agent")
    assert MS.in_scope("howto:lessons/coder", "howto:lessons/coder") and not MS.in_scope("howto:lessons/tester", "howto:lessons/coder")
    assert MS.in_scope("world:topics/copper/wiki", "world") and MS.in_scope("anything", "")
    seen = []
    monkeypatch.setattr(MS, "current_run", lambda agent: "task:3:step:1")
    monkeypatch.setattr(MS, "subscribe", lambda coll, agent="", task="", access="all", run=None, **k: seen.append(run) or "ok")
    MS.handle({"action": "mem_subscribe", "collection": "world:topics/copper/wiki", "agent": "mission:ram", "access": "all"})
    assert seen == ["task:3:step:1"]


def test_a_shared_role_s_entries_about_other_tasks_are_named_not_given(MS):
    """Commissioning, 8 Nov 2026: the exam's tester was given 16 journal entries about other repositories and used none."""
    import journal as J
    for i in range(6):
        J.record("crew:tester", "Tester", None, "done", f"wrote failing tests for the help option names of click, round {i}")
    J.record("crew:tester", "Tester", None, "done", "wrote failing tests for Sentinel copy and pickle identity")
    items = MS.items_agent("agent:crew-tester", MS.words("Preserve Sentinel member identity through copy and pickle"))
    given, named = MS.fill(items, 20000)
    assert [x for x in given if "Sentinel" in x["text"]] and not [x for x in given if "help option" in x["text"]]
    assert len(named) == 6
    every = MS.items_agent("agent:crew-tester", set())                # no task words: every entry is given
    assert len(MS.fill(every, 20000)[0]) == 7
    for i in range(3):                                                 # a mission's last runs, in words its title does not use
        J.record("mission:cars", "Cars", None, "done", f"BYD and XPeng export figures for October, round {i}")
    mine = MS.items_agent("agent:mission-cars", MS.words("Weekly Chinese Automotive News Email"))
    by_age = MS.items_agent("agent:mission-cars", set())
    assert [x["match"] for x in mine] == [x["match"] for x in by_age] and not any(x["named_only"] for x in mine)   # by age alone

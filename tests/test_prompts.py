"""Agent prompts as files (MEM-11): no prompt is left as a constant in ops/ or a configure script, each loads from
prompts/<owner>.md with its version, every send records it, live calls keep replay cases, and the build gate refuses
a changed prompt without a passed replay (old and new text on the same cases, judged pairwise)."""
import ast
import json
import os
import re
import subprocess
import types
from pathlib import Path

import pytest

import prompts as P

ROOT = Path(__file__).resolve().parent.parent
EXEMPT = {"token_probe.py": "a one-off probe of the prompt cache, not an agent"}


def literal_prompts(path):
    """String literals in a Python file that read like an agent prompt."""
    out = []
    for n in ast.walk(ast.parse(path.read_text())):
        s = n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else \
            "".join(v.value for v in n.values if isinstance(v, ast.Constant)) if isinstance(n, ast.JoinedStr) else None
        if s and len(s) >= 120 and (re.match(r"\s*You (are|review|maintain|plan|write|keep|file|explain|complete|finish|set up|triage|watch)\b", s)
                                     or "Answer only JSON" in s):
            out.append(f"{path.name}:{n.lineno}")
    return out


def test_no_agent_prompt_is_left_in_ops_or_a_configure_script():
    found = [x for f in sorted((ROOT / "ops").glob("*.py")) if f.name not in EXEMPT for x in literal_prompts(f)]
    assert found == []
    assert literal_prompts(ROOT / "images/desk/desk.py") == [] and literal_prompts(ROOT / "images/research/server.py") == []   # MEM-13
    for f in sorted((ROOT / "config/hermes").glob("*.sh")) + sorted((ROOT / "ops").glob("*.sh")):
        t = f.read_text()
        assert "<<'SOUL'" not in t and not re.search(r'-z \\?\n?"You ', t), f.name               # SOUL texts and -z prompts come from prompts/
    assert 'render curator LINT' in (ROOT / "ops/vault-lint.sh").read_text() and 'render curator INGEST' in (ROOT / "ops/vault-ingest.sh").read_text()


def test_every_prompt_loads_from_its_file_with_its_version_and_keeps_it_through_format():
    import crew
    import mission_extras as X
    p = crew.MEMORY_PROMPT
    assert isinstance(p, P.Prompt) and p.ref == f"memory/FACTS@{P.sha(P.sections('memory')['FACTS'])}"
    f = p.format(facts="a | world | b")
    assert f.ref == p.ref and f.fills == {"facts": "a | world | b"} and "a | world | b" in f
    assert str(X.WIKI) == P.sections("mission")["WIKI"] and P.version("mission") == P.sha((ROOT / "prompts/mission.md").read_text())
    assert P.check() == [] and len(P.load_replays()) == sum(len(P.sections(o)) for o in P.owners()) >= 38
    assert P.raw("maintainability", "REVIEW") and not P.raw("memory", "FACTS")
    missions = (ROOT / "ops/missions.py").read_text()
    assert missions.count("P.record(src)") == 2 and missions.count("P.case(src, ") == 2                # ask_text and hermes_z
    assert '"prompts": P.version(name)' in (ROOT / "ops/crew.py").read_text() and '"prompts": P.version("mission")' in missions


def test_a_send_records_the_ref_and_a_live_call_keeps_its_case(tmp_path, monkeypatch):
    import runtime as RTM
    seen = []
    monkeypatch.setattr(RTM, "stage", lambda title, detail="", **k: seen.append((title, detail)))
    p = P.text("inbox", "PICK").format(n=3, topics="uranium", rows="- 1 · a · b")
    assert P.record(p) == p.ref and seen == [("Prompt", p.ref)]
    monkeypatch.setattr(P, "CASES", tmp_path / "cases")
    for i in range(P.KEEP + 3):
        P.case(p, f'{{"file": [{i}]}}')
    rows = [json.loads(x) for x in (tmp_path / "cases/inbox.PICK.jsonl").read_text().splitlines()]
    assert len(rows) == P.KEEP and rows[-1]["out"] == f'{{"file": [{P.KEEP + 2}]}}' and rows[0]["fills"]["topics"] == "uranium"
    assert oct(os.stat(tmp_path / "cases/inbox.PICK.jsonl").st_mode)[-3:] == "600"                    # owner-only: fills hold private data
    P.case("a plain string", "x")                                                                    # no ref, no case
    assert len(list((tmp_path / "cases").iterdir())) == 1


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "prompts").mkdir(parents=True)
    (root / "prompts/eval.md").write_text((ROOT / "prompts/eval.md").read_text())
    (root / "prompts/inbox.md").write_text('<!-- prompt: PICK · fills: rows -->\nPick from {rows}. Answer only JSON: {{"file": []}}\n<!-- end -->\n')
    git = lambda *a: subprocess.run(["git", *a], cwd=root, check=True, capture_output=True, text=True)   # noqa: E731
    git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    rec = {k: [{"sha": P.sha(t), "baseline": "seed", "at": "2026-10-30"}] for o in ("eval", "inbox")
           for k, t in ((f"{o}/{n}", t) for n, t in P.parse((root / f"prompts/{o}.md").read_text()).items())}
    (root / "prompts/replays.json").write_text(json.dumps(rec))
    git("add", "-A"); git("commit", "-qm", "seed")
    for k, v in {"ROOT": root, "DIR": root / "prompts", "REPLAYS": root / "prompts/replays.json", "FIXTURES": root / "prompts/cases",
                 "CASES": tmp_path / "cases"}.items():
        monkeypatch.setattr(P, k, v)
    P._cache.clear()
    return root


def test_the_build_gate_refuses_a_changed_prompt_until_its_replay_passed(repo, monkeypatch):
    assert P.check(repo) == []
    f = repo / "prompts/inbox.md"
    f.write_text(f.read_text().replace("Pick from", "Pick the best from"))
    bad = P.check(repo)
    assert len(bad) == 1 and bad[0].startswith("inbox/PICK: its text (") and "python3 ops/prompts.py replay inbox PICK" in bad[0]
    rec = json.loads((repo / "prompts/replays.json").read_text())
    rec["inbox/PICK"].append({"sha": P.sha(P.parse(f.read_text())["PICK"]), "baseline": "sneaked in"})
    (repo / "prompts/replays.json").write_text(json.dumps(rec))
    assert len(P.check(repo)) == 1                                                  # a baseline counts only as the first record
    with pytest.raises(SystemExit, match="no cases to replay, it needs 3"):
        P.replay("inbox", "PICK", ask=lambda t: "", judge_ask=lambda t: "")
    (repo / "prompts/cases").mkdir()
    (repo / "prompts/cases/inbox.PICK.json").write_text(json.dumps([{"fills": {"rows": "- 0"}, "out": "{}"}]))
    with pytest.raises(SystemExit, match="1 case to replay, it needs 3"):                       # one judgement would decide alone
        P.replay("inbox", "PICK", ask=lambda t: "", judge_ask=lambda t: "")
    (repo / "prompts/cases/inbox.PICK.json").write_text(json.dumps([{"fills": {"rows": f"- {i} · news"}, "out": "{}"} for i in range(3)]))
    asked = []

    def ask(t):
        asked.append(t)
        return '{"file": [1]}' if "best" in t else "I can't do that"
    r = P.replay("inbox", "PICK", ask=ask, judge_ask=lambda t: '{"better": "equal"}')
    assert r["passed"] and r["valid"] == [0, 3] and r["cases"] == 3 and len(asked) == 6 and r["from"] != r["sha"]
    assert any("Pick from - 0 · news" in t for t in asked) and any("Pick the best from - 0 · news" in t for t in asked)   # the approved text from git
    assert P.check(repo) == []                                                      # recorded: the gate lets it through


def test_a_replay_the_judge_prefers_the_old_text_on_fails_and_the_gate_stays_shut(repo):
    f = repo / "prompts/inbox.md"
    f.write_text(f.read_text().replace("Pick from", "Pick anything from"))
    (repo / "prompts/cases").mkdir()
    (repo / "prompts/cases/inbox.PICK.json").write_text(json.dumps([{"fills": {"rows": f"- {i}"}, "out": "{}"} for i in (1, 2, 3)]))
    judged = []

    def judge(t):
        judged.append(t)
        new_is_a = "Answer A:\nnew" in t
        return json.dumps({"better": "B" if new_is_a else "A"})                     # always the old answer
    r = P.replay("inbox", "PICK", ask=lambda t: "new" if "anything" in t else "old", judge_ask=judge)
    assert not r["passed"] and r["judge"] == {"new": 0, "old": 3, "equal": 0} and "Pick anything from - 1" in judged[0]
    assert len(P.check(repo)) == 1
    with pytest.raises(SystemExit, match="needs fills the cases lack: topics"):
        f.write_text(f.read_text().replace("{rows}", "{rows} on {topics}"))
        P._cache.clear()
        P.replay("inbox", "PICK", ask=lambda t: "", judge_ask=lambda t: "")


def test_an_agent_s_standing_brief_is_replayed_on_the_requests_its_cases_bring(repo):
    """A raw brief (the scout's system message) is nothing to answer alone: each case brings a request, and the dry run
    asks for the tool calls the agent would make, so the judge sees whether the brief changes them (FND-80)."""
    f = repo / "prompts/scout.md"
    f.write_text("<!-- prompt: BRIEF · raw: sent as written, never filled -->\nSearch the web.\n<!-- end -->\n")
    rec = json.loads((repo / "prompts/replays.json").read_text())
    rec["scout/BRIEF"] = [{"sha": P.sha("Search the web."), "baseline": "seed", "at": "2026-10-30"}]
    (repo / "prompts/replays.json").write_text(json.dumps(rec))
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True); subprocess.run(["git", "commit", "-qm", "brief"], cwd=repo, check=True)
    f.write_text(f.read_text().replace("Search the web.", "For jobs in Germany use jobs_search first. Search the web."))
    P._cache.clear()
    (repo / "prompts/cases").mkdir()
    (repo / "prompts/cases/scout.BRIEF.json").write_text(json.dumps([{"fills": {}, "user": f"AUTOSAR jobs near Heilbronn {i}"} for i in range(3)]))
    asked = []
    r = P.replay("scout", "BRIEF", ask=lambda t: asked.append(t) or ("jobs_search(...)" if "jobs_search first" in t else "web_search(...)"),
                 judge_ask=lambda t: '{"better": "equal"}')
    assert r["passed"] and r["valid"] == [3, 3] and len(asked) == 6
    assert all("AUTOSAR jobs near Heilbronn" in t and "the tool calls you would make" in t and "do not apologise" in t for t in asked)
    assert P.task_of("inbox", "PICK", "Pick from {rows}.", {"fills": {"rows": "- 1"}, "user": "ignored"}) == "Pick from - 1."


def test_the_desk_and_the_scout_read_their_prompts_from_the_mount_and_the_desk_hands_back_its_cases(desk, tmp_path, monkeypatch):
    for f in ("images/desk/desk.py", "images/research/server.py"):                  # one section format for every loader
        assert f"SECTION = re.compile(r\"{P.SECTION.pattern}\", re.M | re.S)" in (ROOT / f).read_text(), f
    monkeypatch.setattr(desk, "PROMPTS", ROOT / "prompts")
    text, ref, fills = desk.prompt("ALERT", topic="Uranium", mission="m", questions="[]", kind="sec", summary="8-K", items="ITEM: x")
    assert ref == f"desk/ALERT@{P.sha(P.sections('desk')['ALERT'])}" and text.startswith("You watch a topic for a research desk. Topic: Uranium.")
    assert "GERMAN_STYLE" not in P.sections("desk")                                  # every briefing is English (FND-21)
    answers = iter(['{"picks": [{"n": 0, "score": 2}]}'])
    resp = lambda *a, **k: types.SimpleNamespace(read=lambda: json.dumps({"choices": [{"message": {"content": next(answers)}}]}).encode(),  # noqa: E731
                                                  __enter__=None)
    monkeypatch.setattr(desk.json, "load", lambda r: json.loads(r.read()))
    monkeypatch.setattr(desk.urllib.request, "urlopen", resp)
    monkeypatch.setenv("VK_DESK", "vk-test")
    monkeypatch.setattr(desk, "CASE_FILE", tmp_path / "prompt-cases.jsonl")
    logged = []
    monkeypatch.setattr(desk, "log", lambda *a: logged.append(" ".join(map(str, a))))
    t, r, f = desk.prompt("TRIAGE", topic="U", mission="m", questions="Q1. q", prefer="a", avoid="b", items="[0] x")
    assert desk.ask(t, "gpt-sub-fast", ref=r, fills=f) == {"picks": [{"n": 0, "score": 2}]}
    assert logged == [f"prompt {r}"]                                                 # the run's log names the version
    row = json.loads((tmp_path / "prompt-cases.jsonl").read_text())
    assert row["ref"] == r and row["model"] == "gpt-sub-fast" and row["fills"]["items"] == "[0] x"
    monkeypatch.setattr(P, "CASES", tmp_path / "cases")
    assert P.main(["prompts.py", "keep", str(tmp_path / "prompt-cases.jsonl")]) == 0
    assert P.main(["prompts.py", "keep", str(tmp_path / "prompt-cases.jsonl")]) == 0                # kept once, however often
    kept = (tmp_path / "cases/desk.TRIAGE.jsonl").read_text().splitlines()
    assert len(kept) == 1 and json.loads(kept[0])["model"] == "gpt-sub-fast"
    sh, alert = (ROOT / "ops/desk.sh").read_text(), (ROOT / "ops/mission_extras.py").read_text()
    assert '-v "$PROMPTS":/prompts:ro' in sh and 'prompts.py" keep "$S/out/prompt-cases.jsonl"' in sh
    assert "/prompts:ro\", \"aistack/desk:1\", \"--alert\"" in alert and 'M.RTM.stage("Prompt", a["prompt"])' in alert and "P.add_case(**a[\"case\"])" in alert
    assert "- ../prompts:/prompts:ro" in (ROOT / "compose/apps.yaml").read_text()
    research = (ROOT / "images/research/server.py").read_text()
    assert 'prompt("guard", "PRIVATE")' in research and "unreadable: refused below (fail closed)" in research
    assert "the scout's brief (prompts/scout.md) could not be read" in research                     # no brief, no research


def test_the_deploy_hands_each_configure_script_its_soul_text_from_the_prompts_file():
    import deploy as D
    assert D.configure_scripts(["prompts/mission.md"]) == ["config/hermes/configure-mission.sh"]
    assert D.configure_scripts(["prompts/main.md", "config/hermes/configure-scout.sh"]) == ["config/hermes/configure.sh", "config/hermes/configure-scout.sh"]
    assert D.configure_scripts(["prompts/memory.md"]) == []
    args, env = D.soul("config/hermes/configure.sh")
    rules = ("WEB", "MISSIONS", "SHOPPING", "LANGUAGE", "PHONE", "CLAUDE")
    assert args == [a for r in rules for a in ("-e", f"SOUL_{r}")] and all(env[f"SOUL_{r}"] == P.sections("main")[f"{r}_RULE"] for r in rules)
    assert env["SOUL_WEB"].startswith("## Web research\nYou have no web tools yourself.") and env["SOUL_LANGUAGE"].startswith("## Language\n")
    assert D.soul("config/hermes/configure-scout.sh") == ([], {})
    for s in ("configure-mission.sh", "configure-builder.sh"):
        t = (ROOT / "config/hermes" / s).read_text()
        assert 'if [ -n "${SOUL_TEXT:-}" ]' in t and "kept: no" in t                     # run by hand without it, the SOUL stays as it is
    t = (ROOT / "config/hermes/configure.sh").read_text()
    assert "for r in web missions shopping language phone claude; do" in t and 'printenv "SOUL_' in t and "rule kept: no SOUL_" in t
    assert "cat -s /opt/data/SOUL.md" in t                                          # no blank lines piling up with every run


def test_a_filled_prompt_that_drives_tools_is_replayed_as_a_dry_run():
    """main/VOICE starts missions: replayed without tools it could only say it cannot act (counted as no answer); its
    cases say dry_run, so both texts are asked for the tool calls they would make."""
    import prompts as P
    out = P.task_of("main", "X", "Spoken in the {room}: {question}", {"fills": {"room": "office", "question": "research X"}, "dry_run": True})
    assert out.startswith("Spoken in the office: research X") and P.DRY_RUN in out
    assert all(c.get("dry_run") for c in json.loads((ROOT / "prompts/cases/main.VOICE.json").read_text()))


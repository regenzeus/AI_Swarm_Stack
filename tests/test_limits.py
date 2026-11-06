"""ops/limits.py (QA-22): no rule that stops, refuses, drops or delays work stays secret; and the ones FND-123 found."""
from pathlib import Path

import pytest

import limits as L
import truncation as T

ROOT = Path(__file__).resolve().parent.parent


def tree(tmp_path, name, text):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    return tmp_path


def test_the_limit_that_refused_the_owner_s_repository_would_fail_the_check_today(tmp_path):
    root = tree(tmp_path, "ops/understand.sh", 'CODE=/home/owner/code; MAX_FILES=${MAX_FILES:-150}\n'
                                                'n=177\nif [ "$n" -gt "$MAX_FILES" ]; then\n  echo refused >&2; exit 3\nfi\n')
    (root / "docs").mkdir()
    bad = "\n".join(L.problems(root))
    assert 'ops/understand.sh:3: [ "$n" -gt "$MAX_FILES" ]' in bad


def test_a_limit_needs_what_it_does_and_why(tmp_path):
    root = tree(tmp_path, "ops/a.py", "MAX_THINGS = 5\n# limit: refuses\nMAX_MORE = 6\nTIMEOUT = 60  # limit: sometimes, because\n"
                                      "# limit: stops, a run that hangs past this fails\nSTEP_TIMEOUT = 40 * 60\n"
                                      "def f(x):\n    if len(x) > 20:\n        raise ValueError('no')\n")
    (root / "docs").mkdir()
    bad = "\n".join(L.problems(root))
    assert "ops/a.py:1: MAX_THINGS" in bad and "ops/a.py:3: MAX_MORE" in bad and "ops/a.py:4: TIMEOUT" in bad and "ops/a.py:8:" in bad
    assert "ops/a.py:6" not in bad


def test_the_list_of_limits_stays_current(tmp_path):
    root = tree(tmp_path, "ops/a.py", "# limit: waits, the memory of the PC\nMAX_THINGS = 5\n")
    (root / "docs").mkdir()
    assert any("out of date" in p for p in L.problems(root))
    (root / L.DOC).write_text(L.render(root))
    assert L.problems(root) == [] and "`MAX_THINGS`" in L.render(root) and "the memory of the PC" in L.render(root)


def test_every_limit_in_the_repository_says_what_it_does_and_why():
    assert L.problems() == []
    assert (ROOT / L.DOC).exists() and "## refuses" in (ROOT / L.DOC).read_text()


def test_nothing_is_left_of_the_size_limit_on_repositories():
    code = "\n".join(p.read_text(errors="replace") for d in ("ops", "images/mission-control") for p in (ROOT / d).glob("*.py"))
    assert "MAX_FILES" not in code.replace('"MAX_FILES"', "")


def test_a_short_list_slice_needs_its_reason(tmp_path):
    root = tree(tmp_path, "ops/a.py", 'for x in spec.get("feeds", [])[:8]:\n    pass\n'
                                      'y = [a for a in b if a][:3]\n'
                                      'z = (raw or [])[:10]\n'
                                      'w = sorted(q)[:5]  # cap: top\n'
                                      'h = commit["sha"][:7]\n'
                                      's = title[:12]\n')
    bad = "\n".join(T.problems(root))
    assert "ops/a.py:1:" in bad and "ops/a.py:3:" in bad and "ops/a.py:4:" in bad
    assert "ops/a.py:5:" not in bad and "ops/a.py:6:" not in bad and "ops/a.py:7:" not in bad


def test_triggers_and_tickers_over_the_limit_are_refused_not_dropped():
    import mission_extras as X
    with pytest.raises(ValueError, match="11 triggers"):
        X.clean_triggers([{"type": "sec_filing", "tickers": ["ACME"]}] * 11)
    with pytest.raises(ValueError, match="11 tickers"):
        X.clean_triggers([{"type": "sec_filing", "tickers": [f"T{c}" for c in "ABCDEFGHIJK"]}])


def test_a_briefing_checks_every_source_it_was_given():
    desk = (ROOT / "images/desk/desk.py").read_text()
    for gone in ('spec.get("symbols", [])[:', 'spec.get("feeds", [])[:', 'spec["filings"][:'):
        assert gone not in desk
    missions = (ROOT / "ops/missions.py").read_text()
    assert 'd.get("feeds", [])[:' not in missions and 'd.get("filings", [])[:' not in missions


def test_a_fan_out_runs_every_item_or_refuses_the_plan():
    import conductor as CD
    agents = {"scout": {"harness": "hermes", "model": "gpt-sub", "type": "agent"}}
    if not CD.runs_steps(agents["scout"]):
        agents["scout"]["steps"] = True
    twelve = [f"item {i}" for i in range(12)]
    nodes = CD.graph([{"step": "Look", "agent": "scout", "why": "", "after": [], "each": twelve}], agents)
    assert [n["item"] for n in nodes] == twelve
    with pytest.raises(ValueError, match=f"{CD.EACH + 1} items to fan out"):
        CD.graph([{"step": "Look", "agent": "scout", "why": "", "after": [], "each": [f"i{i}" for i in range(CD.EACH + 1)]}], agents)


def test_past_the_day_s_budget_the_owner_is_told_once(tmp_path, monkeypatch):
    import swarm_client as SW
    monkeypatch.setattr(SW, "STATE", tmp_path)
    (tmp_path / "notified.json").write_text('{"mids": [], "times": []}')
    msgs = [{"mid": f"m{i}", "sender": "a", "sender_cls": "agent", "text": "@owner look", "context": "room:x"} for i in range(13)]
    sent = []
    send = lambda *a, **k: {"ok": True, "result": {"messages": msgs}}
    assert SW.notify_owner(send=send, notify=sent.append, now=1000.0) == SW.NOTIFY_DAY
    assert len(sent) == SW.NOTIFY_DAY + 1 and "3 more Board messages" in sent[-1] and "Swarm page" in sent[-1]
    msgs.append({"mid": "m99", "sender": "a", "sender_cls": "agent", "text": "@owner again", "context": "room:x"})
    SW.notify_owner(send=send, notify=sent.append, now=2000.0)
    assert len(sent) == SW.NOTIFY_DAY + 1                    # said once a day, not with every message


def test_an_attachment_says_which_sheets_and_rows_it_left_out():
    src = (ROOT / "images/mission-control/server.py").read_text()
    assert "more sheets, not read" in src and "rows of this sheet" in src

"""Truncation (AGENTS.md "Truncation", requirements APP-19, APP-20, QA-16): nothing the owner reads is cut silently, the
owner's input is refused instead of cut, every cap in the code names its reason, and stored JSON stays valid however
long its text."""
import asyncio
import filecmp
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import textcap as TC

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "images/mission-control/web/static"


def test_a_cut_says_what_it_cut_and_input_over_a_limit_is_refused():
    assert TC.cut("short", 10) == "short" and TC.tail("short", 10) == "short"
    c = TC.cut("x" * 50, 10, "the whole text is on its page")
    assert c.startswith("x" * 10) and "40 more characters cut: the whole text is on its page" in c
    t = TC.tail("a" * 5 + "b" * 10, 10)
    assert t.endswith("b" * 10) and t.startswith("[5 earlier characters cut")
    with pytest.raises(ValueError, match="your message is 4,001 characters; the limit is 4,000"):
        TC.limit("m" * 4001, 4000, "your message")
    with pytest.raises(ValueError, match="21 key questions; at most 20"):
        TC.limit_items(range(21), 20, "key questions")
    big = TC.bounded_json({"pack": "p" * 50000}, 1000)
    assert json.loads(big)["cut"] is True and len(big) < 1200                      # still JSON, and marked
    assert json.loads(TC.bounded_json({"a": 1}, 1000)) == {"a": 1}


def test_the_image_copies_of_textcap_are_the_same_file():
    for copy in ("images/mission-control/textcap.py", "images/swarm/textcap.py"):
        assert filecmp.cmp(ROOT / "ops/textcap.py", ROOT / copy, shallow=False), copy
    for df in ("images/mission-control/Dockerfile", "images/swarm/Dockerfile"):
        assert "textcap.py" in (ROOT / df).read_text()


def test_every_cap_names_its_reason_and_an_unexplained_one_fails_the_check(tmp_path):
    import truncation as TR
    assert TR.problems() == [] and len(TR.caps()) > 250                         # the repository as it is (not an empty scan)
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops/a.py").write_text("x = y[:200]\nz = y[:200]  # cap: prompt\n# cap: id\nw = y[-300:]\nv = y[:80]  # cap: because\n"
                                       "u = cut(y, 100)\nshort = y[:8]\n")
    (tmp_path / "ops/b.css").write_text(".a { text-overflow: ellipsis; }\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    bad = TR.problems(tmp_path)
    assert [p.split(": ")[0] for p in bad] == ["ops/a.py:1", "ops/a.py:5", "ops/a.py:6", "ops/b.css:1"]
    assert "an unknown reason 'because'" in bad[1] and "no reason" in bad[0]


def test_the_owner_s_long_input_is_refused_with_its_limit_not_cut(runner, ledger, monkeypatch):
    import builds as B
    monkeypatch.setattr(B, "repos", lambda: ["ai-stack"])
    c = runner.db()
    B.table(c)
    with pytest.raises(ValueError, match="the description is 20,001 characters; the limit is 20,000"):
        B.handle({"action": "build_assign", "repo": "ai-stack", "title": "A change", "description": "d" * 20001, "engine": "hermes"}, c)
    assert c.execute("select count(*) from builds").fetchone()[0] == 0             # nothing stored, not part of it
    import swarm_client as SW
    with pytest.raises(ValueError, match="your message is 4,001 characters"):
        SW.handle({"action": "swarm_post", "to": ["room:all"], "text": "t" * 4001})
    r = SW.call("send", {"idem": "long", "to": ["room:all"], "act": "inform", "text": "t" * 4001}, "owner")
    assert not r["ok"] and "at most 4,000 characters" in r["refused"]                # the Ledger refuses it too


def test_run_inputs_stay_valid_json_however_long_they_are(tmp_path):
    from ledger import Ledger
    cards = [{"id": "doctor", "tools": [], "roles": [], "rooms": ["all"], "contact": ["*"], "model": "claude-subscription"}]
    L = Ledger(str(tmp_path / "s.db"), cards, registry={"rooms": ["all"]})
    L.run_start({"id": "system", "cls": "system"}, "doctor", "r1")
    L.finish({"id": "doctor", "cls": "agent", "via": "runner"}, "f", "looked at it", run="r1", inputs={"signal": "s" * 100000})
    L.db.execute("update runs set inputs=? where run='r1'", (TC.bounded_json({"pack": "p" * 90000}, 40000),))
    ex = L.replays("doctor")                                                     # a cut JSON string used to crash this
    assert ex[0]["inputs"]["cut"] is True and "more characters cut" in ex[0]["inputs"]["text"]


def test_journal_lines_and_the_phone_s_approval_cards_are_shown_whole(monkeypatch, tmp_path):
    import crew
    line = "Finished swarm-sync.service - Swarm: publish the Ledger's view for the app and copy its events into the activity feed " * 4
    monkeypatch.setattr(crew, "sh", lambda *a, **k: line + "\nnext")
    assert crew.journal_tail("swarm-sync") == [line, "next"]                      # the screenshot of 2026-10-30: no cut lines
    sys.path.insert(0, str(ROOT / "images/phone"))
    monkeypatch.setenv("PHONE_DIR", str(tmp_path))
    monkeypatch.setenv("PHONE_HOST", "100.64.0.10")
    import phone
    phone = importlib.reload(phone)
    text, url = "a sentence the owner should read in full before allowing it " * 6, "https://example.org/" + "p" * 300
    assert text in phone.describe("phone_type", {"text": text})                  # he approves exactly what is typed
    assert url in phone.describe("phone_url", {"url": url})
    fn = getattr(phone.phone_type, "fn", phone.phone_type)
    assert asyncio.run(fn("x" * 501, "test")).startswith("Refused: 501 characters to type")


def test_the_app_wraps_text_and_shows_the_rest_of_a_list():
    for f in list(STATIC.glob("*.css")) + list(STATIC.glob("*.js")):
        if "vendor" in f.name:
            continue
        src = f.read_text()
        assert not re.search(r"text-overflow:\s*ellipsis|line-clamp|class=\"[^\"]*\bellipsis\b", src), f.name
    css = (STATIC / "app.css").read_text()
    assert ".wrap { min-width: 0; overflow-wrap: anywhere; }" in css
    js = (STATIC / "app.js").read_text()
    assert 'id="hfmore"' in js and "Show older (${mine.length - items.length} more)" in js
    first = re.search(r"^const firstLine = .*;$", js, re.M)[0]
    out = subprocess.run(["node", "-e", first + 'process.stdout.write(firstLine("one\\ntwo") + "|" + firstLine("only"));'],
                         capture_output=True, text=True, check=True).stdout
    assert out == "one …|only"

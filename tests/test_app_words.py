"""APP-70: the app speaks the factory design's words only (Platform, Factory, Site, Workflow, Standard workflow, Trigger,
Run, Step, Agent, Skill, Ask, Result, Ticket, Policy, Scorer). The words that went (task, mission, crew, duty, door,
occurrence, plan, wave, swarm, team room, conductor) are never in a text the owner reads: every string of the app's
scripts is read with ESLint's own parser (tests/app_strings.cjs) and what a person sees of it is scanned. Code names
(a key, a route, a class, an action) may keep the old words until phase B renames them."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "images/mission-control/web"
sys.path.insert(0, str(ROOT / "ops"))
import app_lint  # noqa: E402  (the scripts in index.html's order)

BANNED = re.compile(r"\b(tasks?|missions?|crews?|duty|duties|doors?|occurrences?|plans?|planned|planning|planner|waves?|swarms?|"
                    r"team ?rooms?|conductors?)\b", re.I)


def visible(text):
    """What a person reads of a string: no tags, attributes, addresses, class names or keys."""
    t = re.sub(r"<[^<>]*>", " ", text)
    if ">" in t and ("<" not in t or t.index(">") < t.index("<")):
        t = t[t.index(">") + 1:]                 # the end of a tag that began before a ${}
    if "<" in t and ">" not in t[t.rindex("<"):]:
        t = t[:t.rindex("<")]                    # a tag that goes on after a ${}
    t = re.sub(r"#/\S*", " ", t)                 # an address in the app
    t = re.sub(r"\{\w+\}", " ", t)              # a placeholder filled in from data
    t = re.sub(r"\b\w+(?:[-_.:/]\w+)+\b", " ", t)   # a class, a key, a path or an id
    t = re.sub(r"\b[\w-]+=\S*", " ", t)          # an attribute
    if re.fullmatch(r"\s*[a-z0-9_:./-]*\s*", t):
        return ""                                # one lowercase word alone is a key in code, not a sentence
    return t


def strings():
    files = [p.name for p in app_lint.scripts()]
    out = subprocess.run(["node", str(Path(__file__).with_name("app_strings.cjs")), str(WEB / "static"), *files],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return [json.loads(x) for x in out.stdout.splitlines()]


def offenders(rows):
    return [f"{r['file']}:{r['line']}: {m.group(0)!r} in {visible(r['text']).strip()!r}"
            for r in rows for m in BANNED.finditer(visible(r["text"]))]


def test_the_app_never_says_a_word_the_factory_design_retired():
    rows = strings()
    assert len(rows) > 3000                      # every script was read
    bad = offenders(rows)
    assert not bad, f"{len(bad)} texts with a retired word:\n" + "\n".join(bad)


@pytest.mark.parametrize("text,hit", [("Open the mission", True), ("New task", True), ("Who is on the crew", True),
                                      ("Show me the plan first", True), ("the team room", True), ("Run now", False),
                                      ('<a class="tkrow" href="#/task/12">', False), ("task", False), ("data-tasks=", False),
                                      ("mission-control", False)])
def test_the_scan_finds_a_retired_word_in_text_and_leaves_code_alone(text, hit):
    assert bool(offenders([{"file": "x.js", "line": 1, "text": text}])) is hit


def test_the_page_names_the_app_and_its_places_in_the_new_words():
    html = (WEB / "index.html").read_text()
    assert not BANNED.search(visible(re.sub(r"<script.*?</script>", " ", html, flags=re.S)))
    assert not [c for c in re.findall(r'content="([^"]*)"', html) if BANNED.search(c)]   # the title a phone's home screen shows

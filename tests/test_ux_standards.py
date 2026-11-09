"""One look and wording across the app (TSK-31): the app's formatting helpers are the only place a date, a time or a
number becomes text; every action says what happens next; every empty state offers its next action. The journey
check (ops/journeys.py) proves the rest in a browser: every route at 375 px, a card that stands for a page opens it."""
import webjs
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "images/mission-control/web/static"
FILES = (*webjs.APP_PARTS, "swarm.js", "shop.js", "guide.js")
FORMAT_BLOCK = re.compile(r"// ---------- formatting \(TSK-31\).*?// ---------- end of formatting ----------", re.S)
# what only the helpers may do: locale formatting, Intl, and an ISO time cut into a clock or a date for the eye
OWN_FORMAT = re.compile(r"toLocale(?:Date|Time)?String|\bIntl\.|\.slice\((?:11|5|0), ?16\)|toISOString\(\)\.slice")
# toFixed for text is the helpers' (nf); a number in an SVG coordinate or a CSS length is no text
GEOMETRY = re.compile(r'(?:\b(?:x|y|cx|cy|r|width|height|points|stroke-dasharray)="[^"]*\$\{[^}]*toFixed|toFixed\(\d\)\}?%|'
                      r'width:\$\{[^}]*toFixed|\.style\.\w+ = [^;]*toFixed|toFixed\(1\)\},\$\{)')


def sources():
    for f in FILES:
        yield f, (STATIC / f).read_text()


def formatting_outside():
    """Each line outside the formatting block that formats a date, a time or a number itself: (file:line, text)."""
    bad = []
    for f, text in sources():
        block = FORMAT_BLOCK.search(text)
        lo, hi = (text[:block.start()].count("\n"), text[:block.end()].count("\n")) if block else (-1, -1)
        for i, line in enumerate(text.split("\n")):
            if lo <= i <= hi or "fmt-ok" in line:
                continue
            if OWN_FORMAT.search(line) or ("toFixed(" in line and not GEOMETRY.search(line)):
                bad.append(f"{f}:{i + 1}: {line.strip()[:140]}")  # cap: preview
    return bad


def calls(text, name):
    """Each call name(...) as its list of top-level argument strings (strings, templates and nesting respected)."""
    out = []
    for m in re.finditer(rf"(?<![\w.]){name}\(", text):
        i, depth, args, cur, q = m.end(), 1, [], "", None
        while i < len(text) and depth:
            ch = text[i]
            if q:
                cur += ch
                if ch == "\\":
                    cur += text[i + 1]
                    i += 1
                elif ch == q:
                    q = None
            elif ch in "\"'`":
                q, cur = ch, cur + ch
            elif ch in "([{":
                depth, cur = depth + 1, cur + ch
            elif ch in ")]}":
                depth -= 1
                if depth:
                    cur += ch
            elif ch == "," and depth == 1:
                args.append(cur.strip())
                cur = ""
            else:
                cur += ch
            i += 1
        args.append(cur.strip())
        out.append((text[:m.start()].count("\n") + 1, [a for a in args if a]))
    return out


def words_of(arg):
    """The literal messages in an argument (a string, a template's text, each branch of a ternary)."""
    arg = re.sub(r'[=!]==? *(?:"[^"]*"|\'[^\']*\')', "", arg)              # a value compared is no message
    arg = re.sub(r'(?:"[^"]*"|`[^`]*`) *\+', "", arg)                      # the start of a sentence joined on
    return [s for a, b, c in re.findall(r'"([^"]*)"|`([^`]*)`|\'([^\']*)\'', arg) for s in (a or b or c,) if s]   # "": no answer, no toast


def actions_without_next():
    """act(request, message): a call with no message, or a message too short to say what happens next."""
    bad = []
    for f, text in sources():
        text = text.replace("async function act(req, okMsg)", "")
        for line, args in calls(text, "act"):
            if len(args) < 2:
                bad.append(f"{f}:{line}: no message")
                continue
            if args[1] == "null":
                continue                                  # a read (a search, a viewer): its answer shows in place
            for s in words_of(args[1]):
                if len(re.sub(r"\$\{[^}]*\}", "x", s).split()) < 3:
                    bad.append(f"{f}:{line}: “{s}” does not say what happens next")
    return bad


def empty_states_without_action():
    """emptyState(text, action): every empty state says what fills it and offers that action."""
    bad = []
    for f, text in sources():
        for line, args in calls(text, "emptyState"):
            if text.split("\n")[line - 1].startswith("function emptyState("):
                continue
            if len(args) < 2 or args[1] in ('""', "''", "null"):
                bad.append(f"{f}:{line}: an empty state with no action")
    return bad


def test_dates_times_and_numbers_are_formatted_by_the_app_s_helpers_only():
    assert not formatting_outside(), "\n".join(["formatted outside the helpers:"] + formatting_outside())


def test_the_helpers_say_dates_and_numbers_one_english_way():
    import json
    import subprocess
    text = webjs.app_js()
    block = FORMAT_BLOCK.search(text)[0]
    js = block + """
const now = Date.now(), at = new Date(2026, 9, 20, 18, 40);
console.log(JSON.stringify([dt(at), day(at), clock(at), nf(1234), kn(4200), kn(42000), kn(1.25e6), usd(0.42), eur(12.345), gb(4.2e9),
  dt(at.getTime() / 1000), when(new Date(now - 12 * 60e3)), when(at), dt(null), eur(null)]));"""
    js = js.replace("rel(d)", "'rel'")
    import os
    import shutil
    out = json.loads(subprocess.run([shutil.which("node") or "node", "-e", js], capture_output=True, text=True, check=True,
                                    env={**os.environ, "TZ": "Europe/Berlin"}).stdout)
    year = "" if __import__("datetime").date.today().year == 2026 else " 2026"
    assert out == [f"Tue 20 Oct{year}, 18:40", f"Tue 20 Oct{year}", "18:40", "1,234", "4.2k", "42k", "1.3M", "$0.42", "€12.35", "4.2 GB",
                   f"Tue 20 Oct{year}, 18:40", "rel", f"Tue 20 Oct{year}, 18:40", "–", "?"]


def test_every_action_says_what_happens_next():
    assert not actions_without_next(), "\n".join(["actions that do not say what happens next:"] + actions_without_next())


def test_every_empty_state_offers_its_next_action():
    assert "function emptyState(" in webjs.app_js()
    assert not empty_states_without_action(), "\n".join(empty_states_without_action())


def test_the_checks_catch_what_they_are_for():
    assert OWN_FORMAT.search('x.toLocaleTimeString("en-GB")') and OWN_FORMAT.search("(e.ts || '').slice(11, 16)")
    assert GEOMETRY.search('<rect x="${x.toFixed(1)}"') and not GEOMETRY.search("<b>${(n / 1000).toFixed(1)} s</b>")
    assert calls('act({ action: "x", a: [1, 2] }, on ? "Paused" : "Resumed: it runs again at its next time");', "act") == \
        [(1, ['{ action: "x", a: [1, 2] }', 'on ? "Paused" : "Resumed: it runs again at its next time"'])]
    assert words_of('on ? "Paused" : `Resumed ${x}`') == ["Paused", "Resumed ${x}"]

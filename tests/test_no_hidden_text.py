"""APP-57: names are never cut, and a list shows every row from the start (the owner, 9 Nov 2026: "Truncation keeps
creeping in. Need All here and all should start as default."). A scan of the app's scripts that fails on a new fold."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "images/mission-control/web/static"


def scripts():
    for f in sorted(STATIC.glob("*.js")):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            yield f.name, n, line


def test_no_row_is_hidden_by_its_place_in_the_list():
    bad = [f"{f}:{n}" for f, n, ln in scripts() if re.search(r"\$\{\s*i\s*>=?\s*\d+\s*\?\s*[\"']\s*hidden", ln)]
    assert not bad, f"rows hidden by their index (every row shows from the start, APP-57): {bad}"


def test_a_show_all_names_its_reason():
    bad = [f"{f}:{n}" for f, n, ln in scripts() if re.search(r"[Ss]how all", ln) and "cap:" not in ln and "skclear" not in ln
           and not ln.lstrip().startswith("//")]
    assert not bad, f'a "Show all" without a cap: reason (a list shows every row from the start, APP-57): {bad}'


def test_a_name_is_never_made_by_cutting():
    for f, n, ln in scripts():
        if re.search(r"(?:const|function)\s+\w*(?:[Tt]itle|[Ll]abel|[Nn]ame)\w*\s*(?:=|\()", ln):
            assert not re.search(r"\.slice\(0,|\.substring\(0,|…", ln), f"{f}:{n} makes a name by cutting (APP-57)"
    src = (ROOT / "ops/tasks.py").read_text()
    body = src.split("def title_of(text):", 1)[1].split("\ndef ", 1)[0].split('"""')[-1]   # its code, not its docstring
    assert "…" not in body and "[:" not in body

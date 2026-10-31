#!/usr/bin/env python3
"""The app's scripts checked for names that do not exist and similar mistakes (APP-24, FND-52: "watch is not defined"
broke Start mission for days and no check saw it).

  python3 ops/app_lint.py        exit 1 with each problem as file:line, 0 when clean, 2 when ESLint is not installed

The scripts are classic browser scripts sharing one global scope, so they are joined in the order index.html loads
them and linted as one (a name another script defines is then known); each problem is reported at its own file and
line. ESLint and its browser globals live in /opt/eslint of the builder and CI images (ESLINT_HOME to override).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "images/mission-control/web"
HOME = Path(os.environ.get("ESLINT_HOME", "/opt/eslint"))
RULES = {"no-undef": "error", "no-redeclare": ["error", {"builtinGlobals": False}], "no-dupe-keys": "error", "no-unreachable": "error",
         "no-const-assign": "error", "no-func-assign": "error", "valid-typeof": "error", "no-dupe-else-if": "error",
         "no-duplicate-case": "error", "no-unsafe-negation": "error", "no-self-assign": "error", "no-dupe-args": "error"}


def scripts():
    """The app's own scripts in the order index.html loads them (the vendored libraries are globals, not linted)."""
    html = (WEB / "index.html").read_text()
    return [WEB / s.lstrip("/") for s in re.findall(r'<script[^>]*src="(/static/[^"]+\.js)"', html) if "/vendor/" not in s]


def main():
    eslint = HOME / "node_modules/.bin/eslint"
    if not eslint.exists():
        print(f"   ESLint is not installed here ({eslint}); the builder and CI images carry it")
        return 2
    files, parts, spans, line = scripts(), [], [], 1
    for f in files:
        text = f.read_text()
        if not text.endswith("\n"):
            text += "\n"
        n = text.count("\n")
        spans.append((f, line, line + n - 1))
        parts.append(text)
        line += n
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "all.js").write_text("".join(parts))
        (Path(d) / "eslint.config.mjs").write_text(
            f'import globals from "{HOME}/node_modules/globals/index.js";\n'
            "export default [{ files: [\"all.js\"], languageOptions: { ecmaVersion: 2024, sourceType: \"script\",\n"
            "  globals: { ...globals.browser, d3: \"readonly\", marked: \"readonly\", DOMPurify: \"readonly\" } },\n"
            f"  rules: {json.dumps(RULES)} }}];\n")
        p = subprocess.run([str(eslint), "-f", "json", "all.js"], cwd=d, capture_output=True, text=True, timeout=300)
    try:
        msgs = json.loads(p.stdout)[0]["messages"]
    except (ValueError, IndexError):
        print(f"   ESLint did not answer: {(p.stderr or p.stdout).strip()[-500:]}")  # cap: preview
        return 1
    bad = []
    for m in msgs:
        f, a, _ = next((s for s in spans if s[1] <= m.get("line", 0) <= s[2]), (Path("?"), 1, 0))
        bad.append(f"{f.relative_to(ROOT) if f.is_absolute() else f}:{m.get('line', 0) - a + 1}: {m.get('ruleId')}: {m['message']}")
    for b in bad:
        print("  ", b)
    print(f"   {len(files)} scripts, {len(bad)} problem{'s' if len(bad) != 1 else ''}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

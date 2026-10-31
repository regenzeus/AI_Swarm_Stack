#!/usr/bin/env python3
"""Do the Semgrep rules (.semgrep.yml) still catch what they should? Run by ops/check.sh.

Scans tests/semgrep/ (deliberately bad code, excluded from the normal scan) and compares the findings with the
fixtures' annotations: a `ruleid: <id>` comment means the next line must be flagged by that rule, `ok: <id>` means
it must not. Exit 1 on any mismatch, so a rule that silently stops matching fails the checks.
"""
import json, re, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "semgrep"
# Semgrep's default ignore list skips any tests/ folder (and git-ignore rules apply inside a repo), so scan a copy
# of the fixtures outside the repo; otherwise nothing is scanned and every rule looks broken.
with tempfile.TemporaryDirectory() as tmp:
    for f in FIX.glob("*.*"):
        shutil.copy(f, tmp)
    p = subprocess.run(["semgrep", "scan", "--config", str(ROOT / ".semgrep.yml"), "--json", "--metrics", "off",
                        "--disable-version-check", "--quiet", "--no-git-ignore", tmp], capture_output=True, text=True)
out = json.loads(p.stdout or "{}")
if not out.get("paths", {}).get("scanned"):
    print("  semgrep scanned no fixture files:", p.stderr.strip() or out.get("errors"))
    sys.exit(1)
found = {(Path(r["path"]).name, r["start"]["line"], r["check_id"].rsplit(".", 1)[-1]) for r in out.get("results", [])}
bad = []
for f in sorted(FIX.glob("*.*")):
    lines = f.read_text().splitlines()
    for i, ln in enumerate(lines, 1):
        m = re.search(r"(ruleid|ok):\s*([\w-]+)", ln)
        if not m:
            continue
        hit = (f.name, i + 1, m[2]) in found
        if (m[1] == "ruleid") != hit:
            bad.append(f"{f.name}:{i + 1} {m[2]}: {'not flagged' if m[1] == 'ruleid' else 'flagged although marked ok'}")
for b in bad:
    print("  " + b)
print(f"{len(bad)} mismatches in {len(list(FIX.glob('*.*')))} fixture files")
sys.exit(1 if bad else 0)

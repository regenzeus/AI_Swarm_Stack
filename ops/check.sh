#!/usr/bin/env bash
# Every automatic check of this repo, in one place. CI (.forgejo/workflows/ci.yml), the builder sandbox
# (ops/builds.py) and `make check` (in the CI runner image) all run exactly this script, so they can't disagree.
# Prints "ALL CHECKS PASSED" at the end only when every check passed. Needs no secrets and no running services.
# PYTEST: pytest to use (default: pytest on PATH, with tests/requirements.txt installed).
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
step() { local name=$1; shift; printf '== %s\n' "$name"; if "$@"; then echo "   ok"; else echo "   FAILED: $name"; fail=1; fi; }
skip() { printf '== %s\n   skipped: %s\n' "$1" "$2"; }

step "shell scripts (shellcheck)" shellcheck -S error ops/*.sh smoke/*.sh config/hermes/*.sh images/*/*.sh
step "python (syntax, undefined names, unused imports)" ruff check --no-cache --select E9,F63,F7,F82,F401 --extend-exclude tests/semgrep .
if command -v node >/dev/null 2>&1; then
  step "app javascript parses" sh -c 'for f in images/mission-control/web/static/*.js; do node --check "$f" || exit 1; done'
else
  skip "app javascript parses" "node not installed here (CI runs it)"
fi
if [ -x "${ESLINT_HOME:-/opt/eslint}/node_modules/.bin/eslint" ]; then
  step "app scripts: no undefined names (ops/app_lint.py, APP-24)" python3 ops/app_lint.py
else
  skip "app scripts: no undefined names" "ESLint not installed here (the builder and CI images carry it)"
fi
step "yaml parses" python3 ops/ci_yaml_check.py
step "agent registry (ops/registry.py: cards, keys, grants, units)" python3 ops/registry.py check
step "agent prompts (ops/prompts.py: each change replay-tested, MEM-11)" python3 ops/prompts.py check
step "truncation (ops/truncation.py: every cap names its reason)" python3 ops/truncation.py check
if command -v semgrep >/dev/null 2>&1; then           # the repo's own rules (.semgrep.yml), offline
  step "security patterns (semgrep)" semgrep scan --config .semgrep.yml --metrics off --disable-version-check --error --quiet --exclude tests/semgrep .
  step "semgrep rules still catch what they should" python3 ops/semgrep_selftest.py
else
  skip "security patterns (semgrep)" "semgrep not installed here (CI and the builder run it)"
fi
step "benchmark still frozen" sh -c 'test "$(sha256sum eval/bench-v1.yaml | cut -d" " -f1)" = "$(cut -d" " -f1 eval/FROZEN.sha256)"'
if docker compose version >/dev/null 2>&1; then
  step "compose files valid" bash ops/ci-compose-check.sh
else
  skip "compose files valid" "docker compose not installed here (CI runs it)"
fi
step "requirements (ops/req.py: fields, links, tests, rendering)" python3 ops/req.py check
step "unit tests (pytest)" "${PYTEST:-pytest}" -q -p no:cacheprovider tests

if [ "$fail" = 0 ]; then echo "ALL CHECKS PASSED"; else echo "SOME CHECKS FAILED"; fi
exit "$fail"

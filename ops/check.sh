#!/usr/bin/env bash
# Every automatic check of this repo, in one place. CI (.forgejo/workflows/ci.yml), the builder sandbox
# (ops/builds.py) and `make check` (in the CI runner image) all run exactly this script, so they can't disagree.
# Prints "ALL CHECKS PASSED" at the end only when every check passed, and names on that line any check that could not
# run in a place known to lack its tool. Needs no secrets and no running services.
# PYTEST: pytest to use (default: pytest on PATH, with tests/requirements.txt installed).
# CHECK_NOT_HERE: the tools this place lacks on purpose, separated by spaces. The builder sandbox has no Docker by design
# (docs/SECURITY.md), so there it defaults to docker-compose; everywhere else it is empty and a missing tool fails (QA-26).
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
not_run=""
if [ -z "${CHECK_NOT_HERE+set}" ] && [ -x /opt/tools/bin/pytest ]; then CHECK_NOT_HERE="docker-compose"; fi
step() { local name=$1; shift; printf '== %s\n' "$name"; if "$@"; then echo "   ok"; else echo "   FAILED: $name"; fail=1; fi; }
missing() {                                            # missing <check> <tool>: a check that could not run is never a pass
  printf '== %s\n' "$1"
  case " ${CHECK_NOT_HERE:-} " in
    *" $2 "*) echo "   not run: this place has no $2"; not_run="$not_run${not_run:+, }$1" ;;
    *) echo "   FAILED: $1: $2 is missing, so this check could not run"; fail=1 ;;
  esac
}

step "shell scripts (shellcheck)" shellcheck -S error ops/*.sh smoke/*.sh config/hermes/*.sh images/*/*.sh
step "python (syntax, undefined names, redefined names, unused imports)" ruff check --no-cache --select E9,F63,F7,F82,F401,F811 --extend-exclude tests/semgrep,images/mission-control/server.py,images/mission-control/server.*.py,ops/missions.py,ops/missions.*.py,ops/builds.py,ops/builds.*.py,images/swarm/ledger.py,images/swarm/ledger.*.py .
step "python kept in parts, linted joined (ops/py_parts_lint.py, PLT-25)" python3 ops/py_parts_lint.py
if command -v node >/dev/null 2>&1; then
  step "app javascript parses" sh -c 'for f in images/mission-control/web/static/*.js; do node --check "$f" || exit 1; done'
else
  missing "app javascript parses" node
fi
if [ -x "${ESLINT_HOME:-/opt/eslint}/node_modules/.bin/eslint" ]; then
  step "app scripts: no undefined names (ops/app_lint.py, APP-24)" python3 ops/app_lint.py
else
  missing "app scripts: no undefined names" eslint
fi
step "yaml parses" python3 ops/ci_yaml_check.py
step "agent registry (ops/registry.py: cards, keys, grants, units)" python3 ops/registry.py check
step "model policy (ops/modelpolicy.py, GEN-05)" python3 ops/modelpolicy.py check
step "data class and egress (ops/dataguard.py, GEN-14)" python3 ops/dataguard.py check
step "agent prompts (ops/prompts.py: each change replay-tested, MEM-11)" python3 ops/prompts.py check
step "truncation (ops/truncation.py: every cap names its reason)" python3 ops/truncation.py check
step "limits (ops/limits.py: every limit says what it does and why, QA-22)" python3 ops/limits.py check
if command -v semgrep >/dev/null 2>&1; then           # the repo's own rules (.semgrep.yml), offline
  step "security patterns (semgrep)" semgrep scan --config .semgrep.yml --metrics off --disable-version-check --error --quiet --exclude tests/semgrep .
  step "semgrep rules still catch what they should" python3 ops/semgrep_selftest.py
else
  missing "security patterns (semgrep)" semgrep
fi
step "benchmark still frozen" sh -c 'test "$(sha256sum eval/bench-v1.yaml | cut -d" " -f1)" = "$(cut -d" " -f1 eval/FROZEN.sha256)"'
if docker compose version >/dev/null 2>&1; then
  step "compose files valid" bash ops/ci-compose-check.sh
else
  missing "compose files valid" docker-compose
fi
step "requirements (ops/req.py: fields, links, tests, rendering)" python3 ops/req.py check
# Parallel when pytest-xdist is there (the builder image and CI have it): PYTEST_WORKERS processes, 6 of the PC's 8
# threads by default, leaving the stack room. Each worker gets a temp folder of its own (tests/conftest.py).
PAR=()
if "${PYTEST:-pytest}" -p xdist --version >/dev/null 2>&1; then PAR=(-n "${PYTEST_WORKERS:-6}"); fi   # limit: paces, 6 test workers so the running stack keeps two threads
step "unit tests (pytest${PAR:+, ${PAR[1]} workers})" "${PYTEST:-pytest}" -q -p no:cacheprovider "${PAR[@]}" tests

if [ "$fail" = 0 ]; then echo "ALL CHECKS PASSED${not_run:+, but not run here: $not_run}"; else echo "SOME CHECKS FAILED"; fi
exit "$fail"

# tests/: unit tests and docs coverage

pytest, run by `ops/check.sh` (CI, the builder, `make check`). Dependencies are in `requirements.txt` (pinned,
installed into a throwaway venv). **Everything external is faked**: no Docker, LiteLLM, Hermes, vault, network or
secrets. The whole suite runs in under a minute.

| File | Covers |
|---|---|
| `conftest.py` | import paths, fixtures: `runner` (ops/missions.py with every path in `tmp_path` and side effects off), `at` (fixed time), `desk` |
| `test_runner.py` | schedules, request validation, duplicate guard, pause detection, queueing, cost windows |
| `test_triggers.py` | trigger validation and the event watcher (baseline, then fire once) |
| `test_builds.py` | builder requests and the approve path with a real local git origin: merge, deploy, rollback |
| `test_server.py` | the app API (TestClient): auth, inbox, vault paths, wiki links, chat on Hermes sessions |
| `test_desk.py` | desk text helpers and the URL guard |
| `test_guide.py` | the in-app guide covers every tool, screen and `make` target; examples and live blocks are valid |
| `semgrep/` | fixtures of deliberately bad code: `ops/semgrep_selftest.py` checks the `.semgrep.yml` rules still flag them |
| `test_repo_docs.py` | every directory has an `AGENTS.md` listed in the root map; file headers exist |
| `test_new_machine_docs.py` | new-PC instructions and the rehearsal's manual checklist retain the five required setup topics |

These are the core files. Every test file, every test and the requirement it proves are in
`requirements/REQUIREMENTS.md` (Test index); a new test must be claimed by a requirement (`ops/req.py`).

## Rules

- A new behaviour gets a test in the file for its module, using the existing fixtures. Copy the nearest test.
- Patch with `monkeypatch`, write only under `tmp_path`, and never sleep (inject time with the `at` fixture or by
  patching `now`).
- A test that needs a real service doesn't belong here: it belongs in `smoke/` or `eval/`.
- If a test fails, fix the code or the test's assumption. Never skip or loosen it to get green.

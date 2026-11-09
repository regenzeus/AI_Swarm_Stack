# .forgejo/workflows/: CI

`ci.yml` runs on every push to Forgejo (NAS), on the `wsl-ci` runner (`images/ci-runner`, label `host`, no
secrets, no Docker socket). It installs `tests/requirements.txt` into a throwaway venv and runs `ops/check.sh`.

Keep the logic in `ops/check.sh`, not here: the builder and `make check` run the same script, and a check that
only CI knows would make them disagree. This file should only prepare the environment.

The Mission Control runner reads each repo's latest CI result (Stack page, builder approvals: a build deploys only
when its CI is green).

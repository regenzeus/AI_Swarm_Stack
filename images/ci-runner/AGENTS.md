# images/ci-runner/: the CI runner

The Forgejo Actions runner (`config.yaml`) for the repos on the NAS Forgejo. Jobs run directly in this container
(label `host`), so the image carries the check tools: python 3.12, pip, git, node, shellcheck, ruff, pyyaml, semgrep and the
docker CLI (compose validation only, no socket).

`make check` runs `ops/check.sh` in this same image, so local checks and CI can't drift. When you add a check
tool to `ops/check.sh`, add it here too (and to `images/builder`). The runner has no secrets and no stack network.
It was registered once with a token from the NAS.

Its service runs with the feature `forgejo-ci` (GEN-47), not with `builder`: a deployment without Forgejo has nothing to
register it with, so it leaves the feature off and still builds this image for `make check`.

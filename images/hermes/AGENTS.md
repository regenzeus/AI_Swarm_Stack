# images/hermes/: Hermes Agent

The upstream `nousresearch/hermes-agent` image (version in `versions.env`, `HERMES_IMAGE`) plus `ddgs` (keyless web
search for the scout) and `hindsight-client` (long-term memory). The image is shared by the profiles main, scout,
curator and mission. The builder image builds on it.

Profiles are configured by `config/hermes/*.sh`, not here. This image only adds packages.

## Rules

- Pin every added package. When upgrading Hermes, follow `UPGRADE.md`: bump `versions.env`, rebuild, run
  `make smoke` and `make bench-gate` before committing.
- The image's entrypoint drops root to uid 10000. Don't override that to run as root (it breaks the gateway).

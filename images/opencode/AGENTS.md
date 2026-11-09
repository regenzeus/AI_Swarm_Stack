# images/opencode/: OpenCode

The OpenCode server and web UI (tailnet `:8445`) for hands-on changes in `~/code` (WSL ext4). It talks to models
only through LiteLLM with key `vk-code`, and reaches package registries only through `pkgproxy`.

Pin the OpenCode version in the `Dockerfile`. The login is shown with `make opencode-password`. OpenCode reads
the repo's `AGENTS.md` files like any other coding agent.

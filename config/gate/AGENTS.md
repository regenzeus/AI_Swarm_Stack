# config/gate/: single sign-in

Your Tailscale login is the only sign-in. `tailscale serve` (on Windows) adds the `Tailscale-User-Login` header for
your own devices, and these Caddy configs let a request through only when it carries that header:

| File | Gate for | Runs as |
|---|---|---|
| `hermes-dashboard.Caddyfile` | the Hermes dashboard (`:8448`) | compose service `gate-hermes-dashboard`, in Hermes' network namespace with the dashboard (its chat attaches to Hermes' gateway on loopback): the dashboard listens on loopback only, so its own password stays off |
| `codemap.Caddyfile` | the code map viewer (`:8446`) | a sidecar started by `ops/understand-dashboard.sh` in the viewer's namespace; it also adds the viewer's fixed access token |

Mission Control (its own middleware) and Open WebUI (`WEBUI_AUTH_TRUSTED_EMAIL_HEADER`) check the same header
themselves. OpenCode and Phoenix are tailnet-only without a login.

## Rules

- A gate refuses every request without the header (`smoke/smoke.sh` checks the dashboard's gate). Don't add exceptions.
- The image is pinned (`GATE_IMAGE` in `versions.env`). Configs are read-only mounts, and the containers have a
  read-only root filesystem.
- Local processes on the PC could forge the header. That is an accepted risk in `docs/SECURITY.md`, because
  anything that can do that can read the files directly.

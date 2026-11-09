# images/phone/: the AI phone

Hermes' hands on the owner's **old test phone** (ai-phone on the tailnet), never the main phone. `phone.py` drives
it with ADB over Tailscale (Google platform-tools, checksum-pinned in the `Dockerfile`) and offers MCP tools through
LiteLLM (`mcp_servers.phone`, granted to `vk-main` in `ops/keys.sh`): `phone_look`, `phone_tap`, `phone_type`,
`phone_swipe`, `phone_key`, `phone_open`, `phone_url`, `phone_apps`, `phone_done`, `phone_storage` and `phone_apps_report` (read-only cleanup facts: sizes, counts, dates, never file contents; also run by `ops/cleanup.py`), `phone_files` (biggest files and old data by year: names, sizes, dates; the S22 is no longer the owner's private phone), `phone_delete` (a file or folder on /sdcard, optionally only files older than N days; the approval shows files, size and dates), `phone_uninstall` and `phone_trim_caches` (each asks the owner every time, even inside his time window, like spending money; never blocked or system apps) (a summary to Telegram
via the host runner, `done/`).

Shared folder `/srv/ai/phone` (`/phone` here and in Mission Control): `state.json`, `pending/` (approval
requests), `decisions/` and `control/` (written by Mission Control: the owner's answers, pair/connect requests),
`STOP`, `log.jsonl`, `shots/`, `blocklist.txt`, `home/.android` (the ADB pairing key, this user only).

## Rules

- These guards are the point of this service; never weaken them: the firewall (`entrypoint.sh`: the one phone IP
  only), Stop, the block list (checked before and after every action), the owner's approval for every action that
  changes something (15 min, no answer = no), and the log.
- Never point `PHONE_HOST` at the main phone. Phone sessions on the main phone are a separate, later design.
- `timeout: 960` for `phone` in `config/litellm/config.yaml` must stay above the 15 min approval wait, and Hermes'
  `mcp_servers.vault.timeout` (configure.sh) above both.
- Screenshots go to the owner (approval card, log); the model gets one only on `phone_look(picture=true)`.
- Money guard (`MONEY`, `SECRET_FIELD`, `CARDLIKE` in `phone.py`): a tap on a buy/pay/order/subscribe label always
  needs its own approval (no time window, its approval opens none); secret fields and card/IBAN-shaped text are
  refused. Over-asking is fine, under-asking is a bug: add shop wording, never remove it.
- Purchases (`docs/SHOPPING.md`): `purchases/<id>.json` is written only by the runner after the owner approved a
  proposal in Mission Control. While it is open: steps inside that shop app run without asking, typing and
  change/address/payment taps are refused, and the final buy button is tapped once and only if `final_check()`
  passes (deterministic: item, variant, seller, total ≤ ceiling, address words, no sign-in/code/captcha/3-D Secure).
  Keep the check strict: a false stop is fine, a false pass is a bug. `research/` holds read-only app searches
  (`shop_look`, through the guard like any action).
- Blocked apps are never read: `guard(..., acting=False)` runs before any screen read.
- Every logged action also goes to the runtime record (`rt_emit`: `runtime/phone-<date>.jsonl`, forwarded by the
  runner). Keep it best-effort: it must never fail or slow an action.

Approved cleanup steps: `ops/phone_agents.py` (crew Phone cleanup) writes `/phone/cleanup/<step>-<n>.json` after the owner's Approve in Mission Control; the control loop runs each once (`cleanup_do`: delete by age at a `deletable()` path, uninstall a third-party app, trim caches) with `guard(acting=False)`'s Stop/lock/block-list checks, and writes `<step>-<n>.result.json` (ok, text, bytes freed). Never anything else from that folder.

# images/browser/: the scout's browser

Playwright MCP (`@playwright/mcp`, pinned in the `Dockerfile`, headless Chromium, in-memory profile) on
`127.0.0.1:8931`, behind `guard.py`, the only MCP server LiteLLM sees (`browser:8000`, `mcp_servers.browser`, granted
to `vk-scout` only in `ops/keys.sh`). Guard tools: `browse_open`, `browse_look`, `browse_click`, `browse_search`,
`browse_back`. The research adapter (`images/research`) tells the scout to use them for shops and prices; shopping
missions (`ops/shopping.py`) reach it only through `research`.

## Rules

- It only looks. Keep the guard's refusals: login/account/cart/checkout/payment URLs (before and after every step),
  buy/cart/order/sign-in buttons, typing outside search fields, personal data in searches.
- Never grant it to a key whose agent holds private data (main, mission): page content is untrusted, and a browser
  is a way out. The scout has no private data; the research adapter filters what goes out.
- Isolation like `images/fetch`: `webonly` network, `entrypoint.sh` egress firewall against private/LAN/Tailscale
  ranges, unprivileged user. No bot-detection evasion: a shop with a bot check is skipped.
- One upstream session, owned by one task (`upstream()`): anyio cancel scopes forbid sharing a client session
  across request tasks, and a new session would lose the open page.

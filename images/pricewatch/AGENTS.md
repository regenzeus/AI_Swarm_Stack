# images/pricewatch/: the shopping agents' price watch

changedetection.io (Apache-2.0, upstream image pinned by digest as `PRICEWATCH_IMAGE` in `versions.env`) re-reads
the offer pages of open purchase proposals (`restock_diff`: price and stock from the page's schema.org data). The
runner talks to it through `ops/pricewatch.py` on `127.0.0.1:8095` (API key from its datastore,
`/srv/ai/pricewatch`), and `ops/shopping.py` decides and reports. Design: `docs/SHOPPING.md`.

## Rules

- Sealed like `images/browser`: network `pricenet` only, `entrypoint.sh` installs the egress firewall against
  private/LAN/Tailscale ranges, then drops every capability. Keep `read_only`, `tmpfs /tmp`, the memory limit.
- No notifications: never configure notification URLs, apprise or Telegram here. Reporting is the runner's job.
- Plain HTTP fetcher only (no Playwright/Chrome sidecar): small and without a browser on the internet.
- Upstream runs as root; under rootless Docker that is the unprivileged host user, and all capabilities are dropped.
- Bump the tag (`aistack/pricewatch:<upstream version>`) together with `PRICEWATCH_IMAGE`; pick a release at least
  two weeks old.

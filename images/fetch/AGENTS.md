# images/fetch/: the isolated page reader

`mcp-server-fetch` (URL → markdown) behind `mcp-proxy`, with `fetch_pdf.py` adding full PDF reading (pypdf):
annual reports, ASX announcements and SEC filings. For sec.gov it sends the `SEC_CONTACT` user agent, which SEC
requires. `entrypoint.sh` sets up the egress firewall before starting.

The container sits on its own network with internet access but **no route to the LAN or Tailscale ranges**.
Only the scout (through the research tool) uses it.

## Rules

- The egress firewall in `entrypoint.sh` is a security boundary: never widen it.
- Output size is capped (`max_length`). Keep long documents paged, not unbounded.
- Pins: `mcp-server-fetch`, `mcp-proxy`, `pypdf` in the `Dockerfile` (see the comment in `versions.env`).

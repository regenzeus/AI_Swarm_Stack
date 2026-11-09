# Page reader for the scout: mcp-server-fetch (URL -> markdown; PDFs -> text via fetch_pdf.py + pypdf) published
# over MCP streamable HTTP by mcp-proxy.
# Defence against prompt-injected SSRF, two layers:
#  1. Network: on "webonly" it can reach the internet and LiteLLM only (not qmd, Phoenix, Hermes).
#  2. Firewall (entrypoint.sh): outbound traffic to private/LAN/Tailscale/link-local ranges is rejected,
#     so the NAS, router and other home devices are unreachable. Rules are set as root at start; the
#     server then runs as an unprivileged user that cannot change them.
FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends iptables util-linux && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir mcp-server-fetch==2026.8.18 mcp-proxy==0.13.0 pypdf==5.1.0 \
 && useradd -r -u 10001 fetch
COPY entrypoint.sh /entrypoint.sh
COPY fetch_pdf.py /app/fetch_pdf.py
# The federal job board's search (jobs.py, MCP on 8001): same network, firewall and user as the page reader
COPY jobs.py /app/jobs.py
EXPOSE 8000 8001
ENTRYPOINT ["sh", "/entrypoint.sh"]

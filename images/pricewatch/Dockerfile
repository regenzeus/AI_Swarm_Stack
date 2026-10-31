# The shopping agents' price watch: changedetection.io (Apache-2.0, https://github.com/dgtlmoon/changedetection.io),
# pinned by digest in versions.env (PRICEWATCH_IMAGE). Sealed like images/browser: entrypoint.sh installs an egress
# firewall against private/LAN/Tailscale ranges and then drops every capability. No notifications are configured (no
# Telegram, no apprise): ops/pricewatch.py reads its API and the runner reports. Plain HTTP fetcher, no browser.
ARG PRICEWATCH_IMAGE
FROM ${PRICEWATCH_IMAGE}
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends iptables && rm -rf /var/lib/apt/lists/*
COPY entrypoint.sh /pricewatch-entrypoint.sh
ENTRYPOINT ["sh", "/pricewatch-entrypoint.sh"]

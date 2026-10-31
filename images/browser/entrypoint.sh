#!/bin/sh
set -e
# Same egress firewall as images/fetch: replies to LiteLLM and Docker DNS stay allowed; new outbound connections
# to private, LAN, Tailscale and link-local ranges are rejected, so pages cannot reach the NAS, router or tailnet.
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -d 127.0.0.11 -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -d 127.0.0.11 -p tcp --dport 53 -j ACCEPT
for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16 127.0.0.0/8 0.0.0.0/8 224.0.0.0/4; do
  iptables -A OUTPUT -d "$net" -j REJECT
done
ip6tables -A OUTPUT -o lo -j ACCEPT 2>/dev/null || true
ip6tables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || true
for net in fc00::/7 fe80::/10 ::1/128; do ip6tables -A OUTPUT -d "$net" -j REJECT 2>/dev/null || true; done
echo "egress firewall: private ranges blocked"
# Playwright MCP on loopback only (the guard is the door); then the guard for LiteLLM. Both unprivileged.
setpriv --reuid=browser --regid=browser --init-groups --inh-caps=-all --bounding-set=-all \
  env HOME=/home/browser playwright-mcp --headless --isolated --no-sandbox --browser chromium --host 127.0.0.1 --port 8931 \
  --allowed-hosts 127.0.0.1:8931 --viewport-size 1280x2000 &
exec setpriv --reuid=browser --regid=browser --init-groups --inh-caps=-all --bounding-set=-all \
  env HOME=/home/browser /opt/guard/bin/python /app/guard.py

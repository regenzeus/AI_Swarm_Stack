#!/bin/sh
set -e
# Replies to inbound MCP requests (from LiteLLM) and Docker DNS stay allowed; new outbound connections to
# private ranges are rejected.
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
# the job board search (jobs.py, port 8001) beside the page reader, same user and firewall; restarted if it stops
( while true; do
    setpriv --reuid=fetch --regid=fetch --init-groups --inh-caps=-all --bounding-set=-all python /app/jobs.py
    echo "jobs server stopped; restarting in 5 s"; sleep 5
  done ) &
exec setpriv --reuid=fetch --regid=fetch --init-groups --inh-caps=-all --bounding-set=-all \
  mcp-proxy --host 0.0.0.0 --port 8000 -- python /app/fetch_pdf.py

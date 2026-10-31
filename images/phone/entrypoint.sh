#!/bin/sh
set -e
# The AI phone's firewall: new outbound connections may go to the one phone (PHONE_HOST) and Docker DNS only;
# replies to LiteLLM's MCP requests stay allowed. No internet, no LAN, no other Tailscale device.
[ -n "$PHONE_HOST" ] || { echo "PHONE_HOST not set"; exit 1; }
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -d 127.0.0.11 -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -d 127.0.0.11 -p tcp --dport 53 -j ACCEPT
iptables -A OUTPUT -d "$PHONE_HOST" -p tcp -j ACCEPT
iptables -A OUTPUT -j REJECT
ip6tables -A OUTPUT -o lo -j ACCEPT 2>/dev/null || true
ip6tables -A OUTPUT -j REJECT 2>/dev/null || true
echo "egress firewall: only $PHONE_HOST"
mkdir -p /phone/home && chown phone:phone /phone/home && chmod 700 /phone/home   # the ADB pairing key: this user only
exec setpriv --reuid=phone --regid=phone --init-groups --inh-caps=-all --bounding-set=-all \
  env HOME=/phone/home python /app/phone.py

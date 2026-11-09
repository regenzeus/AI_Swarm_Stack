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
# IPv6: each rule must hold, unless the container has no IPv6 address beyond loopback (review CNX-R13: `|| true` hid a
# missing IPv6 firewall).
v6() {
  ip6tables "$@" 2>/dev/null && return 0
  if awk '$6 != "lo" {f=1} END {exit !f}' "${IF_INET6:-/proc/net/if_inet6}" 2>/dev/null; then
    echo "IPv6 firewall rule failed (ip6tables $*) and this container has IPv6: not starting"; exit 1
  fi
  echo "IPv6 firewall rule not set (ip6tables $*): this container has no IPv6 beyond loopback"
}
v6 -A OUTPUT -o lo -j ACCEPT
v6 -A OUTPUT -j REJECT
echo "egress firewall: only $PHONE_HOST"
mkdir -p /phone/home && chown phone:phone /phone/home && chmod 700 /phone/home   # the ADB pairing key: this user only
exec setpriv --reuid=phone --regid=phone --init-groups --inh-caps=-all --bounding-set=-all \
  env HOME=/phone/home python /app/phone.py

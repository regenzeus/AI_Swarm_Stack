#!/bin/sh
set -e
# The mail connector's firewall: new outbound connections only to IMAPS (993) and Docker DNS; replies to LiteLLM's
# MCP requests stay allowed. No web, no LAN, no Tailscale, no SMTP (this connector cannot send mail).
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -d 127.0.0.11 -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -d 127.0.0.11 -p tcp --dport 53 -j ACCEPT
for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16; do
  iptables -A OUTPUT -d "$net" -j REJECT
done
iptables -A OUTPUT -p tcp --dport 993 -j ACCEPT
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
v6 -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
v6 -A OUTPUT -p tcp --dport 993 -j ACCEPT
v6 -A OUTPUT -j REJECT
echo "egress firewall: IMAPS only"
exec setpriv --reuid=conn --regid=conn --init-groups --inh-caps=-all --bounding-set=-all python /app/mail.py

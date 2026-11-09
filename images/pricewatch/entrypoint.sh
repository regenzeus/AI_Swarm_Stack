#!/bin/sh
set -e
# Same egress firewall as images/browser: replies (the runner's API calls on the published port) and Docker DNS stay
# allowed; new outbound connections to private, LAN, Tailscale and link-local ranges are rejected, so a watched page
# cannot make it reach the NAS, the router, the tailnet or the other services.
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
# changedetection.io without any capability (rootless Docker: uid 0 here is the unprivileged host user).
cd /app
exec setpriv --inh-caps=-all --bounding-set=-all --no-new-privs python ./changedetection.py -d /datastore

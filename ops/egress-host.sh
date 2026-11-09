#!/usr/bin/env bash
# The outbound rule of a deployment with an egress list (GEN-14, docs/PLATFORM.md §5), applied as root:
#   wsl -d <distro> -u root -- bash <stack>/ops/egress-host.sh <user> [apply|remove|show]
# apply: the stack's user (and so, with rootless Docker, every container) may reach loopback, its DNS servers and the hosts
# of egress.txt; everything else it starts is refused. The rule lives in the kernel until WSL stops, so a work deployment
# runs this from /etc/wsl.conf's [boot] command and hourly (names resolve to new addresses), docs/PLATFORM.md §5.
# A deployment without an egress list (home) gets no rule: this script says so and changes nothing.
set -euo pipefail
U=${1:?usage: egress-host.sh <user> [apply|remove|show]}; MODE=${2:-apply}
cd "$(dirname "$0")/.."
[ "$(id -u)" = 0 ] || { echo "run as root (wsl -u root)" >&2; exit 2; }
CHAIN=AISTACK_EGRESS
remove() {
  while iptables -D OUTPUT -m owner --uid-owner "$U" -j "$CHAIN" 2>/dev/null; do :; done
  iptables -F "$CHAIN" 2>/dev/null || true; iptables -X "$CHAIN" 2>/dev/null || true
  while ip6tables -D OUTPUT -m owner --uid-owner "$U" -j REJECT 2>/dev/null; do :; done
  ip6tables -D OUTPUT -m owner --uid-owner "$U" -o lo -j ACCEPT 2>/dev/null || true
}
case "$MODE" in
  show) iptables -S "$CHAIN" 2>/dev/null || echo "no outbound rule"; exit 0 ;;
  remove) remove; echo "the outbound rule for $U is gone"; exit 0 ;;
  apply) ;;
  *) echo "usage: egress-host.sh <user> [apply|remove|show]" >&2; exit 2 ;;
esac
RULES=$(runuser -u "$U" -- python3 ops/dataguard.py rules "$U") || { echo "$RULES"; exit 1; }   # the user's own deployment
remove
printf '%s\n' "$RULES" | iptables-restore --noflush
# IPv6: loopback only (the egress hosts are reached over IPv4)
ip6tables -A OUTPUT -m owner --uid-owner "$U" -o lo -j ACCEPT
ip6tables -A OUTPUT -m owner --uid-owner "$U" -j REJECT
echo "outbound rule for $U: $(iptables -S "$CHAIN" | grep -c RETURN) allowed destinations, the rest refused"

#!/usr/bin/env bash
# Proves the outbound rule of ops/dataguard.py in a sandbox (GEN-14): a private user and network namespace (unshare -rn),
# where iptables changes nothing of the machine. Two listeners stand in for the internet: 127.0.0.2:8443 is on the egress
# list, 127.0.0.3:8443 is not. With the rule for this (namespace) user applied, the first answers and the second is refused;
# without it both answer, so the test can fail. No root, no change outside the namespace.
#   bash ops/egress-selftest.sh      exit 0: the rule holds; 77: this machine cannot make the sandbox (no unshare or iptables)
set -uo pipefail
cd "$(dirname "$0")/.."
command -v unshare >/dev/null && command -v iptables-restore >/dev/null || { echo "skipped: no unshare or iptables here"; exit 77; }
unshare -rn true 2>/dev/null || { echo "skipped: user namespaces are not allowed here"; exit 77; }
exec unshare -rn bash -c '
set -uo pipefail
ip link set lo up 2>/dev/null || { echo "skipped: no ip command"; exit 77; }
python3 - <<"EOF" &
import socket, threading
def serve(addr):
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind((addr, 8443)); s.listen()
    while True:
        c, _ = s.accept(); c.close()
for a in ("127.0.0.2", "127.0.0.3"):
    threading.Thread(target=serve, args=(a,), daemon=True).start()
threading.Event().wait(30)
EOF
sleep 1
probe() { python3 -c "import socket,sys; socket.create_connection((sys.argv[1], 8443), timeout=3)" "$1" 2>/dev/null && echo open || echo refused; }
before="$(probe 127.0.0.2) $(probe 127.0.0.3)"
python3 -c "
import sys; sys.path.insert(0, \"ops\")
import dataguard as DG
print(\"\n\".join(DG.rules(\"0\", [(\"127.0.0.2\", 8443)], resolve=lambda h, p: [h], dns=[], loopback=(\"127.0.0.1/32\",))))
" | iptables-restore --noflush || { echo "FAILED: the rule could not be applied"; exit 1; }
after="$(probe 127.0.0.2) $(probe 127.0.0.3)"
echo "without the rule: listed $(echo $before | cut -d" " -f1), unlisted $(echo $before | cut -d" " -f2)"
echo "with the rule:    listed $(echo $after | cut -d" " -f1), unlisted $(echo $after | cut -d" " -f2)"
[ "$before" = "open open" ] && [ "$after" = "open refused" ] && { echo "the outbound rule holds"; exit 0; }
echo "FAILED: the outbound rule does not hold"; exit 1
'

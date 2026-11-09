#!/usr/bin/env bash
# WSL's kernel keeps whole blocks of memory free (PLT-35). Runs as root, once; it persists and survives restarts:
#   wsl -d <distro> -u root -- bash <the stack's folder>/ops/wsl-memory.sh
# (ops/bootstrap-wsl-1-root.sh runs it on a new machine.)
#
# Why, found 9 Nov 2026: calls into WSL from Windows failed again and again with WSAETIMEDOUT. Each call opens a
# Hyper-V socket, and the kernel must allocate 512 KB of contiguous memory for its ring (an order-7 page block). With
# the memory fragmented (swap in use, caches dropped back to Windows often), that allocation failed:
#   page allocation failure: order:7 ... vmbus_alloc_ring ... hvs_probe
#   UtilAcceptVsock: accept4 failed 110
# so the call never got its channel. Three kernel settings keep such blocks available:
#   vm.min_free_kbytes          a larger free reserve (45 MB was the default here), so reclaim starts before it is tight
#   vm.watermark_scale_factor   reclaim wakes earlier and frees more at a time (2 % of memory instead of 0.1 %)
#   vm.compaction_proactiveness the kernel compacts memory in the background, keeping large blocks whole
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "refused: run as root (wsl -d <distro> -u root -- bash $0)" >&2; exit 1; }
CONF=/etc/sysctl.d/90-aistack-memory.conf
cat > "$CONF" <<'EOF'
# The AI Stack (PLT-35, ops/wsl-memory.sh): keep whole blocks of memory free, so a new channel into WSL can always get
# its ring. limit: waits, 256 MB stay free; reclaim starts earlier rather than later
vm.min_free_kbytes = 262144
vm.watermark_scale_factor = 200
vm.compaction_proactiveness = 50
EOF
sysctl -q -p "$CONF"
echo 1 > /proc/sys/vm/compact_memory            # once now, so the large blocks are back without waiting
big=$(awk '$4=="Normal" || $4=="DMA32" {for (i=12; i<=NF; i++) n+=$i} END {print n+0}' /proc/buddyinfo)   # order 7 and up
echo "WSL keeps whole blocks free: min_free $(sysctl -n vm.min_free_kbytes) kB, $big free blocks of 512 kB or more"

# The file cache goes back to Windows every 30 minutes. WSL's autoMemoryReclaim drops it only when WSL is idle, and the
# stack never is: on 9 Nov 2026 the programs used 2.6 GB, the cache held 4.3 GB, and Windows had 0.4 GB free. Dropped
# cache is free memory, which WSL hands back to Windows at once; the cost is reading some files from disk again.
cat > /etc/systemd/system/aistack-drop-cache.service <<'EOF'
[Unit]
Description=AI Stack: hand WSL's file cache back to Windows (PLT-35, ops/wsl-memory.sh)
[Service]
Type=oneshot
ExecStart=/bin/sh -c 'sync; echo 1 > /proc/sys/vm/drop_caches; echo 1 > /proc/sys/vm/compact_memory'
EOF
cat > /etc/systemd/system/aistack-drop-cache.timer <<'EOF'
[Unit]
Description=AI Stack: hand WSL's file cache back to Windows every 30 minutes (PLT-35)
[Timer]
OnBootSec=10min
# limit: paces, the cache goes back every 30 minutes; between drops it may grow again
OnUnitActiveSec=30min
[Install]
WantedBy=timers.target
EOF
if [ -d /run/systemd/system ]; then               # systemd runs (a working machine): start it now
  systemctl daemon-reload
  systemctl enable --now aistack-drop-cache.timer >/dev/null
  before=$(awk '/^(Buffers|Cached):/ {s+=$2} END {print int(s/1024)}' /proc/meminfo)
  systemctl start aistack-drop-cache.service
  after=$(awk '/^(Buffers|Cached):/ {s+=$2} END {print int(s/1024)}' /proc/meminfo)
  echo "file cache handed back to Windows: $before MB -> $after MB; again every 30 minutes"
else                                              # the bootstrap, before systemd: enabled for the first boot
  systemctl enable aistack-drop-cache.timer >/dev/null
fi

#!/bin/sh
# Prints "<errors> <rw|ro> <bytes>" for the root disk. Run as root by the Windows task ai-stack disk heal (ops/windows/disk-heal.ps1).
d=$(findmnt -no SOURCE / | sed s,/dev/,,)
n=$(dmesg | grep -cE "EXT4-fs (error|warning) \(device $d\)|EXT4-fs \($d\): .*(with errors|e2fsck recommended)|EXT4-fs \($d\): Remounting filesystem read-only")
echo "$n $(findmnt -no OPTIONS / | cut -d, -f1) $(blockdev --getsize64 /dev/$d)"

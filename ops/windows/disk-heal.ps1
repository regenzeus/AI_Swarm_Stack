# Self-healing check for the WSL disk of the AI stack (Ubuntu-24.04). Copy of ~/ai-stack/ops/windows/disk-heal.ps1.
# Runs as the normal user (no admin) from the task "ai-stack disk heal": at logon and every 15 minutes.
# Healthy -> nothing happens. If the kernel reported an ext4 error, or / went read-only (usually after the PC lost
# power or was switched off while WSL was running), it stops the stack, lets WSL check and repair the disk
# (`wsl --manage --resize` runs e2fsck -f -y before it resizes; the size grows by 1 GB, which is only the limit),
# starts everything again and reports on Telegram.   Test run: disk-heal.ps1 -Force
param([switch]$Force)
$distro = "Ubuntu-24.04"
$log = "C:\AI\logs\disk-heal.log"
function Log($m) { "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $m | Add-Content $log -Encoding utf8 }
function Clean($lines) { ($lines | ForEach-Object { "$_" -replace "`0", "" } | Where-Object { $_.Trim() }) -join "`n" }

$state = Clean (wsl.exe -d $distro -u root -e sh /home/owner/ai-stack/ops/disk-state.sh)
# Only an exact "<n> rw|ro <bytes>" answer counts. Anything else (e.g. a WSL timeout message) is not a disk
# problem: log it and do nothing. (2026-10-25: a timeout text was misread as a disk error and WSL was stopped.)
if ($state -notmatch '^(\d+) (rw|ro) (\d+)$') { Log "could not read disk state, nothing done: $($state -replace '\s+', ' ')"; exit 1 }
$errors, $mode, $bytes = $Matches[1], $Matches[2], $Matches[3]
if (-not $Force -and $errors -eq "0" -and $mode -eq "rw") { exit 0 }

Log "disk problem (errors=$errors, mounted $mode) - repairing"
wsl.exe -d $distro -u owner -e bash -lc "cd ~/ai-stack && docker compose -p aistack stop -t 20" | Out-Null
$size = "{0}MB" -f ([int64]$bytes / 1MB + 1024)
$ok = $false
foreach ($try in 1..3) {                      # e2fsck exits non-zero when it fixed something; the next pass is clean
    wsl.exe -d $distro -u root -e sync        # wsl --shutdown can drop writes of the last seconds (seen 2026-10-25)
    wsl.exe --shutdown
    $out = Clean (wsl.exe --manage $distro --resize $size)
    $rc = $LASTEXITCODE
    Log "pass $try (exit $rc):`n$out"
    if ($rc -eq 0) { $ok = $true; break }
}

Start-ScheduledTask "ai-stack WSL keepalive"
Start-Sleep 10
wsl.exe -d $distro -u owner -e bash -lc "cd ~/ai-stack && docker compose -p aistack start" | Out-Null
Start-Sleep 30
$after = Clean (wsl.exe -d $distro -u root -e sh /home/owner/ai-stack/ops/disk-state.sh)
$msg = if ($ok) { "Disk check: the WSL disk had an error (usually after the PC was switched off hard). Repaired automatically, the stack is running again. State now: $after" }
       else { "Disk check: the WSL disk has an error and the automatic repair did not finish. The stack may be read-only. Log: $log" }
Log $msg
wsl.exe -d $distro -u owner -e /home/owner/ai-stack/ops/notify.sh $msg | Out-Null

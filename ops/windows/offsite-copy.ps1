# Off-site copy of the nightly backup: OneDrive syncs it to Microsoft's cloud (the file is age-encrypted before it
# leaves WSL). Copy of ~/ai-stack/ops/windows/offsite-copy.ps1. Runs as the normal user from the task
# "ai-stack offsite copy" (daily 05:00 and at logon). Keeps the newest 7 in OneDrive\AI-Backup.
$src = "\\wsl.localhost\Ubuntu-24.04\srv\ai\backup-outbox"
$dst = "$env:USERPROFILE\OneDrive\AI-Backup"
$log = "C:\AI\logs\offsite-copy.log"
# limit: drops, a log over 1 MB becomes <log>.1 and the one before goes (review OPS-R17: no Windows log was rotated)
function Log($m) {
    if ((Test-Path $log) -and (Get-Item $log).Length -gt 1MB) { Move-Item $log "$log.1" -Force }
    "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), ("$m" -replace "`0", "") | Add-Content $log -Encoding utf8   # WSL's spaced UTF-16
}

if (-not (Get-Process OneDrive -ErrorAction SilentlyContinue)) {        # it is set to autostart, but had stopped
    Start-Process "C:\Program Files\Microsoft OneDrive\OneDrive.exe" -ArgumentList "/background"
    Log "OneDrive was not running - started it"
}
New-Item -ItemType Directory -Force $dst | Out-Null
$new = Get-ChildItem $src -Filter "aistack-*.tar.gz.age" -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
if (-not $new) { Log "no backup in the outbox"; exit 1 }
$final = Join-Path $dst $new.Name
if ((Test-Path $final) -and (Get-Item $final).Length -eq $new.Length) { exit 0 }
# A failed or short copy is no copy: it is not renamed, not logged as copied, and the next run tries again (review OPS-R12:
# a WSL timeout during Copy-Item went on to the rename and "copied", and the partial file then stopped every retry).
$part = Join-Path $dst ".$($new.Name).part"
$failed = $null
try {
    Copy-Item $new.FullName $part -Force -ErrorAction Stop
    $got = (Get-Item $part -ErrorAction Stop)
    if ($got.PSIsContainer -or $got.Length -ne $new.Length) { throw "copied $($got.Length) of $($new.Length) bytes" }
    Move-Item $part $final -Force -ErrorAction Stop
} catch { $failed = $_.Exception.Message -replace '\s+', ' ' }
if ($failed) {                    # outside the catch: an error while cleaning up cannot skip the exit (seen in a dry run)
    Log ("copy of {0} FAILED, nothing kept: {1}" -f $new.Name, $failed)
    try { Remove-Item $part -Force -ErrorAction Stop } catch { Log "and its partial file stays: $($_.Exception.Message)" }
    exit 1
}
Get-ChildItem $dst -Filter "aistack-*.tar.gz.age" | Sort-Object Name -Descending | Select-Object -Skip 7 | Remove-Item -Force
Log ("copied {0} ({1:N0} MB) to OneDrive" -f $new.Name, ($new.Length / 1MB))

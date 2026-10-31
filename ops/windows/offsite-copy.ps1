# Off-site copy of the nightly backup: OneDrive syncs it to Microsoft's cloud (the file is age-encrypted before it
# leaves WSL). Copy of ~/ai-stack/ops/windows/offsite-copy.ps1. Runs as the normal user from the task
# "ai-stack offsite copy" (daily 05:00 and at logon). Keeps the newest 7 in OneDrive\AI-Backup.
$src = "\\wsl.localhost\Ubuntu-24.04\srv\ai\backup-outbox"
$dst = "$env:USERPROFILE\OneDrive\AI-Backup"
$log = "C:\AI\logs\offsite-copy.log"
function Log($m) { "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $m | Add-Content $log -Encoding utf8 }

if (-not (Get-Process OneDrive -ErrorAction SilentlyContinue)) {        # it is set to autostart, but had stopped
    Start-Process "C:\Program Files\Microsoft OneDrive\OneDrive.exe" -ArgumentList "/background"
    Log "OneDrive was not running - started it"
}
New-Item -ItemType Directory -Force $dst | Out-Null
$new = Get-ChildItem $src -Filter "aistack-*.tar.gz.age" -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
if (-not $new) { Log "no backup in the outbox"; exit 1 }
if (Test-Path (Join-Path $dst $new.Name)) { exit 0 }
Copy-Item $new.FullName (Join-Path $dst ".$($new.Name).part") -Force
Move-Item (Join-Path $dst ".$($new.Name).part") (Join-Path $dst $new.Name) -Force
Get-ChildItem $dst -Filter "aistack-*.tar.gz.age" | Sort-Object Name -Descending | Select-Object -Skip 7 | Remove-Item -Force
Log ("copied {0} ({1:N0} MB) to OneDrive" -f $new.Name, ($new.Length / 1MB))

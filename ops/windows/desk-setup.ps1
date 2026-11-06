# Installs the Windows desk (PLT-31) and Remote Control at logon (PLT-32): run once, and again after a change to these
# scripts (no admin): it copies them to C:\AI\ops and restarts both tasks. It never overwrites desk-folders.txt.
param([string]$From = "\\wsl.localhost\Ubuntu-24.04\home\owner\ai-stack\ops\windows")
$ops = "C:\AI\ops"
New-Item -ItemType Directory -Force $ops | Out-Null
foreach ($f in "desk.ps1", "desk-common.ps1", "desk-settings.json", "claude-remote.ps1", "desk-signin.ps1", "hidden.vbs") {
  Copy-Item -Force -LiteralPath (Join-Path $From $f) (Join-Path $ops $f)
}
if (-not (Test-Path -LiteralPath "$ops\desk-folders.txt")) {
  $lines = @("# The folders Claude on this PC may read when your assistant asks. One per line; the first is the default.",
    "# Only you can change this file: the stack cannot write to C:.")
  if (Test-Path -LiteralPath "C:\Programming") { $lines += "C:\Programming" }
  $lines | Set-Content -Encoding utf8 "$ops\desk-folders.txt"
}
$me = "$env:USERDOMAIN\$env:USERNAME"
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -Hidden -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
foreach ($t in @(@("ai-stack Windows desk", "desk.ps1"), @("ai-stack Claude remote", "claude-remote.ps1"))) {
  $action = New-ScheduledTaskAction -Execute "C:\Windows\System32\wscript.exe" -Argument "`"$ops\hidden.vbs`" `"$ops\$($t[1])`""
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $me
  Register-ScheduledTask -TaskName $t[0] -Action $action -Trigger $trigger -Settings $set -Force | Out-Null
  Stop-ScheduledTask -TaskName $t[0] -ErrorAction SilentlyContinue
  Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -match [regex]::Escape("$ops\$($t[1])") } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-ScheduledTask -TaskName $t[0]
}
Write-Output "Installed: ai-stack Windows desk, ai-stack Claude remote. Allowed folders: $ops\desk-folders.txt"

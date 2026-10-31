# Windows host setup for the ai-stack (run once in a normal PowerShell; no admin needed).
# 1) WSL must not idle-shut down, or every container stops with it.
@'
[general]
instanceIdleTimeout=-1

[wsl2]
localhostForwarding=true
vmIdleTimeout=-1
'@ | Out-File -Encoding ascii "$env:USERPROFILE\.wslconfig"

# 2) Start WSL (and with it rootless Docker and the stack) at logon, hidden.
$action  = New-ScheduledTaskAction -Execute "C:\Windows\System32\wsl.exe" -Argument "-d Ubuntu-24.04 -u owner -e sleep infinity"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$set     = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -Hidden
Register-ScheduledTask -TaskName "ai-stack WSL keepalive" -Action $action -Trigger $trigger -Settings $set -Force | Out-Null

# 3) Publish Open WebUI on the tailnet only (Serve must be enabled once in the Tailscale admin).
& "C:\Program Files\Tailscale\tailscale.exe" serve --bg --https=443 http://127.0.0.1:3080

# Windows host setup for the ai-stack (run once in a normal PowerShell; no admin needed).
# 1) WSL must not idle-shut down, or every container stops with it.
#    10 of 16 GB of RAM for WSL, and a 16 GB swap on an SSD with room (PLT-27): the memory of idle services moves
#    to disk instead of crowding the work. Point swapFile at the drive with the most free space (the PC of 2 Nov 2026:
#    F:); its folder must exist.
@'
[general]
instanceIdleTimeout=-1

[wsl2]
memory=10GB
swap=16GB
swapFile=F:\\wsl-swap\\swap.vhdx
localhostForwarding=true
vmIdleTimeout=-1

[experimental]
autoMemoryReclaim=dropCache
'@ | Out-File -Encoding ascii "$env:USERPROFILE\.wslconfig"
New-Item -ItemType Directory -Force F:\wsl-swap | Out-Null

# 2) Start WSL (and with it rootless Docker and the stack) at logon, hidden.
$action  = New-ScheduledTaskAction -Execute "C:\Windows\System32\wsl.exe" -Argument "-d Ubuntu-24.04 -u owner -e sleep infinity"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$set     = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -Hidden
Register-ScheduledTask -TaskName "ai-stack WSL keepalive" -Action $action -Trigger $trigger -Settings $set -Force | Out-Null

# 3) Publish Open WebUI on the tailnet only (Serve must be enabled once in the Tailscale admin).
& "C:\Program Files\Tailscale\tailscale.exe" serve --bg --https=443 http://127.0.0.1:3080

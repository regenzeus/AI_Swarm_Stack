# Sets up the Windows worker (GEN-11, DEC-45, docs/PLATFORM.md section 6). The owner runs it once, as administrator:
#   powershell -NoProfile -ExecutionPolicy Bypass -File worker-setup.ps1 [-Owner <your Windows user>] [-DryRun]
# It makes the local standard account aiworker (you type its password; it is stored only by Windows for the task), the
# folders of C:\AIWorker with who may do what in each, the task "ai-stack worker" (as aiworker, at startup) and the task
# "ai-stack worker broker" (as you, at logon, hidden). It approves no job kind: that is worker-approve.ps1, per kind.
# -DryRun prints every step and changes nothing.
param([string]$Owner = $env:USERNAME, [string]$Root = "C:\AIWorker", [string]$Account = "aiworker", [switch]$DryRun)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
function Step($what, [scriptblock]$do) { Write-Host "- $what"; if (-not $DryRun) { & $do } }

if (-not $DryRun) {
  $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  if (-not $admin) { Write-Host "Run this as administrator (right-click PowerShell, Run as administrator)."; exit 1 }
}
Write-Host "The Windows worker: the account $Account, the folders of $Root, the owner $Owner."

# 1. The account: standard, not an administrator, hidden from the sign-in screen.
if (-not (Get-LocalUser -Name $Account -ErrorAction SilentlyContinue)) {
  Step "make the local standard account $Account (you type its password; nobody else needs it)" {
    $pw = Read-Host -AsSecureString "A password for $Account"
    $script:Password = $pw
    New-LocalUser -Name $Account -Password $pw -PasswordNeverExpires -UserMayNotChangePassword -AccountNeverExpires -Description "ai-stack Windows worker: runs declared jobs only" | Out-Null
    Add-LocalGroupMember -Group (Get-LocalGroup -SID "S-1-5-32-545").Name -Member $Account          # Users
  }
} else { Write-Host "- the account $Account is there already" }
Step "make sure $Account is in no administrators group" {
  $adm = (Get-LocalGroup -SID "S-1-5-32-544").Name
  if (Get-LocalGroupMember -Group $adm | Where-Object { $_.Name -like "*\$Account" }) { throw "$Account is an administrator: remove it from $adm first" }
}
Step "hide $Account from the sign-in screen" {
  $k = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList"
  New-Item -Force $k | Out-Null; New-ItemProperty -Path $k -Name $Account -Value 0 -PropertyType DWord -Force | Out-Null
}

# 2. The folders, and who may do what in each (no inheritance from C:\).
$rules = [ordered]@{
  "bin"     = @("${Owner}:(OI)(CI)M", "${Account}:(OI)(CI)RX")    # the worker's script: the owner's, the account reads it
  "jobs.d"  = @("${Owner}:(OI)(CI)M", "${Account}:(OI)(CI)RX")    # the job kinds: the owner writes them
  "inbox"   = @("${Owner}:(OI)(CI)M", "${Account}:(OI)(CI)RX")    # the broker writes, the worker reads
  "outbox"  = @("${Account}:(OI)(CI)M", "${Owner}:(OI)(CI)RX")    # the worker writes, the broker reads
  "repos"   = @("${Account}:(OI)(CI)M", "${Owner}:(OI)(CI)RX")    # the worker's own clones
  "scratch" = @("${Account}:(OI)(CI)M", "${Owner}:(OI)(CI)RX")    # one folder per job, deleted after it
  "home"    = @("${Account}:(OI)(CI)M")                           # the account's own settings
}
Step "make $Root with only SYSTEM and administrators inheriting" {
  New-Item -ItemType Directory -Force $Root | Out-Null
  & icacls $Root /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "${Owner}:RX" "${Account}:RX" | Out-Null
}
foreach ($d in $rules.Keys) {
  Step "$Root\$d : $($rules[$d] -join ', ')" {
    $p = Join-Path $Root $d
    New-Item -ItemType Directory -Force $p | Out-Null
    & icacls $p /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" @($rules[$d]) | Out-Null
  }
}
Step "$Root\approved.json: the owner writes it, $Account reads it" {
  $f = Join-Path $Root "approved.json"
  if (-not (Test-Path -LiteralPath $f)) { [IO.File]::WriteAllText($f, "{}") }
  & icacls $f /inheritance:r /grant:r "*S-1-5-18:F" "*S-1-5-32-544:F" "${Owner}:M" "${Account}:R" | Out-Null
}
Step "copy worker.ps1 into $Root\bin" { Copy-Item -LiteralPath (Join-Path $here "worker.ps1") (Join-Path $Root "bin\worker.ps1") -Force }

# 3. The tasks.
$ps = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
Step "the task 'ai-stack worker': worker.ps1 as $Account, at startup, restarted when it stops" {
  $action = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Root\bin\worker.ps1`" -Root `"$Root`""
  $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
  $pw = $script:Password
  if (-not $pw) { $pw = Read-Host -AsSecureString "The password of $Account (for its task)" }
  $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw))
  Register-ScheduledTask -TaskName "ai-stack worker" -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $settings `
    -User $Account -Password $plain -RunLevel Limited -Force | Out-Null
  $plain = $null
  Start-ScheduledTask -TaskName "ai-stack worker"
}
Step "the task 'ai-stack worker broker': worker-broker.ps1 as $Owner, at logon, hidden" {
  Copy-Item -LiteralPath (Join-Path $here "worker-broker.ps1") "C:\AI\ops\worker-broker.ps1" -Force
  $action = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"C:\AI\ops\worker-broker.ps1`" -Root `"$Root`""
  $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
  Register-ScheduledTask -TaskName "ai-stack worker broker" -Action $action -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $Owner) -Settings $settings `
    -User $Owner -RunLevel Limited -Force | Out-Null
  Start-ScheduledTask -TaskName "ai-stack worker broker"
}

Write-Host @"

Done. Still to do, by you:
  1. Each job kind: put its JSON into $Root\jobs.d and approve it: worker-approve.ps1 <kind> (as yourself, not as admin).
  2. The worker's clones: sign in as $Account once (runas /user:$Account cmd) and clone each repository into $Root\repos,
     with its own read access (a token of its own, never yours). Maven settings go to $Account's own %USERPROFILE%\.m2.
  3. The network: limit what $Account can reach to the repository and package servers. On a company PC that is IT's
     to set (docs/WORK-APPROVALS.md, item 3); this script does not change the firewall.
  4. Check it: worker-selftest.ps1 -Worker $Root\bin\worker.ps1 (as ${Account}, with runas /user:${Account}).
"@

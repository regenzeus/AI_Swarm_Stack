# The one step only you can do, once: sign Claude Code in on this PC with your subscription and trust the first allowed
# folder. Run it in a normal PowerShell: powershell -ExecutionPolicy Bypass -File C:\AI\ops\desk-signin.ps1
. "$PSScriptRoot\desk-common.ps1"
$exe = Find-Claude
if (-not $exe) { Write-Output "Claude Code was not found: open the Claude desktop app once, then run this again."; exit 1 }
$folders = Get-Folders
& $exe auth login
if ($folders.Count) {
  Write-Output "Next, Claude opens in $($folders[0]). Accept the folder trust question, turn on Remote Control if it asks, then type /exit."
  Set-Location -LiteralPath $folders[0]
  & $exe
}
Write-Output "Done. Within 10 minutes your assistant can ask Claude on this PC, and the phone has a session called Windows PC."

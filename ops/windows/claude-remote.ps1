# Keeps one `claude remote-control` running at logon, so the phone always has a way in to this PC (PLT-32). Started hidden by
# the task "ai-stack Claude remote". It starts new sessions in the first folder of desk-folders.txt and asks for your OK as
# usual: no permission flags. It cannot bring back old sessions of the desktop app. Its connection link is never logged.
. "$PSScriptRoot\desk-common.ps1"
$single = New-Object System.Threading.Mutex($false, "Local\aistack-claude-remote")
if (-not $single.WaitOne(0)) { exit 0 }
$wait = 30
while ($true) {
  $exe = Find-Claude
  $folders = Get-Folders
  if ($exe -and $folders.Count) {
    $t0 = Get-Date
    try {
      $p = Start-Process -FilePath $exe -ArgumentList 'remote-control --name "Windows PC"' -WorkingDirectory $folders[0] -WindowStyle Hidden -PassThru
      $p.WaitForExit()
      Write-DeskLog "claude-remote" "ended with code $($p.ExitCode) after $([int]((Get-Date) - $t0).TotalSeconds) s"
    } catch { Write-DeskLog "claude-remote" "error: $($_.Exception.Message)" }
    if (((Get-Date) - $t0).TotalSeconds -ge 120) { $wait = 30 }   # it ran fine for a while: start again soon
  } else { Write-DeskLog "claude-remote" "waiting: no Claude Code or no folder in desk-folders.txt" }
  Start-Sleep -Seconds $wait
  $wait = [math]::Min($wait * 2, 300)                             # signed out or no network: every 5 minutes at most
}

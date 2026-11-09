# Re-points every "ai-stack *" scheduled task that runs a PowerShell script to hidden.vbs, so none opens a window or
# takes the focus. Run once after copying ops/windows to C:\AI\ops (and again after registering a new task):
#   powershell -ExecutionPolicy Bypass -File C:\AI\ops\hide-tasks.ps1
$vbs = Join-Path $PSScriptRoot 'hidden.vbs'
if (-not (Test-Path $vbs)) { throw "hidden.vbs is not next to this script ($vbs)" }
$wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
foreach ($t in Get-ScheduledTask -TaskName 'ai-stack *') {
    $a = $t.Actions[0]
    if ($a.Execute -notmatch 'powershell(\.exe)?$') { "kept    $($t.TaskName) ($($a.Execute))"; continue }
    if ($a.Arguments -notmatch '-File\s+"?([^"]+?\.ps1)"?(\s+(.*))?$') { "skipped $($t.TaskName): no -File script in its arguments"; continue }
    $arg = "`"$vbs`" `"$($Matches[1])`"" + $(if ($Matches[3]) { " $($Matches[3])" } else { '' })
    Set-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Action (New-ScheduledTaskAction -Execute $wscript -Argument $arg) | Out-Null
    "hidden  $($t.TaskName) -> $arg"
}

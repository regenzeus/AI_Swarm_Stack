# The owner's tap for a job kind of the Windows worker (GEN-11, DEC-45): shows the kind's definition and, on "yes", writes
# the SHA-256 of its file into C:\AIWorker\approved.json. Editing the definition later changes its hash, and the kind stops
# until it is approved again. Run by the owner, in the owner's own account (the worker's account may only read the file).
#   powershell -NoProfile -ExecutionPolicy Bypass -File worker-approve.ps1 <kind> [-Root C:\AIWorker] [-Revoke]
param([Parameter(Mandatory = $true)][string]$Kind, [string]$Root = "C:\AIWorker", [switch]$Revoke)
$ErrorActionPreference = "Stop"
$Utf8 = New-Object System.Text.UTF8Encoding($false)
$file = Join-Path $Root "jobs.d\$Kind.json"
$appr = Join-Path $Root "approved.json"
$current = @{}
if (Test-Path -LiteralPath $appr) { foreach ($p in ([IO.File]::ReadAllText($appr, $Utf8) | ConvertFrom-Json).PSObject.Properties) { $current[$p.Name] = "$($p.Value)" } }
if ($Revoke) {
  $current.Remove($Kind) | Out-Null
  [IO.File]::WriteAllText($appr, ($current | ConvertTo-Json -Compress), $Utf8)
  Write-Host "$Kind is no longer approved."
  exit 0
}
if (-not (Test-Path -LiteralPath $file)) { Write-Host "There is no job kind $Kind ($file)."; exit 1 }
Write-Host "The job kind $Kind, as the worker will run it:`n"
Write-Host ([IO.File]::ReadAllText($file, $Utf8))
Write-Host "`nEach step runs as the account aiworker, in a scratch copy, with the values of a request checked by their types."
Write-Host "Code a patch changes runs in the build. Approve this kind? Type yes to approve."
if ((Read-Host) -ne "yes") { Write-Host "Not approved."; exit 1 }
$current[$Kind] = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText($appr, ($current | ConvertTo-Json -Compress), $Utf8)
Write-Host "$Kind is approved (sha256 $($current[$Kind]))."

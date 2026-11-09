# The Windows worker's broker (GEN-11, DEC-45, docs/PLATFORM.md section 6). A hidden loop under the owner's own account,
# started at logon by the task "ai-stack worker broker". Only the owner's account can read WSL (\\wsl.localhost), and the
# job must not run as the owner, so this carries files between the two and runs nothing:
#   WSL requests\<id>\  -> checked (its shape, names, sizes, age) -> C:\AIWorker\inbox\<id>\   (the worker may only read it)
#   C:\AIWorker\outbox\  -> C:\AI\exports\.host\worker\                                         (WSL reads it, read-only)
#   worker-broker.ps1 [-Requests <WSL folder>] [-Root C:\AIWorker] [-Exports C:\AI\exports\.host\worker] [-Once]
param([string]$Requests = "\\wsl.localhost\Ubuntu-24.04\srv\ai\state\winworker\requests", [string]$Root = "C:\AIWorker",
      [string]$Exports = "C:\AI\exports\.host\worker", [switch]$Once)
$ErrorActionPreference = "Stop"
$Utf8 = New-Object System.Text.UTF8Encoding($false)
$Inbox = Join-Path $Root "inbox"; $Outbox = Join-Path $Root "outbox"
$IdRx = '^[a-f0-9]{12}$'; $NameRx = '^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$'
$RequestKb = 1100         # limit: refuses, a request's files in all (a patch of at most 1 MB, and its request.json)
$Pending = 20             # limit: waits, requests waiting in the inbox; more stay in WSL until one is done
$StaleS = 3600            # limit: refuses, a request older than this was left from before a sleep
$CopyMb = 60              # limit: drops, an answer's files past this are not copied to WSL; its result names them
$KeepDays = 7

function Now-Unix { [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() }
function Save-Json($path, $obj) {
  New-Item -ItemType Directory -Force (Split-Path $path) | Out-Null
  $tmp = "$path.tmp"; [IO.File]::WriteAllText($tmp, ($obj | ConvertTo-Json -Depth 8 -Compress), $Utf8); Move-Item -Force -LiteralPath $tmp $path
}
function Refuse($id, $why) {
  Save-Json (Join-Path $Exports "$id\result.json") ([ordered]@{ id = $id; status = "refused"; error = "the broker refused it: $why"; steps = @(); artifacts = @(); ended = (Now-Unix) })
}

# One request from WSL: checked, copied into the inbox whole (a temporary name, then renamed), and removed from WSL.
function Carry($dir) {
  $id = $dir.Name
  $files = @(Get-ChildItem -LiteralPath $dir.FullName -Force)
  $why = $null
  if ($files | Where-Object { $_.PSIsContainer -or ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) }) { $why = "a request holds files only" }
  elseif ($files | Where-Object { $_.Name -notmatch $NameRx }) { $why = "a file name of the request is not plain" }
  elseif (-not ($files | Where-Object { $_.Name -eq "request.json" })) { $why = "no request.json" }
  elseif ((($files | Measure-Object Length -Sum).Sum) -gt $RequestKb * 1024) { $why = "its files are over $RequestKb KB" }
  else {
    try { $req = [IO.File]::ReadAllText((Join-Path $dir.FullName "request.json"), $Utf8) | ConvertFrom-Json } catch { $req = $null }
    if (-not $req) { $why = "request.json is no JSON" }
    elseif ("$($req.id)" -ne $id) { $why = "its id is not its folder's" }
    elseif ((Now-Unix) - [double]$req.at -gt $StaleS) { $why = "it waited over an hour" }
  }
  if ($why) { Refuse $id $why }
  else {
    $tmp = Join-Path $Inbox ".tmp-$id"
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force }
    New-Item -ItemType Directory -Force $tmp | Out-Null
    foreach ($f in $files) { Copy-Item -LiteralPath $f.FullName (Join-Path $tmp $f.Name) }
    Rename-Item -LiteralPath $tmp $id
  }
  Remove-Item -LiteralPath $dir.FullName -Recurse -Force
}

# The worker's answers, mirrored for WSL; a request whose result came back leaves the inbox.
function Mirror {
  if (-not (Test-Path -LiteralPath $Outbox)) { return }
  New-Item -ItemType Directory -Force $Exports | Out-Null
  $st = Join-Path $Outbox "status.json"
  if (Test-Path -LiteralPath $st) { Copy-Item -LiteralPath $st (Join-Path $Exports "status.json") -Force }
  foreach ($d in Get-ChildItem -LiteralPath $Outbox -Directory) {
    if ($d.Name -notmatch $IdRx) { continue }
    $dest = Join-Path $Exports $d.Name
    $done = Test-Path -LiteralPath (Join-Path $dest "result.json")
    if ($done -and $d.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays)) { continue }
    New-Item -ItemType Directory -Force $dest | Out-Null
    $size = 0
    foreach ($f in Get-ChildItem -LiteralPath $d.FullName -Recurse -File) {
      if ($f.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
      $size += $f.Length
      if ($size -gt $CopyMb * 1MB) { continue }
      $rel = $f.FullName.Substring($d.FullName.Length + 1)
      if ($rel -eq "result.json") { continue }                     # the result last: whoever reads it finds the rest there
      $to = Join-Path $dest $rel
      New-Item -ItemType Directory -Force (Split-Path $to) | Out-Null
      Copy-Item -LiteralPath $f.FullName $to -Force
    }
    $res = Join-Path $d.FullName "result.json"
    if (Test-Path -LiteralPath $res) {
      Copy-Item -LiteralPath $res (Join-Path $dest "result.json") -Force
      $in = Join-Path $Inbox $d.Name
      if (Test-Path -LiteralPath $in) { Remove-Item -LiteralPath $in -Recurse -Force }
    }
  }
  foreach ($d in Get-ChildItem -LiteralPath $Exports -Directory) {
    if ($d.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays)) { Remove-Item -LiteralPath $d.FullName -Recurse -Force }
  }
}

New-Item -ItemType Directory -Force $Inbox | Out-Null
$single = New-Object System.Threading.Mutex($false, "Local\aistack-worker-broker")
if (-not $Once -and -not $single.WaitOne(0)) { exit 0 }
while ($true) {
  try {
    Mirror
    if (Test-Path -LiteralPath $Requests) {
      $waiting = @(Get-ChildItem -LiteralPath $Inbox -Directory | Where-Object { $_.Name -match $IdRx }).Count
      foreach ($dir in (Get-ChildItem -LiteralPath $Requests -Directory | Sort-Object LastWriteTime)) {
        if ($dir.Name -notmatch $IdRx) { continue }                 # .tmp-<id>: the stack is still writing it
        if ($waiting -ge $Pending) { break }
        Carry $dir; $waiting++
      }
    }
  } catch { try { [IO.File]::AppendAllText((Join-Path $env:LOCALAPPDATA "ai-stack\worker-broker.log"), "$(Get-Date -Format s) $($_.Exception.Message)`n", $Utf8) } catch {} ; if ($Once) { throw } }
  if ($Once) { break }
  Start-Sleep -Seconds 3
}

# The Windows worker (GEN-11, DEC-45, docs/PLATFORM.md section 6). It runs as the local standard account aiworker, from the
# task "ai-stack worker" that worker-setup.ps1 registers, and it runs only what the owner declared and approved here:
#   - a job kind is a JSON file of jobs.d (written by the owner; the account may only read it);
#   - it runs only while approved.json holds its name with the SHA-256 of its file (worker-approve.ps1);
#   - every value of a request is checked by its parameter's type, a patch's paths against the kind's patch_paths;
#   - every step is an argument list, its values one argument each, never a command line someone wrote.
# The same rules as ops/winjobs.py (the stack's tests run them in ops/fakeworker.py); worker-selftest.ps1 checks this file.
#   worker.ps1 [-Root C:\AIWorker] [-Once]
param([string]$Root = "C:\AIWorker", [switch]$Once, [double]$MinuteS = 60, [int]$BeatS = 10)
$ErrorActionPreference = "Stop"
$Utf8 = New-Object System.Text.UTF8Encoding($false)
$Inbox = Join-Path $Root "inbox"; $Outbox = Join-Path $Root "outbox"; $Jobs = Join-Path $Root "jobs.d"
$Repos = Join-Path $Root "repos"; $Scratch = Join-Path $Root "scratch"
$IdRx = '^[a-f0-9]{12}$'; $KindRx = '^[a-z][a-z0-9.-]{0,63}$'; $NameRx = '^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$'; $ParamRx = '^[a-z][a-z0-9_]{0,31}$'
$Builtins = @("scratch", "repos", "patch", "out")
$Types = @("enum", "hex40", "int", "name", "file", "bool")
$StaleS = 3600            # limit: refuses, a request older than this was left from before a sleep
$ValueMax = 200           # limit: refuses, a value past this is no commit, name or number
$LogMax = 200000          # limit: drops, a log past this comes back as its end, with a marker
$ArtifactsMb = 50         # limit: drops, artifacts past this are left out, and the result names them
$Busy = @{}

function Now-Unix { [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() }
function Save-Json($path, $obj) {
  New-Item -ItemType Directory -Force (Split-Path $path) | Out-Null
  $tmp = "$path.tmp"
  [IO.File]::WriteAllText($tmp, ($obj | ConvertTo-Json -Depth 8 -Compress), $Utf8)
  Move-Item -Force -LiteralPath $tmp $path
}
function Read-Json($path) { try { return [IO.File]::ReadAllText($path, $Utf8) | ConvertFrom-Json } catch { return $null } }
function Has($obj, $name) { return $obj -and ($obj.PSObject.Properties.Name -contains $name) }
function Props($obj) { if ($obj) { return @($obj.PSObject.Properties) } else { return @() } }

# ---- a job kind and its approval
function Test-Kind($k) {
  $p = @()
  if (-not ("$($k.kind)" -match $KindRx)) { $p += "kind: a name of a-z, 0-9, . and -" }
  $params = @{}
  foreach ($prop in (Props $k.params)) {
    $n = $prop.Name; $d = $prop.Value; $params[$n] = $d
    if (-not ($n -match $ParamRx) -or ($Builtins -contains $n -and $n -ne "patch")) { $p += "parameter ${n}: a-z, 0-9 and _, and no built-in name" }
    if ($Types -notcontains "$($d.type)") { $p += "parameter ${n}: type $($d.type) is none of $($Types -join ', ')"; continue }
    if ($n -eq "patch" -and $d.type -ne "file") { $p += "parameter patch: the patch is a file parameter" }
    if ($d.type -eq "enum" -and -not (@($d.values).Count -and -not (@($d.values) | Where-Object { "$_" -notmatch $NameRx }))) { $p += "parameter ${n}: an enum needs values, each a plain name" }
    if ($d.type -eq "int" -and -not ((Has $d "min") -and (Has $d "max"))) { $p += "parameter ${n}: an int needs min and max" }
    if ($d.type -eq "name" -and -not ("$($d.from)" -match $NameRx)) { $p += "parameter ${n}: a name needs from" }
    if ($d.type -eq "file" -and -not (Has $d "max_kb")) { $p += "parameter ${n}: a file needs max_kb" }
  }
  $steps = @($k.steps)
  if (-not $steps.Count) { $p += "steps: a list of argument lists" }
  foreach ($s in $steps) {
    foreach ($a in @($s)) {
      foreach ($m in [regex]::Matches("$a", '\{([^{}]*)\}')) {
        $ref = $m.Groups[1].Value
        if (-not $params.ContainsKey($ref) -and $Builtins -notcontains $ref) { $p += "step $(@($s)[0]): {$ref} is no parameter of this kind" }
      }
    }
  }
  if ($params.ContainsKey("patch") -and -not (Has $k "patch_paths")) { $p += "a kind with a patch says which paths it may change (patch_paths)" }
  if (-not ($k.minutes -is [int] -and $k.minutes -gt 0 -and $k.minutes -le 1440)) { $p += "minutes: its time limit, 1 to 1440" }
  return $p
}

function Get-Kinds {
  $out = @{}
  if (-not (Test-Path -LiteralPath $Jobs)) { return $out }
  foreach ($f in Get-ChildItem -LiteralPath $Jobs -Filter *.json -File) {
    $sha = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLower()
    $k = Read-Json $f.FullName
    if (-not $k) { $out[$f.BaseName] = @{ k = $null; sha = $sha; problems = @("not JSON") }; continue }
    $p = @(Test-Kind $k)
    if ("$($k.kind)" -ne $f.BaseName) { $p += "the file is $($f.Name), the kind $($k.kind)" }
    $out[$f.BaseName] = @{ k = $k; sha = $sha; problems = $p }
  }
  return $out
}

function Get-Approvals { $a = Read-Json (Join-Path $Root "approved.json"); $h = @{}; foreach ($p in (Props $a)) { $h[$p.Name] = "$($p.Value)" }; return $h }

function Why-Not($kind, $kinds, $appr) {
  if (-not $kinds.ContainsKey($kind)) { return "no job kind $kind is declared on Windows" }
  $e = $kinds[$kind]
  if ($e.problems.Count) { return "the job kind $kind is not valid: $($e.problems -join '; ')" }
  if (-not $appr.ContainsKey($kind)) { return "the job kind $kind is not approved: the owner runs worker-approve.ps1 $kind on Windows" }
  if ($appr[$kind] -ne $e.sha) { return "the job kind $kind changed since its approval: the owner approves it again (worker-approve.ps1 $kind)" }
  return $null
}

function Get-Names {
  $n = @{}
  foreach ($d in Get-ChildItem -LiteralPath $Root -Directory) { $n[$d.Name] = @(Get-ChildItem -LiteralPath $d.FullName -Name) }
  return $n
}

# ---- a request's values, by type: -> @{ values = ...; why = ... }
function Test-Values($k, $values, $reqDir, $names) {
  $out = @{}
  $given = @{}; foreach ($p in (Props $values)) { $given[$p.Name] = $p.Value }
  $params = @{}; foreach ($p in (Props $k.params)) { $params[$p.Name] = $p.Value }
  $odd = @($given.Keys | Where-Object { -not $params.ContainsKey($_) } | Sort-Object)
  if ($odd.Count) { return @{ why = "values for no parameter: $($odd -join ', ')" } }
  foreach ($n in $params.Keys) {
    $d = $params[$n]
    if (-not $given.ContainsKey($n)) { return @{ why = "no value for $n" } }
    $v = $given[$n]
    if ($v -is [string] -and $v.Length -gt $ValueMax) { return @{ why = "$n is $($v.Length) characters; $ValueMax at most" } }
    switch ($d.type) {
      "enum"  { if (@($d.values) -cnotcontains "$v" -or -not ($v -is [string])) { return @{ why = "$n is '$v': one of $(@($d.values) -join ', ')" } } }
      "hex40" { if (-not ($v -is [string] -and $v -cmatch '^[0-9a-f]{40}$')) { return @{ why = "${n}: a commit, 40 lowercase hex characters" } } }
      "int"   { if (-not ($v -is [int] -or $v -is [long]) -or $v -lt $d.min -or $v -gt $d.max) { return @{ why = "${n}: a whole number from $($d.min) to $($d.max)" } }; $v = "$v" }
      "bool"  { if (-not ($v -is [bool])) { return @{ why = "${n}: true or false" } }; $v = if ($v) { "true" } else { "false" } }
      "name"  { if (-not ($v -is [string] -and $v -match $NameRx -and @($names["$($d.from)"]) -ccontains $v)) { return @{ why = "$n is '$v': one of the names in the worker's $($d.from) ($(@($names["$($d.from)"]) -join ', '))" } } }
      "file"  {
        if (-not ($v -is [string] -and $v -match $NameRx)) { return @{ why = "${n}: a file name of the request's own folder" } }
        $f = Join-Path $reqDir $v
        if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { return @{ why = "${n}: $v is not a file of the request" } }
        $it = Get-Item -LiteralPath $f
        if ($it.Attributes -band [IO.FileAttributes]::ReparsePoint) { return @{ why = "${n}: $v is a link" } }
        if ($it.Length -gt $d.max_kb * 1024) { return @{ why = "${n}: $v is $([int]($it.Length / 1024)) KB; $($d.max_kb) KB at most" } }
      }
    }
    $out[$n] = "$v"
  }
  return @{ values = $out }
}

# ---- a patch's paths
function Convert-Glob($g) {
  $rx = ""; $i = 0
  while ($i -lt $g.Length) {
    if ($g.Substring($i).StartsWith("**/")) { $rx += "(?:.*/)?"; $i += 3 }
    elseif ($g.Substring($i).StartsWith("**")) { $rx += ".*"; $i += 2 }
    elseif ($g[$i] -eq "*") { $rx += "[^/]*"; $i += 1 }
    elseif ($g[$i] -eq "?") { $rx += "[^/]"; $i += 1 }
    else { $rx += [regex]::Escape([string]$g[$i]); $i += 1 }
  }
  return "^$rx\z"
}

function Test-Patch($k, $text) {
  $paths = New-Object System.Collections.Generic.HashSet[string]
  foreach ($ln in ($text -split "`r?`n")) {
    if ($ln.StartsWith("GIT binary patch") -or $ln.StartsWith("Binary files ")) { return "the patch is refused: a binary patch" }
    if ($ln -match '^(?:new file mode|deleted file mode|old mode|new mode|index \S+) (?:120000|160000)\s*$' -or $ln.StartsWith("Subproject commit")) { return "the patch is refused: a symbolic link or a submodule" }
    $found = @()
    if ($ln -match '^diff --git a/(\S+) b/(\S+)$') { $found = @($Matches[1], $Matches[2]) }
    elseif ($ln -match '^(?:---|\+\+\+) [ab]/(\S+)') { $found = @($Matches[1]) }
    elseif ($ln -match '^(?:rename|copy) (?:from|to) (\S+)$') { $found = @($Matches[1]) }
    elseif (($ln.StartsWith("--- /") -or $ln.StartsWith("+++ /")) -and -not ($ln.StartsWith("--- /dev/null") -or $ln.StartsWith("+++ /dev/null"))) { return "the patch is refused: a path outside the repository" }
    foreach ($p in $found) {
      if ($p -eq "/dev/null") { continue }
      if ($p.StartsWith("/") -or $p.Contains("\") -or ($p -split "/") -contains ".." -or $p -match '^[A-Za-z]:') { return "the patch is refused: the path '$p' leaves the repository" }
      [void]$paths.Add($p)
    }
  }
  if (-not $paths.Count) { return "the patch is refused: no file in the patch" }
  $allow = @($k.patch_paths.allow | ForEach-Object { Convert-Glob $_ })
  $deny = @($k.patch_paths.deny | ForEach-Object { Convert-Glob $_ })
  foreach ($p in ($paths | Sort-Object)) {
    if ($deny | Where-Object { $p -cmatch $_ }) { return "the patch changes $p, which this job kind does not let a patch change" }
    if (-not ($allow | Where-Object { $p -cmatch $_ })) { return "the patch changes $p, outside the paths this job kind allows ($(@($k.patch_paths.allow) -join ', '))" }
  }
  return $null
}

# ---- running a step: each argument quoted for CreateProcess, never through a shell of our making
function Quote-Arg([string]$a) {
  if ($a.Length -and $a -notmatch '[\s"]') { return $a }
  $out = '"'; $bs = 0
  foreach ($ch in $a.ToCharArray()) {
    if ($ch -eq '\') { $bs++ }
    elseif ($ch -eq '"') { $out += ('\' * (2 * $bs + 1)) + '"'; $bs = 0 }
    else { $out += ('\' * $bs) + $ch; $bs = 0 }
  }
  return $out + ('\' * (2 * $bs)) + '"'
}
function Fill($a, $vals) { return [regex]::Replace("$a", '\{([a-z_]+)\}', { param($m) $vals[$m.Groups[1].Value] }) }

function Write-Beat($out, $id) { Save-Json (Join-Path $out "claimed.json") ([ordered]@{ id = $id; at = (Now-Unix); beat = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0 }) }

function Refuse($id, $kind, $why) {
  Save-Json (Join-Path (Join-Path $Outbox $id) "result.json") ([ordered]@{ id = $id; kind = $kind; status = "refused"; error = $why; steps = @(); artifacts = @(); ended = (Now-Unix) })
}

function Run-Job($reqDir) {
  $id = Split-Path $reqDir -Leaf
  $out = Join-Path $Outbox $id
  New-Item -ItemType Directory -Force $out | Out-Null
  $req = Read-Json (Join-Path $reqDir "request.json")
  if (-not $req) { return Refuse $id $null "the request could not be read" }
  $kindName = "$($req.kind)"
  if ("$($req.id)" -ne $id) { return Refuse $id $kindName "the request's id is not its folder's" }
  if ((Now-Unix) - [double]$req.at -gt $StaleS) { return Refuse $id $kindName "the request waited over an hour, so it was dropped" }
  $kinds = Get-Kinds
  $why = Why-Not $kindName $kinds (Get-Approvals)
  if ($why) { return Refuse $id $kindName $why }
  $k = $kinds[$kindName].k
  $checked = Test-Values $k $req.values $reqDir (Get-Names)
  if ($checked.why) { return Refuse $id $kindName $checked.why }
  $vals = $checked.values
  $patchPath = ""
  if ($vals.ContainsKey("patch")) {
    $patchPath = (Resolve-Path -LiteralPath (Join-Path $reqDir $vals["patch"])).Path
    $why = Test-Patch $k ([IO.File]::ReadAllText($patchPath, $Utf8))
    if ($why) { return Refuse $id $kindName $why }
  }
  if (Has $k "needs_gb") {
    $free = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)
    if ($free -lt $k.needs_gb) { return Refuse $id $kindName "Windows has only $free GB of memory free; this job needs $($k.needs_gb) GB" }
  }
  $scr = Join-Path $Scratch $id
  if (Test-Path -LiteralPath $scr) { Remove-Item -LiteralPath $scr -Recurse -Force }
  New-Item -ItemType Directory -Force $scr | Out-Null
  $lock = if ($k.lock) { "$($k.lock)" } else { $kindName }
  $script:Busy[$lock] = $id
  Write-Beat $out $id
  $fill = @{}; foreach ($n in $vals.Keys) { $fill[$n] = $vals[$n] }
  $fill["scratch"] = $scr; $fill["repos"] = $Repos; $fill["out"] = (Join-Path $out "artifacts"); $fill["patch"] = $patchPath
  $steps = @(); $log = New-Object System.Text.StringBuilder; $status = "done"; $err = $null
  $deadline = (Get-Date).AddSeconds($MinuteS * $k.minutes)
  $n = 0; $all = @($k.steps)
  foreach ($s in $all) {
    $n++
    $argv = @(@($s) | ForEach-Object { Fill $_ $fill })
    $t0 = Get-Date
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $argv[0]
    $psi.Arguments = (@($argv | Select-Object -Skip 1 | ForEach-Object { Quote-Arg $_ }) -join " ")
    $psi.WorkingDirectory = $scr; $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = $Utf8; $psi.StandardErrorEncoding = $Utf8
    $code = $null
    try {
      $p = [System.Diagnostics.Process]::Start($psi)
      $o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync()
      $beatAt = Get-Date
      while (-not $p.WaitForExit(500)) {
        if (((Get-Date) - $beatAt).TotalSeconds -ge $BeatS) { Write-Beat $out $id; $beatAt = Get-Date }
        if ((Get-Date) -gt $deadline) {
          & taskkill.exe /T /F /PID $p.Id 2>$null | Out-Null
          $status = "failed"; $err = "step $n ($(@($s)[0])) stopped at the job's time limit of $($k.minutes) minutes"
          break
        }
      }
      if ($status -ne "failed") { $p.WaitForExit(); $code = $p.ExitCode }
      [void]$log.AppendLine("`$ step ${n}: $(@($s)[0])"); [void]$log.AppendLine($o.Result + $e.Result)
    } catch {
      $status = "failed"; $err = "step ${n}: $(@($s)[0]) could not be started ($($_.Exception.InnerException.Message))"
    }
    $steps += [ordered]@{ n = $n; exit = $code; seconds = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1) }
    [IO.File]::AppendAllText((Join-Path $out "progress.jsonl"), (([ordered]@{ at = (Now-Unix); step = $n; of = $all.Count; exit = $code } | ConvertTo-Json -Compress) + "`n"), $Utf8)
    if ($status -eq "failed") { break }
    if ($code -ne 0) { $status = "failed"; $err = "step $n ($(@($s)[0])) exited with $code"; break }
  }
  $arts = Join-Path $out "artifacts"
  New-Item -ItemType Directory -Force $arts | Out-Null
  $text = $log.ToString()
  if ($text.Length -gt $LogMax) { $text = "[... the first $($text.Length - $LogMax) characters of the log were cut]`n" + $text.Substring($text.Length - $LogMax) }
  [IO.File]::WriteAllText((Join-Path $arts "log.txt"), $text, $Utf8)
  $names = @("log.txt"); $left = @(); $size = 0
  $globs = @($k.collect | ForEach-Object { Convert-Glob ("$_" -replace '\\', '/') })
  foreach ($f in Get-ChildItem -LiteralPath $scr -Recurse -File -ErrorAction SilentlyContinue) {
    if ($f.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
    $rel = $f.FullName.Substring($scr.Length + 1) -replace '\\', '/'
    if (-not ($globs | Where-Object { $rel -cmatch $_ })) { continue }
    $size += $f.Length
    if ($size -gt $ArtifactsMb * 1MB) { $left += $rel; continue }
    $dest = $rel -replace '/', '__'
    Copy-Item -LiteralPath $f.FullName (Join-Path $arts $dest)
    $names += $dest
  }
  $script:Busy.Remove($lock)
  Remove-Item -LiteralPath $scr -Recurse -Force -ErrorAction SilentlyContinue
  Save-Json (Join-Path $out "result.json") ([ordered]@{ id = $id; kind = $kindName; status = $status; error = $err; steps = $steps; artifacts = $names; left_out = $left; ended = (Now-Unix) })
}

function Write-Status {
  $kinds = Get-Kinds; $appr = Get-Approvals; $ks = [ordered]@{}
  foreach ($n in ($kinds.Keys | Sort-Object)) {
    $why = Why-Not $n $kinds $appr; $k = $kinds[$n].k
    $ks[$n] = [ordered]@{ approved = (-not $why); why = $why; sha = $kinds[$n].sha; retry = [bool]($k -and $k.retry); lock = if ($k -and $k.lock) { "$($k.lock)" } else { $n } }
  }
  Save-Json (Join-Path $Outbox "status.json") ([ordered]@{ ts = (Now-Unix); kinds = $ks; busy = $script:Busy
      free_gb = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1) })
}

function Take-Next {
  if (-not (Test-Path -LiteralPath $Inbox)) { return $null }
  foreach ($d in (Get-ChildItem -LiteralPath $Inbox -Directory | Sort-Object LastWriteTime)) {
    if ($d.Name -match $IdRx -and -not (Test-Path -LiteralPath (Join-Path $Outbox $d.Name))) { return $d.FullName }
  }
  return $null
}

New-Item -ItemType Directory -Force $Outbox, $Scratch | Out-Null
$single = New-Object System.Threading.Mutex($false, "Global\aistack-windows-worker")
if (-not $Once -and -not $single.WaitOne(0)) { exit 0 }
$statusAt = [datetime]::MinValue
while ($true) {
  try {
    if (((Get-Date) - $statusAt).TotalSeconds -ge $BeatS) { Write-Status; $statusAt = Get-Date }
    $next = Take-Next
    if ($next) { Run-Job $next; Write-Status; $statusAt = Get-Date }
    elseif ($Once) { break }
    if ($Once -and -not (Take-Next)) { break }
  } catch {
    try { [IO.File]::AppendAllText((Join-Path $Outbox "worker.log"), "$(Get-Date -Format s) error: $($_.Exception.Message)`n", $Utf8) } catch {}
    if ($Once) { throw }
  }
  if (-not $Once) { Start-Sleep -Seconds 2 }
}

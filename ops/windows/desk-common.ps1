# Shared by desk.ps1, claude-remote.ps1 and desk-signin.ps1 (PLT-31, PLT-32). Copied to C:\AI\ops by desk-setup.ps1.
$script:Ops = "C:\AI\ops"
$script:FoldersFile = "$script:Ops\desk-folders.txt"
$script:Utf8 = New-Object System.Text.UTF8Encoding $false

# The Claude Code that the desktop app keeps up to date, or one installed by hand: the newest version found.
function Find-Claude {
  $cmd = Get-Command claude -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $all = @(Get-ChildItem "$env:LOCALAPPDATA\Claude-Data\claude_*\claude-code\*\*\claude.exe" -ErrorAction SilentlyContinue)
  if (-not $all.Count) { return $null }
  $best = $all | Sort-Object { try { [version]$_.Directory.Parent.Name } catch { [version]"0.0" } } | Select-Object -Last 1
  return $best.FullName
}

# The folders Claude may read: one per line in desk-folders.txt, a file only you can change (WSL cannot write to C:).
function Get-Folders {
  if (-not (Test-Path -LiteralPath $script:FoldersFile)) { return @() }
  $out = @()
  foreach ($line in [IO.File]::ReadAllLines($script:FoldersFile, $script:Utf8)) {
    $t = $line.Trim()
    if (-not $t -or $t.StartsWith("#")) { continue }
    if (Test-Path -LiteralPath $t -PathType Container) { $out += (Resolve-Path -LiteralPath $t).Path.TrimEnd("\") }
  }
  return ,$out
}

function Write-DeskLog($name, $text) {
  $dir = "$env:LOCALAPPDATA\ai-stack"
  New-Item -ItemType Directory -Force $dir | Out-Null
  $f = "$dir\$name.log"
  if ((Test-Path -LiteralPath $f) -and (Get-Item -LiteralPath $f).Length -gt 1MB) { Move-Item -Force -LiteralPath $f "$f.old" }
  [IO.File]::AppendAllText($f, "$(Get-Date -Format s) $text`r`n", $script:Utf8)
}

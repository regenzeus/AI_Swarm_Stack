# Disk analysis "like TreeSize" for the PC cleanup mission (ops/cleanup.py). Read-only: it never deletes or changes
# anything. Copied to C:\AI\ops\disk-scan.ps1; started by host-probe.ps1 when the runner asks for a scan
# (\\wsl.localhost\Ubuntu-24.04\srv\ai\state\pcscan\request.json), at below-normal priority.
# Output: C:\AI\exports\.host\diskscan.json (WSL reads it as /srv/win-exports/.host/diskscan.json).
param([int]$Depth = 6, [int]$TopFiles = 60)
$ErrorActionPreference = "SilentlyContinue"
(Get-Process -Id $PID).PriorityClass = "BelowNormal"
$out = "C:\AI\exports\.host"
New-Item -ItemType Directory -Force $out | Out-Null

Add-Type -Language CSharp -TypeDefinition @"
using System; using System.IO; using System.Collections.Generic;
public static class DiskScan {
  public static Dictionary<string, long> Dirs = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
  public static List<KeyValuePair<string, long>> Top = new List<KeyValuePair<string, long>>();
  public static long Files, Errors; public static int MaxDepth = 4, TopN = 60; static long minTop = 0;
  static void AddTop(string p, long l) {
    if (Top.Count >= TopN && l <= minTop) return;
    Top.Add(new KeyValuePair<string, long>(p, l));
    if (Top.Count > TopN) { Top.Sort((a, b) => b.Value.CompareTo(a.Value)); Top.RemoveAt(Top.Count - 1); minTop = Top[Top.Count - 1].Value; }
  }
  public static long Walk(string path, int depth) {
    long total = 0; DirectoryInfo d = new DirectoryInfo(path);
    try { foreach (FileInfo f in d.EnumerateFiles()) { try { long l = f.Length; total += l; Files++; AddTop(f.FullName, l); } catch { Errors++; } } } catch { Errors++; }
    try { foreach (DirectoryInfo s in d.EnumerateDirectories()) {
        if ((s.Attributes & FileAttributes.ReparsePoint) != 0) continue;     // junctions and links: counted once, where they point
        total += Walk(s.FullName, depth + 1); } } catch { Errors++; }
    if (depth <= MaxDepth) Dirs[path] = total;
    return total;
  }
}
"@

function SizeOf($path) {
  if (-not (Test-Path -LiteralPath $path)) { return $null }
  $it = Get-Item -LiteralPath $path -Force
  if (-not $it.PSIsContainer) { return $it.Length }
  if ([DiskScan]::Dirs.ContainsKey($it.FullName)) { return [DiskScan]::Dirs[$it.FullName] }
  $sum = 0L; Get-ChildItem -LiteralPath $path -Recurse -Force -File -ErrorAction SilentlyContinue | ForEach-Object { $sum += $_.Length }; return $sum
}

$t0 = Get-Date
[DiskScan]::MaxDepth = $Depth; [DiskScan]::TopN = $TopFiles
$drives = @()
# local NTFS/ReFS drives only: cloud drives (Google Drive, OneDrive) would fetch or stream files
foreach ($d in (Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | Where-Object { $_.FileSystem -in "NTFS", "ReFS" -and $_.VolumeName -notmatch "Google Drive|OneDrive|Dropbox" })) {
  $root = "$($d.DeviceID)\"
  $s = Get-Date
  [void][DiskScan]::Walk($root, 0)
  $drives += [ordered]@{ root = $root; label = $d.VolumeName; total = [long]$d.Size; free = [long]$d.FreeSpace; seconds = [int]((Get-Date) - $s).TotalSeconds }
}
$dirs = [DiskScan]::Dirs.GetEnumerator() | Where-Object { $_.Value -ge 200MB } | Sort-Object Value -Descending | Select-Object -First 400 |
  ForEach-Object { [ordered]@{ path = $_.Key; size = $_.Value; depth = ($_.Key.TrimEnd('\').Split('\').Count - 1) } }
$files = [DiskScan]::Top | Sort-Object Value -Descending | ForEach-Object {
  $f = Get-Item -LiteralPath $_.Key -Force
  [ordered]@{ path = $_.Key; size = $_.Value; modified = $(if ($f) { $f.LastWriteTime.ToString("yyyy-MM-dd") } else { "" }) } }

# Known clutter: what it is, and how safe it is to clear (the mission explains; the owner decides).
$L = $env:LOCALAPPDATA; $U = $env:USERPROFILE
$known = @(
  @{ label = "Your temporary files"; path = $env:TEMP; verdict = "safe"; how = "Disk Cleanup or delete the folder's contents (in-use files are skipped)" },
  @{ label = "Windows temporary files"; path = "C:\Windows\Temp"; verdict = "safe"; how = "Disk Cleanup > Temporary files" },
  @{ label = "Recycle Bin"; path = "C:\`$Recycle.Bin"; verdict = "safe"; how = "Empty the Recycle Bin" },
  @{ label = "Crash dumps"; path = "$L\CrashDumps"; verdict = "safe"; how = "Delete the folder's contents" },
  @{ label = "Windows Update downloads"; path = "C:\Windows\SoftwareDistribution\Download"; verdict = "caution"; how = "Disk Cleanup > Windows Update Cleanup (not by hand)" },
  @{ label = "Old Windows installation"; path = "C:\Windows.old"; verdict = "caution"; how = "Disk Cleanup > Previous Windows installation(s)" },
  @{ label = "Brave cache"; path = "$L\BraveSoftware\Brave-Browser\User Data\Default\Cache"; verdict = "safe"; how = "Brave > Settings > Delete browsing data > Cached images and files" },
  @{ label = "Brave code cache"; path = "$L\BraveSoftware\Brave-Browser\User Data\Default\Code Cache"; verdict = "safe"; how = "same as the Brave cache" },
  @{ label = "Chrome cache"; path = "$L\Google\Chrome\User Data\Default\Cache"; verdict = "safe"; how = "Chrome > Delete browsing data > Cached images and files" },
  @{ label = "Edge cache"; path = "$L\Microsoft\Edge\User Data\Default\Cache"; verdict = "safe"; how = "Edge > Clear browsing data > Cached images and files" },
  @{ label = "Discord cache"; path = "$env:APPDATA\discord\Cache"; verdict = "safe"; how = "Quit Discord, delete the folder's contents" },
  @{ label = "NVIDIA installer downloads"; path = "C:\ProgramData\NVIDIA Corporation\Downloader"; verdict = "safe"; how = "Delete the folder's contents" },
  @{ label = "NVIDIA unpacked drivers"; path = "C:\NVIDIA"; verdict = "safe"; how = "Delete the folder (driver already installed)" },
  @{ label = "Downloads"; path = "$U\Downloads"; verdict = "caution"; how = "Check by hand: old installers (.exe/.msi/.zip) can go" },
  @{ label = "Steam games"; path = "C:\Program Files (x86)\Steam\steamapps\common"; verdict = "caution"; how = "Uninstall games you no longer play in Steam" },
  @{ label = "Videos"; path = "$U\Videos"; verdict = "caution"; how = "Your files: move to the NAS or delete what you don't need" },
  @{ label = "Page file"; path = "C:\pagefile.sys"; verdict = "never"; how = "Windows manages it" },
  @{ label = "Hibernation file"; path = "C:\hiberfil.sys"; verdict = "never"; how = "Windows manages it (only gone if hibernation is off)" },
  @{ label = "AI stack cache (rehearsal rootfs)"; path = "C:\AI\cache"; verdict = "caution"; how = "Needed for the new-PC rehearsal" }
)
$clutter = @(foreach ($k in $known) { $sz = SizeOf $k.path; if ($sz -ne $null -and $sz -gt 0) { [ordered]@{ label = $k.label; path = $k.path; size = [long]$sz; verdict = $k.verdict; how = $k.how } } })
# The WSL disk (the whole AI stack lives in it): never delete; it can be compacted
$vhdx = @(Get-ChildItem -Path "$L\Packages\*Ubuntu*\LocalState\*.vhdx", "$L\wsl\*\*.vhdx" -Force -ErrorAction SilentlyContinue | ForEach-Object {
  [ordered]@{ label = "WSL disk (the AI stack)"; path = $_.FullName; size = $_.Length; verdict = "never"; how = "Never delete. It only grows; compacting needs WSL shut down (later)" } })
$clutter += $vhdx
# Steam: one entry per game
$steam = @(Get-ChildItem "C:\Program Files (x86)\Steam\steamapps\common" -Directory -ErrorAction SilentlyContinue | ForEach-Object {
  [ordered]@{ name = $_.Name; size = [long](SizeOf $_.FullName); last_used = $_.LastWriteTime.ToString("yyyy-MM-dd") } } | Sort-Object { $_.size } -Descending)
# Old installers in Downloads
$inst = @(Get-ChildItem "$U\Downloads" -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.Extension -in ".exe", ".msi", ".zip", ".iso", ".7z", ".rar" -and $_.LastWriteTime -lt (Get-Date).AddDays(-90) } |
  Sort-Object Length -Descending | Select-Object -First 30 | ForEach-Object { [ordered]@{ name = $_.Name; size = $_.Length; modified = $_.LastWriteTime.ToString("yyyy-MM-dd") } })

$res = [ordered]@{ ts = (Get-Date).ToUniversalTime().ToString("o"); seconds = [int]((Get-Date) - $t0).TotalSeconds
  files = [DiskScan]::Files; errors = [DiskScan]::Errors; drives = $drives; dirs = @($dirs); top_files = @($files)
  clutter = @($clutter | Sort-Object { $_.size } -Descending); steam_games = $steam; old_installers = $inst }
($res | ConvertTo-Json -Depth 5 -Compress) | Set-Content -Encoding utf8 "$out\diskscan.json.tmp"
Move-Item -Force "$out\diskscan.json.tmp" "$out\diskscan.json"

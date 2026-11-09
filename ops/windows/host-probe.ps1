# Windows resource numbers for Mission Control's Stack page, every 30 s, into C:\AI\exports\.host\host.json
# (WSL reads C:\AI\exports read-only as /srv/win-exports). One hidden loop, started at logon by the task
# "ai-stack host probe" (no admin needed); it never changes anything.
$dir = "C:\AI\exports\.host"
New-Item -ItemType Directory -Force $dir | Out-Null
# Hardware facts (board, CPU, memory slots and modules, GPU, disks) for shopping missions (ops/shopping.py), hourly.
function Write-Hardware {
  $arr = Get-CimInstance Win32_PhysicalMemoryArray
  $mods = @(Get-CimInstance Win32_PhysicalMemory | ForEach-Object { [ordered]@{
      slot = $_.DeviceLocator; gb = [math]::Round($_.Capacity / 1GB); part = "$($_.PartNumber)".Trim(); maker = "$($_.Manufacturer)".Trim()
      type = @{26 = "DDR4"; 34 = "DDR5"; 24 = "DDR3"}[[int]$_.SMBIOSMemoryType]; rated_mhz = $_.Speed
      configured_mhz = $_.ConfiguredClockSpeed; volts = $_.ConfiguredVoltage / 1000 } })
  $b = Get-CimInstance Win32_BaseBoard
  $h = [ordered]@{
    ts = (Get-Date).ToUniversalTime().ToString("o")
    cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name.Trim()
    board = "$($b.Manufacturer) $($b.Product)".Trim()
    bios = (Get-CimInstance Win32_BIOS).SMBIOSBIOSVersion
    memory = [ordered]@{ slots = ($arr | Measure-Object MemoryDevices -Sum).Sum; max_gb = [math]::Round(($arr | Measure-Object MaxCapacity -Sum).Sum / 1MB); modules = $mods }
    gpu = @(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name })
    disks = @(Get-CimInstance Win32_DiskDrive | ForEach-Object { "$($_.Model) ($([math]::Round($_.Size / 1GB)) GB)" })
  }
  ($h | ConvertTo-Json -Depth 4 -Compress) | Set-Content -Encoding utf8 "$dir\hardware.json.tmp"
  Move-Item -Force "$dir\hardware.json.tmp" "$dir\hardware.json"
}
# A disk scan for the PC cleanup mission (ops/cleanup.py): the runner drops a request file in WSL; this loop starts
# C:\AI\ops\disk-scan.ps1 (read-only, below-normal priority) and removes the request. One scan at a time.
$scanReq = "\\wsl.localhost\Ubuntu-24.04\srv\ai\state\pcscan\request.json"
$scan = $null
$hwAt = [datetime]::MinValue
while ($true) {
  try { if (((Get-Date) - $hwAt).TotalHours -ge 1) { Write-Hardware; $hwAt = Get-Date } } catch {}
  try {
    if ((-not $scan -or $scan.HasExited) -and (Test-Path -LiteralPath $scanReq)) {
      Remove-Item -LiteralPath $scanReq -Force
      $scan = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "C:\AI\ops\disk-scan.ps1"
    }
  } catch {}
  try {
    $os = Get-CimInstance Win32_OperatingSystem
    $cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
    $c = Get-PSDrive C
    $vm = (Get-Process -Name vmmemWSL, vmmem -ErrorAction SilentlyContinue | Measure-Object WorkingSet64 -Sum).Sum
    $avail = (Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory).AvailableMBytes   # free plus the cache Windows hands back
    $o = [ordered]@{
      ts = (Get-Date).ToUniversalTime().ToString("o")
      ram_total_gb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
      ram_free_gb = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
      ram_available_gb = [math]::Round($avail / 1024, 2)
      cpu_pct = [int]$cpu
      disk_c_free_gb = [math]::Round($c.Free / 1GB, 1)
      disk_c_total_gb = [math]::Round(($c.Used + $c.Free) / 1GB, 1)
      wsl_vm_gb = [math]::Round($vm / 1GB, 2)
    }
    ($o | ConvertTo-Json -Compress) | Set-Content -Encoding utf8 "$dir\host.json.tmp"
    Move-Item -Force "$dir\host.json.tmp" "$dir\host.json"
  } catch {}
  Start-Sleep -Seconds 30
}

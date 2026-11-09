# Keep Bitbucket (and F:\Bitbucket\TestRepo) level with Forgejo, which is canonical for TestRepo.
# Copy of ~/ai-stack/ops/windows/bitbucket-sync.ps1. Runs every 30 min from the task "ai-stack bitbucket sync"
# as the normal user. Fast-forward only: if Bitbucket ever has commits Forgejo lacks, it stops and logs.
# It compares Forgejo's main (fetched now) with what Bitbucket last took (origin/main here), not with the local clone:
# a push that failed once is tried again on the next run, and every failure ends the task with exit 1 (review OPS-R3:
# from 25 Oct the push failed for want of a stored credential, the clone was already fast-forwarded, and every later run
# saw nothing to do and reported success).
$repo = "F:\Bitbucket\TestRepo"
$log = "C:\AI\logs\bitbucket-sync.log"
# limit: drops, a log over 1 MB becomes <log>.1 and the one before goes (review OPS-R17: no Windows log was rotated)
function Log($m) {
    if ((Test-Path $log) -and (Get-Item $log).Length -gt 1MB) { Move-Item $log "$log.1" -Force }
    "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), ("$m" -replace "`0", "") | Add-Content $log -Encoding utf8   # WSL's spaced UTF-16
}
$env:GCM_INTERACTIVE = "never"; $env:GIT_TERMINAL_PROMPT = "0"; $env:WSL_UTF8 = "1"   # WSL's own errors as UTF-8, not spaced UTF-16
$code = "/home/owner/code/TestRepo"

$fetch = (wsl.exe -d Ubuntu-24.04 -u owner -e git -C $code fetch -q origin main 2>&1) | Out-String
if ($LASTEXITCODE -ne 0) { Log "could not fetch Forgejo's main: $($fetch.Trim())"; exit 1 }
$forgejo = (wsl.exe -d Ubuntu-24.04 -u owner -e git -C $code rev-parse origin/main) -join ""
if ($forgejo -notmatch '^[0-9a-f]{40}$') { Log "could not read Forgejo's head: $forgejo"; exit 1 }
$mirror = (git -C $repo rev-parse --verify -q refs/remotes/origin/main) -join ""
if ($forgejo -eq $mirror) { exit 0 }                       # Bitbucket has it already
$local = (git -C $repo rev-parse main) -join ""
if ($forgejo -ne $local) {
  $made = (wsl.exe -d Ubuntu-24.04 -u owner -e git -C $code bundle create /tmp/testrepo-sync.bundle refs/remotes/origin/main 2>&1) | Out-String
  if ($LASTEXITCODE -ne 0) { Log "could not bundle Forgejo's main: $($made.Trim())"; exit 1 }
  $bundle = "$env:TEMP\testrepo-sync.bundle"
  try { Copy-Item "\\wsl.localhost\Ubuntu-24.04\tmp\testrepo-sync.bundle" $bundle -Force -ErrorAction Stop }
  catch { Log "could not copy the bundle from WSL: $_"; exit 1 }
  $pull = git -C $repo pull --ff-only $bundle refs/remotes/origin/main 2>&1 | Out-String
  if ($LASTEXITCODE -ne 0) { Log "not a fast-forward, nothing pushed: $($pull.Trim())"; exit 1 }
}
$push = git -C $repo push origin main 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) { Log ("PUSH FAILED (exit {0}), Bitbucket stays at {1}: {2}" -f $LASTEXITCODE, ($mirror + "nothing").Substring(0,7), $push.Trim()); exit 1 }
Log ("pushed {0} -> {1}: {2}" -f ($mirror + "nothing").Substring(0,7), $forgejo.Substring(0,7), $push.Trim())

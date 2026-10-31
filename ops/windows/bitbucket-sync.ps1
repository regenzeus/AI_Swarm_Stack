# Keep Bitbucket (and F:\Bitbucket\TestRepo) level with Forgejo, which is canonical for TestRepo.
# Copy of ~/ai-stack/ops/windows/bitbucket-sync.ps1. Runs every 30 min from the task "ai-stack bitbucket sync"
# as the normal user. Fast-forward only: if Bitbucket ever has commits Forgejo lacks, it stops and logs.
$repo = "F:\Bitbucket\TestRepo"
$log = "C:\AI\logs\bitbucket-sync.log"
function Log($m) { "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $m | Add-Content $log -Encoding utf8 }
$env:GCM_INTERACTIVE = "never"; $env:GIT_TERMINAL_PROMPT = "0"

$forgejo = (wsl.exe -d Ubuntu-24.04 -u owner -e git -C /home/owner/code/TestRepo rev-parse main) -join ""
$local = (git -C $repo rev-parse main) -join ""
if ($forgejo -notmatch '^[0-9a-f]{40}$') { Log "could not read Forgejo head: $forgejo"; exit 1 }
if ($forgejo -eq $local) { exit 0 }
wsl.exe -d Ubuntu-24.04 -u owner -e git -C /home/owner/code/TestRepo bundle create /tmp/testrepo-sync.bundle main 2>$null | Out-Null
$bundle = "$env:TEMP\testrepo-sync.bundle"
Copy-Item "\\wsl.localhost\Ubuntu-24.04\tmp\testrepo-sync.bundle" $bundle -Force
$pull = git -C $repo pull --ff-only $bundle main 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) { Log "not a fast-forward, nothing pushed: $pull"; exit 1 }
$push = git -C $repo push origin main 2>&1 | Out-String
Log ("pushed {0} -> {1} (exit {2}) {3}" -f $local.Substring(0,7), $forgejo.Substring(0,7), $LASTEXITCODE, $push.Trim())

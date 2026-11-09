# The Windows worker's self-test (GEN-11): worker.ps1 on this PC against the protocol cases the stack's tests run on
# ops/fakeworker.py, in a folder of its own under %TEMP% (nothing of C:\AIWorker is touched). It runs as whoever starts it,
# so it checks the rules, not the account separation; worker-setup.ps1 runs it once more as aiworker.
#   powershell -NoProfile -ExecutionPolicy Bypass -File worker-selftest.ps1 [-Worker <path of worker.ps1>]
# Needs git and Python (py) on PATH. Exit 0 when every case holds; each case prints ok or FAILED with what came back.
param([string]$Worker = "$PSScriptRoot\worker.ps1")
$ErrorActionPreference = "Stop"
$Utf8 = New-Object System.Text.UTF8Encoding($false)
$root = Join-Path $env:TEMP ("aiworker-selftest-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$failed = 0

function W($path, $text) { New-Item -ItemType Directory -Force (Split-Path $path) | Out-Null; [IO.File]::WriteAllText($path, $text, $Utf8) }
function Run-Git { $ErrorActionPreference = "Continue"; & git.exe -c core.autocrlf=false @args 2>&1 | Out-Null; if ($LASTEXITCODE) { throw "git $args failed" } }
function Id { -join ((1..12) | ForEach-Object { "0123456789abcdef"[(Get-Random -Maximum 16)] }) }
function Ask($kind, $values, $files) {
  $id = Id; $d = Join-Path $root "inbox\$id"
  foreach ($f in $files.Keys) { W (Join-Path $d $f) $files[$f] }
  W (Join-Path $d "request.json") (([ordered]@{ id = $id; kind = $kind; values = $values; at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() }) | ConvertTo-Json -Compress)
  return $id
}
function Result($id) { return [IO.File]::ReadAllText((Join-Path $root "outbox\$id\result.json"), $Utf8) | ConvertFrom-Json }
function Expect($name, $id, $status, $says) {
  $r = Result $id
  if ($r.status -eq $status -and (-not $says -or "$($r.error)" -like "*$says*")) { Write-Host "ok      $name" }
  else { Write-Host "FAILED  $name -> $($r.status): $($r.error)"; $script:failed++ }
}
function Run-Worker([double]$minuteS = 60) { & powershell -NoProfile -ExecutionPolicy Bypass -File $Worker -Root $root -Once -MinuteS $minuteS -BeatS 1 }

try {
  $app = "def answer():`n    return 41`n"
  $repo = Join-Path $root "repos\demo"
  W "$repo\src\app.py" $app
  W "$repo\run.py" "import sys, pathlib`nsys.path.insert(0, str(pathlib.Path(__file__).parent / 'src'))`nimport app`nok = app.answer() == 42`npathlib.Path('report.xml').write_text('<testsuite failures=%d/>' % (0 if ok else 1))`nsys.exit(0 if ok else 1)`n"
  W "$repo\pom.xml" "<project/>`n"
  Push-Location $repo
  Run-Git init -q -b main; Run-Git -c user.name=t -c user.email=test@example.com add -A; Run-Git -c user.name=t -c user.email=test@example.com commit -qm init
  $commit = (& git rev-parse HEAD).Trim()
  Pop-Location
  $kind = [ordered]@{
    kind = "demo.build"; about = "Apply a patch to a clean copy and run its check"
    params = [ordered]@{ repo = @{ type = "name"; from = "repos" }; commit = @{ type = "hex40" }; patch = @{ type = "file"; max_kb = 64 }; goal = @{ type = "enum"; values = @("check", "full") } }
    patch_paths = @{ allow = @("src/**"); deny = @("**/pom.xml", "**/*.cmd") }
    steps = @(@("git", "-c", "core.autocrlf=false", "clone", "--quiet", "{repos}\{repo}", "{scratch}\src"), @("git", "-C", "{scratch}\src", "checkout", "--quiet", "--detach", "{commit}"),
              @("git", "-C", "{scratch}\src", "apply", "--check", "{patch}"), @("git", "-C", "{scratch}\src", "apply", "{patch}"), @("py", "{scratch}\src\run.py", "{goal}"))
    collect = @("report.xml"); minutes = 5; lock = "build"; retry = $true
  }
  W "$root\jobs.d\demo.build.json" ($kind | ConvertTo-Json -Depth 6)
  $sha = (Get-FileHash "$root\jobs.d\demo.build.json" -Algorithm SHA256).Hash.ToLower()
  W "$root\approved.json" (@{ "demo.build" = $sha } | ConvertTo-Json -Compress)
  $fix = "diff --git a/src/app.py b/src/app.py`n--- a/src/app.py`n+++ b/src/app.py`n@@ -1,2 +1,2 @@`n def answer():`n-    return 41`n+    return 42`n"
  $vals = [ordered]@{ repo = "demo"; commit = $commit; patch = "patch.diff"; goal = "check" }

  $ok = Ask "demo.build" $vals @{ "patch.diff" = $fix }
  $bad = Ask "demo.build" ([ordered]@{ repo = "demo"; commit = "HEAD & calc.exe"; patch = "patch.diff"; goal = "check" }) @{ "patch.diff" = $fix }
  $pom = Ask "demo.build" $vals @{ "patch.diff" = "diff --git a/pom.xml b/pom.xml`n--- a/pom.xml`n+++ b/pom.xml`n@@ -1 +1 @@`n-<project/>`n+<project><build/></project>`n" }
  $dots = Ask "demo.build" $vals @{ "patch.diff" = "diff --git a/src/../run.py b/src/../run.py`n--- a/src/../run.py`n+++ b/src/../run.py`n@@ -1 +1 @@`n-x`n+y`n" }
  $none = Ask "maven.deploy" @{} @{}
  $odd = Ask "demo.build" ([ordered]@{ repo = "other"; commit = $commit; patch = "patch.diff"; goal = "check" }) @{ "patch.diff" = $fix }
  Run-Worker
  Expect "a declared, approved job runs end to end" $ok "done"
  $r = Result $ok
  if (@($r.artifacts) -contains "report.xml" -and @($r.artifacts) -contains "log.txt") { Write-Host "ok      its evidence comes back" } else { Write-Host "FAILED  artifacts: $($r.artifacts)"; $failed++ }
  if (-not (Test-Path (Join-Path $root "scratch\$ok"))) { Write-Host "ok      its scratch copy is gone" } else { Write-Host "FAILED  scratch left"; $failed++ }
  Expect "a value with shell syntax is refused by its type" $bad "refused" "a commit, 40 lowercase hex"
  Expect "a patch to the build file is refused" $pom "refused" "does not let a patch change"
  Expect "a patch path with .. is refused" $dots "refused" "leaves the repository"
  Expect "an undeclared kind is refused" $none "refused" "no job kind maven.deploy"
  Expect "a name not in the worker's list is refused" $odd "refused" "one of the names in the worker's repos"

  [IO.File]::AppendAllText("$root\jobs.d\demo.build.json", " ", $Utf8)          # edited after its approval
  $changed = Ask "demo.build" $vals @{ "patch.diff" = $fix }
  Run-Worker
  Expect "a kind changed since its approval does not run" $changed "refused" "changed since its approval"

  $slow = $kind; $slow.steps = @(, @("py", "-c", "import time; time.sleep(30)")); $slow.params = @{}; $slow.Remove("patch_paths"); $slow.minutes = 1
  W "$root\jobs.d\demo.build.json" ($slow | ConvertTo-Json -Depth 6)
  W "$root\approved.json" (@{ "demo.build" = (Get-FileHash "$root\jobs.d\demo.build.json" -Algorithm SHA256).Hash.ToLower() } | ConvertTo-Json -Compress)
  $late = Ask "demo.build" @{} @{}
  Run-Worker 3
  Expect "a job past its time limit is stopped" $late "failed" "time limit"

  $st = [IO.File]::ReadAllText("$root\outbox\status.json", $Utf8) | ConvertFrom-Json
  if ($st.kinds."demo.build".approved -and $st.ts) { Write-Host "ok      the status names the approved kinds" } else { Write-Host "FAILED  status: $($st | ConvertTo-Json -Compress)"; $failed++ }
} finally {
  Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}
if ($failed) { Write-Host "$failed case(s) FAILED"; exit 1 }
Write-Host "every case holds"
exit 0

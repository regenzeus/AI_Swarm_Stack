# New-PC rehearsal: builds the stack from scratch in a throwaway WSL distro ("airehearsal") exactly as on a new
# PC, from the OFF-SITE copies (backup and key from OneDrive), then compares its data with the live stack and
# deletes the distro again. Copy of ~/ai-stack/ops/windows/rehearse-new-pc.ps1. Normal user, no admin.
# Isolation: own vault folder, no ports, no Telegram, no internet for LiteLLM, no timers, no NAS/Forgejo keys.
# Manual follow-up checklist (replacement PC only; commands and details in NEW-MACHINE.md).
# The comparisons below cover core restored data, NOT these newer integrations. Do not enable them in
# airehearsal or change compose/rehearsal.yaml to run them alongside the live stack.
# [ ] Dashboard access: tailscale serve --bg --https=8448 http://127.0.0.1:9119; check tailscale serve status
#     and open https://<pc>.ts.net:8448 from a signed-in tailnet device. Port 9119 is gate-hermes-dashboard,
#     requiring Tailscale-User-Login. Keep 127.0.0.1 bindings and the gate: no Funnel or public listener.
# [ ] Windows resources: copy host-probe.ps1 to C:\AI\ops, register "ai-stack host probe" at logon as the
#     normal user (hidden powershell.exe, no execution time limit), then Start-ScheduledTask. Check that
#     C:\AI\exports\.host\host.json updates every 30 s and Mission Control's Stack page shows the numbers.
# [ ] Builder image: ARG HERMES_IMAGE=aistack/hermes:0.22.5-web3 is the Dockerfile default, matching versions.env.
#     Build Hermes first; --build-arg HERMES_IMAGE="$HERMES_IMAGE" explicitly selects the versions.env pin.
#     ops/new-machine.sh passes no build arguments and visits builder before Hermes; prebuild both as documented.
# [ ] Profiles: reapply configure.sh, configure-scout.sh and configure-curator.sh; run configure-mission.sh
#     with -e LITELLM_MISSION_KEY="$VK_MISSION" through sops exec-env, as in NEW-MACHINE.md (never print keys).
#     Run docker exec aistack-builder-1 sh /config/configure-builder.sh in the separate builder home;
#     Compose supplies LITELLM_BUILDER_KEY from VK_BUILDER. Verify mission in hermes profile list.
# [ ] Dashboard API-key synchronization: configure.sh replaces the API_SERVER_KEY entry in the container's
#     /opt/data/.env with the Compose environment value; never inspect/edit it or generate a replacement key.
#     Run docker restart aistack-hermes-1 after configuration (repeat both steps after dashboard key drift),
#     then make smoke and chat in Mission Control/Open WebUI. Check missions.service and exercise a small
#     mission and build on the replacement PC; a test build does not authorize deployment.
$ErrorActionPreference = "Stop"
$R = "C:\AI\_rehearsal"; $log = "C:\AI\logs\rehearsal.log"; $live = "Ubuntu-24.04"; $d = "airehearsal"
$rootfs = "C:\AI\cache\ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz"
function Log($m) { $l = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $m; $l | Add-Content $log -Encoding utf8; Write-Host $l }
function Clean($lines) { ($lines | ForEach-Object { "$_" -replace "`0", "" } | Where-Object { $_.Trim() }) -join "`n" }
function InLive($cmd) { Clean (wsl.exe -d $live -u owner -e bash -lc $cmd) }
function InReh($cmd) { Clean (wsl.exe -d $d -u owner -e bash -lc $cmd) }
$t0 = Get-Date
Log "=== rehearsal start"

# 1. Fresh backup and off-site copy, as the nightly jobs would have left them
Log (InLive "cd ~/ai-stack && bash ops/backup.sh 2>/dev/null | tail -1")
powershell -NoProfile -ExecutionPolicy Bypass -File C:\AI\ops\offsite-copy.ps1
$backup = Get-ChildItem "$env:USERPROFILE\OneDrive\AI-Backup" -Filter "aistack-*.tar.gz.age" | Sort-Object Name | Select-Object -Last 1
$key = "$env:USERPROFILE\OneDrive\AI-Keys\ai-stack-backup-key.txt"

# 2. Staging folder as on a new PC: repo download + backup + key, plus an empty vault folder of its own
if (wsl.exe --list --quiet | ForEach-Object { $_ -replace "`0", "" } | Where-Object { $_ -eq $d }) { wsl.exe --unregister $d | Out-Null }
Remove-Item -Recurse -Force $R -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$R\staging\ai-stack", "$R\vault", "$R\exports", "$R\wsl" | Out-Null
InLive "cd ~/ai-stack && git archive --format=tar HEAD > /tmp/rehearsal-stage.tar" | Out-Null
Copy-Item "\\wsl.localhost\$live\tmp\rehearsal-stage.tar" "$R\stage.tar"
tar -xf "$R\stage.tar" -C "$R\staging\ai-stack"; Remove-Item "$R\stage.tar"
Copy-Item $backup.FullName "$R\staging\"; Copy-Item $key "$R\staging\age-key.txt"
Log "staged: repo HEAD, $($backup.Name) and the key from OneDrive"

# 3. Fresh Ubuntu, stage 1 (root), restart the distro only (never wsl --shutdown: the live stack runs)
wsl.exe --import $d "$R\wsl" $rootfs --version 2 | Out-Null
Log "imported fresh Ubuntu 24.04 as $d"
$s1 = Clean (wsl.exe -d $d -u root -e env REHEARSAL=1 STAGE=/mnt/c/AI/_rehearsal/staging/ai-stack VAULT_WIN=C:/AI/_rehearsal/vault EXPORTS_WIN=C:/AI/_rehearsal/exports bash /mnt/c/AI/_rehearsal/staging/ai-stack/ops/bootstrap-wsl-1-root.sh)
Log "stage 1: $(($s1 -split "`n")[-1])"
wsl.exe --terminate $d | Out-Null

# 4. Stage 2: rootless Docker, build images, restore the backup
$s2 = Clean (wsl.exe -d $d -u owner -e env REHEARSAL=1 "COMPOSE_EXTRA=-f compose/rehearsal.yaml" BUILD_ONLY=images/hermes/ "UP_SERVICES=postgres litellm hermes hindsight-db" bash -lc "bash ~/ai-stack/ops/new-machine.sh 2>&1 | grep -v '^ *[0-9a-f]\{12\}' | tail -25")
Log "stage 2:`n$s2"
Start-Sleep 60

# 5. Compare live and rehearsal
$q = @{
  "LiteLLM virtual keys" = "docker exec aistack-postgres-1 psql -U litellm -d litellm -tAc 'select count(*) from \""LiteLLM_VerificationToken\""'"
  "Hermes skills"        = "docker exec aistack-hermes-1 sh -c 'find /opt/data/skills -name SKILL.md | wc -l'"
  "Hermes sessions"      = "docker exec aistack-hermes-1 sh -c 'ls /opt/data/sessions | wc -l'"
  "Hermes memory core"   = "docker exec aistack-hermes-1 sh -c 'cat /opt/data/memories/*.md | md5sum | cut -c1-8'"
  "Hermes healthy"       = "docker exec aistack-hermes-1 sh -c 'curl -s localhost:8642/health' | grep -c ok"
  "long-term memory facts" = "docker exec aistack-hindsight-db-1 psql -U hindsight -d hindsight -tAc 'select count(*) from memory_units'"
  "vault pages"          = "find /srv/vault -name '*.md' | wc -l"
  "ai-stack commit"      = "git -C ~/ai-stack rev-parse --short HEAD"
  "skills repo commit"   = "git -C ~/hermes-skills rev-parse --short HEAD"
  "code repos"           = "ls ~/code | wc -l"
}
$ok = $true
foreach ($k in $q.Keys) {
  $a = InLive $q[$k]; $b = InReh $q[$k]
  $same = ($a -eq $b); if (-not $same) { $ok = $false }
  Log ("{0} {1,-24} live={2,-10} rehearsal={3}" -f ($(if ($same) { "SAME" } else { "DIFF" })), $k, $a, $b)
}
$result = "RESULT: {0} in {1:N0} min" -f ($(if ($ok) { "new-PC restore reproduces the live stack" } else { "differences, see C:\AI\logs\rehearsal.log" })), ((Get-Date) - $t0).TotalMinutes
Log $result
wsl.exe -d $live -u owner -e /home/owner/ai-stack/ops/notify.sh "New-PC rehearsal (fresh Ubuntu, backup and key from OneDrive): $result" | Out-Null

# 6. Tear down (only the rehearsal's own distro and folder)
if (-not $env:KEEP_REHEARSAL) { wsl.exe --unregister $d | Out-Null; Remove-Item -Recurse -Force $R; Log "rehearsal distro removed" }

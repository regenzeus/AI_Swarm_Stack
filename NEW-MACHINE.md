# Moving the stack to another Windows PC

What lives where: code and config in Forgejo on the NAS (ai-stack, vault, hermes-skills, TestRepo); everything
else (Hermes memory and sessions, LiteLLM keys and spend, Open WebUI chats, search index, state) in the nightly
encrypted backup on the NAS (/volume1/docker/ai-backup). The decryption key is in your NAS home
(~/.ai-stack/age-key.txt) and in F:\AI-backup\age-key.txt. Keep one more copy offline (USB stick or password
manager): without it the backups cannot be opened.

## Steps (about 30 min, mostly waiting)

1. Windows: install WSL (`wsl --install -d Ubuntu-24.04`), Tailscale and Git; sign in to Tailscale.
2. Copy the ai-stack repo to C:\AI\_staging\ai-stack (download it as a zip from Forgejo in the browser, or
   `git clone http://192.168.1.10:3000/regenzeus/ai-stack.git`).
3. Stage 1 as root: `wsl -d Ubuntu-24.04 -u root -- bash /mnt/c/AI/_staging/ai-stack/ops/bootstrap-wsl-1-root.sh`,
   then `wsl --shutdown`.
4. Put the age key in place before stage 2 (stage 2 would otherwise create a new one):
   `wsl -d Ubuntu-24.04 -u owner -- bash -lc 'mkdir -p ~/.config/sops/age && cat > ~/.config/sops/age/keys.txt && chmod 600 ~/.config/sops/age/keys.txt' < F:\AI-backup\age-key.txt`
5. NAS access for owner: create an SSH key in WSL (`ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_synology`) and add
   its .pub to the NAS user (DSM: user regenzeus, ~/.ssh/authorized_keys) and to Forgejo (Settings, SSH keys).
   Then copy the `Host synology` / `Host forgejo` entries from the old ~/.ssh/config.
6. Stage 2: `wsl -d Ubuntu-24.04 -u owner -- bash -lc '~/ai-stack/ops/bootstrap-wsl-2-user.sh'` (secrets come
   from the repo, encrypted to your age key, so nothing needs re-entering).
7. Build the local `aistack/*` images before `make up` (the build loop is in `ops/new-machine.sh`; build Hermes
   before the builder, as below). Then `make up`, `make restore` (newest backup; or `make restore FILE=...`).
   Finish the profile/key-sync steps below before `make smoke`. Alternatively, after bootstrap,
   `bash ops/new-machine.sh` builds the images, restores the backup and enables the timers and `missions.service`;
   it does not configure the profiles or Windows tasks.
8. Windows side: copy `ops/windows/*.ps1` to `C:\AI\ops` and register the tasks (disk heal, Bitbucket sync, WSL
   keepalive, off-site copy, **host probe** for Mission Control's resource view, see `host-setup.ps1` and the
   header of each script). `host-setup.ps1` currently registers only WSL keepalive and serves Open WebUI on 443;
   the other tasks and ports still need registering separately. Register the host probe as shown below.
   `tailscale serve --bg --https=<port> http://127.0.0.1:<local>` for:

   | tailnet port | local | what |
   |---|---|---|
   | 443 | 3080 | Open WebUI |
   | 8443 | 6006 | Phoenix |
   | 8445 | 4096 | OpenCode |
   | 8446 | 5173 | Understand Anything code map |
   | 8447 | 8090 | Mission Control |
   | 8448 | 9119 | Hermes admin (dashboard) |

   For the Hermes admin gate, run this in Windows PowerShell:
   `tailscale serve --bg --https=8448 http://127.0.0.1:9119`. Verify with `tailscale serve status` and open
   `https://<pc>.ts.net:8448` from a signed-in tailnet device. Local port 9119 forwards to `gate-hermes-dashboard`,
   which requires `Tailscale-User-Login`; it is not an unguarded dashboard listener. Keep all published ports
   on `127.0.0.1`, keep the gate, and use Serve only: no Funnel, public listener or router port forwarding.

   ChatGPT login is in the backup (litellm-auth); if it expired: `make chatgpt-login`.
9. Apply the Hermes profiles and dashboard API-key synchronization below, even after a restore. E-mail delivery
   is already configured (`make email-setup` only to change it). If not using `new-machine.sh`, enable the runner
   with `systemctl --user daemon-reload` and `systemctl --user enable --now missions.service`.

## Builder image prerequisite

`images/builder/Dockerfile` takes `ARG HERMES_IMAGE=aistack/hermes:0.22.5-web3`: this is the default base image
when `--build-arg` is omitted, not a required extra argument. It currently matches `HERMES_IMAGE` in
`versions.env`. Build Hermes first; the generic `ops/new-machine.sh` build loop does not pass
build arguments and visits the builder before Hermes. In WSL, from `~/ai-stack`:

```bash
. ./versions.env
docker build -t "$HERMES_IMAGE" images/hermes
docker build --build-arg HERMES_IMAGE="$HERMES_IMAGE" -t aistack/builder:1 images/builder
```

The explicit override keeps the builder on the pin in `versions.env` if it later differs from the Dockerfile
default (as `ops/deploy.py` already does). Build the remaining local images before starting the full stack.

## Windows desk and Remote Control

Run `powershell -ExecutionPolicy Bypass -File \\\\wsl.localhost\\Ubuntu-24.04\\home\\owner\\ai-stack\\ops\\windows\\desk-setup.ps1` once,
then `C:\\AI\\ops\\desk-signin.ps1` to sign Claude Code in. See `ops/windows/AGENTS.md` (PLT-31, PLT-32).

## Windows host-probe task

After copying `ops/windows/host-probe.ps1` to `C:\AI\ops\host-probe.ps1`, register and start the task from a
normal Windows PowerShell session (no admin). The settings let the long-running loop continue on battery
without Task Scheduler's execution time limit:

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\AI\ops\host-probe.ps1'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -Hidden
Register-ScheduledTask -TaskName "ai-stack host probe" -Action $action -Trigger $trigger -Settings $settings -Force
Start-ScheduledTask -TaskName "ai-stack host probe"
Get-ScheduledTask -TaskName "ai-stack host probe"
Get-Content C:\AI\exports\.host\host.json
```

Allow the first sample to be written, then check that `ts` advances every 30 seconds in
`C:\AI\exports\.host\host.json`. WSL reads this through `/srv/win-exports/.host/host.json`; Mission Control's
Stack page should show Windows CPU, RAM and disk numbers. The probe writes only this resource snapshot and
does not need a network listener.

## Hermes profiles and dashboard API-key synchronization

Run these in WSL after the containers are up. The main, scout and curator configurations live in the restored
Hermes home, but reapplying the scripts brings them up to date. The mission profile uses its own `VK_MISSION`
key, supplied as `LITELLM_MISSION_KEY`; the builder has a separate home and gets `LITELLM_BUILDER_KEY` from
Compose (`VK_BUILDER`). Use the existing sops environment injection, not copied or printed key values:

```bash
docker exec -u hermes aistack-hermes-1 sh /config/configure.sh
docker exec -u hermes aistack-hermes-1 sh /config/configure-scout.sh
docker exec -u hermes aistack-hermes-1 sh /config/configure-curator.sh
sops exec-env secrets/agent-keys.enc.yaml 'docker exec -e LITELLM_MISSION_KEY="$VK_MISSION" -u hermes aistack-hermes-1 sh /config/configure-mission.sh'
docker exec aistack-builder-1 sh /config/configure-builder.sh
docker restart aistack-hermes-1
```

The first command is also the existing **dashboard API-key synchronization** step: the dashboard shares
`hermes-home` and can write an `API_SERVER_KEY` into the container's `/opt/data/.env` that overrides the Compose
environment. `configure.sh` replaces that entry with the gateway container's `API_SERVER_KEY` when it is nonempty,
so the gateway, Mission Control and Open WebUI agree again. Do not inspect or edit the file or generate another
key. Re-run `configure.sh` and `docker restart aistack-hermes-1` after dashboard changes if chat gets an
authentication error. Restarting also reloads profile configuration and cached MCP tools.

Verify with `make smoke`, a chat in Mission Control and Open WebUI, and
`systemctl --user is-active missions.service`. Confirm the mission profile exists with
`docker exec -u hermes aistack-hermes-1 hermes profile list`; the builder uses its own default profile, not a
`-p builder` profile inside the main container. In Mission Control, run a small mission and a small build
assignment to exercise both profiles; review the build without approving a deployment just to test setup.

The restore is tested weekly (restore-drill.timer) and the move was rehearsed on 27 Oct
(`ops/windows/rehearse-new-pc.ps1`, throwaway distro). Its automated comparisons cover core restored data only;
the script's manual follow-up checklist covers the newer setup topics above. Mission Control, builder and
Hermes dashboard remain disabled in `compose/rehearsal.yaml`. Do not publish ports, register Windows tasks,
enable timers or run live missions/builds from the throwaway rehearsal: validate those on the replacement PC
after the isolated restore check. A passing restore comparison alone does not prove the full setup is ready.

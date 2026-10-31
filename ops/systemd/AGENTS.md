# ops/systemd/: user units and timers

systemd **user** units for `owner` (`~/.config/systemd/user`, installed by `ops/deploy.py` and `ops/new-machine.sh`).
Each job is a `name.service` (what to run) plus, if scheduled, a `name.timer` (when).

| Unit | Job |
|---|---|
| `missions.service` | the Mission Control runner (always on) |
| `backup` / `restore-drill` | nightly encrypted backup to the NAS; weekly proof that it restores |
| `vault-ingest` | converts and indexes new vault files |
| `memory-review` | decides staged memory writes by rule |
| `skills-sync` | mirrors Hermes' skills into git every 5 minutes |
| `curate` | the weekly learning run |
| `crew-checker` | hourly: the Checker (did each shipped idea work; autonomy rules; a failing agent pauses itself) |
| `swarm-sync` | every minute: the app's view of the Ledger and its events on the activity feed (`ops/swarm_client.py feed`) |
| `graphify-sync` | refreshes code graphs |
| `digest` | the morning Telegram digest |
| `upgrade-check` | monthly report on newer pinned versions |
| `stack-ready` | after a boot, checks that Hermes sees its tools |
| `desk.service` | one briefing run (started by `make desk`) |

## Rules

- Secrets: `ExecStart=sops exec-env <file> '<command>'`, never `EnvironmentFile=` with plain values.
- `Persistent=true` on timers that must catch up after the PC was off.
- A new job appears on the Stack page automatically (the runner lists the user timers). Give the unit a clear
  `Description=`.

`docker-no-detach-netns.conf` is a drop-in for rootless Docker itself (classic network-namespace mode; see the file).

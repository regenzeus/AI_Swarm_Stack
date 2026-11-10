# ops/systemd/: user units and timers

systemd **user** units for `owner` (`~/.config/systemd/user`, installed by `ops/deploy.py` and `ops/new-machine.sh`).
Each job is a `name.service` (what to run). **n8n decides when it runs** (WFL-09, DEC-51): a crew job's workflow in
`n8n/workflows/` starts its service through the step service (`ops/flows.py` run_crew: `systemctl --user start --wait
<unit>.service`), and Run now on its page starts the same unit.

## The one rule, and its exceptions

n8n starts every scheduled job. A unit keeps a `name.timer` only when it **must run when n8n is down**:

| Timer | Why systemd, not n8n |
|---|---|
| `stack-ready` | after a boot: waits for Docker and Hermes' tools, restarts Hermes once, opens the gate for the jobs (PLT-28). It brings the stack up, n8n included, so it cannot wait for n8n |
| `backup` | the nightly encrypted backup to the NAS. It holds n8n's own database, so a broken n8n must never stop it |
| `restore-drill` | the weekly proof that the newest backup restores, for the same reason |

Everything else (the crew, the syncs, the vault ingest, the trial rotation, the nightly restart of the services that
grow while idle) is a service without a timer. `grep -rn "OnCalendar\|OnUnit\|OnBoot" ops/systemd` lists only the three
above. A deploy removes the installed copy of a timer the repository dropped (stopped, disabled, deleted with its
drop-ins; `ops/deploy.py` remove_units).

| Unit | Job |
|---|---|
| `missions.service` | the Mission Control runner (always on): missions, tasks, the step service's worker |
| `backup` / `restore-drill` | nightly encrypted backup to the NAS; weekly proof that it restores (timers) |
| `stack-ready` | after a boot: the gate for the jobs (timer, 30 s after boot) |
| `vault-ingest` | converts and indexes new vault files |
| `memory-review` | decides staged memory writes by rule |
| `skills-sync` | mirrors Hermes' skills into git |
| `curate` | the weekly learning run |
| `crew-*` | the crew's own jobs (`ops/crew.py`: the Checker, the Coach, the Editor, the Health doctor, ...) |
| `crew-tax-find`, `crew-tax-file` | the tax desk's steps without a model, before and after its reader (`ops/tax.py`, TAX-01, TAX-03) |
| `swarm-sync` | the app's view of the Ledger and its events on the activity feed (`ops/swarm_client.py feed`) |
| `graphify-sync` | refreshes code graphs |
| `repofacts-sync` | refreshes the facts of repositories whose HEAD moved, one at a time (`ops/repofacts.py`) |
| `digest` | the morning Telegram digest |
| `upgrade-check` | monthly report on newer pinned versions |
| `tracker-poll` | the trackers' changed items start or wake their runs in n8n, each change once (`ops/runreg.py poll`, WFL-19) |
| `rotation` | one trial a night of the weekly rotation, when the stack is idle (TRL-14) |
| `recycle` | restarts qmd, Phoenix and Open WebUI at night, when the stack is idle (PLT-27) |
| `desk.service` | one briefing run (started by `make desk`) |
| `swarm-eval@.service` | one agent-change experiment (started by `ops/evals.py`) |

## Rules

- No home folder or user id in a unit (PLT-33): `%h` for the user's home, `unix://%t/docker.sock` for its Docker.
- Secrets: `ExecStart=sops exec-env <file> '<command>'`, never `EnvironmentFile=` with plain values.
- A new scheduled job: its service here, its entry in `ops/crew.py` CREW (with `unit`), and its workflow made by
  `python3 ops/n8n_gen.py crew <job> '<cron>'` (inactive until `ops/n8n_switch.py <file> on`). Never a new timer,
  unless the job must run when n8n is down; then add it to the table above with the reason.
- `Persistent=true` on a kept timer that must catch up after the PC was off. n8n does not catch up a run the PC slept
  through.
- Every scheduled job starts with `ExecCondition=/usr/bin/python3 %h/ai-stack/ops/stack_gate.py` (PLT-28; a test
  holds all of them to it). Not up means skipped, not failed. A job that runs every few minutes takes no arguments; one that
  runs daily or less often takes `--wait 1800 --slot <minutes after boot>`, its own slot so the heavy jobs after a boot
  start one at a time. The wait counts against `TimeoutStartSec`, so add it there.
- A crew job appears on its Agents page and as the stack's task automatically (`ops/crew.py`, `ops/tasks.py`). Give
  the unit a clear `Description=`.

`docker-no-detach-netns.conf` is a drop-in for rootless Docker itself (classic network-namespace mode; see the file).
`docker-boot.conf` is another: Docker keeps trying to start for as long as it takes (PLT-29). A deploy installs a changed
`docker-<name>.conf` as `docker.service.d/<name>.conf`; it takes effect at Docker's next start, and a deploy never restarts Docker.

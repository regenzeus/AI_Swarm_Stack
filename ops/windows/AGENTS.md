# ops/windows/: the Windows host

PowerShell scripts that run on Windows 10 (as the user, **no admin**). They are registered as Task Scheduler tasks
by `host-setup.ps1`.

| Script | Job |
|---|---|
| `host-setup.ps1` | one-time setup: tasks, folders, `tailscale serve` ports |
| `host-probe.ps1` | Windows RAM, CPU and disk every 30 s, for the Stack page (`C:\AI\exports\.host\host.json`) |
| `disk-heal.ps1` | self-healing check of the WSL disk |
| `offsite-copy.ps1` | copies the encrypted nightly backup to OneDrive |
| `bitbucket-sync.ps1` | keeps Bitbucket level with Forgejo for TestRepo |
| `rehearse-new-pc.ps1` | builds the whole stack from scratch in a throwaway WSL distro |
| `desk.ps1`, `desk-common.ps1`, `desk-settings.json` | PLT-31: the stack's one way to ask Windows: status, and read-only questions to Claude Code in the folders of `C:\AI\ops\desk-folders.txt` |
| `claude-remote.ps1` | PLT-32: keeps one `claude remote-control` running from logon, for the phone |
| `worker.ps1` | GEN-11: the Windows worker, as the standard account `aiworker`: runs only job kinds declared in `C:\AIWorker\jobs.d` and approved by their hash (docs/PLATFORM.md §6) |
| `worker-broker.ps1` | GEN-11: carries requests from WSL into the worker's inbox and its answers back to `C:\AI\exports\.host\worker`, as the owner; runs nothing |
| `worker-setup.ps1`, `worker-approve.ps1`, `worker-selftest.ps1` | the setup the owner runs once as administrator (`-DryRun` first), the owner's tap per job kind, and the worker's check against the protocol cases |
| `desk-setup.ps1`, `desk-signin.ps1` | install or update those (no admin), and the one sign-in only the owner can do |
| `disk-scan.ps1` | read-only disk analysis (like TreeSize) for the PC cleanup mission, started by `host-probe.ps1` on the runner's request; writes `C:\AI\exports\.host\diskscan.json` |

## Rules

- Windows PowerShell 5.1 syntax: no `&&`, `||`, `?:`, `??`. Write files with an explicit `-Encoding utf8`.
- Never need admin rights, never change system or security settings, never touch router or firewall rules.
- Scripts that are copied elsewhere say so in their header and are kept in sync from here.
- WSL asks, Windows fetches (DEC-43). A request is data: never a command to run, never a generic "run this", and interop stays off.
  The list of folders stays on Windows, where WSL cannot write. A level that changes anything needs the owner's tap on the whole job.

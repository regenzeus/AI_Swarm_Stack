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
| `disk-scan.ps1` | read-only disk analysis (like TreeSize) for the PC cleanup mission, started by `host-probe.ps1` on the runner's request; writes `C:\AI\exports\.host\diskscan.json` |

## Rules

- Windows PowerShell 5.1 syntax: no `&&`, `||`, `?:`, `??`. Write files with an explicit `-Encoding utf8`.
- Never need admin rights, never change system or security settings, never touch router or firewall rules.
- Scripts that are copied elsewhere say so in their header and are kept in sync from here.

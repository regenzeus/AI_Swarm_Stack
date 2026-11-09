# deployments/example-work/checks/: the judge's checks this deployment adds

One file per repository, `<repo>.yaml`, with a list of checks the judge runs after its own steps (GEN-15,
docs/PLATFORM.md §7). The owner writes them; no agent does. A check runs in the sandbox (`where: wsl`, a `command`) or
as a job kind of the Windows worker (`where: windows`, a `job` and its `values`); a failing one reopens the change with
its problems, and one that cannot run is no pass.

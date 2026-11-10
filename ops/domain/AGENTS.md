# ops/domain: what a domain's work uses (docs/AI-STACK.md)

The parts a deployment's work uses, whatever decides when it runs (n8n, DEC-51; the Conductor for plans until it moves):
- `packs.py`: a domain kept outside the repository (agents, skills, MCP servers, job kinds, n8n workflows, exams),
  pinned by commit and approved per commit in the queue (GEN-21, GEN-30, GEN-32).
- `places.py`: where a command's job runs (wsl, wsl-host, windows) through the worker protocol, each job kind approved
  at its place by its hash (GEN-22).
- `trackers.py`, `forgework.py`: trackers and the forge read with a cursor and written through shadow mode; a change's
  branch from a tag and its draft pull request (GEN-25, GEN-26).
- `roles.py`: who decides for a role (GEN-27). `artifacts.py`: saved files by hash (GEN-29). `record.py`: a run's
  bundle and a pack's exams (GEN-31).

Nothing here starts a run or keeps a scheduler: a module hands events on (`trackers.poll`, `forgework.poll_prs`) or
does one thing when asked. The queue reads `decisions()` of packs, trackers and places (ops/decisions.py); the app's
actions reach `handle()` through ops/missions.requests.py. Tests: tests/test_domain_*.py.

# ops/domain: what a domain's work uses (docs/AI-STACK.md)

The parts a deployment's work uses, whatever decides when it runs (n8n, DEC-51; the Conductor for plans until it moves).
None of them names a domain: a deployment's domain arrives as a pack, and the tests use a toy pack and stand-ins (the
boundary is checked, GEN-44).
- `packs.py`: a domain kept outside the repository (agents, skills, MCP servers, job kinds, n8n workflows, exams),
  pinned by commit and approved per commit in the queue (GEN-21, GEN-30, GEN-32). A workflow with a node outside the
  deployment's `N8N_NODES_INCLUDE` (read through the data guard, `dataguard.n8n_nodes()`, the one reading of it,
  WFL-17), or a webhook outside `item/<pack>/` or `<pack>/`, is refused with the reason (GEN-42). An approval or
  refusal syncs n8n at once (`sync_n8n`, through `ops/n8n_sync.py sync_packs`, GEN-43); a canvas edit of a pack's
  workflow goes back to the pack's own repository as a branch and a draft pull request (`propose`), never to the
  stack's, and what runs stays the approved commit's version. A new commit replaces its workflows in place: waiting
  runs finish on the version they started with (WFL-24, docs/N8N-MIGRATION.md §11).
- `places.py`: where a command's job runs (wsl, wsl-host, windows) through the worker protocol, each job kind approved
  at its place by its hash (GEN-22). The local places' worker is `ops/localworker.py`; a worker runs one job at a time,
  and a request queued behind a job of hours is never given up: the pick-up clock counts only while the worker is gone
  or idle, and a job's run limit is its kind's own minutes (GEN-40).
- `trackers.py`, `forgework.py`: trackers and the forge read with a cursor (Jira's in the token user's time zone,
  paged, GEN-41) and written through shadow mode; a change's branch from a tag and its draft pull request (GEN-25,
  GEN-26). Jira goes through atlassian-python-api, pinned for the runner (ops/runner-requirements.txt). A comment is
  the stack's own by its author (`me`) or by the write mark it ends with (`trackers.own`, WFL-26), so a tracker where
  the stack writes with the owner's account (home's Forgejo inbox, GEN-45) still tells the owner's replies from the
  stack's comments; `trackers.item_text` is an item as an agent step that names it reads it (WFL-25).
- `roles.py`: who decides for a role (GEN-27). `artifacts.py`: saved files by hash (GEN-29). `record.py`: a run's
  bundle (`export_run`, from the run register) and a pack's exams (GEN-31).

Nothing here starts a run or keeps a scheduler: a module hands events on (`trackers.poll`, `forgework.poll_prs`, each
to a `hand` the run register gives before its cursor moves) or does one thing when asked. Which run an event starts or
wakes is the run register's (`ops/runreg.py`, WFL-19); a run's zip is `record.export_run`, made from the register with
only the workflow's shape from git or the pack cache (WFL-23). A tracker entry that cannot be used is refused with its
reason at load (`trackers.refused`: a Jira query with its own ORDER BY, an unknown kind or restart, a `${NAME}` the
deployment.env beside it does not set).

The outside-write rule: every write the stack makes to a system outside it (a tracker's comment, summary, attachment,
link, transition, label) waits in shadow per kind until the owner lets that kind go live (GEN-25, WFL-21). The one
stated exception is a draft pull request (DEC-54): a change for an item, with FORGE_PUSH, and a canvas edit of a pack's
workflow go out as drafts directly, because a draft changes nothing people use until they merge it, and the stack
never merges. State files are written whole or not at all (`ops/statefile.py`). The queue reads `decisions()` of
packs, trackers and places (ops/decisions.py); the app's actions reach `handle()` through ops/missions.requests.py.
Tests: tests/test_domain_*.py, and the whole path in tests/test_work_deployment.py.

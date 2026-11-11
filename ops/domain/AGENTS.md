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
  stack's comments; `trackers.item_text` is an item as an agent step that names it reads it (WFL-25),
  `trackers.read_item` and `fetch` the item and its attachments for the step `item` (WFL-28). A new tracker counts
  its items from its first pass (`start: now`, the default) or a date; a tracker that has its state keeps it
  (`trackers.start_of`, WFL-27). The owner judges each shadow write: send it (written through the adapter once, with
  its write id), keep it back, or wrong (WFL-29). The summary edits only the comment whose id the stack kept when it
  wrote it (WFL-30); attach, transition and label are done when the item holds them already (WFL-31). Events carry
  the comments' texts (`said`) for the run register; a pull request's comments are their own source (WFL-32).
- `records.py`: the read cache of a tracker of record (REC-01 to REC-08). A tracker in trackers.yaml names the pack
  whose `records.yaml` types its items (`records: <pack>`); `write: off` makes a tracker read-only (trackers.py
  `read_only`: every write is kept in the stack, its answer says `off`; the adapter's `put` refuses; a shadow write
  from before cannot be sent), and a tracker without a workflow is read for its records only and starts no run. The
  tracker poller (`runreg.poll`) calls `records.refresh`: one pass of `sync` (each tracker's own cursor, `adapter.record`
  of each changed item, nothing written to the tracker) and the app's view (`public/records.json`). Queries:
  `missing_work_products`, `missing_link(tracker, link, types)`, `missing_fields`, `links_of`; `measures` computes the
  pack's measures with the records behind each number. CLI: `python3 ops/domain/records.py sync|view|measures|missing`.
  **The gated transition hook**, for the Ask system's gate: `records.set_gate(fn)` once where the runner starts;
  `trackers.write` of a transition asks `records.check_transition(tracker, key, to)`, which finds the pack's gate for
  the record's type and status (`gate_of`: `{id: gate:<tracker>/<key>/<to>, gate: true, tracker, key, type, to, role,
  question}`; a record not in the cache meets every gate on that status) and calls `fn(need)`. `fn` answers `{state:
  approved|waiting|refused, person, role, chip, ask, at, why}`; the write goes on (into shadow, as every write) only
  for `state: approved`, `chip: true`, no `interpreted_as`, `by_default` or `rule`, and a person `roles.may` lets hold
  the role; the approval is kept in the cache's `gates` table and shown on the record. Otherwise the write answers
  `{refused: true, gate: need, why}`, so the caller opens the gate Ask and writes again once it is answered; with no
  `fn` set every gated transition is refused with the reason.
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
Tests: tests/test_domain_*.py (records: tests/test_domain_records.py, on the toy pack and a stand-in Jira in
tests/fixtures/jira/five.json), and the whole path in tests/test_work_deployment.py.

# n8n

The deployment's workflows (WFL-08, docs/N8N-MIGRATION.md). n8n decides when work starts and in what order; every step
of the stack's own work goes to Mission Control's step service (`http://mission-control:8099/steps`, ops/flows.py)
through the stack's own node, which waits for the answer.

| Path | What |
|---|---|
| `workflows/*.json` | one workflow per file, imported by every deploy that changes them (`ops/n8n_sync.py import`), active or not as the file says |
| `custom/` | the stack's own node, AI Stack step (WFL-06), loaded by n8n when it starts |

The editor lives inside the app: **Workflows** in the desk menu (`#/workflows`), served by the app under `/n8n/`
behind its gate (WFL-13, `images/mission-control/server.frames.py`). Webhooks and resume URLs stay at n8n's root on its
own tailnet port 8450 (`WEBHOOK_URL`), which is also the direct fallback when the app is down
(`https://<pc>:8450/n8n/`); without the tailnet they stay on `http://127.0.0.1:5678/` (WFL-15). A step's title is how
the app's pages name it: keep it equal to the node's name, as `ops/n8n_gen.py` does, so a run's steps line up with the
workflow's nodes (`ops/flows_view.py`).

n8n holds time and order only (DEC-54): what a run did is the step service's run register (`ops/runreg.py`, WFL-23),
and a run's zip is made from it, never from n8n's API. The deployment's data class sets what n8n may hold and load: in
a customer-class deployment n8n gets lean answers (status, ids, a summary; WFL-22), loads only the logic nodes and the
AI Stack step (`N8N_NODES_INCLUDE`, the data guard's list; WFL-17), and keeps its executions on the PC (WFL-18). A
tracker item's workflow starts with a Webhook trigger at `item/<pack>/<name>` that answers with its execution, and
branches on a wait's outcome with an IF node (docs/N8N-MIGRATION.md §3.6); the test pack's item workflow
(tests/fixtures/packs) is the example.

A pack's workflows are not here: they come from the pack's approved commit, named `<pack>/<name>` under ids starting
with `pack` (`ops/n8n_sync.py sync_packs`, GEN-43). An edit of one on the canvas is a proposal: `export` and every sync
send it to the pack's own repository (branch `ai/canvas-<date>`, a draft pull request where its forge allows) and put
the approved version back; it runs once a commit with it is approved. A changed workflow is imported in place: a run
that waits finishes on the version it started with (WFL-24, docs/N8N-MIGRATION.md §11).

Change a workflow on the canvas, then `python3 ops/n8n_sync.py export` in a session's worktree and land it. n8n is the
one scheduler (WFL-09): a job with `"active": false` runs only when started by hand (Run now) until its switch
(`ops/n8n_switch.py <file> on`). A workflow the runner made for a task since the last export, or switched off, is kept in
`/srv/ai/missions/flows/made/` (`ops/n8n_jobs.py`); an export brings it here and its copy there goes.

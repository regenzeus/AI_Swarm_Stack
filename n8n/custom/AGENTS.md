# n8n/custom

The stack's own n8n node (WFL-06), loaded by n8n from N8N_CUSTOM_EXTENSIONS (compose/core.yaml); plain JavaScript,
nothing is built or fetched. n8n names a node loaded this way `CUSTOM.<name>`, and reads it when it starts: a change
here reaches n8n after a restart of its container.

| File | What |
|---|---|
| `AistackStep.node.js` | **AI Stack step**: one block of the palette per kind, sent to Mission Control's step service (`POST http://mission-control:8099/steps`, ops/flows.py); the node waits until the runner posts the answer to its execution, and the answer is its output. An answer that failed, was refused or was cancelled fails the node on resume, so the run ends as an error; an answer with an `outcome` (a wait on an item: `reply` or `timeout`) is a result the workflow branches on (an IF node on `{{ $json.outcome }}`), never a failure |

Kinds (the step service's `KINDS`): Agent step (`agent`), Coding change (`build`), Crew job (`crew`), Plan task
(`task`), Ask the owner (`ask`, optionally for a role: only its people may answer), Notify the owner (`notify`), Recall
(`recall`), Remember (`remember`), Run command (`command`), Run a plan (`plan`), Wait for the item (`wait_item`: the
item's tracker and key, at most `timeout_hours`), Write to the item (`tracker`: comment, summary, attach, link,
transition or label, in shadow until its kind goes live). A Coding change for a tracker item also names the item
(`<tracker>/<key>`), its base ref or tag and its target branch: it goes out as a draft pull request.

Each step also sends its workflow's name and its node's name, so the run register (ops/runreg.py) keeps the run's steps
by name.

The Agent, Crew job, Place, Repository, Tracker and Role pickers are n8n `loadOptions` methods that read
`GET http://mission-control:8099/catalog` (the lists the runner writes every minute, public/step-catalog.json).

Rules:
- A new kind goes into ops/flows.py first (validated, run through the stack's own code, reported, tested), then here
  with its fields; `tests/test_n8n_sync.py` checks that every kind of the step service is offered.
- Keep the node's `name` and `version`: every workflow in `../workflows` names `CUSTOM.aistackStep` version 1.
- Test a change on a throwaway n8n (its own Postgres and a stand-in step service on a private network), never on the
  live one.

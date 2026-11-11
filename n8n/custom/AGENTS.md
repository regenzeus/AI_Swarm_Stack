# n8n/custom

The stack's own n8n node (WFL-06), loaded by n8n from N8N_CUSTOM_EXTENSIONS (compose/core.yaml); plain JavaScript,
nothing is built or fetched. n8n names a node loaded this way `CUSTOM.<name>`, and reads it when it starts: a change
here reaches n8n after a restart of its container.

| File | What |
|---|---|
| `AistackStep.node.js` | **AI Stack step**: one block of the palette per kind, sent to Mission Control's step service (`POST http://mission-control:8099/steps`, ops/flows.py); the node waits until the runner posts the answer to its execution, and the answer is its output. An answer that failed, was refused or was cancelled fails the node on resume, so the run ends as an error; an answer with an `outcome` (a wait on an item: `reply` or `timeout`) is a result the workflow branches on (an IF node on `{{ $json.outcome }}`), never a failure |

Kinds (the step service's `KINDS`): Agent step (`agent`), Coding change (`build`), Crew job (`crew`), Plan task
(`task`), Ask a person (`ask`, an Ask of ops/asks.py: type, choices, words or not, default, deadline, role, gate, sensitivity; it answers {status, outcome, values, words, person, role, via, interpreted_as}, ASK-19), Notify the owner (`notify`), Recall
(`recall`), Remember (`remember`), Run command (`command`), Run a plan (`plan`), Wait for the item (`wait_item`: the
item's tracker and key, at most `timeout_hours`, Wake on `on`: the item's comments, its pull request's, or either),
Write to the item (`tracker`: comment, summary, attach, link, transition or label, in shadow until its kind goes live),
Read the item (`item`: its text, comments and attachments; Fetch its files for `attach_to` a place, the attachments
named or all, answered by artifact id). An Agent step with "Read the item of" sends `from_item: true`. A Coding change
for a tracker item also names the item (`<tracker>/<key>`), its base ref or tag and its target branch: it goes out as a
draft pull request.

Each step also sends its workflow's name and its node's name, so the run register (ops/runreg.py) keeps the run's steps
by name.

The Agent, Crew job, Place (also Fetch its files for), Repository, Tracker and Role pickers are n8n `loadOptions` methods that read
`GET http://mission-control:8099/catalog` (the lists the runner writes every minute, public/step-catalog.json).

Both calls carry the step service's token, `Authorization: Bearer $AISTACK_STEP_TOKEN` from n8n's own environment
(compose/core.yaml, sops; SEC-25): the node's code reads it, workflow expressions cannot (`N8N_BLOCK_ENV_ACCESS_IN_NODE`).

Rules:
- A new kind goes into ops/flows.py first (validated, run through the stack's own code, reported, tested), then here
  with its fields; `tests/test_n8n_sync.py` checks that every kind of the step service is offered.
- Keep the node's `name` and `version`: every workflow in `../workflows` names `CUSTOM.aistackStep` version 1.
- Test a change on a throwaway n8n (its own Postgres and a stand-in step service on a private network), never on the
  live one.

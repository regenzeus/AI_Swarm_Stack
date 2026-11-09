# ops/engine: the AI Stack's engine (docs/AI-STACK.md, docs/AI-STACK-PLAN.md)

Temporal runs every plan and template; this package is the stack's side of it.
- `client.py`, `worker.py`, `converter.py` (references only, AES-GCM codec), `shapes.py`: the engine library.
- `graph.py`: the graph model and the templates' canonical YAML. `runner.py`: the one workflow that runs any graph.
- `activities.py`: what blocks do, through the Conductor's own step runner and adapters.
- `bridge.py`: the runner's side (ENGINE switch, starts, the pass that also polls trackers); `cutover.py`: the switch,
  smoke checks, rollback and the 14-day count. `projector.py`: what the app shows.
- `templates.py` (list, save, describe), `packs.py`, `trackers.py`, `forgework.py`, `places.py`, `artifacts.py`,
  `roles.py`, `record.py`: the features of docs/AI-STACK.md §4 to §11. `preview.py`: the dark preview.
Workflow code (runner.py) does no I/O and must replay: change it only with a `workflow.patched()` marker for runs in
flight, and run tests/test_engine_runner.py (the replay test).

# config/templates/demo: the preview's demo templates

The templates the preview runs on its own engine (ops/engine/preview.py), each in the canonical form of the graph model
(ops/engine/graph.py): one Start, its blocks, one or more Ends. `ticket` (a reported problem to an accepted fix: a wait
with reminders, an approval, a fan-out, a loop), `briefing` (a morning briefing as a plan runs it), `triage` (a decision
whose branches meet again). They touch nothing outside: the preview's activities only sleep and answer references.
A change here must stay canonical: tests/test_engine_view.py checks it.

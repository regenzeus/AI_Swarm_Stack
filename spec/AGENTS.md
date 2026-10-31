# spec/: requirements-checker pilot

A research pilot: read a specification, find which code implements each requirement, and judge whether it meets it.
`README.md` describes the method and results. Pipeline: `ingest.py` (PDF → spec model, offline) → `extract.py`
(requirements from specs without numbering) → `link.py` (requirement → code) → `judge.py` (verdict with evidence).
`pilot/` holds the pilot's baseline, mutation and report scripts.

## Rules

- Each step reads the previous step's output files and writes its own, so every step can be re-run alone.
- Offline steps stay offline. Model calls go through LiteLLM on the subscription.
- Report numbers with how they were measured (`pilot/report.py`). Don't put a result in the README without its run file.

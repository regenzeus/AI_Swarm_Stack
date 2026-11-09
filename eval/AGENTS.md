# eval/: quality measurement

| Path | What it is |
|---|---|
| `bench-v1.yaml` | the **frozen** benchmark for Hermes (profile main): 40 cases. Its hash is in `FROZEN.sha256` and checked by `ops/check.sh` |
| `bench.py` | runs the benchmark and scores it (`make bench`, or `make bench-gate` for the 14-case gate) |
| `retrieval.py`, `qrels/` | search quality per qmd collection: recall@8, nDCG@8, MRR against hand-made relevance judgements (`make retrieval`) |
| `fixtures/` | inputs for gate tests (for example a deliberately harmful skill patch the curator gate must reject) |
| `results/` | committed result files of past runs, for comparison (`*-try.json` are ignored) |

## Rules

- **Never change `bench-v1.yaml`.** A new benchmark is a new file (`bench-v2.yaml`) with its own frozen hash, so
  results stay comparable over time.
- Benchmarks use the subscription only and take minutes, so they are not part of `make check`. Run the gate before
  changing prompts, profiles, models or the curator.
- Commit result files you compare against, with the date in the name.

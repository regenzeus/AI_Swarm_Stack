# spikes/eval/: the evaluation spike (stage 0, not product)

Can Phoenix hold exam sets, run experiments and a calibrated rubric judge well enough to be the work side's interim
scorer now and the base of stage 6's evaluation? The report, with the measurements and the verdict, is
[docs/spikes/EVAL.md](../../docs/spikes/EVAL.md).

| File | What it is |
|---|---|
| `exam.py` | The scorer: `run <set>` puts a set into Phoenix as a dataset, runs one experiment and judges every result with the rubric (a phoenix-evals classifier through the site's gateway); `from-bench` turns the frozen benchmark's judged answers into a set |
| `rubric.md` | The judge's rubric and prompt: pass or fail against the expected outcome, with the part that decided it |
| `change-requests.yaml` | 18 made-up change requests with an expected outcome, a made-up result and a person's verdict: the calibration set |
| `run.sh` | Runs `exam.py` in a throwaway container: the pinned Python image, `requirements.txt`, the gateway key from the environment |
| `requirements.txt` | Every package pinned (a pip freeze) |
| `phoenix.sh`, `phoenix-onsite.env` | The spike's throwaway Phoenix (the stack's pinned image) with the settings that keep data on the site |

## Rules

- Sets in git hold made-up items only: invented repositories, requests and results. Real cases go into the site's own
  Phoenix, never into git.
- The gateway key is read from the environment (`sops exec-env`), never passed on a command line or printed.
- A case states its outcome so a reader can check it; a case that does not is unfair to the judge and to the agent.
- Nothing here is deployed or imported by the stack; stage 1 rebuilds what it keeps (see the report).

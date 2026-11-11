# spikes/: stage 0 spikes

Short, honest trials of the risky choices of the platform design (docs/PLATFORM-DESIGN.md §11, stage 0). Each ends in
"yes, this choice holds" or "no, use this replacement", with evidence in its report under `docs/spikes/`. Spike code is
not product: no requirement entries, nothing here is deployed or imported by the stack, and stage 1 rebuilds what it
keeps.

| Folder | Question | Report |
|---|---|---|
| `eval/` | Can Phoenix hold exam sets, run experiments and a calibrated rubric judge, as the work side's interim scorer now and the base of stage 6? | [docs/spikes/EVAL.md](../docs/spikes/EVAL.md) |

## Rules

- A spike runs only its own throwaway containers, named `spike-<name>-*`, on its own network, with no port published
  except on 127.0.0.1, and removes them when it ends. It never touches the live stack.
- Every image and package is pinned to an exact version; lockfiles are committed; no tool is installed on the host.
- Demo data only: nothing private, nothing work-specific.

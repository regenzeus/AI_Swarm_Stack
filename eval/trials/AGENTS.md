# eval/trials/: the trials (docs/SWARM-TRIALS.md)

One file per trial, `<name>.yaml`: the task in the owner's words, what is forbidden (patterns for the pages agents
read and the actions they take), the answer key's folder name, the similarity reference inside it, the budget.
`ops/trials.py` loads and checks it; `make trial-check NAME=…` proves its key, `make trial NAME=…` runs it.

The answer key is never here: it lives in `/srv/ai/private/trials/<key>/` (`inputs/` for the agents, `score.py` and its
vectors, `reference/` that must score fully, the upstream code for the similarity check), which no container mounts.
A trial whose key is in the repository can be read by the agents it tests.

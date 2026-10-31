# requirements/: what the stack must do

The engineered requirements of the AI stack (method: [README.md](README.md)). YAML files are the source;
`REQUIREMENTS.md` is generated from them (`python3 ops/req.py render`) and checked to be current.

| File | Holds |
|---|---|
| `stakeholder-needs.yaml` | `SN-*`: what the owner wants, in his terms |
| `constraints.yaml` | `CST-*`: limits nothing may break |
| `decisions.yaml` | `DEC-*`: dated owner decisions, the "why" behind requirements |
| `<area>.yaml` | system requirements per subsystem (`PLT`, `SEC`, `GW`, `AST`, `KNW`, `RES`, `MIS`, `APP`, `BLD`, `CRW`, `OBS`, `PHN`, `CNX`, `SHP`, `HSE`, `QA`, `SWM`) |
| `findings.yaml` | `FND-*`: contradictions and incoherent parts, with evidence |
| `swarm.yaml` | the agent swarm, not built yet: grouped, with rollout `phases` and an `acceptance` criterion per requirement |
| `glossary.md` | the names of the parts a requirement may use as its subject |
| `unmapped-tests.txt` | tests no requirement claims yet; may only shrink |

## Rules

- **Change a requirement in the same commit as the behaviour**, and name its id in the commit body
  (`Requirements: MIS-05, PHN-11`). New behaviour gets a new requirement in its area file, with the next free
  number; ids are never reused or renumbered.
- **Write it with EARS** (README.md): one behaviour, a named subject from `glossary.md`, numbers with units, no vague
  words (`ops/req.py` lists them).
- **Verification is evidence.** `implemented` needs `verify.by` that exists: a test as
  `tests/test_x.py::test_name`, or for inspection a file that holds the behaviour. A new test is claimed by a
  requirement in the same commit, or `make check` fails.
- **Never silently resolve a contradiction.** Record it in `findings.yaml` (evidence, affected requirements,
  recommendation) and link it from each affected requirement; resolve it in its own change, with the owner where
  `decision: true`.
- **Status follows reality.** If the code breaks a requirement, mark it `violated` with a `gap` and a finding;
  don't weaken the statement to make it pass. Planned and proposed requirements are never shown as built.
- Run `python3 ops/req.py check` (part of `make check`) and `python3 ops/req.py render` before committing.

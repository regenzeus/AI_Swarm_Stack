# Requirements of the AI stack

This directory is the single, checked statement of **what the AI stack must do and must never do**. It was
reverse-engineered on 2026-10-29 from the owner's instructions, decisions, the docs, the in-app guide, the
`AGENTS.md` rules, the code and its tests, and it is kept current with every change (see "Keeping it current").

`REQUIREMENTS.md` is the readable rendering, generated from the YAML files here by `python3 ops/req.py render`.
Never edit it by hand: `make check` fails when it is stale.

## Method

| Practice | Source | How it is applied here |
|---|---|---|
| Requirement quality | ISO/IEC/IEEE 29148:2018, §5.2.5 | every requirement is necessary, singular, unambiguous, feasible, verifiable, correct and traceable |
| Requirement set quality | ISO/IEC/IEEE 29148:2018, §5.2.6 | complete (every need is refined), consistent (contradictions are logged as findings), bounded |
| Statement syntax | EARS (Mavin et al., 2009) | ubiquitous, event-driven, state-driven, unwanted-behaviour and optional-feature patterns, below |
| Priority | MoSCoW | `must`, `should`, `could` (a `won't` is a decision, recorded in `decisions.yaml`) |
| Verification | ISO/IEC/IEEE 29148: inspection, analysis, demonstration, test | each requirement names its method and the exact test, check or file that verifies it |
| Traceability | bidirectional | stakeholder need ← requirement → test and code; the checker refuses dangling links both ways |
| Rationale capture | decision records | owner decisions are dated records (`DEC-*`) that requirements cite as their source |
| Consistency | review findings | contradictions and incoherent parts are findings (`FND-*`) with evidence, never silently resolved |
| Baselines and change control | git | every change is a commit; a baseline is a tagged commit |

### Levels

1. **Stakeholder needs** (`stakeholder-needs.yaml`, `SN-*`): what the owner wants, in his words, with the source.
2. **Constraints** (`constraints.yaml`, `CST-*`): limits nothing may break (hardware, money, safety, hard rules).
3. **Decisions** (`decisions.yaml`, `DEC-*`): dated owner decisions, including the ones that changed earlier decisions.
4. **System requirements** (one file per subsystem, e.g. `missions.yaml`, `MIS-*`): what the stack shall do.
   Each refines at least one need or constraint (`parents`).
5. **Findings** (`findings.yaml`, `FND-*`): contradictions, incoherent parts, drift between docs, code and
   requirements, each with evidence and a recommendation.

### EARS patterns

| Pattern | Template |
|---|---|
| Ubiquitous | The `<system>` shall `<response>`. |
| Event-driven | When `<trigger>`, the `<system>` shall `<response>`. |
| State-driven | While `<state>`, the `<system>` shall `<response>`. |
| Unwanted behaviour | If `<condition>`, then the `<system>` shall `<response>`. |
| Optional feature | Where `<feature is present>`, the `<system>` shall `<response>`. |

The `<system>` is always a named part from `glossary.md` (the runner, Mission Control, the gateway, the AI phone
service, …), never "the system" when a part is meant. One requirement states one behaviour. Numbers carry units.

### The record

```yaml
- id: MIS-012                      # prefix of the file, then a number; never reused, never renumbered
  title: Usage-limit pause          # a few words
  statement: When a mission run fails because the subscription's usage limit is reached, the runner shall mark the
    run waiting and retry it every 30 minutes for up to 8 hours.
  type: functional                  # functional | quality | interface | constraint | process
  priority: must                    # must | should | could
  status: implemented               # see below
  parents: [SN-13, CST-02]          # needs, constraints or other requirements it refines
  sources: [DEC-01, docs/MISSION-CONTROL.md]
  rationale: The subscription pauses for hours; a failed run would lose the work.
  verify:
    method: test                    # test | inspection | analysis | demonstration
    by: [tests/test_runner.py::test_paused]
  trace: [ops/missions.py]          # files that implement it
  findings: [FND-07]                # optional
  gap: …                            # required when status is partial or violated
  acceptance: Test that …            # required when status is planned: how it will be verified
  phase: 1                          # optional; only in an area that lists its phases (swarm.yaml)
  group: Ledger                     # optional; groups an area's requirements under a heading
```

### Status

| Status | Means | Required |
|---|---|---|
| `implemented` | built, and the `verify` references prove it | `verify.by` |
| `partial` | built in part | `gap` says what is missing |
| `violated` | the requirement stands, but the system currently breaks it | `gap` and at least one finding |
| `planned` | approved by the owner, not built yet | a parent need or decision, and `acceptance` |
| `proposed` | suggested, not yet approved by the owner | nothing else; it is not a commitment |
| `deprecated` | no longer valid | `superseded_by` or `reason` |

## Keeping it current

The requirements stay true because changing the stack without them fails the checks:

- `ops/req.py check` runs in `ops/check.sh` (so in CI, in the builder and in `make check`). It refuses
  missing fields, unknown statuses, duplicate ids, dangling parents, sources, findings and trace paths, `verify`
  references to tests that do not exist, needs that no requirement refines, vague words in statements (EARS
  lint), a planned requirement without `acceptance`, a `phase` its area does not list, and a stale
  `REQUIREMENTS.md`.
- **Every unit test is claimed by a requirement.** A new test that no requirement lists in `verify.by` fails the
  check. `unmapped-tests.txt` may only shrink: a listed test that is now claimed, or gone, must be removed.
- **Definition of done** (root `AGENTS.md`): a change that adds or changes behaviour updates its requirement in the
  same commit (statement, status, `verify`, `trace`), and the commit body names the ids (`Requirements: MIS-012`).
- A contradiction found while working is written down as a finding, not resolved silently; resolving it is a change
  of its own, with the owner where it needs a decision.

Commands: `python3 ops/req.py check` (what CI runs), `python3 ops/req.py render` (rewrite `REQUIREMENTS.md`),
`python3 ops/req.py show MIS-012` (one requirement with everything that points at it).

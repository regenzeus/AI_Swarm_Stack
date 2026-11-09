# Change requests: the stack as the developer of the onboarded repositories

Design and record, 6 November 2026. Built: [ops/changes.py](../ops/changes.py) and [ops/repowiki.py](../ops/repowiki.py); the
state of each requirement is in its status. Its requirements are CHG-01 to CHG-18 in
[requirements/changes.yaml](../requirements/changes.yaml). It builds on the builder ([ops/builds.py](../ops/builds.py)),
the Conductor and the roles of [SWARM-TRIALS.md](SWARM-TRIALS.md), the memory design of [MEMORY.md](MEMORY.md) and
the onboarding job (BLD-26).

## What the owner wants

Read from the request of 6 November:

1. **Take over development.** Give the stack a change request for any onboarded repository and get back a branch where
   the change is implemented the way that repository does things, with its tests run and new tests where they belong.
2. **A swarm, not one coder.** Several specialised agents, each with its own view and its own key, with programs as
   judges, in the pattern Blitzy sells but on one PC and with the stack's own freedoms: any harness, two vendors, the
   owner's own memory.
3. **It gets better with use.** The agents keep what they learn about each repository and reach it next time, in a wiki
   per codebase that every code agent reads.
4. **Proven on the stack itself first**, and better than opening Claude with the repository loaded, in a way that lasts.
5. **The failure modes known in advance**, and good requirements engineering before a line is written.

## Why "the agents learn" is half true today

The stack already has the memory an agent needs: one wiki per mission or topic with one writer (MEM-03), journals per
agent read at each run's start (MEM-05), superseded facts that are never dropped (MEM-12), the Librarian's weekly tidy,
lessons the Coach turns into replayed agent changes. **None of it reaches the code roles.** The builder gets a code
graph pack and the assignment, writes nothing down, and reads nothing from its last build; the owner's review comments
are kept on the build and never again; the tester, breaker and judge ran only in trials; the onboarding job writes a code
map, a digest and an analysis that no agent is told to read before changing code. So the owner's intuition is right, and
the design below is that pattern applied to repositories, with one correction: a wiki about code goes stale the moment
the code moves, so every fact on it cites a commit and the code graph tells the lint which pages to re-verify.

## The model

A **change request** is a task of kind `change` with a repository, through the Conductor like every task (TSK-21):

```
request  →  specification  →  plan  →  steps (coder, tester, judge, breaker, reviewers, prober)  →  branch + report
    ↑              ↑                                                                                       │
 the owner      the owner's Go (medium and large)                                         the owner's review ──┘
                                                                                     (merge, changes, reject: each a lesson)
```

Every step is a run in the task's trace, hands over by artifact (MEM-15), and stops at the task's budget (TRL-11). The
output is always the same: a branch on Forgejo, a pull request there, the request's page in Mission Control with the
evidence, and one message. Nothing merges or deploys without the owner's tap (CST-07 stays).

## Intake: from a sentence to a specification

Doors: the chat ("Change ai-stack: …"), the repository's page (**Request a change**), Telegram, and the self-review's
ideas (the Ledger's `idea` with a plan is already a request). The intake agent (`prompts/intake.md`, on its own key)
writes the **change specification**, an artifact of kind `spec` in the Ledger, owned by the request:

| Part | Rule |
|---|---|
| Title and goal | one sentence each, the owner's words kept |
| Acceptance criteria | numbered, testable, EARS form ("When X, the app shall Y"); each one the Tester can write a test for |
| Scope | the files and modules it touches, from the repository wiki and the code graph; what is out of scope, in words |
| Size class | **S** (one file, under 100 lines, no new interface), **M** (a feature in one area, tests to add), **L** (several areas, an interface or a schema changes, parallel tasks); the class picks the plan and the budget |
| Risks | what could break, from the wiki's map of fragile areas and the blast radius |
| Open questions | at most three; the intake asks only when a question blocks the plan, and otherwise writes its assumption into the specification where the owner sees it |
| Budget | tokens, minutes and usage windows by size class, with the stack's own figures as the default (today: builds of ai-stack took 13,000 to 1,180,000 tokens) |

The owner sees the specification on the request's page. An S request runs at once under autonomy `auto`; an M or L
request waits for the owner's **Go** on the specification, which he may edit first. This is the one place a human is
in the loop before the work, and it is where most multi-agent failures are cheapest to catch (MAST: a task specified
badly is the first class of failure).

## The roles

Cards in `config/agents.yaml`, most of them there already. The rules of SWARM-TRIALS.md hold: separation of duties,
information barriers enforced by keys and workspaces, checks on the other engine, briefs not chatter.

| Role | Does in a change request | Reads | May not | Today |
|---|---|---|---|---|
| **Orchestrator** | the plan by size class; checkpoints between waves; stops at the budget | the specification, the wiki | do a step itself | exists (intake, Conductor) |
| **Analyst** | for L: turns the request and any specification the owner points at into the acceptance criteria | the request, documents | the code | exists |
| **Architect** | for M and L: the design and the task split with file leases for parallel coders; reads the wiki's architecture and conventions first | the specification, the wiki, the code graph | write code | exists (planner) |
| **Coder** | one task: implements in the repository's style, runs the tests, commits on the branch; runs the baseline first | the specification, its task, the wiki, the pack, the code | the acceptance tests before they run, the answer key of a trial | exists (builder; opencode as the second engine) |
| **Tester** | acceptance tests from the criteria alone, one per criterion, named by it | the specification, the public interface | the coder's code | exists (trials only) |
| **Judge** | a program: baseline on main, the suite on the branch, red-before-green of each acceptance test, reruns of what fails once, the repository's own checks; sends failures back to the coder for fix rounds (TRL-08) | everything, as a program | change code | exists (trials only); the baseline and red-before-green are new |
| **Breaker** | for M and L: edge cases and odd inputs through the public interface, each failure a reproducing test | the specification, the program as a black box | the source | exists (trials only) |
| **Reviewer** | two lenses on the other engine (requirements, security), and a third, **conventions**: does the change do things the way this repository does them (the wiki's Conventions page), and did it keep docs and requirements current where the repository keeps them | the diff, the wiki, the code | - | exists; the lens is new |
| **Prober** | tries the change for real where the repository can be run: starts it in the sandbox, calls its interface or drives its pages (Playwright), and keeps the evidence (a log, a screenshot) | the branch, the specification | the owner's data | new |
| **Tracer** | for ai-stack: maps each criterion to the code and the test that meets it (ops/req.py prove already does part) | the branch | - | exists |
| **Presenter** | the report: what was asked, what was done, the evidence per criterion, what was not done, the cost | everything of the task | - | exists (trials only) |
| **Scribe** | the repository wiki's one writer: seeds it at onboarding, folds every step's findings after a request, writes the retro | everything of the task, the wiki | change code | new |
| **Coach** | monthly: the retros and scorecards into agent changes, each replayed before it applies | runs, scorecards, retros | - | exists |

Plans by size class, as templates the Orchestrator starts from and may change at a checkpoint. Each starts with the
baseline (and, for a repository with no profile yet, a run that finds how it is set up and tested):

- **S**: coder → judge → reviewers (three lenses) → presenter → scribe. One slot, one engine.
- **M**: tester → red before green → coder → judge with up to three fix rounds → breaker → judge again → reviewers →
  prober → presenter → scribe. The tester runs first rather than beside the coder: then it cannot see the new code, by
  construction, and needs no second workspace.
- **L**: analyst → architect → up to three coders in parallel on tasks with their files → the rest of the M plan.

What was built differently from the first draft, and why:

- **Step builds stack on the change's branch.** A step's build branches from `change/<id>-<slug>` and merges back into it, so
  the owner reviews one branch. A **carrier build** (a row in the builder's table) then puts that branch through what exists:
  the build page, Approve, CI, the merge queue, deploy and rollback. A step's build holds no lease on the repository: steps run
  one after another, and a conflict shows when the judge merges main in.
- **A fix round reruns only what it must.** The coder, one judge, and the steps after them; the breaker's tests stand.
- **One sandbox image.** The coder needs the toolchain in its own container, so the builder's image carries them all (CHG-13),
  rather than one image each.
- **The Presenter is a program.** The report is drawn from the judge's, the reviewers' and the prober's records, so it cannot
  say more than they found.
- **Budgets** are tokens by size (docs/LIMITS.md). Time is not budgeted: a change waits for memory, usage limits and the owner's
  review, and none of that is spending. The report and the wiki come even at a spent budget.

## Memory: one wiki per repository

The answer to the owner's question is yes, with these rules.

**Where.** `vault/repos/<name>/wiki/`, a Ledger artifact owned by the Scribe (MEM-03), indexed by qmd, named on the
card of every code role (MEM-04) and of the assistant, not on the scout's (it reads the web). Its limit and curator are
the agent wikis' (200 pages, the Librarian and the Memory Keeper).

**Pages**, each fact with its evidence (a commit, a build, a request, a review comment, a run):

| Page | Holds | Seeded from |
|---|---|---|
| Overview | what the repository is and does | the onboarding analysis |
| Architecture | modules, boundaries, the main flows, the core abstractions | the code map's layers and tour, the code graph's god nodes |
| Conventions | style, naming, where tests, docs and requirements live, commit messages, what a change must update | AGENTS.md, CLAUDE.md, CONTRIBUTING, the first ten merged changes |
| How to build and test | the commands, the toolchain, how long the suite takes, the tests known to flake | the onboarding's build step, each judge run |
| Fragile areas | the files where changes failed or were sent back, with what went wrong | each retro |
| Decisions | why things are the way they are: the owner's review comments marked as rules, the repository's own ADRs | the owner, the Scribe |
| Lessons | what went wrong in a past request and what to do instead, each with its evidence and a date | each retro; the owner's "request changes" and rejections |
| Glossary | the repository's own words | the code map |
| Open questions | what nobody has settled | any step |

**What the wiki is for, and what it is not.** It holds *why* and *how we do things here*, which the code does not say.
Facts about *what the code is* come from the code itself and the code graph, which are current at every commit. A page
says "as of commit X"; the Librarian's lint marks a page **to re-verify** when a file it cites has changed since (the
code graph knows the files), and a coder is told the wiki is what the swarm believed, never an authority over the code.
The onboarding job's code map, digest and analysis are the wiki's **sources** (the raw layer), not the wiki.

**Who writes.** The Scribe alone, after each request (the retro) and at onboarding (the seed, step 7 of the job). Every
other role contributes a **help** on the wiki's artifact (SWM-109) that the Scribe folds in: the judge's flaky test,
the breaker's edge case, the reviewer's convention the coder broke. The owner edits any page in the app, and his edit
wins (a fact he wrote carries `by: owner` and the Scribe never supersedes it without a review comment).

**How learning reaches the next request.** A code role's run opens like every other agent's (MEM-05): its journal
(new for the code roles: the builder keeps none today), then the wiki, its own pages first (Conventions, How to build,
Fragile areas, Lessons), then the pack. A lesson that concerns a role rather than a repository ("the tester writes
tautological tests when it sees an example") goes through the Coach as an agent change with a replay, as every other
agent change does. A lesson that concerns the owner's taste ("he rejects a change that touches two areas at once")
becomes a Conventions line marked as his decision.

**Keeping it honest.** Cite or drop: a fact without evidence is not written. Re-verify on change. The Librarian's lint
and merges. The owner's edits win. Superseded, never deleted (MEM-12). And the exam below measures whether the wiki
helps: a trial arm with the wiki hidden must score lower than the arm with it, or the wiki is noise.

## Output: what the owner gets back

- A branch `change/<id>-<slug>` on Forgejo and a pull request there with the report as its description (ops/builds.py
  opens pull requests already). A repository not on Forgejo first becomes buildable (the existing **Let the builder
  change it**); a GitHub pull request on the owner's own GitHub repositories is a later door.
- The request's page in Mission Control: the specification with each criterion's state (met with its test, not met
  with why), the plan with each step's run, the diff with its blast radius, the judge's evidence (baseline, after,
  red-before-green, reruns), the reviewers' verdicts, the prober's log and screenshot, the cost, and the report.
- Three buttons: **Merge** (ai-stack: and deploy, as today), **Request changes** (text; a fix round on the same branch,
  and the text is a lesson candidate), **Reject** (reason; a lesson candidate). The Scribe reads all three.
- One message when it ends, either way, with the headline of the report.

## Durably better than opening Claude with the repository loaded

A single Claude session with the repository loaded is good, and for an S change nearly as good as this; the design
must not make S changes slower than they need to be. What one session cannot give, and this design does:

| | One session | Change requests |
|---|---|---|
| Memory across changes | none; the next session starts cold | the repository wiki, the journals, lessons that survived a replay |
| Who checks the work | the same model that wrote it | a program as the judge, a tester that never saw the code, reviewers on the other vendor's model, a breaker |
| Tests | "I ran the tests" in the transcript | the judge's own run, baseline against after, red-before-green per criterion, reruns for flakes |
| Tried for real | no | the prober starts it and keeps the evidence |
| The owner's taste | retold each time | Decisions and Conventions on the wiki, his review comments kept |
| Proof of improvement | none | the exam: the same cases, scored over versions, with the wiki on and off |
| Cost control | the session's limit | a budget per size class, the stop at the budget, two vendors |
| Scope | what the chat holds | the Conductor: parallel tasks with file leases, checkpoints, resumable after a restart |

Where it is not better: it is slower and costs more tokens per change, it needs the sandbox and the toolchain of the
repository, and it is only as good as its judges. That is why the exam comes before trusting it.

## Sandboxes: running what the repository needs

The builder's image carries the toolchains (python, node with pnpm, go, rust, java) with no secrets, the package proxy as its
only network, memory and time limits. `dsh-superagent-prototype` needs private alpha packages the proxy cannot serve. Each
repository's profile (`vault/repos/<name>/profile.json`, found by really running it) names its toolchain. A repository whose dependencies the proxy cannot
serve is onboarded with that said on its page, and its requests are refused with the reason until the owner allows the
dependency.

BLD-18 says third-party code is never run, and onboarding keeps that: studying a repository runs nothing. Running its
tests is running its code; the owner's tap **Let the builder change it** is the consent for that, in the sealed
sandbox only, and BLD-18's wording changes to say so (CHG-12).

## The failure modes, and what catches each

| Failure | Seen where | Caught by |
|---|---|---|
| The request was misread | MAST class 1 | the specification with criteria, shown; the owner's Go on M and L; the Tester works from the criteria, so a misreading fails its tests |
| The coder says the tests pass and did not run them | every coding agent | the judge is a program; the coder's claim is not read; the run record shows its tool calls (OBS-16) |
| Tests written to pass the code | tautological tests | the tester cannot see the code; red-before-green: a test that passes on main is no acceptance test |
| Flaky tests blamed on the change | real suites | the baseline on main first; a failure is rerun once; the flake goes on the How-to-build page |
| Scope creep, unrelated edits | large diffs | the size class's budget; the conventions lens; the blast radius on the page |
| The stack rewrites its own checks or exam | self-modification | protected paths for ai-stack: ops/check.sh, the pipeline's own tests, eval/, the private answer keys, secrets, the deploy; a request naming them needs the owner's word in the specification |
| Text in a third-party repository steers an agent | prompt injection | the code is data (BLD-18); no secrets in the sandbox; the tester and breaker read the specification, not the code; the reviewers look for it |
| A usage limit mid-change | every day | the step waits and resumes (TSK-08); the second vendor's engine for reviews |
| The PC's memory | 16 GB | two slots, headroom before a step (TSK-08); S plans on one slot |
| The wiki fills with wrong facts and misleads | self-poisoning | cite or drop; re-verify on change; the Librarian; the owner's edits win; the exam's wiki-off arm |
| "Done" without doing | agents | BLOCKED stops the step (TSK-32); the Presenter cites evidence per criterion; the judge decides, not the report |
| Context lost between steps | long tasks | hand-offs by reference (MEM-15); the specification and the wiki excerpt in every brief |
| Cost runs away | 1.18 M tokens on one build | the budget per class; the stop at the budget (TRL-11); the exam's cost column |
| A step runs twice after a restart | restarts | the Conductor's recovery (TSK-09), a branch per request, idempotent commits |

## The exam: proof, not promises

BLD-25 (proposed) asked for the builder to be measured on the owner's own projects. The exam makes it concrete, as
trials of a new type, **replay**: a real commit C of an onboarded repository with its parent P, where C added or changed
tests. The task is C's message and pull request text, rewritten by the Analyst as a request the owner could have typed;
the agents start from P and never see C; the score is C's tests run against their branch (the hidden suite), the
suite at P run against it (regressions), the conventions lens's verdict, the tokens and the minutes. Ten cases per
repository, picked from history by a script, their keys in `/srv/ai/private/trials/` like every other key. Arms:
`wiki` and `no-wiki`, `one-coder` and `swarm`. The scoreboard shows each case over versions: that is what "it gets
better" means here, as a number.

## Order of work

| Phase | Brings | Gate |
|---|---|---|
| 0. Baseline | three real ai-stack changes through today's builder; the exam at version 0 on click and ai-stack | numbers to beat |
| 1. Memory | the repository wiki and the Scribe; journals for the code roles; the onboarding's seed step; lessons from the owner's review comments | every code role's opening reads the wiki; the exam's wiki arm scores at least the no-wiki arm |
| 2. Intake | the specification with criteria and size class; the request's page; the owner's Go | ten requests specified, the owner accepts eight without editing |
| 3. The pipeline | the plans by class on the Conductor; the judge's baseline, red-before-green and reruns; the conventions lens; the Presenter's report; the pull request | an M change on ai-stack lands through the pipeline with its evidence |
| 4. Sandboxes | one image per toolchain; BLD-18's wording; mochi-mqtt buildable | the judge runs mochi-mqtt's tests |
| 5. The prober | API probes and Playwright in the sandbox; ai-stack's journeys as probes | a UI change comes back with a screenshot of it working |
| 6. Skills | a pinned library by role (the Superpowers set as the first candidate: brainstorm, plan, test first, debug, review), each adopted only where the exam improves | a skill that improves no score is not kept |
| 7. Learning proven | the exam monthly; the Coach reads the retros; the scoreboard on the Code tab | the second month scores above the first |

Phase 0 needs no design and can start now. Phases 1 to 3 are the core; 4 to 7 each stand alone.

## Decisions taken as defaults, the owner's to overrule

When the owner said "Implement it end to end" these four were still open, and the recommended default was taken:

1. **Consent to run third-party code:** the tap **Let the builder change it** is it (CHG-12).
2. **The owner's Go on M and L** before the work.
3. **Protected paths for ai-stack** as listed in `PROTECTED` in ops/changes.py.
4. **Phase 0 first.**

## Sources

- MAST, the taxonomy of multi-agent failures (2025): specification, inter-agent misalignment, verification.
- Blitzy's public description of its approach (knowledge graph, approved specification, more checking than generating);
  its scale figures are its own and unverified.
- SWE-bench Pro and SWE-bench Verified as the shape of the replay exam: real commits, hidden tests.
- The stack's own record: builds 1 to 27, the trials of 1 to 3 November, the onboarding runs of 6 November.

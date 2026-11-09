# Generalising the stack

Written 7 November 2026. The owner read a review written for one possible use (regression checks of one project at work) and decided:
"We don't want to tailor to [that project], but we want to generalise the stack." This document says what that means, from an audit of the
code with file and line for each claim. Requirements GEN-01 to GEN-12 (`requirements/generalise.yaml`) carry it.

## What generalising means here

A second person, on other hardware, with other jobs for it, can run this stack without editing the core. Three layers get there:

| Layer | Holds | Example |
|---|---|---|
| **Core** | what every deployment needs: the Conductor, the run record, the queue, the checks, memory, the app's frame | "a step waits for a slot" |
| **Domains** | one kind of work, each in its own module with its step kinds, pages and routes | shopping, the desk, change requests, the phone |
| **Deployment** | one person's setup, in configuration, never in code | hosts, the owner's name, which models may be used |

**The test:** the core names no domain, the code names no person, and a clean install runs from one configuration file.

That project stays out of this. If it ever goes ahead, it would be one more domain on a separate deployment, and it would find these seams ready.

## What the audit found

| Area | Today | Evidence |
|---|---|---|
| Checks that hide a failure | 11 places where a check that could not run reports "fine" or says nothing | `checker.py:51`, `crew.py:529,719,763,783`, `keeper.py:449`, `trials.py:159`, `builds.py:954`, `check.sh:10`, `improve.py:96`, `postmaster.py:84` |
| Waits for you | 11 kinds reach the queue, 7 do not, and Home builds its own list | `decisions.py:153`, `server.py:108`; not in it: `app.js:1602,1067,1071,1064,1135`, `checker.py:198`, `changes.py:150` |
| Starting work on a schedule | 7 mechanisms; the docs disagree on what registers the Windows tasks | 24 timers, crew, missions, Conductor, 17 runner threads, Hermes cron, 7 Windows tasks |
| Forge | Forgejo in 31 files; 3 separate copies of the CI status call; no interface | `builds.py:305,1029`, `missions.py:1195`, `digest.py:95`, `repos.py:115` |
| The owner | "The owner" on 157 lines in 29 files and 39 in prompts; the memory bank is called `owner` in 5 places; a decision mostly does not record who made it | `keeper.py:39`, `journal.py:42`, `crew.py:1057`, `decisions.py:239` |
| Models | The subscription rule lives in a card check, a test's own constant and comments; `ANTHROPIC_API_KEY` still passes through | `registry.py:81`, `test_keys_policy.py:11`, `compose/core.yaml:47` |
| Domains in the core | `DOMAINS` exists, but the Conductor still names some, and a new page takes 7 edits in 7 places | `conductor.py:72,74,570,676`, `app.js:212,315,320`, `server.py:41,2538`, `missions.py:1058` |
| Where work runs | Everything is `docker exec` on this host; 132 lines in 49 files; memory headroom assumes one PC | `conductor.py:97,315,416,616` |
| Constraints | 15, of which 6 are this home's, 3 a deployment's choice and 6 true everywhere, all in one file | `requirements/constraints.yaml` |
| A new install | None exists: NEW-MACHINE.md is a move, which needs the old Forgejo, backup and key. The guard test covers 8 values in 6 places | `NEW-MACHINE.md:3-7`, `tests/test_deployment.py:17,21` |
| End-to-end checks | Journeys run each night, but none exercises you deciding something | `ops/journeys.py`, `ops/journeys.mjs:3` |

## The other AI's list, and what we do with it

**Build now.** Each is worth having whoever uses the stack.

| # | Change | Theirs | Done when |
|---|---|---|---|
| GEN-01 | A check says **pass, fail or unknown**. A check that could not run is unknown, and shows on the health board | F1 | the 11 places above are gone, and a test breaks each one |
| GEN-02 | **One queue** for everything waiting on you. Home and the queue read the same list | F3 | the 7 missing kinds are in it; ones you cannot act on stay on the health board |
| GEN-03 | A **journey that decides**: a test item goes through the queue and its result is checked, every night | F6 | it fails when approving stops working |
| GEN-04 | **One forge module** behind one interface, with Forgejo its only implementation | G3, interface only | no other file calls Forgejo's API; the CI status has one home |
| GEN-05 | **A model policy file**: which providers and models this deployment allows. Home stays subscriptions only | G5, policy only | the card check and the test read one file; the stray key is gone |
| GEN-06 | **Constraints split** into what holds everywhere and what this deployment chose | G7 | `requirements/constraints.yaml` holds the first, `deployments/home/` the second |
| GEN-07 | **The owner in configuration**: name, memory bank. Every answer records who gave it | G4, first step | no person's name in the code; prompts follow through their replay gate |
| GEN-08 | **A clean install from one file**, rehearsed. The guard test covers every value and folder | new | a second stack comes up on a clean WSL from the env file |

**Build after those.**

| # | Change | Theirs | Why it waits |
|---|---|---|---|
| GEN-09 | **Domains own their pages and routes**, and the Conductor names none | G1, G6 | it moves much code at once; best when the checks above can catch a slip |
| GEN-10 | **One schedule table** you can read: everything that starts by itself. Missions and Conductor tasks share it; timers are listed, not moved | F2, reduced | moving 24 timers and Windows tasks adds risk and little value; seeing them all is the gain |

**Not now, and what would change that.**

| # | Change | Theirs | Starts when |
|---|---|---|---|
| GEN-11 | A `where` on step kinds, and workers that pull jobs | G2 | a real second place to run work exists. The Windows desk and the phone stay as they are until then |
| GEN-12 | Several people, roles and sign-in | G4 | a second real user |
| — | Typed step outputs | F4 | hand-offs by reference work today; the need has not shown up |
| — | Splitting the big files for its own sake | F5 | never as a project: GEN-04 and GEN-09 split what they touch |
| — | Plugin manifests (`pack.yaml`), Bitbucket, Jira, the regression page | G1, G3, G6 | only for a real domain that needs them; that domain exists now: designed in [AI-STACK.md](AI-STACK.md) (GEN-21 to GEN-32) |

## Order and how it is proven

1. GEN-01, GEN-02, GEN-03: honesty first, so that everything after them can be trusted to fail loudly.
2. GEN-04, GEN-05, GEN-06, GEN-07: the seams, one at a time, each with no change in behaviour.
3. GEN-08: the clean install, the real proof. It replaces the new-PC rehearsal as the test of "a different environment".
4. GEN-09, GEN-10.

Each lands alone with the whole check green, between exam arms and never during one.

**Risk.** Most of this moves working code with no visible gain for a while. The rule that keeps it honest: no step changes what the stack does, and any
step that cannot show that with its tests waits.

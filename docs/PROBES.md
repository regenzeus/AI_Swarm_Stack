# Probes

Experiments on the stack (docs/NEXT-PHASE.md, Part 5; TRL-17): each with its question and measure written before it
runs, what it found and the change it led to. Newest first.

## P5: the memory ceiling (2 Nov 2026)

- **Question:** a briefing and a trial at once on 10 GB of RAM with the new 16 GB swap: where do time-outs start?
- **Measured** (free, memory pressure and docker stats every 20 s, 18:48 to 18:58): the semver trial (task #118) and
  the uranium briefing started together. The briefing filed in 3 min 51 s (323 items read, 68 new, 7 chosen); the
  trial ended in 9 min with 351 of 351, clean room ok. Memory in use peaked at 6.3 GB, at least 3.6 GB stayed
  available, swap peaked at 3.4 of 16 GB, memory pressure (some, 10 s) at 9 %. No time-out, no killed process, no
  failed step. The trial took 9 minutes against 2 alone on 1 Nov, with 8 steps and 31 model calls against 23: the
  plan differed, so contention is not shown to be the cause.
- **Found too:** GDELT refused two of the briefing's searches (HTTP 429, rate-limited), which the desk skips and logs.
- **Changed:** nothing; the pair fits. The ceiling was not reached: the next try is the heaviest pair (Mustache and a
  deep research task).

## P7: does it remember last week? (2 Nov 2026)

- **Question:** asked fresh, with no chat history, does Hermes know what the stack found and what the owner told it?
- **Measured:** seven questions with known answers (a shopping price, a recommended speaker, a briefing's numbers, the
  owner's language, an alert's subject, a version a task looked up, the owner's ChatGPT plan), one new session each.
  First run: 4 of 7. The two answers that lived only in a task's answer file were not found: qmd had no collection
  for /vault/tasks. The ChatGPT plan was never told to Hermes, and it said it did not know: a right answer.
- **Found too:** Hermes ended its answers with "Quellen:". A skill it had written for itself on 25 Oct
  (vault-answering) asked for that German label; nothing in the repository did.
- **Changed:** a "tasks" collection in qmd (d0891d6), indexed; the skill's label is "Sources:". Second run: 6 of 7,
  the Home Assistant answer citing task 114's file, the miss still the honest "don't know".

## P3: ten one-sentence tasks (2 Nov 2026)

- **Question:** does a task given in one sentence get the right plan (kind, agents, rhythm, trigger) without help?
- **Measured:** `make tasks-gate`, eval/tasks-v1.yaml's 20 sentences through the intake (it plans and starts nothing):
  builds, research, analyses, questions about the stack, three alerts and two schedules. 20 of 20 planned right
  (eval/results/20261102-180728-tasks-gate.json). The plans' running was measured on real tasks in P2, P4 and P6.
- **Found too:** a task's name was cut at 80 characters mid-word without a mark (task 93: "... estimates as s").
- **Changed:** a long name is cut at a word and ends with "…" (d0891d6, QA-21).

## P6: breaking news, from the story to the phone (2 Nov 2026)

- **Question:** how long from a breaking story to the owner knowing what it means?
- **Measured** (the uranium rule's two firings of 2 Nov, from the bus, the firings and the notification log): the story
  was raised and the "rule fired" push sent in the same second (12:06:16, 13:21:02); the three-line answer reached the
  phone 3 min 15 s and 4 min 23 s later. But the Macusani story had been published by three outlets at 12:00 to 12:01
  and was raised at 13:21: about 80 minutes went to the news search's listing (the stack looks every 10 minutes).
- **Found too:** the "done" message carried only the task's title, so the three lines were only in the app; and the
  Cameco alert of 1 Nov (task 93) never ran: a restart had cut off its planning and it waited 27 hours (FND-117).
- **Changed:** an alert's answer is in its message (cut visibly past 1,500 characters); a planning a restart cut off is
  planned again at the worker's start, or failed and said why when older than six hours. Open: the 80 minutes need the
  issuers' own feeds (FND-118).

## The operational sweep (2 Nov 2026, the owner: "the infrastructure online and the AI Stack operational and battle tested")

- **Up:** 28 containers running, no failed unit or timer, the backup of 03:31 (799 MB) and the restore drill of 1 Nov
  passed, Home Assistant and the voice side reachable, both model routes answering, the smoke test 11 of 11.
- **Memory:** swap was full (3,070 of 3,072 MB). It was held by services sitting idle: qmd 720 MB, Hindsight 590 MB,
  Open WebUI 535 MB, Phoenix 320 MB, rootless Docker's network helper 290 MB. qmd, Open WebUI and Phoenix were restarted
  (their data is on disk): 1,526 MB. They grow back; PLT-27's budget per container is the lasting answer.
- **Journeys:** every route, the task replay, the e-mail, 47 make targets and 20 tools pass, except two task pages that
  scrolled sideways at 375 px by up to 2,417 px: a task's original words held a 350-character link that could not
  break ("You wrote: ..."), the phone widened the page and the agents' map drew to that width. Fixed: the line wraps.
- **Health board:** every night's journey check showed as "never finished": the journeys have no swarm card, so the
  Ledger refused their finish (FND-113, fixed d67bbbe; the two runs on record closed). The builder's "failed" was build
  #19 of last night's trial; the app error on the phone page was already fixed in the code.

## P4: pull the plug (2 Nov 2026)

- **Question:** a service a step depends on goes down mid-step: does the task recover, or fail honestly?
- **Setup:** a small real task (#115: is Hermes newer than v0.22.5?); the web-fetch service restarted the moment its
  scout made its first call.
- **Found:** the scout's next fetch failed ("All connection attempts failed"), it tried again 8 s later when the
  service was back, and the task ended done with the right answer 22 s after the restart. A first attempt (#114) missed:
  the scout had finished fetching 6 s before the restart. Both answers were useful: Home Assistant 2026.11.0 is not yet
  stable (2026.10.4 is, so the 2026.11.0b2 pin stays); Hermes v0.22.5 is the newest release and the one we run.
- **Changed:** nothing; it holds.

## P2: two at once (2 Nov 2026)

- **Question:** do two tasks whose scout steps run at the same time stay apart, and fit in memory?
- **Setup:** #116 (Synology DSM) and #117 (LiteLLM) given together.
- **Found:** both steps ran in parallel (15:27:29 to 15:28:01 and 15:27:39 to 15:28:13), both answered right, each
  scout run went under its own task, swap peaked at 1,827 MB. But for a Conductor step's own scout run the parent is
  still guessed (the live step of that agent most recently active): it came out right here partly because the steps
  started 10 s apart; two that start within the same second could be swapped (FND-114, open).
- **Proposed:** put the step's run id at the head of its prompt so the run record matches it exactly, as research calls
  now are (FND-111); it changes every step prompt, so it goes through the replay gate.

## P1: why does the crew's checker fail one run in four? (2 Nov 2026)

- **Question:** the checker failed 25 of its 95 runs since 28 Oct, and no page raised it. Is the job broken?
- **Measure:** its failed runs grouped by their ending; the Ledger's refusals behind them.
- **Found:** the job is not broken. It fails on purpose when the swarm shows a fault, so that the health board alerts.
  All 25 failures (31 Oct 15:24 to 1 Nov 14:36) were one fault: the Ledger refused the requirements sync 1,128 times,
  because its card-number guard read a file name's stamp (20261031-140852 passes the Luhn check) as a payment card.
  That false positive was found and fixed on 1 Nov (FND-93); no run has failed since.
- **Changed:** nothing in the checker yet. The lesson is FND-112: a job that reports a finding as its own failure makes
  its failure rate mean two things, and failure rates are what the licences of Part 1 and the self-pause after three
  failed runs will read. Proposed: end such a run as done and raise the finding through the health board's alert.
- **Also measured:** the doctor's evidence was refused by the same guard twice, and its upserts six times as duplicates
  of open ideas (the Ledger asking it to update or link them instead): correct refusals.

## P8: a cold start of the PC, rehearsed (4 Nov 2026)

- **Why:** the owner restarted the PC and got a morning of failures (FND-119). A real cold start can't be run on demand, so
  the rehearsal holds what failed: containerd's database stays locked while WSL boots, which makes Docker's starts fail the
  same way ("timeout waiting for containerd to start").
- **How:** a throwaway user unit holds `flock` on `meta.db` for two minutes from the start of the boot (`Before=docker.service`),
  then `wsl --shutdown` and the Windows keep-alive task. Pass: Docker comes up by itself after the lock goes, no unit failed,
  no run failed, no health alert, one "online" message, one line in `/srv/ai/state/boots.jsonl`, `make smoke` passes.
- **Result (12:01 to 12:06):** the lock made containerd fail just as it did that morning. Docker failed 6 times, came up on
  its 7th try as soon as the lock went (145 s after boot) and did not need touching. The runner waited 3 min 45 s, then
  started; frequent jobs were skipped, none failed; no run failed, no health alert went out; the one message was "AI stack
  online 4 min after the start: 26 of 26 services running. Docker needed 7 tries."; `make smoke` 11 of 11.
- **Not covered:** a real cold start of Windows, which can't be run from here. The first one reports itself on the Stack
  page and in `/srv/ai/state/boots.jsonl`.

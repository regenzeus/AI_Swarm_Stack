# Asks: how the stack asks a person (ASK-01 to ASK-20)

Built 11 Nov 2026 on the owner's word: "Yes build it. Best practise. Robust durable interaction system." It replaces
the decision queue as it was (`ops/decisions.py` is now its adapter) with one kind of question, the Ask, under a policy.

## A human on the loop

The stack acts within a policy and asks by exception. Every kind of action has a **tier** (`config/policy.yaml`, a
deployment's `policy.yaml`, the owner's standing rules):

| Tier | What happens |
|---|---|
| do | done at once, with an undo record (what, how to undo it, until when) |
| tell | done at once, with an undo record and one line in the activity (no push) |
| ask | an Ask waits in Needs you |
| never | refused |

Every kind that acts on the owner's things starts at **ask**. The owner turns a kind into "do it" with one answer
("Yes, and always for this kind") or on the policy page (Stack → What the stack may do): a **standing rule** that allows
the kind, under a limit on one of its facts if wanted ("cache cleanup below 1 GB"), or answers it with a default ("never
ask me this again, use No"). Each rule says who made it and when, and can be removed.

The **stop switch** (Home and the policy page) holds every agent run, workflow step, plan step and crew job the runner
would start, and pauses the swarm; what runs finishes. It says who switched it and what it held, and a second tap
resumes.

## The Ask

One durable record in `/srv/ai/asks/asks.db` (SQLite, write-ahead log, each write committed whole), owned by the runner
(`ops/asks.py`). The app reads what the runner publishes (`state.json` → `asks`) and drops answers into the runner's
inbox, where they wait while the runner is down; the app shows them as kept and sends nothing twice: an answer is kept by
its answer id, and the same id again changes nothing.

| Field | What it is |
|---|---|
| question, why, facts | one sentence; a short line shown on a tap; a few key values |
| choices | chips, each an outcome of its registered kind; a chip may also be a link to the source |
| allow_words | true, except at a gate |
| default, deadline | the outcome applied at the deadline ("applied by default"), or none: it then expires |
| role, gate | who answers (default the owner); a gate is answered only by a tap of a person in its role |
| task, ticket, source | the owning task, its tracker ticket, where it came from (workflow/run/node, crew job, build ...) |
| sensitivity | normal or private: a private Ask carries no figure to tickets, pushes, logs or n8n |
| status | open, answered, dismissed, snoozed, expired, escalated |
| answer | outcome, values, words, person, role, via (app, telegram, ticket, mail), time, understood as, confirmed |

Each source **registers its kind once** (`asks.register`): its outcomes and values, the action kind its tier comes from,
gate, role, default and wording. `ops/decisions.py` registers every Needs you source of before (builds, purchases, the AI
phone's cleanup, memory, tasks, agents' questions, ideas, packs, tracker shadows, command approvals, workflow questions,
mail sorting, the tax desk, the House, the journey's test item), and the app adds the three only it sees.

An answer is **held for 15 s** with a one-tap undo, then the stack acts on it through the source's own request (the
chip's act). A source that refuses reopens the Ask with the reason. **Dismiss** (with words) and **Later** ("tomorrow
morning", "tonight", "in 3 hours", "next week", a weekday or a date) work on every Ask. Asks of one kind fold into one
card with one answer for all and an answer per item.

## Answers in your own words

A reply box on every Ask but a gate. The words go to the interpreter (`prompts/intake.md` INTERPRET, gpt-sub-fast, no
tools; `ops/asks_words.py`): the Ask's question, its outcomes and values schema in, JSON out: an outcome with its values, or one short question
back. An unsure reading asks back in the card; a sure one is held with "Understood as …" and the one-tap undo. An
instruction becomes a snooze, a standing rule (never for a gate) or a note to the asking task.

## Roles and gates

A role names sign-in logins and an escalation order (`deployments/<name>/roles.yaml`; home has none: every role is the
owner's). The person of an answer comes from the app's sign-in, never from the page; someone outside the role is refused
and the card says who can answer.

A **gate** is resolved only by an explicit chip tap in the app by a person holding its role. No tier, standing rule,
default, interpreter, group answer, digest or deadline resolves it. Words are a comment; the interpreter may only suggest a
chip. At its deadline it reminds, 24 h later it goes to the next in the escalation order and the owner last; it never
proceeds. `tests/test_asks.py` has one test per path. The `stack` command line and the agents' stack tools never answer,
dismiss or put off a gate: `ops/asks.py` refuses each by its way in, `cli` or `mcp`, with the role that answers it
(WAY-07, [CLI.md](CLI.md)).

## Tickets, channels and the data rule

Each deployment declares its channels (home: app, ticket, Telegram; the work example: app, ticket, mail). A channel it
does not declare, or whose feature is off, sends nothing. Tickets: one per task or decision in the deployment's tracker
(home: the Forgejo inbox), never one per Ask: an Ask's task, else its kind's one ticket ("Your taxes" for the tax desk's
questions, a build's for a build), and none for a kind without one (ideas wait for the ideas-as-tickets step). A pass
writes one comment per ticket with its new Asks, and each answer goes back once. Every write goes through
`ops/domain/trackers.py`, opening a ticket included (its own kind, open): in shadow it waits for the owner's judgement,
read-only it stays in the stack. Only Asks created after tickets began get one: on 11 Nov 2026 the first sync of the
migration opened 89 issues, one per Ask; a migration now opens none. A reply on a ticket answers the one Ask waiting there. The data rule caps every
Ask, answer and record text (2,000 characters by default; refused, never cut), refuses a path of extracted content (it
goes by reference to a local path) and makes a text with a private marker private.

## n8n: the Ask block

The AI Stack step's `ask` kind takes type, question, choices, allow_words, default, deadline, role, gate and
sensitivity, opens an Ask, and answers the workflow `{status, outcome, values, words, person, role, via,
interpreted_as}`, so a workflow branches with n8n's If and Switch. The waiting run resumes through the step service as
before.

## The records' gate

A pack can gate a record's status (the toy pack: a change request reaching Approved, for the role approver). The Asks are
the records' gate (`records.set_gate(asks.record_gate)` when the runner starts): a transition to such a status opens one
gate Ask for the role, a workflow's tracker step waits on it, and only the role holder's tap on Approve, applied after its
hold, lets the write through; Not now or a dismissal refuses it (ASK-20).

## Not built yet

- Telegram replies in your own words: a new Ask of a workflow is pushed to Telegram, but a reply there is not read yet;
  the reply goes in the app or on the ticket.
- Mail as a channel (the work example declares it): nothing is sent by mail yet.
- Routine do and tell actions as a periodic log line on their task's ticket, or one weekly Upkeep ticket.
- Ideas as a weekly digest card (phase 3 of the design).


# The memory stack

Decided 7 November 2026 (DEC-44), built as one change and then commissioned. It replaces the memory parts of
[MEMORY.md](MEMORY.md) and [MEMORY-TAB.md](MEMORY-TAB.md) where they differ; what existed before is measured in
[MEMORY-OVERVIEW.md](MEMORY-OVERVIEW.md). Requirements MEM-22 to MEM-49.

## Why it looks like this

One measured fact shapes everything: **memory put into an agent's prompt gets used; memory the agent must ask for is
mostly ignored.** Claude builders made 552 tool calls in 75 runs, 538 of them `Bash`, and none to a memory tool; Serena
was never called. And what was put in was often the wrong thing: the same 12,000 characters of repository wiki for
every coding task, which changed no exam score. So the stack's job is to **choose what goes into each run's prompt**,
from everything it knows, for that task, and to measure whether it was used.

## The owner's requirements, and what was added

| The owner asked | How the stack meets it |
|---|---|
| The system creates memories as it runs | Every run can **yield** candidates (its notes, its result). They enter only through **reconcile** (MEM-35 to MEM-37). |
| Organised and curated | Six **sectors**, each with one organisation pattern and one writer rule; one **memory agent** with three jobs (MEM-42, MEM-43). |
| A run has the memories relevant to its kind of task | Not access but **presence**: each run's **opening** is built for its task from its subscriptions, within a budget (MEM-24 to MEM-26). |
| Fight bloat, deduplicate within a sector; redundancy across sectors is fine | Reconcile keeps one entry per fact inside a sector; a copy in another sector names the entry it came from (MEM-35, MEM-48). |
| Save LLM context, not disk | Budgets per run kind; **given** and **used** measured on every run; Health shows both (MEM-27, MEM-44). |
| AI-navigable; AI always finds what is relevant | A **catalogue** of collections, each saying what question it answers; one **search** over everything; pointers for what did not fit (MEM-22, MEM-28). |
| Scalable | Constant per run: the budget. Growing without limit: pages and facts. Wikis split into parts by their links, and unread pages are archived (MEM-40, MEM-41). |
| Layers, retrieval methods, organisation patterns | Four layers, five methods, declared per collection (below). |
| Hermes makes skills from common patterns | The **Distiller** proposes a skill from a tool sequence that worked across tasks, behind the benchmark gate (MEM-39). |
| Everything transparent | The Memory tab is the catalogue; every run page shows what memory it was given, used and yielded (MEM-45, MEM-46). |
| All agents reach the whole stack, except agent-specific memory | Access classes: all, private, own, owner (MEM-30). |
| New agents wired automatically | Subscriptions come from the card's roles; a card that resolves to none fails the build (MEM-24). |
| Results of actions onboarded (the copper newsletter) | A result is filed as a dated source, then compiled by its wiki's writer; a Claude task's answer about a repository is folded into its wiki (MEM-37). |
| Only the good stuff | A rubric: durable, sourced, new or superseding, not about the agent's own run, not a restatement of code (MEM-35). |
| Maintenance is agentic | The memory agent: Keeper nightly, Librarian and Distiller weekly, **without the owner's approval** (DEC-44, MEM-42). |
| Coding is the most important case | A coding step's opening is built from its task; a coder gets a note on each file the first time it reads it (MEM-31, MEM-32). |
| A wiki that gets too big splits | By its link graph into parts with hubs (MEM-40). |
| Offer and subscribe; some subscriptions preset | Presets by role, the offer at the end of every opening, `subscribe` for the rest (MEM-24, MEM-25, MEM-28). |
| Some proactive querying | Two bounded forms: the opening is rebuilt from each step's own inputs, and a coder's first read of a file brings its note. Not a watcher of the agent's reasoning (MEM-32, MEM-33). |
| Simple, powerful, scalable | One opening builder, one memory tool, one memory agent, one settings file, no new database. |

Added, because the design needs them: provenance and trust on every item; time (supersede, never delete); undo on
every automatic change; a run goes on when a store is down (MEM-34); untrusted text marked (MEM-49); trials with answer
keys before structural changes run (MEM-47).

## The pieces

### Sectors

| Sector | Holds | Lives in | Writer |
|---|---|---|---|
| **Owner** | facts about the owner | Hindsight bank `owner`; the profile Hermes shows every turn | the chat's gatekeeper (retain mission) |
| **World** | what the stack found out | one wiki per mission or topic and the vault wiki, with filed sources | each wiki's one writer (compile) |
| **Code** | how each repository works and where it hurts | `vault/repos/<repo>/`, `/srv/ai/code-docs/<repo>.*`, the builds' history | the Scribe; programs for facts, maps and graphs |
| **How-to** | how to do a kind of job | playbooks `vault/howto/lessons/<role>.md`, Hermes skills, prompts | the Distiller; the owner for prompts |
| **Agents** | what one agent is in the middle of | `vault/agents/<id>/MEMORY.md` | the runner |
| **Records** | what happened | run records, chats, task hand-offs, the Ledger | every run |

### Layers

1. **Raw:** records, filed sources, results. Exact, dated, never rewritten.
2. **Compiled:** wiki pages, facts files, playbooks, skills. One writer each; every entry names its source and date.
3. **Catalogue and index:** the catalogue, qmd, the code graph, wiki links. Hold no knowledge of their own.
4. **Working:** a run's opening. Assembled per task, within a budget, logged, discarded.

### Collections and the catalogue

A **collection** is the unit that is offered and subscribed: `owner:facts`, `world:topics/copper/wiki`,
`world:topics/copper/wiki#companies` (a part after a split), `code:ai-stack`, `howto:lessons/code`, `howto:skills`,
`agent:mission-ram-upgrade-to-32-gb`, `work:ledger`. `ops/memstack.py` writes the catalogue every hour to
`public/memory-catalogue.json`. Each card has: id, sector, parent, the question it answers, size, last change, trust
(exact, compiled, extracted), access, writer, the methods it supports, and how it fills an opening.

### Retrieval methods

| Method | For | Backed by |
|---|---|---|
| Opening | what every run of this kind needs, before it starts | `memstack.opening` |
| Search | a question in words | qmd (hybrid), Hindsight recall, the code map's file matches |
| Graph | what calls or changes with what | the code graph, CodeLore coupling, wiki links |
| Time | what happened lately | journals, run records |
| Catalogue | what exists at all | the catalogue |

## A run, end to end

```
offer ─► subscribe ─► opening ─► work ─────────────────► end
catalogue  presets by   ranked fill   memory tool          used measured, lessons tallied,
+ task     role + own   within budget search/open/note     candidates reconciled
```

### Subscriptions

`config/memory.yaml` presets them by role, so a new card is wired by its roles alone:

| Role | Subscribed |
|---|---|
| `code` | `code:{repo}`, `howto:lessons/code`, `agent:{self}` |
| `research`, `missions`, `briefings` | `agent:{self}`, `work:ledger`, `world:{own}`, `world:*`, `owner:facts`, `howto:lessons/{role}` |
| `assistant` | Hermes recalls long-term memory itself every turn; the memory tool for the rest |
| `knowledge`, `memory` | `agent:{self}`, `work:ledger`, `world:*`, `howto:lessons/{role}` |
| everything else | `agent:{self}`, `work:ledger`, `howto:lessons/{role}` |

### What goes in when there is more than the budget (D2)

Budgets are generous and are **experiment parameters**: `config/memory.yaml` holds them, every run records the
budget it used, and a trial arm may override them. The opening is filled in four steps:

1. **Must-haves first**, whatever the task: the agent's own working state and standing notes, the swarm's instructions
   and the owner's messages, a coder's commands that work, and anything the owner pinned.
2. **Everything else is ranked** by `match × trust × freshness × use`:
   - *match*: how well the item fits the task (search rank, or the code map's file match);
   - *trust*: exact 1.0, compiled 0.8, extracted 0.6;
   - *freshness*: 1.0 while the item is younger than 90 days, falling to 0.5 at a year;
   - *use*: the share of this collection's items that earlier runs of the same kind used (never below 0.5, so a
     new collection gets its chance).
3. **Placed in rank order while they fit.** An item too big for what is left is cut to fit when it is the best
   remaining and at least 800 characters fit; the cut says how much is missing and where the rest is.
4. **What does not fit becomes a pointer**: its ref and title, so the agent can `open` it. Then the offer.

Health shows, per run kind over 30 days, the characters given and the share used, which is how the budgets get tuned.

### The memory tool (D4)

One MCP server per access class, each with the same four tools: `memory` for the assistant, the missions and the
curator; `memorypublic` for the scout and for every coder. `memorypublic` reads only the World (no private wikis, no filed
sources), Code and How-to. The coders get it because they run a shell on other people's code with a way out to the package
registries: with the owner's facts as well, that would be the lethal trifecta. Which server a key is granted decides the
access, never what the caller says (`ops/keys.sh`).

| Tool | Does |
|---|---|
| `search(query, scope)` | one search over every collection the caller may read, grouped by collection |
| `open(ref)` | one entry whole: a page, a fact, a file's facts, a playbook |
| `subscribe(collection)` | that collection's slice for this task, within its budget |
| `note(kind, text, evidence)` | a candidate: `lesson`, `fact`, `failure`, `owner` or `skill` |

It replaces `qmd`, `graphify` and `agent_note` in every grant. Serena stays with the coders: it is a code tool, not
memory.

### Proactive, bounded (D3)

- **At every hand-off** a step's opening is built from its own inputs: its request, the files its spec names, the text
  its earlier steps handed on.
- **On a coder's first read of a file**, a Claude Code hook returns that file's note: how often it changes, what changes
  with it, its tests, and the failures and wiki lines that cite it. The notes are prepared before the build starts,
  so the hook needs no network.

### Writing: yield, rubric, reconcile

| Source | Becomes |
|---|---|
| `note(lesson)` | a line in the role's playbook, with its evidence and a tally |
| `note(fact)` | a filed source for its wiki's writer (`raw/_inbox`), naming the agent and evidence |
| `note(failure)` | a fact line on the repository wiki's Fragile areas page, with its evidence |
| `note(owner)` | long-term memory's retain, which keeps only facts about the owner |
| `note(skill)` | an idea for the Distiller |
| a Claude task's answer about a repository | folded into that repository's wiki by the Scribe when the rubric finds durable facts in it |
| a mission's result | filed as a dated source, then compiled by its wiki's writer (as before) |

The rubric rejects a candidate without evidence, about the agent's own run, or (for code) restating the code. Reconcile
inside the sector: **add**, **confirm** (a repeat adds its date), **supersede**, **skip**. Every outcome goes to
`/srv/ai/missions/memory/writes.jsonl` with how to undo it.

### Keeping it in check

| Rule | What happens |
|---|---|
| Budget | every opening, cut visibly, nothing stops |
| Split | a wiki over 60 pages is grouped by its links and shared sources into parts with hub pages; its index becomes a hub of parts; a part under 8 pages joins the part it links to most |
| Archive | a page no opening gave and no agent opened for 90 days, not confirmed in that time, is marked archived: searchable last, never in an opening |
| Dedupe | reconcile inside each sector; the Keeper's duplicates in long-term memory |
| Lessons | a lesson's tally rises with runs that went well with it and falls with runs that failed; at 0 it is retired |
| Index | qmd's orphaned share over 10% is cleaned (as before) |

### The memory agent (D1: fully autonomous)

One card, `memory`, three jobs, no owner approval anywhere:

| Job | When | Does |
|---|---|---|
| Keeper | nightly | MEM-21's hygiene; a copy of one of the owner's facts that adds a detail is merged into the older (MEM-50); when two of the owner's facts disagree the newer holds and the older is dated; applies the move list; disputes its research could not settle stay marked on both pages |
| Librarian | weekly | splits, merges, archive, the wiki tidy |
| Distiller | weekly | lesson tallies, retired lessons, at most one skill proposal |

Every change is logged with its undo and shown on its page. Structural changes (splits, archives, moves, skill
publishes) run only while the memory trials pass (MEM-47).

## Coding memory

Per repository, the code sector is: the commands that work (profile), the facts (repowise, CodeLore), the code map
(Understand Anything), the graph (Graphify), the wiki (the Scribe), the failures (failed and rejected builds), and the
written analysis. A coding step's opening (MEM-31) is `repofacts.brief` for the task: the named or matched files with
their facts and tests, the failures and wiki lines citing them, the commands. The fixed 12,000-character wiki opening
is gone. The file notes (MEM-32) add the rest as the coder moves through the code.

The exam decides what stays: arms `stack` (the new opening) and `stack+notes` (with the file notes) against
`swarm` on fair cases.

## Implementation map

| Part | Where |
|---|---|
| Catalogue, presets, opening, search, open, subscribe, given and used | `ops/memstack.py` |
| Settings | `config/memory.yaml` |
| Candidates, rubric, reconcile, playbooks, undo | `ops/memwrite.py` |
| Splits and archive | `ops/librarian.py` |
| Lesson tallies and skill proposals | `ops/distiller.py` |
| Autonomous Keeper | `ops/keeper.py`, `ops/crew.py` |
| The memory MCP servers | `images/mission-control/server.py` (ports 8097, 8098), `config/litellm/config.yaml`, `ops/keys.sh`, `config/agents.yaml` |
| File notes | `config/hermes/claude-hooks/memory_hook.py`, `ops/builds.py` |
| Trials | `ops/memtrials.py`, `eval/trials/memstack.yaml`, `ops/replay.py` arms |
| UX | the Memory tab, the run page, Stack → Health (`images/mission-control/web/static/app.js`) |

## Migration: nothing starts from zero

The memory stack is a way of choosing, writing and keeping memory, not a new store. Collections are views over the stores
that were there, so everything the stack knew on 7 November is in the first opening after the landing.

| What existed | What happens to it |
|---|---|
| Wikis (vault, missions, topics), filed sources, repository wikis, facts files, code maps, code graphs, journals, the Ledger, skills | Read where they are; the catalogue lists each as a collection on its first refresh. Nothing is copied or moved. |
| Long-term memory (Hindsight, bank `owner`) | Read where it is. The 151 facts of the move list leave it on the memory agent's first night with passing trials (DEC-44), each filed for the wikis naming its long-term id, each with Undo. |
| Lessons an agent kept with `agent_note` | They are standing notes of its journal and keep reaching it through `agent:{self}`, as a must-have. New lessons go through `note` into the role's playbook. |
| The swarm's lessons for a card | Given through `work:ledger`, as before. |
| The fixed wiki opening, the first opening builder | Kept only as exam arms (`memory: wiki`, `journal.brief_v1`), so the exam can compare them with the new opening. |
| `qmd`, `graphify` and `agent_note` in agents' hands | Replaced by the memory tool. The qmd and Graphify services stay: the memory stack searches through them, and the app uses them. |

What does start empty, because it is new: the role playbooks (`vault/howto/lessons/`), the given and used records, the
write log and the trials' results (all under `/srv/ai/missions/memory/`). Until a collection has been given to five
runs of a kind, its use weight is neutral. No page is archived before the read record covers 90 days.

## Commissioning

Done on 7 and 8 November 2026: [MEMORY-COMMISSIONING.md](MEMORY-COMMISSIONING.md) has what was proven, what was found and fixed, and the exam.


After the landing, in this order: the catalogue builds and lists every collection; the grants are applied to the live
keys (`ops/update-keys.py`); an opening for each run kind is built and read; the memory tool answers from Hermes and
from a Claude build; a build sees a file note; the Keeper applies the move list; the trials run and pass; a week of
given and used numbers shows on Health.

# Memory: how the stack remembers, and the design it grows into

The concept and the Memory tab are in [MEMORY-TAB.md](MEMORY-TAB.md): each kind of knowledge has one home. This document is the design and its history.

Written 2 November 2026 after the owner asked: do we use the swarm database, should we use it more, is the memory
design sensible (agent context, LLM wiki, database), should the wikis go into the database, are the wikis and the
database curated, are contradictions and false facts corrected, what is best practice, and what the trials' failures
teach. The design of 30 October ([DEC-31](../requirements/decisions.yaml), `requirements/memory.yaml`) still holds;
this document adds what the trials and today's measurements found and the next design steps. The requirements win
where they differ.

## The short answers

| Question | Answer |
|---|---|
| Do we use the swarm database? | Yes. The Ledger (SQLite, 7 MB) holds 510 artifacts and 1,409 events. Over the last 7 days agents read its start pack 130 times and filed their work 72 times. Most artifacts (448) are the requirements mirrored for the agents; the rest are ideas, proposals, the wikis' ownership and helps, and agent changes. |
| Keep SQLite? | Yes (SWM-73, the owner's call). It has one writer, uses WAL, takes a nightly snapshot that the restore drill checks, and holds 7 MB. Postgres would add a second failure point and buy nothing on one machine. |
| Use it more? | Yes, for **work on memory**, not for memory itself: open contradictions, stale pages and helps become Ledger items an agent can pick up (MEM-17). Facts stay in one home each. |
| Three tiers: context, wiki, database? | Close, but the database is not a tier above the wiki. The stack has the CoALA kinds: **working** memory (a run's opening and a task's hand-offs), **episodic** (journals, run records), **semantic** (the wikis for the world, Hindsight for you), **procedural** (prompts, skills, cards), plus the **Ledger** as the team's shared work board and **qmd** as the search over all of them. |
| Feed the wikis into the database? | No. One home per fact (MEM-02). The vault's markdown is versioned by git, readable in Obsidian and searched by qmd; a copy in the Ledger would drift from it and make contradictions by construction. The Ledger keeps a pointer per wiki (its writer, its helps). |
| Curated sensibly? | Half. Reading is well built: one opening per run, its own wiki first, one search. Writing and correcting had gaps: a compile wrote over the parts of a page it never saw (FND-103, fixed today), a marked contradiction waits for nobody, and the long-term memory's forget queue has waited for you since 30 October (55 suggestions). |
| Contradictions and false facts corrected? | Marked, not yet worked. The Librarian marks contradictions with both sources and keeps an old fact under Superseded. But nothing settles a mark: the two on the voice-speaker wiki are still open, and one mark was lost to FND-103. Hindsight holds the same preference up to five times, some facts in Spanish and German, and about 35 facts on agent runs that belong in journals. |
| Is the 01:00 failure a bug? | Yes, a defect (FND-99), fixed the same night. It belongs to a family: four of the night's five faults, and today's FND-103, sit where one agent hands text to the next. The lessons are below. |

## What the stack has (measured 2 November, 06:00)

| Kind | Store | Home | Size | Written by | Read by (last 7 days) | Curator |
|---|---|---|---|---|---|---|
| working | a run's opening | assembled per run (`ops/journal.py`, MEM-05) | one budget | the runner | every run | the fixed order |
| working | a task's hand-offs | `missions.sqlite` task_steps.output | per step | each step | the steps after it, the checkpoint, the judge | **none: not in the inventory** |
| episodic | agent journals | `vault/agents/*/MEMORY.md` | 19 journals, 55 KB | the runner | each agent at its start (180 writes) | memory crew (folds old entries) |
| episodic | run records | `runtime.db` | 749 runs, 31 MB | every run | you, the doctor, the judge, trials | 90-day trim |
| semantic (world) | agent wikis | `vault/missions,topics/*/wiki` | 13 wikis, 133 pages | each wiki's one writer (compile) | 45 wiki searches, 49 qmd queries | the Librarian (weekly) |
| semantic (world) | vault wiki | `vault/wiki` | 44 pages | the curator; the Librarian's hubs | search | vault lint |
| semantic (world) | your notes | `vault/raw` | 14 notes | you, imports | search | never rewritten |
| semantic (you) | Hindsight | Postgres, bank "owner" | 222 facts (65 world, 74 experience, 83 observation) | your chats | 38 recalls | memory crew proposes, you forget |
| semantic (you) | Hermes' own memory | `USER.md` in Hermes | 160 bytes | Hermes, gated by memory_review | Hermes | memory_review (10 min) **not in the inventory** |
| procedural | prompts, cards | `prompts/`, `config/agents.yaml` | 54 prompts | you, agent changes (replay-gated) | every send | MEM-11 gate |
| procedural | skills | Hermes skills | 13 | the skill keeper | Hermes | curate.py (benchmark gate) |
| procedural | code graphs | graphify per repository | per repo | graphify-sync | the builder (11 queries) | **not in the inventory** |
| shared work | the Ledger | `swarm.db` (SQLite) | 510 artifacts, 7 MB | agents, the runner, you | 130 start packs | checker |
| index | qmd | the qmd container | 578 files, 18% orphaned | qmd | every vault search | the Librarian's cleanup |

## Best practice, and where we stand

| Principle | Where it comes from | The stack | Gap |
|---|---|---|---|
| Kinds kept apart: working, episodic, semantic, procedural | CoALA (Sumers et al. 2023) | yes (MEM-02) | the task's hand-offs and three stores are missing from the inventory (MEM-19) |
| A small working memory assembled on purpose; the rest fetched when needed | MemGPT/Letta tiers; Anthropic's context engineering (just-in-time retrieval, notes kept outside the window) | yes for a run's opening (MEM-05) | hand-offs between steps are copied whole into the next prompt (FND-99, FND-104): pass a handle and a summary, and let the step read the rest |
| Raw sources, a compiled wiki, a schema, a lint | the LLM-wiki pattern (Karpathy) | yes (vault raw → wiki, the Librarian) | none in shape; the compile had FND-103 |
| A write reconciles with what is there: add, update, supersede or nothing, never a blind overwrite | Mem0's update step; Zep/Graphiti | Superseded kept (MEM-12) | a compile overwrote the parts it was not shown (FND-103, fixed); Hindsight adds a fact each time it is said (FND-107) |
| Facts carry time: valid from, valid until; an old fact is invalidated, never deleted | Zep/Graphiti's bi-temporal edges | "until <date>" under Superseded; stale after 90 days | Hindsight facts have no until (a setup "incomplete" stays true forever) |
| Every fact names its source | provenance in RAG and the LLM wiki | wiki facts link their result; PROV for tasks | none |
| A contradiction is a task, not only a mark | Generative Agents' reflection; wiki lint loops | marked (MEM-08) | nobody settles it (MEM-17) |
| A cut the model reads shows itself | (our FND-100) | the checkpoint, now the compile | 92 of 96 prompt caps slice without a mark (MEM-16) |
| Forgetting is designed: decay, retire, restore | MemGPT archival; Hindsight soft-retire | owner-only Forget, soft and restorable (KNW-08) | the queue waits on one person; it grows 25 facts a day (owner decision D2) |
| Memory is measured against an answer key | LongMemEval, LoCoMo | the memory-proof mission, inventory, access map | no trial for memory yet (MEM-20) |

## The design: eight rules

1. **One home per fact, one writer per home.** World knowledge goes in the wikis, your facts in Hindsight, how-to in prompts and skills, what happened in journals and run records. Other agents help a wiki through the Ledger (MEM-03).
2. **The Ledger tracks the work on memory.** Helps, open contradictions, stale pages and duplicates waiting for a decision are Ledger items with an owner and a state, so the swarm's normal loop works them.
3. **Working memory is assembled, never piled up.** A run's opening has one order and one budget (MEM-05). A step gets the results it builds on, each whole up to a budget. Past that budget, the step gets the result's start, its size and a handle to read the rest (MEM-15).
4. **A writer sees what it rewrites, or the rewrite cannot drop it.** A compile reads the whole page, and lines it was not shown come back (MEM-14). The same rule applies to journals and any future rewrite.
5. **Change is superseding, not deleting.** An old fact moves under Superseded with its end date. Hindsight retires softly. The vault's git history keeps every version.
6. **A contradiction is worked to an end.** It is marked with both sources (MEM-08). Then the writer's next compile is told; after 14 days a refinement task researches it; the settled claim moves under Superseded (MEM-17).
7. **Every cut that reaches a model shows itself:** how much is missing and where the whole is (MEM-16, AGENTS.md truncation rules).
8. **Memory is measured.** It has an inventory, growth, an access map and limits (MEM-01, MEM-07, MEM-10), and a trial with an answer key: plant facts, correct some, contradict some, then ask (MEM-20).

## What the trials taught (FND-99 to FND-103)

Every fault of the night sat at a **hand-off**: the place where one agent's output becomes another's input.

| Fault | Hand-off | What went wrong | Lesson |
|---|---|---|---|
| FND-99, 01:00 | analyst → builder | 26,000 characters of results copied into a brief whose limit (20,000) was set for **your** typed text (APP-20: refuse, never cut) | a limit made for one sender was applied to another; machine hand-offs need their own contract |
| FND-100 | steps → checkpoint | the checkpoint read 4,000 characters with no mark and took the list for broken | a silent cut misleads a model as surely as a wrong fact |
| FND-101 | build → task budget | a build's tokens were counted in its own run and in the task's | the same work seen through two records must be counted once, by its source |
| FND-102 | run record → judge | the judge saw summaries, not the evidence | the reader of a hand-off needs the measured record, not the writer's word |
| FND-103 (today) | wiki page → compile → wiki page | the compile saw 3,000 characters and wrote over the whole page: Timeline lines, Open questions, Key facts and one contradiction mark lost over five days on 14 pages; 61 events restored from the vault's history | a writer must see what it rewrites |

Why the tests missed them: each unit test used small inputs. Only a full-size run (a 26,000-character requirements
list, a 6,000-character page) crossed a limit. What to adapt:

- **Pass by reference past a budget (MEM-15).** FND-99's fix moved the results out of the brief, but they are still
  copied: 80,000 characters for a build, and a Hermes step still takes its whole prompt as one command-line argument,
  which Linux refuses past 128 KiB (FND-104). A step should get each earlier result whole up to a budget, then its
  start, its size and a handle to read the rest.
- **Contract tests at real size.** One test should push a 150,000-character result through every adapter (Hermes,
  Claude, build, OpenCode, wiki) and check that each step either gets it whole or gets a marked start with a handle.
- **Marked cuts everywhere a model reads (MEM-16).** `ops/truncation.py` already makes every cut name its reason. The
  next step is that a `prompt` cut uses `textcap.cut`/`tail`, so the model sees the mark. That means 92 places, done
  file by file under the replay gate.
- **Keep running trials.** They found five faults in one night that 781 tests had not. A memory trial (MEM-20) is
  the next to write.

## The plan

| Step | Requirement | State |
|---|---|---|
| 1. The compile sees the whole page and keeps what it was not shown; the lost Timeline lines restored from the vault's history | MEM-14, FND-103 | **done 2 Nov** |
| 2. Hand-offs by reference past a budget, a size contract test through every adapter, a prompt too long for one argument refused | MEM-15, FND-104 | **done 2 Nov** |
| 3. Marked cuts for every prompt cap | MEM-16, FND-105 | **done 2 Nov** (the truncation audit) |
| 4. Contradictions worked to an end through the Ledger | MEM-17, FND-106 | **done 2 Nov** (the Memory Keeper) |
| 5. Long-term memory held once per fact, in English, without agents' runs, passing states dated | MEM-18, FND-107 | **done 2 Nov** (the Memory Keeper) |
| 6. The inventory covers task hand-offs, Hermes' own memory, code graphs and chats | MEM-19, FND-108 | **done 2 Nov** |
| 7. A memory trial with an answer key, gating the Keeper's automatic changes | MEM-20 | **done 2 Nov** |

**The owner's decisions (2 November):** "Yes do all": SQLite confirmed (D1, SWM-73); the memory agent may retire
duplicates and test noise on its own, softly and restorably, with a list for him (D2, DEC-40); steps 2 to 7 built (D3).
He also asked for one dedicated agent that runs periodically and fixes the memory: contradictions, false information,
"designed carefully, best practice". That agent is the Memory Keeper below.

## The Memory Keeper

One agent looks after every memory store: the memory card (`memory`, `ops/keeper.py`), which was the Librarian. Its
weekly wiki tidy (`ops/librarian.py`) is now one of its parts. It runs every night at 04:30. Its judgement parts (the
model's look at long-term memory, the wikis' duplicates and contradictions, the checks across wikis) run on Wednesdays.

### What makes this delicate, and the rules that follow

A memory agent that edits memory can do more harm than the faults it fixes. Two ways it can go wrong: it can
"correct" a true fact from a model's hunch, or it can make the owner's own memory less his. The design follows what
the memory literature and the stack's own incidents agree on:

1. **Nothing is deleted.** A long-term fact is soft-retired (Hindsight's `invalidated`, reversible) or rewritten with
   its old text kept. A wiki fact moves under Superseded with the date it stopped holding (MEM-12). The vault's git
   history keeps every version.
2. **Every change is written down and can be undone.** The change log (`/srv/ai/state/keeper.jsonl`) records what
   was there, what is there now, why, the evidence and how to undo it. Its page under Agents (Memory Keeper) lists the
   changes, each with its Undo.
3. **The world is corrected only from sources.** The Keeper never writes a fact itself. A disputed or outdated wiki
   fact gets a refinement task (TSK-34). Its research steps find sources, and the wiki's own writer folds them in.
4. **The owner's facts stay his.** In long-term memory the Keeper does only hygiene: duplicates, test noise, facts about
   agents' runs, English, end dates. When two of his facts disagree, it asks him which holds now. It never decides.
5. **Gated by an answer key.** The automatic changes run only while the memory trial (MEM-20), on the current prompt,
   scores a precision of at least 0.95 and a recall of at least 0.6. Precision means no planted true fact is touched;
   recall means most planted faults are found. Otherwise every finding becomes a suggestion for the owner, as before.
   A change to the Keeper's prompt runs the trial again.
6. **Bounded.** Each pass makes at most 40 automatic changes in long-term memory, starts 2 dispute tasks and 1
   re-check. The rest waits, listed.
7. **Faults are stopped at the source too.** Hindsight's retain mission now asks for English and for no facts about
   the assistant's own runs or tests, and it does not store a fact again that is already known.
8. **Observable.** Each pass is a run in the run record. Its page under Agents shows the gate, the changes and the open
   disputes, and a weekly line in the activity feed sums up the week.

### What it does, by store

| Store | Fault | What the Keeper does | Autonomy |
|---|---|---|---|
| Long-term memory | the same fact twice (the model confirms, the words overlap) | retires the newer one; the older stays (KNW-08) | automatic, gated |
| | test or benchmark noise | retires it | automatic, gated |
| | a fact about an agent's run (journals and the run record hold those, MEM-06) | retires it | automatic, gated |
| | a fact not in English | rewrites it in English; the original stays in the change log and in Hindsight's audit log | automatic, gated |
| | a passing state ("the setup is incomplete") | gives it the date it held (`occurred_end`) | automatic, gated |
| | two facts of the owner that disagree | asks him which holds now (a suggestion naming both) | never automatic |
| Agent wikis | a contradiction on a page (the Librarian marks it with both sources) | a Ledger item (`memory_issue`) owned by the wiki's writer. Its next compile is told. After 14 days a refinement task researches it. Settled when the claim that no longer holds moves under Superseded. Asked of the owner if a refinement could not settle it | through a task, at most 2 a pass |
| | a page not confirmed for 90 days that agents still read | a refinement task that checks it against today's sources | through a task, 1 a pass |
| | the same subject in two wikis with claims that disagree (the hub pages) | marks both pages with both sources, which makes it a dispute | weekly |
| | duplicates, broken links, orphans | the Librarian's tidy, as before | as before |
| Journals | old entries | folded into standing notes, as before | as before |
| Search index | chunks of files that are gone | cleaned whenever their share passes 10%, every night | automatic |
| Every store | over its limit, unmeasured, unknown | the inventory (MEM-01, MEM-19) and the alerts (MEM-08) | — |

**The owner's decisions**

- **D1:** confirm SQLite for the swarm (SWM-73).
- **D2:** may the memory curator retire exact duplicates and test noise on its own? It would be soft and restorable,
  with a weekly list for you. Today only your Forget retires a fact (KNW-08), and 55 suggestions have waited since
  30 October.
- **D3:** build steps 2 to 7.

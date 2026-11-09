# Commissioning the memory stack

7 to 8 November 2026. The memory stack ([MEMORY-STACK.md](MEMORY-STACK.md), DEC-44, MEM-22 to MEM-50) was built as one
change, landed as `8b561a2`, and then commissioned on the live stack: every feature exercised on real data, every
finding fixed and landed again. This is what was proven, what was found, and what the experiments say.

## What was proven live

| Feature | Requirement | How it was proven | Result |
|---|---|---|---|
| The catalogue | MEM-22 | `memstack.py catalogue` on the live stores | Every store as collections; the RAM mission's wiki (built from mail) marked private |
| The trials and their gate | MEM-47 | coverage on its fixture, continuity on the live missions, recall in the trial bank | All three pass; continuity 6 of 6 missions; recall 3 of 3 including the corrected fact; the owner's bank untouched by the trial |
| Openings for each run kind | MEM-24 to MEM-27 | an opening built for a mission, a crew job, a coding step and a Claude task | Mission: journal, wiki and the owner's facts, 17,787 of 20,000 characters; coding: commands, file facts, failures, journal; every opening recorded as given |
| A coder's file notes | MEM-32 | the hook run inside the real builder sandbox on ai-stack's notes | 630 notes; the first read of `ops/conductor.py` returned its note |
| The memory tool | MEM-28 | the assistant asked to search, open, subscribe and note; a Claude task asked to explain a mechanism | The assistant called `mcp__vault__memory_search`, open, subscribe and note; its note passed the rubric and became lesson `L-39dbf36e`; the Claude task found and called `memorypublic-search` |
| The grants | MEM-29, MEM-30 | the live keys read from LiteLLM | memory: the assistant, the missions, the curator; memorypublic: the scout, the Claude builder, OpenCode; no key holds qmd or graphify |
| What a run used | MEM-44 | the run record after real runs | A Claude task given 2,684 characters used 1,418; an exam builder used 74 % of its opening, a tester 45 %, the intake 100 %, the prober none |
| The write gate | MEM-35, MEM-37 | the Claude task's answer and the assistant's note | The answer (a walk through the code) rejected as a restatement of the code; the note kept with its evidence and run |
| The move list, without the owner | MEM-42, DEC-44 | the memory agent's night, run by hand | 93 facts that are not about the owner moved to the wikis' inbox, each with its Undo; the owner's bank went from 190 entries to 38, all about the owner |
| The merge of a repeated fact | MEM-50 | the deep pass on the live long-term memory | Two copies of the voice-answer preference merged into one, each step with its own Undo; one merge into a fact a night |
| The Keeper's trial with the new rules | MEM-42, MEM-50 | `keeper.py trial` three times on the new prompt | Precision 1.0 every time, recall 0.875 to 0.938, the planted contradiction settled by date, merges made |
| The Librarian and the Distiller | MEM-40, MEM-41, MEM-39 | the weekly pass, run by hand | 19 wikis checked, 1 contradiction marked, orphaned search chunks 80 to 7; no split (no wiki over 60 pages); archive waits, saying the read record covers 0 of 90 days; no skill (no sequence qualifies) |
| The app | MEM-45, MEM-46 | the Memory tab, How-to, a run page, the memory agent's page and Health at 375 px | All draw with no horizontal scroll; the run page shows given, used (57 %) and what the run yielded |

## What commissioning found, and fixed

| Finding | Effect | Fix |
|---|---|---|
| The first landing failed the Python lint (unused imports) | nothing went live | removed; the lint runs before every landing now |
| A crew job is its own short process; the thread that measures a run died with it | crew runs given memory were never measured | a thread the process waits for (`73a48f2`) |
| The move list dropped 58 ids Hindsight no longer held (it re-makes its observations with new ids) | nothing lost, nothing said | the move counts and reports them (`73a48f2`) |
| The memory agent's opening was given a voice-speaker page because its job's name says "memory" | 6,800 wasted characters a night | its role reads no world wikis (`73a48f2`) |
| The owner's voice preference was held six times, each copy adding one detail; the Keeper kept all | bloat in the owner's own sector | the merge (MEM-50, `65fac6c`) |
| A change's intake was given no memory at all: its card's only role is missions | the exam's first stack arm had a blind intake | every coding or review run reads its repository, whatever its card's roles (`65fac6c`) |
| A step that goes back for fix rounds was measured again at each end, its earlier openings with it | Health would overstate memory given per run | each opening measured once (this landing) |
| Two landings were refused because an edit from Windows dropped a file's executable bit | delay only | the landing script gives the bits back first |
| The replays of changed prompts need cases; four prompts had none | the prompt gate could not pass | committed cases (`prompts/cases/`), each prompt replayed and passed |
| **8 Nov, the second night** | | |
| A crew role keeps one journal; every exam run read the earlier runs' entries of its own case (the fix in the agent's words) and wrote its own | the first exam was no clean room: void past each case's first run | an exam's run neither reads nor writes the crew journals or role playbooks (CHG-17, `217e485`); the exam runs again |
| A role shared across tasks was given 16 journal entries about other repositories and used none | 5,300 characters of noise in a coder's opening | a shared role's entries are weighed by what they share with the task, and one sharing nothing is named, not given (`4a2b877`); a mission's are all given, by age (`c4a7aca`) |
| Memory without a file path (a journal entry, a fact, wiki prose) could never count as used | missions and chats measured as using nothing | an item's distinctive terms (figures, names) in what the run said count as use (`217e485`) |
| A coding step's use was read from its build runs, not from the Claude Code runs inside them | every coding step measured 0 % used; read whole, the first clean arm used 85 % | use is read three levels down (`026a5e8`) |
| Coders read files with sed, grep and cat in Bash; the file-note hook answered only Read | not one note in ten builds: the exam's notes arm measured nothing | the hook answers Bash too, three notes a call, each file once (`88666f0`) |
| The PC had 0.35 GB free (WSL held 7.6 GB, 6 GB of it Linux's file cache) | an exam step waited 38 minutes for memory | the file cache dropped once by hand; WSL's memory setting is the owner's (see the review's report) |

## The coding exam

Two fair cases of `click` (help option names, 102 tests; Sentinel copying, 10 tests), the same as on 7 November morning.
Every swarm arm passes every test, so the arms differ in what they cost: tokens and builds (fix rounds).

| Case | Arm | Stack version | Tests passed | Tokens | Builds |
|---|---|---|---|---|---|
| 8 · help option names | one coder | `43ab797` | 99 of 102 | 223,538 | 1 |
| 8 | swarm | `b7e3294` | 102 of 102 | 745,612 | 6 |
| 8 | swarm | `65fac6c` | 102 of 102 | 1,351,346 | 7 |
| 8 | swarm + wiki | `0d2a77e` | 102 of 102 | 1,024,367 | 5 |
| 8 | stack (its intake given no memory) | `73a48f2` | 102 of 102 | 1,611,056 | 8 |
| 8 | stack | `65fac6c` | 102 of 102 | 1,167,737 | 6 |
| 8 | stack + file notes | `65fac6c` | not run: every build failed at its start (the notes folder shadowed, review RUN-R1) | – | – |
| 7 · Sentinel copying | one coder | `b7e3294` | 10 of 10 | 343,096 | 1 |
| 7 | swarm | `b7e3294` | 10 of 10 | 481,453 | 4 |
| 7 | swarm + wiki | `b7e3294` | 10 of 10 | 1,052,481 | 7 |
| 7 | stack | `65fac6c` | 10 of 10 | 631,338 | 5 |

**These numbers are void past each case's first run (found 8 Nov, 01:55).** Each crew role keeps one journal, and every
exam run wrote its entry there and read the entries of the earlier runs: of the same case too, with the fix in the agent's
own words (the builder of case 7's stack arm was given two entries about Sentinel's `__reduce_ex__`). The stack arms got
them as items of their opening, the other arms as "Your own journal" (3,000 characters). So every run after a case's first
had seen a solution; only the two one-coder runs above are clean. An exam's run now neither reads nor writes the crew
journals or the role playbooks (CHG-17), and the exam was run again from 8 Nov 02:11 (below).

## The clean exam (8 November, from 02:11)

The exam runs through the night of 8 November, several runs per arm, interleaved; its table follows when the last arm
has ended.

**How to read it.** The arms differ only in the memory a run is given at its start: none (swarm), the stack's opening
(repository facts, the files and tests the specification names, commands that work), and the opening with the file notes
the coder's first read of a file returns. Every arm runs the same agents with the same budget on the same two cases.

## Experience: what the commissioning taught

- **Coders read only what is pushed.** In every exam build the coders made Bash calls only: no memory tool call, no Serena,
  no graph. The opening is the whole of what memory gives a coder, which is why its shape matters more than any tool.
- **The opening's cost is real but small; fix rounds dominate.** An opening of a few thousand characters adds 2,000 to
  5,000 tokens to each of a coder's model calls (each call re-reads the prompt). One fix round more costs more than that
  over a whole build.
- **Used share separates useful memory from noise.** The intake and the builder used most of what they were given; the
  prober used none. That is the measure the budgets are tuned by.
- **Hindsight changes underneath.** Its observations are re-made with new ids within hours, so any list of its ids goes
  stale (the move list lost 58). The lesson is now in the assistant's playbook (`L-39dbf36e`).
- **A rule that protects detail also protects bloat.** "Facts that add a detail are not duplicates" kept six copies of one
  preference; merging keeps the detail and the single fact.

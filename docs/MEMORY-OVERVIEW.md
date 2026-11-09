# The memory system: what we have, how agents reach it, and what they actually do with it

As of 7 November 2026, main at `923412f`. Everything here was read from the live code (`ops/journal.py`, `ops/builds.py`,
`ops/changes.py`, `ops/repowiki.py`, `ops/memory.py`, `ops/keeper.py`, `config/agents.yaml`, `config/hermes/configure.sh`)
or measured on the live stores and the run record. Run-record numbers cover all 1,620 runs from 28 October to
7 November. Where something was not measured, the text says so.

This is a description, not a redesign. It is meant as the starting point for one.

---

## 1. The short version

- **We have 14 stores.** Five of them are "memory" in the sense the owner means (wikis, long-term, code, skills,
  journals). The rest are records (run records, chats, task hand-offs), shared work (the Ledger) and machinery (the search
  index, code graphs).
- **Memory reaches agents in two ways:**
  - **Pushed:** the runner assembles it into the prompt before the agent starts.
  - **Pulled:** the agent has a tool and must decide to call it.
- **What is pushed gets used, by construction. What must be pulled is mostly ignored, especially by coding agents.**
  - Claude builders made 552 tool calls in 75 runs: 538 were `Bash`, none touched the code graph or Serena.
  - Serena has never been called by any agent.
- **What is pushed is often the wrong thing.** Every coding step gets the same 12,000-character wiki opening,
  whatever the task. In the exam it changed no score and raised the cost.
- **Long-term memory leaked badly.** Of 190 facts, 39 were about the owner. The rest were world news and agents'
  own runs, which belong elsewhere. The gatekeeper's instruction is fixed; 151 facts wait for the owner's tap to move.
- **The UX now shows the five kinds in one Memory tab,** plus six tabs per repository. It is new (7 Nov) and not yet
  used for long.

---

## 2. The concept as built

**Memory is what the stack knows and can look up. Each kind of knowledge has one home** (`docs/MEMORY-TAB.md`).

| Kind | Question it answers | Home | Classic name |
|---|---|---|---|
| Wikis | What has it found out about a topic? | vault wiki, one wiki per mission or topic | semantic (world) |
| Long-term | What does it know about the owner? | Hindsight (Postgres, bank `owner`) + Hermes' profile `USER.md` | semantic (person) |
| Code | How do the repositories work? | repo wikis, facts files, code maps, code graphs, written analysis | semantic (code) |
| Skills | How does it do a particular job? | Hermes skills | procedural |
| Journals | What is each agent in the middle of? | `vault/agents/<id>/MEMORY.md` | episodic |

Not memory in this concept, but stores that hold knowledge too:

- **Records:** run records, chats, task hand-offs.
- **Shared work:** the Ledger.
- **Machinery:** the search index (qmd) and code graphs.
- **How-to:** agent prompts, which are versioned files with a replay gate.

---

## 3. Every store, measured today

| Store | Lives in | Size now | Written by | Read by | Kept tidy by |
|---|---|---|---|---|---|
| **Vault wiki** | `vault/wiki` | 58 pages, 91 KB (+17 in 7 days) | the wiki curator, compiling filed sources | the assistant, missions, the curator, via search | vault lint, the curator |
| **Filed sources** | `vault/raw` | 21 items, 240 KB (10 from mail) | the inbox job, imports, the owner | the curator, search | never rewritten |
| **Mission/topic wikis** | `vault/missions/*/wiki`, `vault/topics/*/wiki` | 169 pages, 701 KB | each mission's own writer, after each result | that mission at the start of each run, related wikis, search | the Memory Keeper |
| **Repo wikis** | `vault/repos/<repo>/wiki` | 70 pages, 94 KB | the Scribe, at onboarding and after each change | the agents changing that repo (pushed) | the Scribe re-checks against code |
| **Repo facts** | `/srv/ai/code-docs/<repo>.facts.json` | 7 repos | repowise + CodeLore, sealed, no model | the repo page; the "brief", in the exam arm only | rebuilt when main moves |
| **Code maps / analysis** | `/srv/ai/code-docs/` | 7 repos | Understand Anything; Claude (read-only analysis) | the repo page; seeds the repo wiki | rebuilt on re-analyse |
| **Code graphs** | Graphify per repo | 7 graphs, 431 MB | rebuilt at each commit | builders' context pack (pushed); tool for the builder and assistant | rebuilt from code |
| **Long-term memory** | Hindsight, Postgres | 190 facts (84 world, 74 observation, 32 experience) | the assistant's chats through a gatekeeper (retain mission); earlier also agents' journals | the assistant every turn (pushed); missions and crew at run start (pushed) | the Memory Keeper; the owner's Forget |
| **Owner profile** | Hermes `USER.md` | 160 characters | the assistant, each write approved | the assistant, every turn | Hermes' memory review |
| **Skills** | Hermes `/opt/data/skills` | 63 (58 came with Hermes, 5 written by it, 3 archived) | Hermes, the skill keeper | the assistant, by choice | the curator (benchmark gate) |
| **Agent journals** | `vault/agents/*/MEMORY.md` | 25 journals, 172 entries, 84 KB | the runner, after every run | that agent, at its next run start (pushed) | the Memory Keeper folds old entries |
| **Agent prompts** | `prompts/*.md` | 23 prompts, 89 KB | the owner, agent changes he approves | each agent, every run | replay gate on change |
| **The Ledger** | `swarm.db` (SQLite) | 645 artifacts, 1,793 events, 9.3 MB | agents, the runner, the owner | swarm agents at run start (270 reads in 14 days) | the checker |
| **Search index** | qmd | 788 files, 2,004 vectors, 21 MB; **13% orphaned, over its 10% limit since today** | the search service from the vault | every vault search, every run opening | the Memory Keeper |
| **Run records** | `runtime.db` | 1,618 runs, 54 MB | every run | the owner, the doctor, replays, the judge | 90-day trim |
| **Task hand-offs** | `missions.sqlite` | 147 step results, 510 KB | each task step | the next steps, the judge | kept with the task |
| **Chats** | app storage | 31 chats | the owner and the assistant | the owner; long-term memory extracts from them | the owner deletes |

---

## 4. How memory is wired into each kind of agent

### 4.1 The run opening (pushed): missions and crew jobs

`ops/journal.py` (MEM-05) puts one **opening** in front of a run's first prompt. It has a fixed order and a budget of
12,000 characters.

1. **From the swarm:** the card's standing instructions, the owner's messages, requests, help received, lessons
   (Ledger start pack).
2. **Its state:** its journal's working state, standing notes and last entries.
3. **Its knowledge:** the top 3 matching wiki pages from the wikis its card names, its own wiki first (MEM-04), as
   snippets.
4. **The owner's facts for this task:** the top 4 Hindsight recalls, at most 900 characters, using the task title as
   the query.
5. **Its team.**

Who gets it:

- **Missions** get the full five parts, with their card (`ops/missions.py:530`).
- **Crew jobs** get it without a card and without tools (`ops/crew.py:1158`).

Coding builds do **not** get this opening. Each read is logged in the run record as a `read_file`, `wiki_search`,
`memory_recall` or `swarm_context` event.

At the end of every run the runner writes a journal entry. A model condenses the run record into Did, Found, Failed and
Open. These show as `journal_write` events.

### 4.2 The owner's assistant (Hermes `main`)

- **Every turn (pushed):**
  - Hermes' profile (`USER.md`).
  - Hindsight in `hybrid` mode: an automatic recall (budget `mid`, kinds observation, world and experience) is added to
    each turn.
  - An automatic retain extracts facts from each turn. The retain mission now keeps only facts about the owner.
  - Memory writes need approval (`memory.write_approval true`).
- **Tools (pulled), through LiteLLM's MCP gateway:**
  - vault search (`qmd`)
  - `research` (which runs the scout)
  - `graphify`
  - `missions`
  - `claude` (starts Claude Code tasks)
  - `swarm`
  - `phone`
  - `mail`
  - `house`
- **Skills:** `skill_view` and `skill_manage`.

### 4.3 The scout (web research)

It gets no wiki, long-term memory or journal opening. It has the web plus `swarm_context`, which it calls itself.

### 4.4 Coding agents

What they get depends on the path the work takes.

| Path | Pushed into the prompt | Tools available (pulled) |
|---|---|---|
| **Plain build** (`ops/builds.py`), Claude engine | the description; earlier task results; the **code graph context pack** for the planned files, only when the plan names files | Serena (symbol tools on the working copy) and Graphify (read-only graph), both via MCP; plus Bash, Read, Grep. The builder prompt names the graph tools. |
| **Plain build**, Hermes engine | same | the same tools through Hermes' builder config |
| **Change request** (`ops/changes.py`) | the **repo wiki opening** (`ops/repowiki.py` `opening()`): 12,000 characters for the coder, 8,000 for intake, 4,000 for the reviewer and prober; plus that role's journal. **In the exam arm "swarm+brief" only:** the task brief from `repofacts.brief()` instead of the wiki. | as above |
| **Claude Code task** (`claude_task`, started by the assistant) | the question | Bash, Read, Grep, Glob; Graphify |
| **Single-shot roles** (intake, judge, reviewer) | whatever their prompt holds, including the repo wiki opening above | none |

Repo knowledge is written back by the **Scribe**. It is the one writer of each repo wiki: it seeds the wiki at
onboarding from the code map, the analysis and the facts, then folds in what each change taught. The owner's review
comments become lessons in the wiki (CHG-11).

### 4.5 The Memory Keeper (`crew:memory`, `ops/keeper.py`)

It runs nightly at 04:30, with its judgement parts on Wednesdays.

- **Long-term memory, automatic but gated by a memory trial:** retires duplicates, test noise and facts about agents'
  runs; rewrites non-English facts; dates passing states.
- **Wikis, through tasks:** turns contradictions into disputes that a research task settles; re-checks stale pages;
  cleans the search index.
- **Its limits:** it deletes nothing, logs every change with an Undo, and never decides between two of the owner's facts.
- **Since 7 Nov:** it can also move facts out to the wikis (class `moved_to_wiki`), but only after the owner taps the list.

---

## 5. The UX

| Where | What the owner sees and can do |
|---|---|
| **Memory tab** (was Wiki) | One search over everything, results grouped by where each lives, each a link. Five parts below it. |
| Memory → Wikis | The page list and map. *Add to the vault* and *Filed sources* (what the vault wiki is compiled from). |
| Memory → Long-term | The owner's profile, then each fact whole, with its kind and where it came from, and its own *Forget* (soft, with Undo). The **move list**: 151 facts proposed to leave long-term memory, each can be unticked; nothing moves until the owner taps. |
| Memory → Code | A row per repository, opening its wiki; names its code map and graph. |
| Memory → Skills | The readable list; a skill opens whole. Most-used first. |
| Memory → Journals | A row per agent; its notebook opens on that agent's page. |
| **Repo page** (Code → a repo) | Six tabs: **Overview** (state, what waits, Request a change, what it is), **Map** (code map, guided tour, graph), **History** (hotspots, what changes together, who knows it, code age), **Health** (repowise's findings), **Analysis** (written analysis), **Wiki** (the repo wiki). |
| **Tasks → Team → an agent** | Its journal, which the owner can edit; its card; the Memory Keeper's page lists every change with Undo. |
| **Stack → Health** | Every store's figures: size, growth, limit, when last tidied, use. |
| **Chat** | Long-term memory works invisibly: recalls and retains are not shown in the conversation. |

---

## 6. What agents actually did with it (measured)

### 6.1 Tool calls from the run record, 28 Oct to 7 Nov

| Agent | Runs | Calls | Memory-related calls |
|---|---|---|---|
| Claude builder | 75 | 552 | **0.** Bash 538, Read 12. No graph, no Serena. |
| Builds (the runner's record of each) | 103 | 8 | None: these are the runner's own records of builds, not an engine. Of 82 builds, 78 ran on Claude, whose calls are the row above; 4 ran on Hermes. *(Corrected the same day: an earlier version read these as unrecorded Hermes builder calls.)* |
| Claude Code tasks | 180 | 666 | Graph 2. The rest is Bash 242, Read 228, Grep 159, Glob 19. |
| Owner's assistant | 98 | 422 | Vault search 81 (query 37, get 28, multi_get 16), skills 69 (view 56, manage 9, list 4), graph 11, repos overview 9, swarm_context 42. Hindsight is pushed every turn; it was never called as a tool. |
| Missions | 79 + named | n/a | Vault search 97, `agent_note` 37 (lessons kept for future runs), research 374. Plus the runner's openings: wiki reads 91, long-term recalls 80. |
| Scout | 366 | n/a | swarm_context 133; the rest is the web (2,497 searches, 1,241 fetches). |
| Intake, judge, reviewer | 119 | 0 | None: single-shot, they get what is pushed. |
| Memory Keeper | 11 | 53 | Wiki 10, recall 6, files 26. |
| Serena (any agent) | n/a | **0** | Never called. |
| Mission Control `memory_search` | n/a | 0 | Built for the app; no agent has it. |

### 6.2 The coding exam (click, two fair cases)

| Case | One coder | Swarm, no wiki | Swarm with wiki |
|---|---|---|---|
| Help names (102 tests) | 99, 224k tokens | 102, 746k | 102, 1,024k |
| Sentinel copying (10 tests) | 10, 343k | 10, 481k | 10, 1,052k |

- **The wiki opening changed no score.** It cost more, mostly through extra fix rounds rather than through reading it.
- **The swarm beat one coder on the help-names case:** it stopped 3 regressions the one coder caused, at 1.4 to 3.3
  times the tokens.
- **The limit of this test:** two small cases in a small repo, where `grep` finds the place in seconds. The repo-facts
  brief (arm "swarm+brief") has not been run yet.

### 6.3 Long-term memory in practice

- **190 facts, read by hand on 7 Nov:** 39 about the owner, 75 about the world (Gamma Metals, copper news, a speaker,
  RAM), 76 about what agents did.
- **The cause:** the retain mission asked for "what was concluded", which covers everything. Until 2 Nov, agents'
  journals were also retained.
- **The owner existed twice,** as `user` and as `the owner`. The two are now merged, and the mission names him.
- **What the Keeper did** (61 changes between 2 and 4 Nov): retired 40 facts about agents' runs, 6 duplicates and 2 test
  facts, and rewrote 13 in English. It has logged no change since 4 Nov because none was due: it ran every night, and
  a night that is not a Wednesday looks only for exact duplicates, of which there were none.
- **The new mission is fixed and proven** with a dry-run extract on real texts: it keeps owner facts only.
- **The move list** (151 facts) waits for the owner.

### 6.4 Other lessons from running it

- **Hand-offs broke, not stores** (FND-99 to FND-103, 1–2 Nov). Every fault of one night sat where one agent's output
  became another's input:
  - a brief limit applied to machine text;
  - a silent cut that misled a checkpoint;
  - a wiki compile that saw 3,000 characters and overwrote the whole page, losing Timeline lines and a contradiction
    mark on 14 pages.

  All are fixed: hand-offs pass by reference past a budget, and every cut shows itself.
- **Contradictions were marked but never worked** until the Keeper turned them into tasks.
- **The search index drifts:** 13% of it points at files that no longer exist.
- **A tool is not knowledge.** 77 builds could call the code graph and none did (`docs/REPO-KNOWLEDGE.md`). That is why
  the facts brief is pushed instead of offered.
- **The wiki is the wrong shape for code.** It opens with the same 12,000 characters every time, mostly restating what
  the code already says. A useful coding memory holds what the code does not say:
  - commands that work;
  - unwritten rules;
  - why things are the way they are, and what was reverted;
  - where it breaks;
  - what failed here before.
- **Skills are mostly stock.** 58 of 63 came with Hermes. The assistant opened skills 56 times; it wrote 5 of its own.

---

## 7. What the redesign should decide

The questions this overview leaves open, each with the evidence that bears on it.

1. **Push or pull, per kind and per agent.** The evidence says coders use only what is pushed, and the assistant does
   pull (vault search, skills). Which agents should get which kinds pushed, and how much?
2. **Task-built openings instead of fixed ones.** Every opening today is built from a title query (missions) or is fixed
   text (repo wiki). Should all openings be chosen for the task (likely files, the pages that cite them, recent failures),
   with a small budget?
3. **One retrieval entry point for agents.** Today there are several: qmd, Graphify, Serena, Mission Control's
   `memory_search` (app only) and Hindsight. Should agents have one `recall(task)` that searches every home and says
   where each answer lives?
4. **Write paths.** The things that write memory are:
   - the Hindsight gatekeeper (per chat turn);
   - wiki compiles (per research result);
   - the Scribe (per change);
   - journal entries (per run);
   - `agent_note` (agent's choice).

   Which of these need the "a writer sees what it rewrites" rule and a reconcile step (add, update, supersede, nothing)?
5. **The person/world boundary.** Long-term memory is now owner-only. Should anything the assistant learns about the
   world in chat go straight to a wiki with the chat as source, instead of being dropped?
6. **Code knowledge.** Which of the code sources earn their place once the exam has run on a large repo?
   - the repo wiki;
   - the facts (repowise, CodeLore);
   - the code map (Understand Anything);
   - the graph (Graphify);
   - Serena.
7. **Observability gaps.** Hindsight recalls inside chats are not visible. Each gap needs fixing before usage can be
   compared.

The answers are in [MEMORY-STACK.md](MEMORY-STACK.md), decided and built on 7 November 2026 (DEC-44).
8. **Measurement.** A memory trial exists for the Keeper (MEM-20). There is no trial yet that shows memory improving an
   agent's outcome, except the coding exam. Which outcome measures should every memory change be held to?

### Best-practice references the current design already draws on

- **CoALA:** kinds kept apart (working, episodic, semantic, procedural).
- **MemGPT/Letta and Anthropic's context engineering:** small assembled working memory, the rest fetched just in time.
- **Karpathy's LLM-wiki:** raw sources, a compiled wiki and lint.
- **Mem0 and Zep/Graphiti:** reconcile-on-write; facts carry time, and an old fact is invalidated, never deleted.
- **LongMemEval and LoCoMo:** memory measured against an answer key.

The gaps against them are listed in `docs/MEMORY.md`.

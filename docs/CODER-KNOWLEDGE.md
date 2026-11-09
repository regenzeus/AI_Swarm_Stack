# How coding agents use what onboarding makes

Decided and built 8 November 2026 (DEC-49, BLD-34 to BLD-38); the exam that must prove it runs from that night. The owner asked: how should coding agents work with all
the information onboarding generates, should it all go into an LLM wiki that can be updated, does Claude Code need any of
it, and how do we make sure it actually improves their work, above all in very large codebases, including keeping to
the codebase's conventions. This document answers from published studies, practitioners' reports and the stack's own
measurements, and proposes what to build and how to prove it.

## The short answer

- **Preprocessing pays only when it is served narrowly.** Generated overview documents pushed into the context do not
  make coding agents more correct; in the largest study they made them slightly worse. What helps is (1) the few facts an
  agent cannot read from the code (commands, slow tests, non-obvious rules), (2) compact experience from earlier work on
  the same files, (3) structure that points the agent to the right place in a large repository, and (4) checks that run
  by themselves. Everything else is for people.
- **Yes, one wiki per repository, and it must update itself.** The analysis, the engineer's guide and the Scribe's pages
  belong in that one wiki, each page citing the files and the commit it was written from, so a change to those files
  marks the page to check. Agents never read the wiki whole: they get the lines that touch their files.
- **Conventions are kept by checks, not by prose.** A rule a program can check becomes a check that runs after every edit
  and before a change is done. Prose stays for the reason behind a rule and for what no program can check.
- **Our own exam says coders read only what is pushed.** In every exam build the coders used Bash only: no memory tool
  call, no graph, no Serena. So offering a tool is not enough; the design pushes a small amount and hooks the rest into
  what the agent already does (reading a file, finishing a change).
- **It must be proved per piece.** Each layer below is an arm of the replay exam on a large repository; a layer that does
  not win on tests passed or on cost is switched off, whatever it cost to build.

## What the evidence says

| Finding | Source |
|---|---|
| LLM-generated context files (like `/init`'s) lowered task success by about 3 % on average; developer-written ones helped slightly; generated files helped only where the repository had no documentation at all | [Gloaguen et al., ETH Zurich, Feb 2026](https://arxiv.org/pdf/2602.11988) |
| Across Claude Code and Codex, context files did not measurably change correctness; the clear effect was on process: told that the test suite is slow, Claude ran it less and finished 24 % faster | [Two-agent ablation, 2026](https://arxiv.org/html/2607.27250v1) |
| Claude Code started with a vector index and dropped it: agentic search (glob and grep in a loop) worked better and is never stale; the cost is more tokens per lookup | [secondary report of Boris Cherny's remarks](https://smartscope.blog/en/ai-development/practices/rag-debate-agentic-search-code-exploration/) |
| A repository-level code graph raised agents' resolve rate on SWE-bench by 32.8 % relative, at a small cost per task; graph tools beat plain retrieval for finding the fault | [RepoGraph](https://arxiv.org/html/2410.14684v1), [ARISE](https://arxiv.org/pdf/2605.03117) |
| How well an agent explores a repository strongly predicts whether it solves the issue; a bigger context window is not the answer | [SWE-Explore](https://www.alphaxiv.org/abs/2606.07297) |
| Correctly selected, summarised experience of related earlier tasks raised resolution and cut tokens and time; unfiltered or wrongly selected experience did not help or hurt | [SWE Context Bench](https://arxiv.org/html/2602.08316v3) |
| Prompts give no guarantee; practitioners move every checkable rule into linters, formatters and agent hooks, and keep the instruction file short, saying the rule and its reason so the hook rarely has to block | [Evil Martians](https://evilmartians.com/chronicles/stop-writing-rules-in-agents-md-use-agent-hooks-and-nano-staged-instead), [Zimmergren](https://zimmergren.net/agentic-ai-engineering-03-why-instructions-arent-enough), [harness engineering](https://www.topgenaijobs.com/blog/harness-engineering-coding-agents) |
| Anthropic's own guidance: keep light references and load data just in time with tools; disclose context progressively (a skill's name first, its body when used) | [Effective context engineering, summarised](https://agentic-ai.readthedocs.io/en/latest/ContextEngineering/anthropic/) |
| Generated code wikis (DeepWiki) are good for a first orientation; they go stale and are less reliable as the code gets complex | [DeepWiki reviews](https://codersera.com/blog/deepwiki-vs-traditional-documentation-developer-decision-framework/amp/), [critique](https://passo.uno/ai-wikis-docs-teather-as-a-service/) |

Most of these are 2026 preprints and practitioner posts; none tests a codebase of a million lines with a clean ablation.
That is the gap our own exam must close.

**So is the preprocessing best practice, or should we just tell Claude Code to analyse and do the job?** Both camps
exist. Cursor, Augment, Sourcegraph and Devin (DeepWiki) index ahead of time; Claude Code deliberately does not. On a
small or medium repository, Claude Code alone does well, and our exam on `click` showed no gain from extra memory, only
cost. The case for preprocessing is the large repository: finding the right files takes many turns, and conventions live
in places the agent does not happen to read. That is where pointers, earlier experience and checks earn their cost.

## What we make today, and who uses it

| What onboarding makes | Does a coding run get it? | Does the app show it? |
|---|---|---|
| The copy of the code | it works in it | the repo page, the source pane |
| Code graph (Graphify): calls, imports, who uses what | yes: the brief's files and who uses them | Code graph |
| Facts: commands that work, tests, languages | yes: the brief's commands | the facts sections |
| Code map with every file explained (Understand Anything) | only through the memory search tool, which coders never call | the viewer and the Map tab |
| Search digest | the same: only through search | search |
| Written analysis or engineer's guide | no | as a document |
| Wiki (the Scribe): conventions, fragile areas, what failed | yes: the brief's "what failed here before" lines | the Wiki tab |
| Pages whose cited files changed (marked to check) | no | no |
| A coder's note per file (MEM-32) | yes, pushed by the hook on the first read of the file | no |
| Lessons of earlier coding runs | yes, in the opening | the Memory tab |
| What a run was given and what it used | measured: coding runs were given 7,400 characters and used 49 % on average over 62 runs | Health; the run page |

## The design: five layers

Each layer has one job, a size it may not exceed, and an exam arm that must show it helps.

### 1. The repository card: always given, at most 1,500 tokens

The handful of facts an agent cannot cheaply read from the code, and nothing it can:

- setup, the fast test for one file, the full suite and how long it takes, the formatter and the linter;
- the non-obvious rules (at most ten), each with its reason and a file that shows it;
- the fragile areas (at most five), each with what broke there;
- a module map: one line per top-level package, and where to start for the common kinds of change.

It is made from the facts, the engineer's guide and the wiki's conventions page, each line citing its files and commit.
Update makes it again from the latest code. The owner can pin or strike a line. It is given in the opening (the same
place as today's brief), never written into the repository unless the owner asks for a real `CLAUDE.md`.

### 2. The task brief: picked for this task (exists, extended)

Today's brief (the files the request matches, who uses them, commands, what failed on those files) gains:

- **the tests that cover these files**, from the graph and the facts, so the agent runs the right tests first;
- **an exemplar**: the existing file most like the one the agent will write or change (same package, same kind), so
  conventions are copied from a real example, which works better than any description of them;
- **the impact set**: what calls the code being changed, in a large repository the one thing grep does not show well.

Its size is the run kind's budget, as now; its used share is measured, as now.

### 3. Hooks: knowledge where the agent already looks

Because coders use only Bash and Read, knowledge rides on those:

- **on the first read of a file** (exists for notes): the file's note, its one-line explanation from the code map, the
  wiki lines that cite it, and its covering tests, three lines at most;
- **on a grep that returns more than 50 hits** in a large repository: the two or three packages the code map says the
  term belongs to, so the agent narrows instead of reading everything;
- tools stay available (the memory tool, a `where`, `callers` and `tests_for` lookup) for the agent that wants them, but
  nothing depends on them being called.

### 4. Gates: conventions and correctness by program

- **after each edit**: the repository's own formatter and linter on the changed files, the result fed back at once;
- **before a change is done**: the covering tests and the impact set's tests must pass, then the full suite as now;
- **mined conventions become checks**: from the code map and the graph, rules a program can verify (import direction
  between layers, where a kind of file lives, naming of tests and modules) are proposed as lint rules or structural
  tests; the owner accepts each, and an accepted rule runs in the gate. What cannot be checked stays as a card line;
- **the review lens "conventions"** compares the change with its exemplar and the card's rules, and names each departure.

### 5. One wiki that stays current

- The written analysis or engineer's guide is cut into wiki pages; every page records the files it cites and the commit.
- Update runs the wiki's recheck: pages whose cited files changed are marked and shown, and the Scribe rewrites them on
  its next pass (the recheck exists; showing and rewriting are new).
- After every coding run, what failed and what was learned is written to the pages of the files it touched (exists for
  failures); a line that no run used in 90 days and no check needs is retired (prune by measured use).

### What a large codebase changes

- The card and the map are per package in a monorepo; the brief starts from the package the request names.
- The code map updates incrementally (built today: only changed files are explained again), so Update stays cheap.
- The impact set and the grep hook matter most here; on a small repository they are switched off by the exam's result.

## How we will know it helps

The replay exam (CHG-17) already replays real commits: the agent gets the commit's message at its parent, and the score
is the tests the commit added. It runs today on `click` (small), where extra memory showed only cost. The proof needs:

1. **A large repository**: ai-stack itself (735 files) and one large public project (picked for over 500,000 lines and
   a good test suite); a large repository on the work deployment once the work PC has pulled.
2. **Twenty cases per repository**, picked from history, spread over packages.
3. **Arms**: plain Claude Code with only the commands; plus the card; plus the brief; plus hooks; plus gates. Three runs
   per arm per case, interleaved, clean (no journals, as since 8 Nov).
4. **Measures**: hidden tests passed, regressions, convention departures (linter and review lens on the diff), tokens,
   wall time, turns until the first right file is opened, files touched that the commit did not touch.
5. **Rule**: a layer stays on for a repository size only if it raises tests passed, or cuts tokens or time without
   lowering tests passed. The result goes in this document and in Health.

## What the app does not show yet

- **Staleness of the wiki**: pages marked because their cited files changed are not shown anywhere.
- **File notes** (MEM-32): pushed to coders, invisible to the owner.
- **What a coding run was given and used** shows on the run page, but not on the build or change it served.
- **Conventions**: there is no page that lists a repository's rules, their source, and whether a check enforces them.
- **The repository card** (new): it would be the first thing on the repo page, editable, with its age in commits.

## What was built (8 November 2026)

| Layer | Where | Requirement |
|---|---|---|
| The repository card, onboarding's ninth step, the Card tab with pin, strike and add | `ops/repocard.py`, `ops/onboard.py`, the repo page | BLD-34 |
| The card first in every coding and review run's opening | `ops/memstack.py` | BLD-34 |
| Everything else exported to the build's sandbox (`/work/.memory/knowledge/<repo>/`) | `ops/repocard.py`, `ops/builds.py` | BLD-35 |
| The code map's line in the file note; a wide search hears its folders | `ops/memstack.py`, `config/hermes/claude-hooks/memory_hook.py` | BLD-35 |
| The repository's linter after each edit; the conventions lens reads the card | `config/hermes/claude-hooks/lint_hook.py`, `ops/builds.review.py` | BLD-36 |
| Tests to run first and the closest example in the brief | `ops/repofacts.py` | BLD-37 |
| The exam's knowledge arm, cases after the knowledge's commit | `ops/replay.py`, `ops/changes.py` | BLD-38 |

| The wiki filled from onboarding: a page per part of the code and per section of the guide, made again each time (the owner, 9 Nov) | `ops/repowiki.py` (`feed`), onboarding's wiki step | BLD-35 |

Not built yet: mined conventions proposed as checks (step 6 below), and the build page showing what a run was given.

## The order of work

1. The repository card from facts, guide and wiki, given in the opening; shown on the repo page; Update remakes it.
2. The brief's covering tests, exemplar and impact set.
3. The read hook with map explanation, wiki lines and tests; the grep hook for large repositories.
4. The edit and finish gates with the repository's own formatter, linter and covering tests; the conventions lens.
5. The large-repository exam with the arms above, run between steps so every layer is measured as it lands.
6. Mined conventions proposed as checks; the wiki's staleness shown and rewritten; pruning by use.

# The memory concept

Written 7 November 2026, after the owner read a first design and said it was not what he asked. He had asked for the kinds of memory to be shown; it had redrawn the app's agents, history and health pages inside a new tab. This replaces it.

## The concept

**Memory is what the stack knows and can look up. Each kind of knowledge has one home.**

| Kind | The question it answers | Comes from | Who reads it | How you correct it |
|---|---|---|---|---|
| **Wikis** | What has it found out about a topic? | Research and filed sources, each fact naming its source | Agents, at the start of a run and by search | Contradictions are worked to an end; a new source supersedes |
| **Long-term** | What does it know about me? | What you say in chats, through a gatekeeper | Your assistant; every agent at the start of a run | Forget, per fact, with Undo |
| **Code** | How do my repositories work? | The code, code maps, past changes | The agents changing that repository | It is re-checked against the code |
| **Skills** | How does it do a particular job? | Hermes, and what it wrote itself | Your assistant, when a job calls for one | Written instructions |
| **Journals** | What is each agent in the middle of? | Each agent, after each run | That agent | Its agent page |

**The rule:** a fact about you goes to long-term memory. A fact about the world goes to a wiki, with its source. How a repository works goes to its code memory. How to do something goes to a skill. What an agent did goes to its journal.

**What memory is not.** Chats, run records and tasks are records of what happened, and keep their own pages. The Ledger is shared work, under Agents. The search index and code graphs are machinery. Their figures are under Stack → Health, with every store's.

## The Memory tab

The Wiki tab becomes **Memory**, with one search over everything and a part per kind. Each part is the thing itself, to read.

```
Memory
[ What does it know about…            ]
 Wikis | Long-term | Code | Skills | Journals
```

- **Wikis**: the page you know, list and map. *Add to the vault* and *Filed sources* (what the vault's wiki is compiled from) sit here because they feed it.
- **Long-term**: your profile, then each fact whole, with its kind, where it came from and its own *Forget*.
- **Code**: a row per repository, opening its wiki; its code map and graph are named.
- **Skills**: the readable list.
- **Journals**: a row per agent; its notebook opens on that agent's page.
- **Search**: results grouped by where each lives, each a link.

## Why the leak mattered

The concept is only true if each home holds what it claims. On 7 November long-term memory held 190 entries, read by hand:

| What it was | Entries | What happens |
|---|---|---|
| About the owner | 39 | Stays |
| About the world: Gamma Metals, copper news, a speaker, RAM | 75 | Filed for the wikis, naming the chat, then retired |
| What agents did | 76 | Retired: their journals and the run record hold it |

Nothing moves until the owner has seen the list. He can untick any, and each retirement has its Undo.

The cause: the gatekeeper's instruction asked for "what was concluded", which covers everything. It now asks only for what is about the owner, and says wikis keep the world. The instruction lives in the compose file, not in `prompts/`, so the replay gate does not cover it. It is proven instead with Hindsight's dry-run extract on real texts, which stores nothing.

The owner also existed twice, as `user` and `the owner`: the instruction now names him, and the two entities are merged.

## What helps a coding task

The exam compared one coder, the swarm, and the swarm with the wiki, on two fair commits of `click`:

| Case | One coder | Swarm, no wiki | Swarm with wiki |
|---|---|---|---|
| Help names (102 tests) | 99, 224k tokens | 102, 746k | 102, 1,024k |
| Sentinel copying (10 tests) | 10, 343k | 10, 481k | 10, 1,052k |

**The wiki did not change a score. Its extra cost mostly came from extra fix rounds, not from reading it:** four coder rounds against one on the Sentinel case, which varies from run to run. Two cases cannot say what the wiki costs or gives.

The owner's point stands: on a task like this a wiki is a stretch, and it depends on what is in it. The cases were small changes in a small repository, where `grep` finds the place in seconds. Today's wiki is also the wrong shape: it opens with the same 12,000 characters in a fixed order, whatever the task, mostly summarising what the code already says.

**What a coding wiki should hold** is what saves a search or prevents a mistake, and that the code does not say:

| Holds | Why it helps | Where it comes from |
|---|---|---|
| Commands that work: set up, test, what is flaky | Saves the search every agent repeats | Already measured: `profile.json` |
| Rules the code does not state: compatibility promises, what must not change | Prevents a mistake a passing test will not catch | Docs, reviews |
| Why: decisions, and attempts that were reverted | Stops the same wrong turn | Commit history, the owner's reviews |
| Where it breaks: files that often need fixing, and what changes together | Warns before a regression | Commit history, with no model at all |
| What failed here before | Grows with use | The judge's rejections, Request changes |

**What it should not hold:** a restatement of the code. It costs tokens, goes stale, and is worse than reading the code.

**And it should be built for the task, not read whole.** From the request: find the likely files; pull the pages citing them, the tests covering them and what usually changes with them; hand over a few thousand characters.

**Understand Anything.** The wiki is already seeded from its digest and written analysis, which is why it reads like a summary of the code. Turning all of it into wiki pages would make more of the wrong thing. Its real value is as a **map used at task time**: its per-file summaries and graph answer "which files matter for this request?", which is what the task-built opening needs first. That matters most in a large unfamiliar repository, and little in `click`.

**How we would know.** The exam needs cases that can tell these apart: a larger repository (`ai-stack` at 635 files, `mochi-mqtt`), more cases, and a measure beyond the score, such as tokens and fix rounds. Then an arm with the task-built opening against the one we have.

## Status

| | |
|---|---|
| The Memory tab, one search, long-term with sources and Forget, the list | Built with this document |
| The gatekeeper's new instruction, and `user` and `the owner` as one | Built; proven on real texts after landing |
| Moving the facts | Waits for the owner's tap on the list |
| A task-built opening for code, and the richer code memory | Proposed, with the exam above as its test |

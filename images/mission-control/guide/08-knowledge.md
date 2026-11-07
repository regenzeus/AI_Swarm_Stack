---
title: Your knowledge and memory
kicker: What the stack knows
part: Knowledge
icon: brain
minutes: 6
summary: The vault holds everything you and your agents write. Search finds it, and long-term memory remembers you.
views: [skills, longterm, codemem, journals, memsearch, sources]
---
The stack has two kinds of knowledge: the **vault**, which holds documents, and **long-term memory**, which holds
facts about you. Both feed every answer Hermes gives.

## The vault

The vault is an Obsidian folder on your PC (`C:\AI\vault`), versioned in git on the NAS. It holds your own notes,
every report and alert, mission notes, the mission wikis, and imported mail and chat exports. You can open it in
Obsidian on the PC like any other vault.

**Search** (qmd) indexes all of it, combining keyword search and meaning-based search, so "copper supply
deficit" also finds a report that says "shortfall in U3O8 production". Hermes searches it before answering.

## Adding knowledge

Drop something in, and it's filed into the vault and searchable within minutes.

```try
label: Add a note, a web page or a file
open: "#/system"
note: Find "Add knowledge". Choose Note, Web page or File, give it a title and add it. It lands in the vault's inbox and gets indexed.
```

```try
label: Add knowledge by chat
chat: Save this to my vault as "Copper thesis": I think the supply deficit lasts until 2030 because restarts are slower than planned.
note: Hermes calls vault_add. Later you can ask "What's my copper thesis?" and it finds it.
```

## Long-term memory

After conversations, the memory system (Hindsight) pulls out lasting facts: your preferences, your holdings,
people and decisions. Hermes recalls them in later conversations, in the app and on Telegram.

New memories that look important wait for your OK first. When some are waiting, a banner on Home and a badge on
**Stack** tell you. Tap **Remember** or **Discard**.

```try
label: Search what it remembers
open: "#/system"
note: Use "Long-term memory" on the Stack page. Search for a word, such as a company you follow.
```

## Forgetting

To make it forget, search memory for a word and tap **Forget conversations containing …**. Every stored
conversation with that text is removed from long-term memory.

> [!note] Memory runs on local models on your PC. Your conversations aren't sent anywhere to build it.

## The Memory tab

Memory is what the stack knows and can look up. Each kind of knowledge has one home, and the **Memory** tab has a part for each, under one search:

- **Wikis**: what it has found out about a topic, each fact naming its source. *Filed sources* are what the vault's wiki is compiled from, as they came.
- **Long-term**: what it knows about you, with where each fact came from. *Forget* takes one fact out, and it can be restored.
- **Code**: what it knows about each repository: its wiki, code map and graph.
- **Skills**: how your assistant does a particular job, each readable.
- **Journals**: each agent's own notebook of what it is in the middle of.

The rule behind it: a fact about you goes to long-term memory, a fact about the world to a wiki, how to do something to a skill, what an agent did to its journal. Chats, runs and tasks are records, and keep their own pages. The figures for each store are under **Stack → Health**.

## The Memory Keeper

Every night one agent, the **Memory Keeper**, looks after all of it. It works by rules that keep your memory yours:
nothing is deleted, every change can be undone, the world is corrected only from sources, and your own facts are
never decided for you.

- **Long-term memory.** It retires a fact you already have (the older one stays), test or benchmark noise, and facts
  about the agents' own runs (their journals keep those). It puts a fact into English and gives a passing state the
  date it held. It does these itself only while its **trial** passes: 32 planted facts, true ones among them, which it
  must sort without touching a true one, three times on its current prompt. Otherwise it only suggests. When two of
  your facts disagree, it asks you which holds now.
- **Contradictions on a wiki** become a *dispute* (Agents → Ideas shows them) owned by the wiki's writer. The writer's
  next update is told of it. After 14 days a research task looks for current sources, and the writer folds them in: the
  claim that no longer holds moves to *Superseded* with its date. If research cannot settle it, you decide.
- **Stale pages** (not confirmed for 90 days) that agents still read get a research task that checks them.
- **The same subject in two wikis** (the hub pages): claims that disagree are marked on both pages with both sources.
- On **Wednesdays** it also does the weekly tidy that was the Librarian's:
  - **Lint**: links to pages that don't exist, pages no other page links to, a wiki over 200 pages, the same subject on
    two pages.
  - **Duplicates**: two pages about the very same thing become one with every fact and source of both. The other stays
    as a short note pointing to it. A merge that would lose or add a single link is refused.
  - **Contradictions**: two claims that can't both be true for the same date get a *contradiction* callout, each with
    its source.
  - **Hub pages**: a subject two or more wikis have a page on gets a hub page in the vault wiki (under *hubs*).
- **Every night** it folds old journal entries into standing notes and cleans the search index when chunks of files
  that are gone pile up.

Its page under **Agents** (*Memory Keeper*) shows what it changed, each change with **Undo**, whether its trial lets it
change anything itself, and the open disputes. Each week's changes are one line in the activity feed.

```try
label: See what the Memory Keeper changed
open: "#/crew/memory"
note: Each change shows the fact, what was done and why, with Undo; above them, whether its trial lets it change anything itself.
```


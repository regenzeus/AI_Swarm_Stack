---
title: Your knowledge and memory
kicker: What the stack knows
part: Knowledge
icon: brain
minutes: 6
summary: The vault holds everything you and your agents write. Search finds it, and long-term memory remembers you.
views: []
---
The stack has two kinds of knowledge: the **vault**, which holds documents, and **long-term memory**, which holds
facts about you. Both feed every answer Hermes gives.

## The vault

The vault is an Obsidian folder on your PC (`C:\AI\vault`), versioned in git on the NAS. It holds your own notes,
every report and alert, mission notes, the mission wikis, and imported mail and chat exports. You can open it in
Obsidian on the PC like any other vault.

**Search** (qmd) indexes all of it, combining keyword search and meaning-based search, so "uranium supply
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
chat: Save this to my vault as "Uranium thesis": I think the supply deficit lasts until 2030 because restarts are slower than planned.
note: Hermes calls vault_add. Later you can ask "What's my uranium thesis?" and it finds it.
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

## All your memory in one view

The stack keeps ten kinds of memory, and **Stack → Memory** shows them all in one list: what each holds, what it is for
(*what happened*, *what is true*, *how to act*, *shared work*, *search*), who writes and who reads it, how big it is, how
much it grew this week, how full it is against its limit, who keeps it tidy and when that last ran, and what is wrong with
it. It refreshes every hour.

| Memory | For | Kept tidy by |
|---|---|---|
| Vault notes | your sources, never rewritten | (nothing to tidy) |
| Vault wiki | knowledge compiled from your notes | the wiki curator |
| Agent wikis | one per mission or topic | the Librarian |
| Agent journals | each agent's own runs (its Memory tab) | the Librarian |
| Old mission notes | NOTES.md files not moved yet (a mission's working state is now in its journal) | moved at its next run |
| Long-term memory | facts about you; what agents found stays in their wikis and journals | the memory gatekeeper and the Librarian |
| The Ledger | ideas, findings, your decisions | the Checker |
| Skills | how Hermes does things | the skill curator |
| Run records | every run's steps | a run's full steps go after 90 days; its summary stays |
| Search index | the search over all of it | the Librarian |

An agent's **Memory** tab is its own diary: what it did in its runs, what it found, what failed. A wiki is shared knowledge
about the world, with sources. A problem the list shows (a full store, an index full of chunks of files that are gone)
says who fixes it. A memory that stays over its limit for 8 days becomes an alert on its curator in Agent health.

## The Librarian

Once a week (Wednesdays) the **Librarian** tidies the memory: it folds old journal entries into standing notes, lists
long-term facts that look duplicate or stale for you to decide on, and tidies every agent wiki and the search index:

- **Lint**: links to pages that don't exist, pages no other page links to, a wiki over 200 pages, the same subject on two
  pages, contradictions not yet settled.
- **Stale**: a page no result has confirmed for 90 days is marked *stale*; the next result that confirms it clears the mark.
- **Duplicates**: two pages about the very same thing become one page with every fact and source of both. The other page
  stays as a short note pointing to it, so no link breaks. A merge that would lose or add a single link is refused.
- **Contradictions**: two claims that can't both be true for the same date get a *contradiction* callout on the page, each
  with its source. The Librarian never picks a winner; a later result settles it.
- **Hub pages**: a subject two or more wikis have a page on gets a hub page in the vault wiki (under *hubs*) that links
  each wiki's page. That is the top layer joining the wikis, instead of one wiki holding all the others.
- **Search index**: it drops the chunks of files that are gone, so search stops finding them.

It adds no facts of its own and forgets nothing: each pass is one vault commit you can undo, and forgetting stays yours.
**Stack → Memory** shows its last pass, wiki by wiki, with the commit.

```try
label: See the Librarian's last pass
open: "#/system"
note: Scroll to Memory, then The Librarian: each wiki's checks, what it merged or marked, and the vault commit.
```


---
title: LLM wikis
kicker: Knowledge that grows with every run
part: Knowledge
icon: wiki
minutes: 4
summary: Each mission maintains its own linked wiki of companies, people, concepts and events, browsable like Obsidian.
views: [wiki]
---
After every run, the mission's results are folded into its **wiki**: one page per company, person, concept,
project or event, linked with `[[wiki links]]`. Over weeks, a briefing turns into a structured knowledge base
you can browse instead of re-reading old reports.

Every wiki has a short **summary** under **About**: what it covers and its most important current facts.
It is rewritten automatically when the wiki's pages change (at most every six hours).

## Browsing

The **Wiki** tab opens with a **map of all your wikis**: one bubble per wiki, sized by its pages (purple the vault wiki, amber
an agent's, teal a topic's), and a line between two wikis for the subjects both have: a page with the same title or alias,
like *Centrus Energy* in the ASPI and the Copper wiki. Tap a bubble to open its wiki, a line for the shared subjects.
There is no wiki that holds all the others: each has one owner and one topic, and the vault wiki is the top layer.

Under the map is the list of all your wikis, each with its pages and links and **who used it in the last 7 days**: which
agents read it (counted in runs, from their run logs: a run's start, its vault searches, its file reads) and who wrote it.
Tap one to open it. A wiki shows its name, its actions (**Improve this wiki**, **Its agent**, **Delete wiki**), a search
field and three tabs:

- **Pages**: every page, grouped by kind (entities, concepts, projects, events, sources), each with its one-line
  summary. Tap a page to read it. It fills the screen; the link at the top goes back to its wiki. **Linked
  mentions** shows every page that points here (backlinks). Links to reports open the report.
- **Graph**: every page is a dot, colored by kind. Tap a dot to open the page.
- **About**: the wiki's summary and who writes it.

Every page has **Correct or research**: say what is wrong or what to find out, and it becomes a task that corrects
the page with sources (Tasks: *Improve a wiki or a page*). **Improve this wiki** does the same for the whole wiki.

Type in the search field to find pages by their text; clear it to see all pages again.

```try
label: Open the wiki graph
open: "#/wiki"
note: Pick a wiki, then switch to Graph. Big clusters are the topics your agents keep returning to.
```

Grey, dotted links point to pages that don't exist yet. The next runs usually fill them in.

Tap **Copy markdown** next to a page's title to copy its original Markdown, including front matter and wiki
links, rather than the rendered page. **Copied** appears only when the clipboard write succeeds. If your browser
blocks clipboard access, an error appears instead; allow access and try again.

```try
label: Copy a wiki page as Markdown
open: "#/wiki"
note: Open any page, tap Copy markdown beside its title, then paste into a text editor to see the original source.
```

## One writer per wiki

Each wiki has one writer: a mission's wiki is written by its runs (after each result), a briefing's by the desk, the vault
wiki by the curator. Another agent that knows something a wiki lacks doesn't edit it: it adds a **help** to that wiki in
the Ledger, with why the writer would not see it (lane discipline, see the swarm chapter). The writer's next update folds
it in, names the helper in the fact's source and marks the help as folded. Every wiki is an item in the Ledger, so its
helps show in Tasks → Activity.

The one other change is the **Memory Keeper**'s weekly tidy (see *Knowledge*): it merges two pages about the same subject,
marks contradictions and pages not confirmed for 90 days, and writes hub pages in the vault wiki for subjects several
wikis share. It adds no facts. When a result changes a fact, the old fact moves to the page's **Superseded** section with
the date it stopped holding, so a page's history stays readable.

## A new wiki on any topic

Tap **New wiki**, name the topic and, if you like, what it should cover. A research agent studies it in depth
(several research steps with sources), writes a report and compiles the wiki from it. The wiki appears with the
first result; run its agent again any time to deepen it.

```try
label: Start a new wiki
open: "#/wiki"
note: On the list of wikis, tap New wiki at the top right, name a topic and tap Research and build the wiki.
```

## Deleting a wiki

On a mission's wiki, **Delete wiki** under its name (tap twice) removes its pages. The mission keeps running but no longer builds a
wiki. Nothing is lost for good: the vault keeps the history, so the pages can be restored. The vault wiki itself
can't be deleted: the curator builds it from your notes, so change or delete the notes instead. Deleting is refused from the AI phone.

## Asking about the wiki

Wikis are part of the vault, so Hermes can answer from them. Just ask about the topic: Hermes searches the vault wiki,
the briefings, every mission's results and wiki, and the agents' memory journals by itself.

```try
label: Ask a question the wiki answers
chat: Using my mission wikis, which companies come up most often together with Kazatomprom, and why?
note: Hermes searches the wiki pages and follows their links.
```

## Rebuilding a wiki

If a wiki gets messy, it can be compiled again from all of the mission's results. From the PC:
`make wiki-rebuild MISSION=<slug>`.

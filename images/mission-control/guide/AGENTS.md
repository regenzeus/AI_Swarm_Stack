# images/mission-control/guide/: the in-app guide

One Markdown file per chapter, `NN-id.md`. `NN` sets the order and `id` is the URL (`#/guide/<id>`). The app shows
them on the guide's own page (`#/guide`: search, chapter index; one tap from the **Stack** page's title row), behind a "How it works" link on every status section, and each screen's **How this page works** link (at its end) opens the chapter that lists that screen in `views:`.
The reader is the owner, not a developer: plain language, second person, short paragraphs, examples first.

## Front matter (all keys required)

```yaml
---
title: Chat with Hermes            # chapter title
kicker: Your assistant              # two to four words above the title
part: Everyday use                  # one of GPARTS in web/static/guide.js
icon: chat                          # a key of `ic` in web/static/app.js
minutes: 6                          # reading time
summary: One sentence for the chapter card.
views: [chat]                       # app routes this chapter explains (for each page's "How this page works" link); [] if none
---
```

## Building blocks

- **Try it** example: one per feature, ideally 2 to 4 per chapter.
  ````
  ```try
  label: Ask Hermes for a status update
  chat: What are my tasks doing right now?         # or  open: "#/tasks"  or  app: 8448
  note: What happens and what to look at.
  ```
  ````
  `chat` types the prompt into Chat but doesn't send it. `open` goes to an app route (`{mission}` is replaced with
  an active mission's slug). `app` opens a tailnet app by port. Examples must be safe to try: nothing that deletes,
  costs money or contacts third parties.
- **Live block**: ```` ```live services``` ```` renders live data. The names are in `LIVEB` in
  `web/static/guide.js` (architecture, services, resources, missions, skills, ci, models, tools, versions, changes,
  apps, costs). Prefer a live block over writing down a list that will change.
- **Callout**: `> [!tip] …`, `> [!note] …`, `> [!warning] …`.
- Section headings are `##` (they form the chapter's table of contents). No `#` heading in the body.

## Keeping it current (enforced by `tests/test_guide.py`)

Every Mission Control MCP tool is mentioned in some chapter, every app screen is in some chapter's `views:`, every
`make` target with `##` help is mentioned as `make <target>`, and every example and live block points at something
real. A new user-visible feature gets a paragraph and an example in the chapter it belongs to, in the same commit.

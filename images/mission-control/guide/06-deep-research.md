---
title: Deep research and the web
kicker: How the stack looks things up
part: Everyday use
icon: search
minutes: 5
summary: How research questions become a plan, several research steps and one synthesis, and how the web is kept at arm's length.
views: []
---
When a question needs more than one search, the stack does **deep research**: it writes a plan, works through 3
to 5 research steps, then combines what it found into one answer with sources. You can watch each step live on
the mission screen.

```try
label: Start a deep research task
chat: Do a deep research task: compare Acme Mining, Kazatomprom and NexGen on cost, growth and risk, and e-mail me the result.
note: Hermes creates a one-off deep task. Open it under Missions to watch the plan and each step tick off.
```

## Who reads the web

Only one agent, the **scout**, is allowed on the web. That's deliberate: web pages can contain hidden
instructions aimed at AI agents ("prompt injection"). The scout has no access to your notes, memory or e-mail,
so there's nothing private it could leak.

Every web question goes through three stages:

1. **Privacy guard.** The question is checked before it leaves the house: patterns, your private-terms list and a
   model check. If in doubt, it's blocked.
2. **Scout.** It searches the web and decides which pages to read.
3. **Page reader.** Pages are read in an isolated container that can reach the internet but not your home
   network. It reads PDFs in full, which is how annual reports and SEC filings get read end to end.

Results come back labelled as untrusted, and Hermes treats them that way.

```try
label: Have it read a filing
chat: Read Beta Materials' latest 10-Q from the SEC and tell me the cash position and the main risks.
note: The page reader fetches the filing from sec.gov (it identifies itself as SEC requires) and reads it in full, PDF or HTML.
```

## Quick questions vs deep research

| You ask | What happens |
|---|---|
| a simple question in chat | Hermes answers from your knowledge, or does one scout lookup |
| "research …" in chat | a one-off mission, usually one research pass |
| "deep research …" or a deep task | plan → 3–5 steps → synthesis, all shown live |

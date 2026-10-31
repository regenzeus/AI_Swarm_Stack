# Truncation audit, 2026-10-30

**Why:** the owner sent a screenshot of the Swarm sync page in which every log line ended in "…", and asked:

> I hate truncation. Do not truncate user facing input. Whenever you truncate anything I need a clear justification.

He also wanted sensible truncation rules in the AGENTS.md files. This page records what the audit found and what changed.

- **The rules:** root `AGENTS.md`, section *Truncation* (DEC-27), and requirements APP-19, APP-20 and QA-16.
- **The live list** of every cap that remains, with its reason: `python3 ops/truncation.py report`.

## What was cut

The audit covered every Python and JavaScript file under `ops/`, `images/` and `smoke/`, and the app's CSS. It found
556 text caps of 40 or more characters, and 16 CSS ellipses or line clamps (about 30 places in the app used them).
About 230 of these cut text the owner reads or types, with no mark (FND-38). The worst:

| What | Where it was cut |
|---|---|
| Log lines on an agent's page (the screenshot) | `crew.journal_tail` cut each line at 300 characters; the `.ellipsis` CSS class then cut it to one line |
| What the AI phone will type or open, on the approval card | 200 characters: the owner approved text he could not fully see |
| The mail Trash approval's sample | sender 40, subject 60 characters |
| The build diff the owner reviews | 1,500 lines, with no sign of the rest |
| A tool's result and arguments in the run log | 3,000 and 6,000 characters, even in the opened view |
| Review findings, health causes and fixes | 600 characters each; review summaries 800 |
| Errors in events, Telegram, health and builds | 120 to 400 characters each |
| The owner's own input | build descriptions 8,000; change requests 4,000; Chatroom posts 4,000; mission goals 4,000; reasons 300; titles 100. All cut silently |

It also found a bug (FND-39): the Ledger stored run inputs as `json.dumps(...)[:40000]`. A longer input became a cut
JSON string that the replay set could no longer read.

## What changed

- **Text the owner reads is whole.**
  - Errors, events, Telegram lines and log lines carry the whole message.
  - The app wraps text (`.wrap`); there is no CSS ellipsis or line clamp any more.
  - Run logs, tool results, diffs and approval cards show everything.
  - The home feed shows 40 items at a time, with "Show older (N more)".
- **The owner's input is refused, never cut.** Over a limit, he gets an error naming it (`textcap.limit()`):
  - build descriptions, change requests, override reasons;
  - mission descriptions, goals, notes, questions and sources;
  - Chatroom posts, reasons, notes, titles and searches.

  The Ledger refuses a Board message over 4,000 characters instead of cutting it. The AI phone refuses to type more
  than 500 characters at once, or to open an address over 2,000 characters; before, it did the first part silently.
- **The caps that remain show themselves.**
  - `textcap.cut()` and `tail()` add "[… N more characters cut …]".
  - Stored text the owner may read keeps at least 20,000 characters (`textcap.STORE`).
  - Stored JSON is bounded with `bounded_json()`, so it still parses.
- **Every remaining cap names its reason** on its line (`cap: <reason>`). `ops/truncation.py check` in
  `ops/check.sh` fails on one without a reason, so no new silent cut can land.

## What remains, and why

320 caps, at the time of this audit:

| Reason | Count | For example |
|---|---|---|
| prompt | 77 | evidence and context in the doctor's, the planner's, the reviewers' and the replay prompts |
| untrusted | 72 | fields a model or another program returns (shop offers, review findings at 4,000), web pages, request headers |
| store | 60 | deploy and check logs (the last 20,000 characters, with the cut shown), step details, the diff file (600,000) |
| id | 42 | build branch slugs, chat and mission titles made from text, issue keys, run titles |
| list | 22 | the newest 300 builder steps (with "N earlier steps"), the last 60 connection actions, graph neighbours |
| parse | 18 | windows searched for "usage limit" or an error marker |
| preview | 15 | a log row's argument summary (the row opens to all of them), a search hit's snippet, a report's excerpt in the feed |
| api | 14 | Telegram's 4,096 characters, push notification bodies, mail subjects, Alexa speech, Forgejo fields |

Caps under 40 characters (short hashes, dates, small lists such as "top 5 senders") are outside the check. The rules
still apply to them, and new code should follow the same rules.

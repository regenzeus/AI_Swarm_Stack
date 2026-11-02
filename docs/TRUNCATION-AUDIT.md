# Truncation audits, 30 October and 2 November 2026

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

## The second audit, 2 November 2026

**Why:** after the overnight trials (FND-100, FND-103: a model took an unmarked cut for the whole text, and a wiki
compile wrote over the parts of a page it was never shown), the owner wrote "Truncation strikes again", noted that
coding models add truncation by reflex and that it is often a bug, and asked for every cut to be justified or fixed,
with no silent and unjustified cut left and the rule written into `AGENTS.md`.

### What the first check missed

The October check made every cap name a reason. It did not make a cut show itself, and it did not see whole kinds of
cut. The audit counted them before changing anything:

| Kind | Found | Example |
|---|---|---|
| A reason someone reads, but a raw slice | 250 | 79 cuts going to a model (`notes[:3000]`, `body[:8000]`, the Librarian's `page[:6000]`), 63 bounds on what agents send, 34 previews, 13 stored records |
| A slice by a constant, not a literal | 35 | `doc_text[:PER_ISSUE]` in the doctor's prompt, `p["body"][:PAGE_CHARS]` in the Librarian's |
| A slice between 20 and 39 | 39 | a mail's date cut to 25 characters (its time zone lost), lists of 20 or 30 items shown as all |
| Shell | 20 | `vault-lint.sh` read the curator's answer through `tail -60`, so a REPORT longer than that was lost |
| SQL limits | 25 | lists of the newest 15, 20, 40 rows with no word of the rest |
| **A model's answer cut at its output limit** | 9 places | no model call read `finish_reason`: a cut answer was parsed or stored as whole (mission results, the desk's JSON, the chat, replays) |
| **A Claude Code run stopped at its turn limit** | 3 places | `error_max_turns` was read as an empty or partial answer |

### What changed

- **New helpers** in `ops/textcap.py` (copied next to every image that uses them, now seven): `fit()` (a marked cut
  within a hard limit), `more()` (a list that ends with "… and N more"), `first()` (a bounded list from an agent that
  says on stderr what it left), `answer()` (a model's answer, refused at its output limit) and `Cut`. `app.js` has
  `clipped()` and `moreOf()`.
- **Every model answer** is read through `textcap.answer()`; a Claude run stopped at its turn limit raises
  (`builds.claude_text()`), and a Claude task that stopped says so in its error. The chat marks an answer that stopped
  at the output limit ("Ask it to go on").
- **About 200 cuts were marked** (`cut`, `tail`, `fit`, `more`, `first`). Each change was read; a list or a value
  that a marker would break (a URL, a Gmail label, a search query) was not converted but given its true reason.
- **Removed, because nothing needed them:** the chat list's 300 (3 chats), a wiki page's newest-30 sources (it
  dropped older provenance), the `tail` on the curator's lint and ingest answers, the cut of exception messages (shown
  whole, as the rule says).
- **Refused instead of cut:** an Alexa command over 300 characters and a text to say aloud over 600 (a cut command
  does something else); an app error report over 4,000 bytes (it was cut, then failed to parse); the owner's Forget of
  more than 50 facts at once.
- **Lists say what they left:** the run viewer counts the events it does not show (it showed the last 1,500 without a
  word), the run's "touched" panel counts its pages, searches, refusals and cut-offs, the journal's opening says how
  many earlier runs are in the journal, the judge's and the self-review's lists end with "… and N more".
- **The check** (`ops/truncation.py`) now sees slices from 20 up and by constant, shell and SQL caps, and the model
  answers; it fails on an unmarked cut someone reads, and one reason covers one cap (a tag on the line above used to
  cover the next cap too, which hid four).

### What remains, and why

502 caps at the end of this audit, each with its reason; `python3 ops/truncation.py report` lists them:

| Reason | Count | Form |
|---|---|---|
| prompt | 98 | all marked |
| untrusted | 88 | all marked |
| list | 77 | each says how many more, next to it |
| id | 71 | short keys, titles, hashes and dates with the whole kept |
| store | 65 | all marked |
| preview | 36 | all marked |
| parse | 32 | windows code searches; nothing shown |
| api | 21 | 15 marked with `fit()`; 6 are URLs, labels and queries a marker would break |
| rotate | 14 | rolling windows of ids, prices and snapshots |


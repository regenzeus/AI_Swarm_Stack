# What a chat made, reachable from the chat (APP-39; designed 2 Nov, built 3 Nov 2026)

The owner dispatched a deep-research mission from the chat ("Bullet Heaven Design Primer and Checkbox
Specification") and could not get from the chat to the mission's page: "if we are creating items in chat they need to
be accessible from chat." The rule this design adds: **what you make somewhere, you reach from there, and the thing
leads back to where it was made.**

## Where the truth is (exact, no guessing)

- Every chat turn is a run in the run record, tied to its chat: Hermes' session `mc-<chat>-<rev>` gives the run the
  ref `chat:<chat>` (the aistack-runtime plugin).
- Every tool result Hermes receives is in that run as a `result` event, its text included. `mission_create` already
  answers `Created: [<slug>] ...` or `Already exists: [<slug>]`.

So "what this chat made" is a read of the record, not a new store: the turns of `chat:<id>`, their `result` events of
the tools that make or change things, and the id each result names. Nothing is inferred by time.

One change makes it robust: every tool that makes or changes something ends its answer with one line the server
reads, `made: <kind>:<id>` or `changed: <kind>:<id>` (Hermes still reads the sentence before it). A tool result
without that line (an older one) is read by its present wording.

**The owner's own case had no id at all.** The runner took longer than mission_create's 6 s wait, so the tool answered
"Creating '…' now" without a slug. Such a pending answer now ends with `made: mission:request-<rid>`, the runner's
request id. The app resolves it from the runner's answer (`public/results/<rid>.json`, kept an hour) and otherwise by
the item's title. Mission titles are unique because a second mission with the same title is refused. Once resolved,
the id is kept in the chat. The same applies to a pending build_assign, which used to say "Build #<request id> queued",
and to a pending claude_task and vault_add.

| Tool | Kind | Page |
|---|---|---|
| mission_create | mission (an agent) | `#/mission/<slug>` |
| build_assign | build | `#/build/<id>` |
| claude_task | Claude task | `#/live/claude-task:<id>` |
| repo_create | repository | `#/repo/<name>` |
| vault_add | a note in the vault | `#/read?path=<path>` |
| send_email | e-mail sent | none: a card without a link |
| mission_control, mission_update, mission_set_triggers | changed: mission | `#/mission/<slug>` |
| build_request_changes, build_recheck, build_switch_engine | changed: build | `#/build/<id>` |
| repo_make_buildable, understand_repo | changed: repository | `#/repo/<name>` |

Hermes has no task_create or wiki tool in the chat, so tasks and wikis are not in the table. A task is given in the
composer, and a wiki is made on the Wiki page.

## What the owner sees

1. **In the answer.** Under the message in which Hermes made something, one card per item: its kind, its name, its
   state now (Running, Done, Waits for you, Failed) and one tap to its page. The state is live: a mission made at
   20:31 shows Running, later Done, with its result's headline. "Already exists" shows the existing item, marked so.
   A failed make shows its error on the card. A change (triggers set, paused) is one small line, not a card.
2. **In the chat's header.** A chip **Made here · 2** opens a sheet with everything this chat made, newest first,
   with the same states. It is the answer to "where did that thing go" without scrolling.
3. **In the chat list.** Each chat in the history shows what it made as small icons with a count, so a chat that
   started a mission is easy to find again.
4. **Back from the item.** A mission, build, Claude task or repository made in a chat says **From a chat: <the
   chat's title>** under its title. One tap opens the chat at the answer that made it, with its card outlined.
   (Home's result cards do not say it yet.)
5. **When it finishes.** The chat that made a one-off mission or task gets a line when it ends ("Bullet Heaven
   Design Primer finished: open the result"), so the conversation and its outcome stay together. A recurring
   mission does not write into the chat every day; its card's state carries it.

## How it is built

- `runrecord.chat_made(chat=None)` reads the `result` events of the tools in the table, for one chat or for all of
  them. It pairs each result with its call's arguments by `call_id` and parses it to `{key, kind, id, verb, title,
  what, ts}`. `verb` is one of made, exists, changed, pending, failed or sent. `key` is the result event's id.
- `server.chat_made(c)` merges those items into `c["made"]` and resolves the pending ones. It saves the chat without
  moving it up the list. What the chat keeps outlives the run record's 90 days of events.
- `made_view` joins an item with its live state from state.json: its name now, its page, its state and the latest
  result's headline. `/api/chats/<id>` carries the joined list as `made`.
- `made_pass` runs every 30 s. It keeps every chat's `made` current and builds the reverse index (`from_chat` in
  `/api/state` and its stream). It also writes the end line. An item counts as one-off when it is a manual mission
  without triggers, a Claude task, or a build (a build's line comes when it waits for review). The line is written
  only when this pass saw the item still open first, so an item that ended before the feature saw it is not
  announced late.
- In `app.js`, a card goes under the first answer after its result. If that turn was edited away, the card is shown
  only in the sheet. The other parts are the header chip and its sheet, the chat-list icons, the "From a chat" link,
  and a 15 s refresh while something the chat made is still on its way.
- Tests are in `tests/test_chat_made.py`. They cover a card with live state, the older wordings (including the
  owner's id-less case), a pending request resolved through the runner, the back link, the one end line (none for a
  recurring mission or for one already over), and the made lines of the tools.

## Not in this design

A chat that only talks about an item (asks about a mission it did not make) gets no card: links Hermes writes in its
text stay as they are. Items made outside the chat (the composer, the app's forms) are not attributed to a chat.

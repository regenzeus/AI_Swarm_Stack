# The app's UX: what the owner does, where everything lives, one visual system

The app (Mission Control, named per deployment, `images/mission-control/`) as of 10 November 2026, after the n8n move
(DEC-51 to DEC-53). This is the reference every screen follows; `images/mission-control/web/AGENTS.md` has the code
patterns, and the dated reviews (`REVIEW-*.md`, [UX-REVIEW-2026-10-30.md](UX-REVIEW-2026-10-30.md)) the history.

## 1. What the owner does, every day

| When | What | Where |
|---|---|---|
| Morning, on the phone | Sees what needs a yes or no, what ran overnight, what is next | **Home**: Needs you, Now, Results |
| Any time, one-handed | Answers a question, approves a purchase, a pack commit, a memory | **Home → Needs you** (`#/decide` for all of them) |
| Any time | Gives a request in a sentence, follows its run | **Home**'s ask bar, **Workflows** → New request, a run's page |
| Any time | Sees every workflow, its diagram and its runs | **Workflows** (the app's own list; n8n's editor one tap away on the desk) |
| At the desk | Reviews and approves code changes | **Stack → Code** |
| Now and then | Reads what the agents know, what could be better | **Agents → What agents know**, **Improve** |
| When something is off | Health, costs, tools, connections | **Stack** |
| When curious | A model call's whole prompt and answer | **Traces** (Phoenix inside the app) |

## 2. Information architecture

**The menu** (the six places, APP-69, 11 Nov 2026): Home, Workflows, Agents, Improve, Chat, Stack, the same on the
phone's bottom bar and the desk's menu. Six thumb-wide targets (62 px at 375 px), the badge on Home counts what needs
the owner, the dot on Stack is the stack's state. The app speaks only the factory design's words (APP-70: Workflow,
Run, Step, Agent, Ask, Trigger, Result; never task, mission, crew, plan, swarm).

| Menu | Holds | Reached from it, at most two taps |
|---|---|---|
| Home | Today (Needs you, In the stack, Now), Activity, Results, Overview (House, what the phone shared, numbers) | `#/decide`, `#/house`, `#/share` |
| Workflows | Every workflow by factory and area; New request; triggers | a workflow's page (`#/workflow/<id>`: diagram, runs, result, agents, settings), a run's page (`#/run/<workflow>/<run>`), an old record's page (`#/task/<id>`), `#/n8n` |
| Agents | Agents, Health and results, Who works with whom, What agents know (All, Wikis, Long-term, Code, How-to, Journals) | an agent's page, a scheduled job's page, a wiki, a skill |
| Improve | Proposals, Scorers, Measures, Benchmarks | an idea's page, `#/measures`, `#/trials` |
| Chat | Hermes, with history | what a chat made |
| Stack | Health (incl. Traces), Costs, Tools, Connections (Gmail, outside agents, packs and trackers), Settings; Code and n8n's editor | `#/build`, `#/n8n`, `#/traces`, `#/guide`, `#/files`, `#/mail` |

**One place for a run** (APP-63): a run is followed on its task's page: *Where it runs* (the workflow, the run, its
state, the step; on the desk n8n's canvas of the run), its steps each with its own log (`#/live/<run>`, the one view of
what an agent did), *Sources* (from what it read to the answer) and *Timeline*. All runs of a workflow are on
Workflows → Runs. No other screen lists runs, except the agents' history on Stack → Costs, which opens each run's log.

**The stack's tools inside the app** (APP-66): a tool whose web UI takes a sub-path is served under the app's address
behind its gate (`server.frames.py`) and shown on a page of the app: n8n (`/n8n/`, Workflows) and Phoenix
(`/phoenix/`, Traces). Hermes admin, OpenCode, the code map dashboard and Open WebUI ask for `/assets/...` at the root
and take no sub-path: they open in their own tab from Stack → Tools, each behind its own gate (the code map's viewer is
inside a repository's page already).

**Old addresses** keep landing somewhere sensible (`MOVED` in `app-base.js`): `#/engine`, `#/runs` → Workflows' runs;
`#/templates` → Workflows; `#/packs`, `#/trackers` → Stack → Connections; `#/telemetry` → Stack → Costs; `#/taskmap` →
the task's Sources; a bare `#/live` → Tasks → Activity; `#/swarm?tab=…` → its Tasks view; `#/missions` → Tasks;
`#/system?tab=guide` → the guide.

**The connection state** (APP-65) is said the same way everywhere (the bar on top while something is off, the rail's
foot, Stack's dot, Home's line): *Not connected* only when this device gets no answer from the app; *The stack is
starting (runner up in about a minute)*, *The runner stopped 12 min ago* or *The runner did not start* otherwise.

## 3. The visual system

Calm and exact, like an instrument: graphite surfaces, one accent, nothing glows (APP-34). Every value below is a CSS
variable at the top of `web/static/app.css`, defined for the dark theme and again for the light one; components never
use a colour of their own.

### Colour tokens

| Token | Use |
|---|---|
| `--bg`, `--bg2` | the page, the side rail's tint |
| `--surface`, `--surface-2`, `--surface-3` | a card, a raised part inside it (segmented control, tag), the selected segment |
| `--border`, `--border-2` | card edges, input edges |
| `--text`, `--muted`, `--faint` | body text, secondary text, captions and timestamps |
| `--accent`, `--accent-2`, `--accent-ink` | the one accent (primary button, focus, selected menu icon), its gradient partner, text on it |
| `--ok`, `--warn`, `--err`, `--run` and their `-bg` | states: done, waits or needs you, failed, running; a pill or banner uses the colour on its `-bg` |

### Type scale

Inter for text, Archivo for page titles, JetBrains Mono for code and numbers in logs. Every `font-size` in the
stylesheets is one of these (`--fs-1` … `--fs-11`); a size between two steps is not allowed. Only the guide's chapter
titles grow with the window between two steps (`clamp`).

| Token | px | Use |
|---|---|---|
| `--fs-1` | 11 | tab bar labels, the smallest captions |
| `--fs-2` | 12 | `.tiny`, pills, tags, timestamps |
| `--fs-3` | 13 | `.small`, list subtitles, section headings (uppercase) |
| `--fs-4` | 14 | list titles, banners |
| `--fs-5` | 15 | body text |
| `--fs-6` | 16 | card titles (`h3`), inputs (no zoom on a phone) |
| `--fs-7` | 20 | a KPI value in a small tile |
| `--fs-8` | 24 | a KPI value, a task's or agent's title |
| `--fs-9` … `--fs-11` | 28, 30, 32 | page titles (`h1`), larger on wider desks |

### Spacing and shape

A 4 px rhythm: `--s-1` 4, `--s-2` 8, `--s-3` 12, `--s-4` 16, `--s-5` 20, `--s-6` 24, `--s-7` 32. Cards have 12 px
radius (`--r`), inner parts 8 px (`--r-s`), pills are round. Gaps: 8 between parts of a row, 12 between cards, 26
between sections (`.section`).

### Components (one of each; no screen makes its own)

| Component | Class | Rule |
|---|---|---|
| Page title row | `.hero` (`.grow` + actions) | the title, one line of state under it, at most two actions; on a phone the actions go under the title |
| Section | `.section-h` with `h2` | an uppercase heading, its note or one link on the right, an `explain()` (i) for how it works |
| Card | `.card` (`.pad`, `.pad-l`) | one thing; a card that stands for a page opens it on a tap anywhere (`data-href`) |
| List | `.list` on a `.card` | rows with an icon tile (`.ic`), a title (`.ttl`), a subtitle (`.sub`), a chevron when it opens something |
| Button | `.btn` (`.sm`, `.primary`, `.ghost`, `.danger`) | one primary per screen; an icon first, then the verb |
| Pill | `.pill` + state | a state in one or two words, coloured by the state tokens |
| Tag | `.tag` | a name or a filter; `.on` when chosen |
| Segmented control | `.seg` | the parts of a page (Stack, Home, a task), one at a time; remembered per device |
| Banner | `.banner` (`.info`) | a way to another page or something that needs attention, full width, one line |
| KPI tile | `.kpi` on a `.card` | a label, a value, one caption |
| Empty state | `emptyState(text, action)` | says what fills it and offers that action |
| Explanation | `explain(key, html, label)` | the small (i); how a thing works is never on the screen until asked |
| Tool page | `toolPage(title, src, views, about)` | a tool inside the app: the title row, its views as a `.seg`, (i), "On its own", the frame filling the window |
| Frame | `.tool-frame` (`.run` inside a task) | the tool's own UI; never redrawn under the owner while the same view is open |

### Layout

- **Phone first** (375 px): one column, the bottom bar, no sideways scroll (the journeys check it nightly), a 16 px
  gutter, a button 40 px high (a small one 32), the bar's targets 62 px wide.
- **Desk** (from 960 px): the side rail (248 px) and the content. Pages of reading and lists keep a measure (1,180 px;
  Home spreads its three parts as columns from 1,100 px); a tool's page and the wide maps use the whole width.
- **Wide screens**: the whole app scales up in steps (1.12 from 1,900 px, 1.3 from 2,400 px, 1.6 from 3,200 px) through
  `zoom` on `.shell`; every height that depends on the window divides by `--z`. A tool's frame undoes the zoom (a
  zoomed frame took its clicks beside where they were aimed, measured at 2,560 and 3,440 px): n8n and Phoenix keep
  their own size, and their frame the window's height in its own pixels.

## 4. Rules every screen follows

1. **Quiet**: what the screen holds says what it is; how it works is behind `explain()` or the chapter (*How this page
   works* at the end, or `how()` on a section). A promise the owner must know before he acts stays beside the action.
2. **Plain words**: no internal names (no "namespace", "occurrence", "door", "pool", "engine", "template"); dates,
   numbers and money only through the formatting helpers (TSK-31).
3. **Whole text**: labels wrap, never an ellipsis; a long list says how many more and offers them (APP-19).
4. **Every action says what happens next** (`act(req, message)`), and an empty state offers its action.
5. **Live without moving**: a live update never moves what is under the owner's finger; a form, a chat or a tool frame
   is never redrawn under typing.
6. **One place each**: a run on its task's page, a decision in Needs you, a tool on its page; an old address keeps
   landing there.
7. **Both themes, both shapes**: every change is looked at in dark and light, at 375 px and at a desk width.

## 5. Status and what is left

Done with DEC-53 (10 Nov 2026): the menu, one place for runs, the Stack page, the connection state, n8n and Phoenix
inside the app, the type scale. Left: about 875 inline `style=""` attributes in the view code (mostly a margin or a
gap) still name pixels instead of the spacing tokens; they follow the 4 px rhythm in the screens changed on 10 Nov and
move to classes as each screen is next touched.

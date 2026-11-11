# images/mission-control/web/: the front end

Plain JavaScript and CSS, **no build step, no framework, no CDN at run time** (marked, DOMPurify, d3 and the Inter,
Archivo and JetBrains Mono fonts are vendored by the Dockerfile into `static/vendor/`).

| File | What it is |
|---|---|
| `index.html` | the shell: side nav (desktop), tab bar (phone, Stack included, its dot = live state), no top bar (a `#livebar` shows only when offline or an update waits), and each page's **How this page works** link |
| `static/app-base.js`, `app-tasks.js`, `app-runs.js`, `app-devices.js`, `app-wiki-code.js`, `app-memory.js`, `app-workflows.js`, `app.js` | the app in parts (PLT-25), loaded in that order into one scope: the base (helpers, icons, formatting, the menu, the connection state, the router and its `MOVED` old addresses), Tasks and Home, the run log, devices and Share, the wiki and Code, Memory, the tools inside the app, and last the Stack page, live data and the start |
| `static/app-workflows.js` | the tools inside the app (WFL-11, WFL-14, APP-66): `toolPage()`, the one page for a tool in a frame; `#/traces` (`vTraces`: Phoenix); n8n: `#/workflows` (`vWorkflows`: n8n's editor in a frame on the desk, a list of the workflows on a phone), a task's and crew job's **Where it runs** (`wfWhereInto`, `wfCrewInto`) and an agent's **In workflows** (`wfInInto`), all from `GET /api/workflows`. The frame's address is `/n8n/...` on the app's own origin; `sw.js` never caches it |
| `static/tax.js` | the tax desk's result (TAX-10): `taxViewInto()` on the page of the task Your taxes (per year: papers per form, sums per form line, missing, questions, the earlier return, files) and `vTax()`, a year's file as a page (`#/tax/<year>/workbook|belege|return`) with its path on the NAS; from `GET /api/tax`, never kept on the device |
| `static/guide.js` | the Guide (`#/guide`, one tap from the Stack page): search, chapter index, chapter reader (`#/guide/<id>`), live blocks, "Try it" cards, progress, `how()` and `explain()` (loaded before `app.js`) |
| `static/app.css`, `static/guide.css` | styles. Design tokens are the CSS variables at the top of `app.css` |
| `sw.js` | service worker: app shell offline (network first), push notifications. Bump `CACHE` when the shell's file list changes |
| `manifest.webmanifest` | install metadata (PWA) |

## Patterns to follow

- **The agent log** is one component: `logHtml(events)` draws every source (runtime record, old timelines, builder and
  Claude task steps, chat tools, crew logs). `logKind()` is the only place where event kinds and tool names become the
  log's kinds (START READ WRITE TOOL WEB MAIL PHONE THINK SAYS WAIT PROPOSE ERROR END); a source may name the kind
  itself (`kind` or `data.kind`). `mountRun(el, run)` embeds a run, live over SSE. Don't add a second renderer.
- **Agents**: `allAgents()` turns missions and crew jobs into one shape (`missionAgent`, `crewAgent`); the list sorts
  by needs you, live, next run; health is the card's colour (`agentHealth`). The agent page's tabs are the same for
  both kinds; it redraws on a state update only when `agentSigOf()` changes, so a streaming log isn't cut.

- **Views** are functions `vName()` that set `view.innerHTML` and then bind events. Register a new view in the
  `render()` map and, if it's a tab, in `NAV`. Every screen gets a guide chapter that lists it in `views:`.
- **Helpers**: `api()` for fetches, `act()` for runner requests (it polls the result), `md()` for markdown
  (sanitized with DOMPurify), `esc()` for **every** value put into HTML, `toast()`, icons from `ic`.
- **Live updates**: only the views in `LIVE` re-render on state changes. Forms, chat and reading views don't, so
  nothing is lost while the user types or reads.
- **Colours** only through the CSS variables (dark and light themes both define them), **font sizes** only through the
  type scale (`--fs-*`), spacing on the 4 px rhythm (`--s-*`): [docs/UX.md](../../../docs/UX.md) is the visual system.
  No hex in component CSS except the wiki folder colours.
- **Phone first**: check every change at 375 px width with no horizontal scroll, and on desktop (side nav ≥ 960 px).
  `make journeys` opens every route at 375 px in a browser, on the live data and with none (ops/journeys.py).
- **One look and wording (TSK-31)**, checked by tests/test_ux_standards.py and the journey checks:
  - Dates, times, numbers and money only through the formatting block at the top of `app.js`: `dt()` "Sat 31 Oct,
    18:40", `when()` (relative within a day), `day()`, `clock()`, `nf()` "1,234", `kn()`/`tok()` "4.2k", `usd()`,
    `eur()` "€12.34", `gb()`, `dur()`, `fmtMs()`. No `toLocale…`, `Intl` or sliced ISO times anywhere else (a key or a
    coordinate is marked `fmt-ok`).
  - A card that stands for a page (its heading is the link) opens it on a tap anywhere: `data-href`.
  - An empty state says what fills it and offers that action: `emptyState(text, action)`.
  - Every `act(req, message)` says what happens next ("Started: its steps show here as they run"), or makes that
    sentence from the answer (`(r) => …`); `null` only for a read whose answer shows in place.
- **No truncated text** (root AGENTS.md, Truncation; APP-19):
  - Text wraps with `.wrap` and `overflow-wrap: anywhere`. Never use `text-overflow: ellipsis`, `line-clamp` or a
    `.slice()` of something the owner reads.
  - A long log row shows whole: rows wrap (`white-space: pre-wrap`).
  - A list shows how many more there are, with a button for them (the home feed's "Show older").
  - A preview is allowed only with a visible "…" one tap from the whole text, tagged `/* cap: preview */`.
  - Your input over a limit gets an error naming the limit, never a cut (APP-20).
- **Updates**: the app checks `/api/version` and reloads itself when a new image is deployed, so new front-end
  files reach installed apps without user action.
- Per-device conveniences (model choice, guide progress) go to `localStorage` behind try/catch. Anything shared
  belongs on the server.

`make check` parses every `static/*.js` with `node --check`.

## Words on a screen

Say it once, after it happens. A sentence on how something works does not sit on the page: the screen shows it by what it holds, the action's own message reports it ("Added: search and chat find it within minutes"), and what a reader may still want sits behind the small `explain()` control. A promise the owner must know before he acts stays beside the action.

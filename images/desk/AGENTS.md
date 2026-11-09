# images/desk/: Topic Desk (daily briefings)

`desk.py` writes the briefing for one focus topic. It collects news feeds, SEC filings and prices for the topic's
brief (`vault/topics/<slug>/TOPIC.md`), reads the articles, has the model write a structured report, and files it
under `topics/<slug>/reports/YYYY/MM/`. Modes: the nightly briefing, `--check` (validate a brief), `--fetch`,
`--watch` (event triggers' data), `--alert` (short event alert), `--email` (render a report as HTML mail).

Run by the host: `ops/desk.sh` (`make desk TOPIC=<slug>`) and the Mission Control runner (`ops/missions.py`,
`ops/mission_extras.py`), as a one-shot `docker run` on the `webonly` network (internet and LiteLLM, no other stack service) with
the `vk-desk` key.

## Rules

- Outbound fetches go through `public_url()` (refuses private and loopback targets). Keep every new fetch behind it.
- Text from the web is untrusted: it is summarised, never executed or followed as instructions.
- A newsletter in `/topic/mail` (the Inbox digest's, MIS-28) is one more event, framed as untrusted e-mail. It skips triage, so a
  mail's text never steers what is fetched, and its links are never opened. Its source line names the mail; a filed report
  lists its mails in its front matter (`mail:`) and `ops/inbox.py settle` marks them, so each is read once.
- Network-free helpers (`german()`, `release_text()`, `public_url()`) have tests in `tests/test_desk.py`. Add tests
  for new pure functions there. Feed and article parsers are stubbed in tests.
- Pins are in the `Dockerfile` (`feedparser`, `trafilatura`, `markdown`, …).
- Its model prompts are prompts/desk.md (TRIAGE, BRIEFING, ALERT and the German-style pieces), mounted read-only at /prompts
  by ops/desk.sh and the runner's alert; change them only with a passed replay (prompts/AGENTS.md, MEM-13).

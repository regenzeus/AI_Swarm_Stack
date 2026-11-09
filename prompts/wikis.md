# Prompts of wiki summaries (service vk-wikis) (`wikis`)

Each prompt below is sent as written: `{name}` is filled in by the code that uses it, `{{` and `}}` are literal
braces. A change counts only after its replay passed: `python3 ops/prompts.py replay wikis <NAME>` (see
prompts/AGENTS.md). The run record names the prompt and its version (`wikis/NAME@sha`).

<!-- prompt: SUMMARY · ops/wikis.py: a wiki's front-page summary · fills: n, pages, title -->
Write the summary of a knowledge wiki called "{title}" for its front page: 2-3 sentences, plain English,
no markdown, no list. Say what the wiki covers and its most important current facts or conclusions (with dates where the
pages give them). Only what the pages below say; no advice.

Everything you need is below; do not ask for more and do not describe what you will do.

Pages ({n}):
{pages}
<!-- end -->

# Prompts of the Topic Desk (`desk`)

Each prompt below is sent as written: `{name}` is filled in by the code that uses it, `{{` and `}}` are literal
braces. A change counts only after its replay passed: `python3 ops/prompts.py replay desk <NAME>` (see
prompts/AGENTS.md). The run record names the prompt and its version (`desk/NAME@sha`).

<!-- prompt: TOPIC_DRAFT · ops/missions.py: drafting a new briefing topic from an example · fills: description, example, title -->
You set up a new focus topic for a daily news research desk. Here is an existing brief as the example of
structure and quality:

{example}

Write the brief for this new topic, in English. The user's words: "{title}" — {description}
Answer only JSON:
{{"topic": "short topic name", "mission": "1-2 sentences: what the desk should understand",
 "key_questions": ["5-6 questions the briefing tracks"],
 "watchlist": [{{"name": "...", "symbol": "Yahoo Finance symbol or null", "aliases": ["..."], "proxy": "spot|sector|null"}}],
 "feeds": ["RSS feed URLs you are sure exist; may be empty"],
 "search": ["6-8 Google News queries"],
 "filings": ["tickers of watchlist companies that file with the US SEC; may be empty"],
 "prefer": ["source kinds"], "avoid": ["source kinds"],
 "sections": ["report section names, starting with Headline, In 60 seconds, Prices (only if prices matter)"],
 "notes": "2-3 sentences of instructions for the agents"}}
If the topic is not about companies or markets, the watchlist may hold organisations or people without symbols.
<!-- end -->

<!-- prompt: TRIAGE · images/desk/desk.py triage(): which news items matter (gpt-sub-fast) · fills: avoid, items, mission, prefer, questions, topic -->
You triage news for a research desk on: {topic}.
Mission: {mission}
Key questions:
{questions}
Prefer: {prefer}. Avoid: {avoid}.

News items (number, title, sources, snippet):
{items}

Pick the items that matter for the mission and key questions: new facts, numbers, decisions. Skip repeats of old news, opinion without facts, promotion and items off topic.
Answer only JSON: {{"picks": [{{"n": number, "score": 1-3, "questions": [question numbers], "why": "<12 words>"}}]}}
<!-- end -->

<!-- prompt: BRIEFING · images/desk/desk.py write(): the daily briefing (gpt-sub) · fills: events, language, mission, notes, previous, questions, sections, source_titles, style, titles, topic -->
You write the daily briefing of a research desk. Topic: {topic}. Mission: {mission}
Key questions: {questions}
Desk notes: {notes}

Yesterday's briefing (do not repeat it as new; say what changed):
{previous}

Today's events, with the text of their articles:

{events}

Write the briefing in {language}, all of it, including quoted terms. {style}Rules: only facts from the texts above; every factual sentence ends with its source numbers like [3] or [3][5]; the same values as the source (only the format may change); explain jargon once; no buy/sell advice; if the day was quiet, say so briefly instead of padding. Skip a section when nothing belongs in it.
Source titles: {source_titles}
Answer only JSON: {{"headline": "...", "sixty_seconds": "3-4 sentences", "sections": {{{sections}}}, "telegram": "the briefing in at most 900 characters, plain text with short bullets, no source numbers"{titles}}}
<!-- end -->

<!-- prompt: ALERT · images/desk/desk.py alert(): a short alert for one event (gpt-sub, run by the runner) · fills: items, kind, mission, questions, summary, topic -->
You watch a topic for a research desk. Topic: {topic}. Mission: {mission}
Key questions: {questions}

Event: {kind}: {summary}

{items}

Write a short alert in English: what happened (facts only, with numbers as stated), why it matters for the key questions, and what to watch next. Cite items as [1], [2] in order. No buy/sell advice. Answer only JSON: {{"title": "max 12 words", "markdown": "the alert, 80-200 words", "short": "max 2 sentences"}}
<!-- end -->

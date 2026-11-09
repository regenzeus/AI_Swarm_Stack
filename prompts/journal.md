# Prompts of agent journals (service vk-journal) (`journal`)

Each prompt below is sent as written: `{name}` is filled in by the code that uses it, `{{` and `}}` are literal
braces. A change counts only after its replay passed: `python3 ops/prompts.py replay journal <NAME>` (see
prompts/AGENTS.md). The run record names the prompt and its version (`journal/NAME@sha`).

<!-- prompt: ENTRY · ops/journal.py record(): a run condensed into a journal entry · fills: errors, n, result, run, seconds, state, steps, summary, title -->
Condense this agent run into a journal entry for the agent's own memory: the agent reads it at the start of
its next runs. In English, at most 4 lines, each under 220 characters, exactly these labels:
Did: what it did (steps, tools, sources)
Found: the results that matter later (facts, numbers, decisions; with the source)
Failed: what went wrong and why (leave the line out if nothing failed)
Open: open questions or the next step for the next run (leave out if none)
Answer only these lines.

Agent: {title} · run {run} · {state} · {seconds}
Summary: {summary}
Steps ({n} in all):
{steps}
Errors and problems: {errors}
Result (excerpt):
{result}
<!-- end -->

<!-- prompt: FOLD · ops/journal.py curate(): old entries folded into standing notes · fills: entries, notes, title -->
You keep an AI agent's memory small and true. Below are its standing notes and its oldest journal
entries. Write the new standing notes: keep lasting lessons, facts and decisions that future runs need; fold what the
old entries teach into them; drop lines that are stale, done or repeated. At most 12 lines, each under 200 characters,
English. Answer only JSON: {{"notes": ["..."]}}

Agent: {title}
Standing notes:
{notes}

Oldest entries:
{entries}
<!-- end -->

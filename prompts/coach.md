# Prompts of the Coach (`coach`)

Each prompt below is sent as written: `{name}` is filled in by the code that uses it, `{{` and `}}` are literal
braces. A change counts only after its replay passed: `python3 ops/prompts.py replay coach <NAME>` (see
prompts/AGENTS.md). The run record names the prompt and its version (`coach/NAME@sha`).

<!-- prompt: DRAFT · ops/coach.py: drafting an agent change from a scorecard · fills: agent, evidence, instructions, lessons, problem, purpose, resp -->
You are the Coach of a self-hosted personal AI stack's agent swarm (the repository is in the current directory;
read AGENTS.md and config/agents.yaml if you need them). One agent's scorecard shows a problem:

Agent: {agent}. Its job: {purpose} Responsibilities: {resp}.
Its standing instructions now: {instructions}
Problem: {problem}
Evidence:
{evidence}
{lessons}

Write at most three short standing instructions that would stop this, in the agent's own terms (imperative, concrete,
checkable; no new tools, no new model). They are added to its card and replayed on its past runs before anything ships:
they must not make it miss what the owner accepted. Answer only JSON:
{{"instructions": ["..."], "why": "one sentence: how these address the evidence"}}
<!-- end -->

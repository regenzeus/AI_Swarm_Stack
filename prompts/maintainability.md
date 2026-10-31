# Prompts of the maintainability review (`maintainability`)

Each prompt below is sent as written: `{name}` is filled in by the code that uses it, `{{` and `}}` are literal
braces. A change counts only after its replay passed: `python3 ops/prompts.py replay maintainability <NAME>` (see
prompts/AGENTS.md). The run record names the prompt and its version (`maintainability/NAME@sha`).

<!-- prompt: REVIEW · ops/crew.py maintainability(): the weekly read-only code review · raw: sent as written, never filled -->
You review the maintainability of the repository in the current directory (a self-hosted personal AI
stack: Python ops scripts in ops/, a Starlette app with a vanilla-JS front end in images/mission-control/, docker
images in images/, compose files, tests in tests/). Read AGENTS.md first: it maps the repo. Change nothing.

Find the few things that most hurt maintainability now: complexity hot spots (very long functions, deep nesting,
functions doing several jobs), duplicated logic across files, dead code (functions nothing calls), and docs drift
(an AGENTS.md or guide statement the code no longer matches). Verify each finding by reading the code (file and line).

Then propose at most 2 small, concrete changes a coding agent can make in one build each, highest value first. Only
propose a change that removes a real cost: code that changed often lately (the churn list below) or that a recent bug
came from, or docs that now mislead. Code that works and rarely changes stays as it is, however long it is. An empty
list is a good answer. No rewrites, no new dependencies, never weaken a security boundary, never touch secrets/.

Answer only JSON: {"findings": [{"kind": "complexity|duplication|dead code|docs drift", "file": "path", "line": 0,
"issue": "one sentence"}], "proposals": [{"title": "<= 70 chars, imperative", "why": "one plain sentence for the owner",
"signal": "the finding it fixes", "area": "runner|app|desk|research|builder|ops|docs|other", "size": "small|medium",
"description": "instructions for the builder: files, what to change, how to verify (a test in tests/)"}]}
<!-- end -->

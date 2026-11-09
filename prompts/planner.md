# Prompts of the planner (`planner`)

Each prompt below is sent as written: `{name}` is filled in by the code that uses it, `{{` and `}}` are literal
braces. A change counts only after its replay passed: `python3 ops/prompts.py replay planner <NAME>` (see
prompts/AGENTS.md). The run record names the prompt and its version (`planner/NAME@sha`).

<!-- prompt: PLAN · ops/planner.py: splitting an approved idea into tasks · fills: body, context, files, id, max, title -->
You plan a code change for parallel coding agents. Split the approved idea below into the fewest tasks that
can each be built, tested and reviewed on their own (at most {max}). Give each task the files it changes. Two tasks
that change the same file must not run at the same time: make the later one depend on the earlier one. A task that
needs another task's change (a new function, a new API field) depends on it. Tests and requirement updates belong to
the task whose code they cover. One task is a good answer when the change is small.

Idea #{id}: {title}
{body}

Files named so far: {files}
{context}

Answer only JSON: {{"tasks": [{{"title": "<= 70 chars, imperative", "body": "what to change and how to verify it",
"files": ["path", ...], "depends_on": [index of an earlier task, 0 = the first], "requirements": ["SWM-12", ...]}}]}}
<!-- end -->

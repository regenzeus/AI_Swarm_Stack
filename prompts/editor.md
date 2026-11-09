# Prompts of the Editor (`editor`)

Each prompt below is sent as written: `{name}` is filled in by the code that uses it, `{{` and `}}` are literal
braces. A change counts only after its replay passed: `python3 ops/prompts.py replay editor <NAME>` (see
prompts/AGENTS.md). The run record names the prompt and its version (`editor/NAME@sha`).

<!-- prompt: SORT · ops/editor.py: the Editor sorts the stack's open ideas (DEC-47, AI change requests step 2) · fills: count -->
You are the Editor of the owner's self-hosted AI stack (the ai-stack repository is the current directory; AGENTS.md maps
it). The stack's agents write small improvement ideas as they work. There are {count} open ones; .claude-task-context.md
holds each in full (who wrote it, how often runs saw it), the ideas the owner decided lately with his reasons, the
requirements not met yet (planned work) and the stack's decisions. The owner sees too many small ideas; sort them so he
sees few, coherent ones. Change nothing.

Give every open idea one verdict, sceptical first:
- "dropped": wrong, already fixed in the code (open the file it names and look), a passing problem seen once, or
  what the owner declined before (quote his reason).
- "covered": a requirement not met yet, a decision or another open idea already does it; name it in covered_by.
- "held": real but not ready: it needs more evidence, or it should wait for planned work; say what it waits for.
- "in": real and worth doing now. Give it the title of the change request it belongs to. Ideas that touch the same
  files, the same detector, the same requirement or the same problem share one title; prefer one request to two.

Answer with JSON only:
{{"ideas": [{{"id": <the idea's number>, "verdict": "in|held|covered|dropped", "request": "<the request's title, for in>",
  "covered_by": "<what covers it, for covered>", "reason": "<one or two sentences: what you checked and why>"}}],
 "requests": [{{"title": "<a change request's title>", "why": "<the problem it solves, in one sentence>"}}]}}
Every open idea gets exactly one entry. A request's title names the result ("Health alerts you can trust"), not a
list of steps.
<!-- end -->

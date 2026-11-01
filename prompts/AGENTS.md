# prompts/: every agent's prompts, one file per agent (MEM-11, DEC-33)

`<owner>.md` holds the prompts of one agent card (`prompts: prompts/<id>.md` on its card in config/agents.yaml), of
one service of that file (`journal`, `wikis`, `eval`) or, in `shared.md`, the templates several cards use. No agent
prompt lives in ops/ or a configure script any more; tests/test_prompts.py fails when one comes back.

## A prompt

```
<!-- prompt: NAME · where it is used · fills: a, b -->
the text, sent as written: {a} is filled in by the code, {{ and }} are literal braces
<!-- end -->
```

The desk (images/desk, `desk.md`) and the research scout (images/research: `scout.md` BRIEF, `guard.md` PRIVATE,
the privacy check of every question) read this folder through a read-only mount with their own copy of the section
pattern (tests/test_prompts.py keeps it equal); they log each version, the desk writes its calls to
/out/prompt-cases.jsonl, which ops/desk.sh keeps as cases (`ops/prompts.py keep`), and an alert hands its case to the
runner. A research call whose prompt file cannot be read is refused.

`· raw: sent as written, never filled` marks a text that is never filled (a Hermes SOUL text, or a prompt whose braces
are JSON). The code loads a prompt with `P.text(owner, NAME)` (ops/prompts.py); shell scripts with
`python3 ops/prompts.py render <owner> <NAME> fill=value ...`. The SOUL texts of Hermes main, mission and the Hermes
builder reach their configure scripts through ops/deploy.py (`SOUL_OF`), which re-runs a script when its prompts file
changes.

## Versions

A prompt's version is the first 12 hex digits of the sha256 of its text: `owner/NAME@sha`. Every send records it in the
run's record (a "Prompt" step), mission and crew runs carry their file's version in the manifest, and the card hash
(SWM-25) changes with the card's prompts file.

## Changing a prompt

Edit the text, then replay it before committing:

```
sops exec-env secrets/agent-keys.enc.yaml "python3 ops/prompts.py replay <owner> <NAME>"
```

The replay takes the prompt's last cases, 3 to 6 of them (live runs keep up to 12 per prompt in /srv/ai/state/prompt-cases, owner-only;
a prompt no run has used yet needs `prompts/cases/<owner>.<NAME>.json`, a list of `{"fills": {...}, "out": "..."}`;
an agent's standing brief, a raw system message, has cases with `"user": "the request"` and is replayed as a dry run that
names the tool calls it would make, as `prompts/cases/scout.BRIEF.json` does),
sends the last approved text and the new one to the agent's own model (Claude without tools in the builder sandbox,
ChatGPT through vk-eval), and lets a judge (`eval.md` JUDGE, gpt-sub) compare each pair in random order. It passes when
the new text gives a valid answer (JSON where the prompt asks for JSON) at least as often and the judge prefers the old
answer no more often than the new one. The result is appended to `replays.json`; commit it with the change.

`python3 ops/prompts.py check` (in ops/check.sh, so for every landing and every build) refuses a prompt whose text has
neither its first-record baseline nor a passed replay. A builder build that touches prompts/ also gets the "agents"
review lens and needs the owner's override.

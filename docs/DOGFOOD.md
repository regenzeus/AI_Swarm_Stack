# Dogfooding: the AI stack develops itself

2026-10-28. Claude (Claude Code, Opus) used the stack the way the owner does: it asked for changes through Mission
Control (a Hermes chat and `build_assign` requests), watched the builds, reviewed every diff, and sent work back
with **Request changes** instead of fixing it. It fixed only the **stack** where the stack was in the way. Approving
stays the owner's tap; none of these builds was approved by Claude.

## The builds

| # | Engine | Assignment | Result | Tokens | Verdict (mine / AI review) |
|---|---|---|---|---|---|
| 4 | ChatGPT (Hermes) | Home "Work" section: reviews, running builds, phone approvals, missions | 1st try: good, but made Home redraw fully during runs and changed the shared build row. After one change request: right. | 2.57 M (1st try) | Ready / fine to deploy |
| 5 | Claude Code | Tidy the AI-phone guide's "You stay in control" list | Right first time. Noticed a rule another session had just added and kept it in the right place. | 16.5 k, 7 turns, under 2 min | Ready / fine to deploy |
| 6 | ChatGPT (Hermes) | One-step Forgejo connect (now *Connect Forgejo* on the Code tab), like Claude Code's | Hit the ChatGPT usage limit; waits until 18:38 | n/a | pending |
| 7 | Claude Code | Switch a build to the other engine (the fix for #6's wait) | Hit the Claude limit twice (shared with the Claude sessions), resumed by itself after a runner restart. Complete and tested, but switching a *waiting* build would have wiped its unfinished work. Found by the AI review (fallback reviewer) and confirmed; sent back. | 36 k, 11 calls | Changes requested / improve first |

Assigned two ways: #4 by chatting with Hermes ("I want a build... please assign it"), #5–#7 as `build_assign` requests
the app sends. Hermes turned the chat request into a better assignment than the one written: it added "inspect the
state shapes first", "avoid unrelated changes" and explicit acceptance criteria.

## What worked

- **The pipeline holds**: branch, sandbox checks, CI, AI review, change requests, re-run checks. Nothing needed manual
  git work.
- **The AI review is a real second pair of eyes.** On #4 it found exactly the two problems Claude found in its own
  review (the Home redraw regression and the shared-row side effect), with file and line, plus a third small one.
- **Change requests work.** One precise, numbered feedback turned #4 into a clean result in 5 minutes.
- **Claude Code as builder is close to Claude-as-developer** on small, well-described tasks: right first time,
  minimal diff, honest summary (it said which checks it could not run and why).
- **ChatGPT's builder writes better tests than asked**: #4 executes the real rendering code with fake state in
  node, covers empty states, escaping and every verdict label.

## What failed or got in the way (ranked)

1. **The ChatGPT subscription is the bottleneck.** #4 took 2.57 M tokens for a 3-file change (it read the 1,600-line
   `app.js` again and again at high reasoning), and one more build hit the usage limit. That limit also stops
   Hermes chat and every ChatGPT review for hours.
2. **A runner restart lost a build.** Another session's deploy restarted the runner the second Claude finished #5;
   the build stayed "working" forever. (Fixed, below.)
3. **No review when the reviewer is at its limit.** #5 went to review with "HTTP 429" instead of a verdict.
   (Fixed, below.)
4. **Developing by chat stopped after step one.** Hermes could assign a build but could not read its review or diff,
   send it back, or re-run checks. (Fixed, below.)
5. **Claude Code shares the owner's Claude subscription with the Claude sessions.** With three parallel Claude
   sessions working, #7 hit the Claude usage limit after 11 calls and waited ~20 minutes. Both engines can be
   exhausted at once: plan heavy session work and heavy builds at different times.
6. **A waiting build can't move to the idle engine.** #6 waits 4 hours while Claude Code is free. (Given to the
   stack itself as #7.)
7. **The host runs out of memory** with three Claude sessions, the builder and the stack: Windows down to ~450 MB
   free, `wsl.exe` timing out (WSAETIMEDOUT) again and again. 32 GB RAM remains the top hardware item.
8. Claude Code's builder reported "yaml module not installed" for `ops/check.sh` although PyYAML is in the image
   (its shell probably doesn't use `/opt/tools/bin` first). The runner's own checks pass; worth a look.

## How the stack compares to Claude directly

- Small, precise tasks: Claude Code builder ≈ Claude directly, in minutes and at a fraction of the tokens.
- Medium UI work with ChatGPT: good structure and tests, but side effects beyond the brief and no sense of cost;
  needs one review round. Claude directly would have avoided the regression by reading `onState` first.
- What the stack can't do yet that Claude did here: notice and fix problems in the stack around the task (runner
  restarts, rate limits, missing tools). That still needs a human or Claude in the loop.
- Writing the assignment matters as much as the engine: numbered points, the files involved, "keep X as it is",
  and the test to add.

## Stack fixes made during this session

- `f682198` **Develop by chat**: Hermes tools `build_details` (assignment, summary, files, checks, CI, every AI-review
  finding, optional diff), `build_request_changes`, `build_recheck`; `builds_overview` shows the AI verdict. Builder
  prompt: read big files by symbol or line range, not whole, to save tokens.
- `f682198` **Builds survive runner restarts**: a "working" build resumes after a restart; an interrupted deploy is
  marked failed instead of repeated. (#5 resumed by itself.)
- `225b995` **Review fallback**: when the reviewer engine is at its limit, the builder's engine reviews, marked "less
  independent" on the build page. (#5 got its review this way.)

## Still proposed

- Route by cost: small or UI tasks to Claude Code by default while ChatGPT is near its limit (`build_assign` could
  pick the engine from the usage state and say why).
- Show the token cost per build on the build page and in `builds_overview`, so expensive patterns become visible.
- A "deploy queue" lock for every session that deploys (the parallel sessions used `~/.aistack-land.lock` by
  convention; `ops/deploy.py` itself could take it).
- Builder check environment for Claude Code: make `ops/check.sh` find the tools regardless of the shell's PATH.

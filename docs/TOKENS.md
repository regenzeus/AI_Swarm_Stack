# Where the tokens go, and what was cut

2026-10-28. Measured with the run timelines (`ops/telemetry.py`), LiteLLM's spend logs and Hermes' session records.
The ChatGPT Plus limit is a 5-hour window; every token the stack sends counts against it, cached input cheaper.

## Before

**Gamma Metals analysis (run 8, deep research):** 161 model calls, 2.44 M input tokens, 0.85 M of them cached (35 %),
26 k output. The scout (research) made 119 of the calls and 1.83 M of the input (75 %).

**Fixed cost of every call** (system prompt + tool definitions, sent again on each call):

| Profile | System prompt | Tool definitions | Per call |
|---|---|---|---|
| scout | ~4.1 k (skills index 1.4 k) | ~2.9 k, 15 tools (`skill_manage` alone 0.9 k) | ~7 k |
| mission | ~4.8 k (skills index 1.4 k) | ~5.1 k, 15 tools (`session_search` 1 k, `clarify` 0.5 k) | ~9.9 k |

**Context growth:** every tool result stays in the conversation and is sent again with every later call of that
session. Scout sessions grew from 7 k to 33 k per call. The biggest results in run 8:

| Tool | Calls | Result size (characters) |
|---|---|---|
| `web_search` (scout) | 56 | 283 k |
| `skill_view` (scout + mission) | 20 | 214 k, up to 14 k each |
| `fetch` (scout) | 33 | 127 k |
| `skills_list` | 11 | 46 k |
| `session_search` (mission) | 2 | 35 k |

Skills were the largest waste: the agents read whole skill documents they did not need, early in a session, and
paid for them again on every following call.

**Caching:** cached hits came in bursts (0, 6.5 k, 0, 0, 15 k …) although every call of a session starts with the
same 7-10 k tokens. Cause: LiteLLM gives each ChatGPT request without a session id its own call id as `session_id`
(`llms/chatgpt/common_utils.py`), and the backend routes its prompt cache by it, so consecutive calls of one
conversation landed in different caches. `prompt_cache_key`, which Codex sends, is filtered out by LiteLLM's
ChatGPT transform.

**Builds, counted the same way:** the earlier "150 times more" compared unequal numbers. Claude Code builds were
counted without cache reads. Build #5 (Claude Code, 8 turns) really used about 171 k input, 90 % from cache, plus
2 k output (shown as 16.7 k). Build #4 (ChatGPT) used 0.75 M after one change request, 2.57 M on its first try, with
little cache. The real gap is 4-15×, and most of it is the cache rate (90 % vs ~35 %) plus the skills and the
reading habits above.

## Changes

- **Gateway: one cache per conversation** (`images/litellm/cache_affinity.py`, LiteLLM callback). A request without
  a session id gets a stable one: hash of key, system prompt and first user message. Every call of one agent run
  now shares one cache; clients that send their own id keep it.
- **Optional `prompt_cache_key`** (`images/litellm/patch_cache_key.py`): passes the same id the way Codex does. Off
  until the probe below shows the backend accepts it (`CHATGPT_PROMPT_CACHE_KEY=1` in the LiteLLM service env).
- **Lean profiles** (`config/hermes/configure-*.sh`): scout = search + page reader only (no skills, no todo); mission
  = vault + research + todo (no skills, no clarify: an unattended run has nobody to answer, no session search);
  builder = no skills. MCP prompt/resource helper tools off for scout and mission. The main chat profile keeps
  everything. Expected per call: scout ~7 k → ~4 k, mission ~9.9 k → ~5.5 k, before any growth; the skill reads
  (214 k + 46 k characters in run 8) disappear.
- **Honest build counts:** both engines now count all input including cached, and the build page and
  `builds_overview` show the cached share.

## Measuring after

- `ops/token_probe.py` (8 small calls): A) one growing conversation without a session id → cached tokens on calls
  2-3 if the hook works; B) a new random id per call (the old behaviour) for comparison; C) whether a reasoning
  summary comes back. Result in `/srv/ai/state/token-probe.json`. Scheduled once after the limit reset.
- The next real mission run (the RAM mission retries by itself): open its Timeline. The warning "no prompt caching"
  should be gone, the cached share well above 35 %, and no `skill_view`/`skills_list` calls.

## Thinking

ChatGPT's reasoning arrives as encrypted content (`reasoning.encrypted_content`, which LiteLLM requests so reasoning
can continue across turns), not as text, and Hermes stores nothing in its reasoning columns. Whether the backend
returns a readable summary through LiteLLM's chat bridge is what probe C tests. If it does, Hermes' provider call
needs to ask for it; if it doesn't, thinking stays invisible for ChatGPT runs (Claude Code builds show theirs).

## Still open

- Results: cap page-reader output (`max_length` 20 k characters today) and web-search results for the scout.
- The scout re-searches what the mission already found: pass the mission's findings into each research question.
- Builder: big files are still read whole sometimes; check Serena use in the builder's steps per build.

# Spike: Phoenix as the interim scorer and the base of evaluation (stage 0)

*11 Nov 2026. Branch `spike/eval`, code in [spikes/eval/](../../spikes/eval/AGENTS.md). Design: PLATFORM-DESIGN.md §5 D5,
§8 and §13 (the scorer row).*

## The question

Can Phoenix (self-hosted, the stack's pinned `arize-phoenix` image, a throwaway container) hold test sets, run
experiments and a calibrated LLM judge well enough that it is

- **(a) the interim scorer** the work side can use right away for its exams, and
- **(b) the base of stage 6's evaluation**, with Langfuse as the named fallback?

## Verdict

**Yes, Phoenix holds; Langfuse is not needed.** A made-up exam set went in as a Phoenix dataset, a written rubric ran as
a phoenix-evals evaluator through the stack's gateway, and every scoring is a Phoenix experiment with each case's
verdict and reason, compared side by side. Against labels written before the judge ran, the judge agreed on 68 of 72
judgements with gpt-sub-fast (four runs of 18 cases, 94%) and 16 of 18 with gpt-sub; it **never passed a case that
should fail**. On 25 of the frozen benchmark's judged answers it agreed with the old benchmark judge 25 of 25. With the
settings below, Phoenix made no outbound connection in 1,161 one-second samples over the runs. The work side can use
it today (usage at the end); stage 6 grows it, as §13 says.

## What exists today (the stack's exams and scorers)

| Exam or scorer | Where | How it scores | What it becomes |
|---|---|---|---|
| The frozen benchmark | `eval/bench-v1.yaml`, `eval/bench.py` | regexes plus a one-line PASS/FAIL rubric judge (gpt-sub-fast) for 13 of 40 cases; results as JSON files in `eval/results/` | a Phoenix dataset with the rubric judge as its evaluator (done here for a handful of its judged answers) |
| The replay exam | `ops/replay.py`, keys in the private trials folder | a program: the hidden tests of the real commit, regressions | stays a program; its scores can be logged as Phoenix evaluations |
| Trials | `eval/trials/*.yaml`, private `score.py` per key | a program per trial | as the replay exam |
| Agent-change experiments | `ops/evals.py` | TF-IDF and rule scores; already mirrors replay sets to Phoenix datasets and experiments over the REST API | the same, through Phoenix's own client |
| Plan and task judges | `ops/staffing.py` (points met or not), `ops/memwrite.py`, `ops/memory_review.py` | one model call per rubric, its own prompt and parser each | one rubric judge kind (this spike's) |

None of them is calibrated against a person's labels, and none keeps its results where they can be compared over time
except the benchmark's JSON files. That is the gap D5 and §8 close.

## What was built

All under `spikes/eval/`, 581 lines with the 247-line made-up set.

- **`change-requests.yaml`**: 18 made-up change requests on four invented repositories, each with the expected outcome
  stated so it can be checked, a made-up result of a run (summary, test evidence, diff stat), and my own verdict
  (`label`, `why`) written **before** the judge ran: 9 pass, 9 fail. The fails cover the ways a change goes wrong in
  the stack's own record: a part missing, a different rule (half up for half even), a kept default changed, tests
  deleted to get green, tests written but never run, a run that stopped blocked, an extra that breaks a stated part.
  Two passes test that the judge is not pedantic: a harmless private rename, and a result reported in German.
- **`rubric.md`**: the judge's rubric and prompt. Pass only when every part of the expected outcome is achieved and shown
  by evidence that ran; fail otherwise, naming the part that decided it.
- **`exam.py`**: the scorer, on Phoenix's own client and evals packages (no REST code of ours).
  - `run <set>` puts the set into Phoenix as dataset `exam-<name>-<hash of the file>` (reused when present, so every
    run of the same set lands on the same dataset and compares there), runs one **experiment** whose output per case is
    the result to judge (from `--results`, or the case's own `result`), and judges each output with a phoenix-evals
    **classifier evaluator** (`judge`: label pass or fail, score, explanation). Where cases carry a person's label, a
    second evaluator `agrees_with_label` scores the judge against it, and the summary prints agreement, Cohen's kappa
    and the confusion counts.
  - `from-bench` turns the frozen benchmark's judged answers into a set, labelled with the benchmark judge's verdict.
- **`run.sh`**: runs `exam.py` in a throwaway container (python:3.12-slim by digest, the 46 packages of
  `requirements.txt` pinned). The gateway key comes from the environment by name (`sops exec-env`), never from the
  command line, and is never printed.
- **`phoenix.sh`, `phoenix-onsite.env`**: the spike's Phoenix, the stack's own pinned image
  (`arizephoenix/phoenix:version-20.26.0`, digest `095f4987…`) on its own network `spike-eval-net`, port
  127.0.0.1:16006 only, with the on-site settings below.

## How it was run

```
sh spikes/eval/phoenix.sh start                     # throwaway Phoenix, on-site settings
cd ~/ai-stack && sops exec-env secrets/agent-keys.enc.yaml \
  'cd ~/wt/spike-eval && PHOENIX_BASE_URL=http://127.0.0.1:16006 sh spikes/eval/run.sh run spikes/eval/change-requests.yaml'
```

The judge's model went through the live LiteLLM gateway (127.0.0.1:4000, OpenAI-compatible) on the existing `vk-eval`
virtual key (`VK_EVAL`, the key `ops/evals.py` uses for replays; models gpt-sub and gpt-sub-fast on the ChatGPT
subscription). Nothing of the live stack was changed.

## Measured results

Every number below comes from `run.sh run ... --json` (the output kept outside git) or from Phoenix's own export of the
experiment (`GET /v1/experiments/<id>/json`). The WSL machine restarted once during the runs (not caused by this spike;
other spikes ran kill tests at the time); Phoenix's container came back with all its experiments, and the two runs
whose JSON output was lost were read back from Phoenix.

### Calibration on the made-up set (18 cases, labels written before any run)

| Run | Model | Judge says pass | Agrees with the person | Kappa | Person pass, judge fail | Person fail, judge pass |
|---|---|---|---|---|---|---|
| 1 (Phoenix experiment 1) | gpt-sub-fast | 7 | 16 of 18 | 0.778 | 2 (cr-01, cr-06) | 0 |
| 2 (experiment 2, read back) | gpt-sub-fast | 9 | 18 of 18 | 1.0 | 0 | 0 |
| 3 (experiment 3) | gpt-sub-fast | 8 | 17 of 18 | 0.889 | 1 (cr-06) | 0 |
| 4 (experiment 4) | gpt-sub-fast | 8 | 17 of 18 | 0.889 | 1 (cr-06) | 0 |
| 5 (experiment 5) | gpt-sub | 7 | 16 of 18 | 0.778 | 2 (cr-01, cr-06) | 0 |

- **gpt-sub-fast over four runs: 68 of 72 agree (94%); confusion person/judge: pass/pass 32, pass/fail 4,
  fail/pass 0, fail/fail 36.** All 9 fails were caught in every run, including the subtle ones (half up for half even,
  a default changed while doing the asked thing, accents ignored as an "improvement", tests deleted, tests not run).
  The harmless-extra case (cr-15) and the report in German (cr-17) passed in every run.
- **Stability:** 16 of 18 cases got the same verdict in all four runs. cr-01 was failed once of four, cr-06 three times
  of four.
- **The two disagreements, adjudicated:** on re-reading, the judge is right both times. cr-01's result never says that
  `tasklist list` shows the due date (only that it sorts), and cr-06's never says the exit code is 0; the outcome asks
  for both, and rule 2 asks for evidence. I had filled the gap by assumption. Against the adjudicated labels, gpt-sub
  agrees 18 of 18 and gpt-sub-fast still 68 of 72 (its runs 2 to 4 passed cr-01, run 2 cr-06 too). The file in git keeps the labels as first written, so its hash and these
  runs stay reproducible; a site's own set should fix such labels after adjudication.
- **Time:** 195 to 234 seconds for 18 cases per run end to end, including the container's package install, at a load
  average of 20 to 29 on the machine (about 3 seconds per judge call when the machine was quiet).
- **Cost:** none counted; both models are on the ChatGPT subscription through `vk-eval`.

### The benchmark's judged answers (a handful of an existing exam)

`exam.py from-bench` built 25 cases from four result files of `eval/bench-v1.yaml` (13 rubric cases of the baseline and
the 12 rubric answers of three later runs, among them 7 the benchmark judge failed). The set was put into this
Phoenix only (dataset `exam-bench-v1-judged-f45ac729ad`), never into git.

| Run | Model | Pass | Agrees with the benchmark judge | Kappa |
|---|---|---|---|---|
| Phoenix experiment 6 | gpt-sub-fast | 18 of 25 | 25 of 25 | 1.0 |

These labels are the old judge's (gpt-sub-fast with a one-line prompt), not a person's: this shows the new judge
reproduces the old scorer on its own cases (answers in German and English), not that both are right.

### In Phoenix

The dataset page lists every experiment with its mean `judge` and `agrees_with_label` scores and its metadata (model,
rubric hash, set). The compare view shows per case the input (request and expected outcome), the reference (the
person's label and why), the result, and both evaluations with their explanations; experiments of the same set sit
side by side. Checked in the browser on the spike's Phoenix.

## What the gateway does (a finding for every judge on it)

phoenix-evals asks a model for a structured answer by **JSON response format** first and falls back to a **tool call**
only when the provider rejects the format. The gateway has `drop_params: true` (`config/litellm/config.yaml`), so it
silently drops `response_format` for the subscription models, which then answer plain text (`pass`) and the parse
fails. Measured with one probe per mode on both models: JSON schema, plain text back; JSON object, plain text back;
tool call, a correct `{"label": ..., "explanation": ...}`. The fix is Phoenix's own documented path, no patch: giving
the labels descriptions (`choices={"pass": (1.0, "..."), ...}`) makes the classifier use a tool call. Stage 1 should
either keep that or let the gateway refuse unsupported parameters for judge keys, so a dropped format fails loudly.

## Data class: what keeps it on the site

The pinned Phoenix 20.26.0 has, **on by default**, an in-app **agent assistant** with **web search and fetch,
server-side bash and GitHub's hosted MCP tools**, code sandboxes that include hosted providers (E2B, Daytona, Vercel,
Modal), web fonts and usage pixels. Its start banner on the live stack today shows the assistant, web access, bash and
GitHub tools enabled; the core sets only `PHOENIX_TELEMETRY_ENABLED=false`. An assistant that reads traces and can
reach the web does not fit a customer data class.

The settings, read from Phoenix's own `config.py` in the pinned image and all in `spikes/eval/phoenix-onsite.env`:

| Setting | Effect |
|---|---|
| `PHOENIX_TELEMETRY_ENABLED=false` | no FullStory or Scarf pixels |
| `PHOENIX_ALLOW_EXTERNAL_RESOURCES=false` | Phoenix makes no public-internet request on its own (fonts, telemetry, WASM download) |
| `PHOENIX_DISABLE_AGENT_ASSISTANT=true` | the assistant (`/chat`) is off for the whole deployment |
| `PHOENIX_AGENTS_DISABLE_WEB_ACCESS`, `_BASH`, `_GITHUB` `=true` | its tools off too, in case it is switched back on |
| `PHOENIX_ALLOWED_SANDBOX_PROVIDERS=NONE` | no code sandboxes, hosted or local |
| `PHOENIX_ALLOWED_PROVIDERS=OPENAI` | the playground offers only an OpenAI-compatible provider (the site's gateway) |
| unset: `PHOENIX_COLLECTOR_ENDPOINT`, `PHOENIX_AGENTS_COLLECTOR_ENDPOINT` | no remote export |

What was seen with them:

- the start banner: assistant, web access, bash, GitHub tools and telemetry all "Disabled", remote export "Disabled";
- the page the browser gets (`GET /`): `allowExternalResources: false`, `agentAssistantDisabled: true`,
  `agentBashDisabled: true`; the only external address in it is the `og:image` link preview, which a browser does not
  fetch;
- Phoenix's own network namespace, sampled once a second from inside its container (`/proc/net/tcp` and `tcp6`, every
  connection that is not inbound to its ports 6006 and 4317) for the whole of experiments 3 to 6:
  **1,161 samples, 0 outbound connections**. A connection shorter than a second can slip between samples; the settings
  above are the guarantee, the sampling the check;
- the scorer's container is told two addresses, both from its environment: `PHOENIX_BASE_URL` and `LITELLM_BASE_URL`.
  Its own traffic was not sampled (it shares the host's network to reach the gateway); that its packages send nothing
  else is read from their configuration, not measured.

At work, the same file goes into the work deployment's Phoenix, its model gateway is the company's (already the
`example-work` pattern), and Phoenix stays behind the app's gate with no port of its own.

## Usage for the work side (the interim scorer, today)

1. **Phoenix**: the core's Phoenix of the work deployment, with the settings of `phoenix-onsite.env` added to its
   environment (one compose change, see "What the lead must do").
2. **A set**, kept on the site (never in git): a YAML file like `change-requests.yaml`, one case per item with `id`,
   `request`, `expected_outcome` (written so a reader can check it), and for calibration `label` and `why`.
3. **The results** of the exam's run, one JSON line per case: `{"id": "cr-07", "result": "<the run's report: summary,
   tests run and their output, diff stat>"}`.
4. **Score:**

   ```
   cd ~/ai-stack && sops exec-env secrets/agent-keys.enc.yaml \
     'sh spikes/eval/run.sh run <set.yaml> --results <results.jsonl> --name "<what ran: version, arm>"'
   ```

   It prints one line per case (verdict, and the reason naming the part that decided it), "N of M pass", and the
   experiment's address in Phoenix, where every case shows its input, the person's label, the result, the judge's
   verdict and explanation, and runs of the same set compare side by side. `--json` prints the same as JSON for a
   program. Exit 0 when every case got a verdict, 1 when one could not be judged (a gateway error: that case is not a
   fail and must be rerun).
5. **Calibrate first:** label 15 to 20 of the site's own cases by hand, run them, and read every disagreement. Trust the
   judge for that kind of exam only at the agreement this spike reached or better; otherwise fix the rubric (or the
   cases) and run again.

`stack exam run <set> [--results R]` is a thin wrapper over step 4: the same arguments, the site's Phoenix and gateway
from the deployment.

## What stage 1 takes from it

- **Do now, before stage 1:** add the settings of `phoenix-onsite.env` to the core's Phoenix (`compose/core.yaml`). The
  live Phoenix runs the agent assistant with web access, server-side bash and GitHub tools today. For the work
  deployment this is a precondition of its data class.
- **The scorer as a platform command:** `stack exam run <set>` over this `exam.py`, in a tools image with
  `requirements.txt` baked in (no install per run), the site's Phoenix and gateway from the deployment. Sets live in a
  factory pack's `evals/` (made-up ones in git, real ones only in the site's Phoenix, referenced by name).
- **One judge kind:** the rubric judge replaces the per-feature judges (benchmark, plan points, memory rubric) one by
  one, each calibrated on its own labelled cases before it is trusted (§8).
- **Repeat and flag:** judge each case three times and report a case whose verdicts differ as "unsure" instead of a
  verdict; here that was 2 of 18 cases, and both were evidence gaps a person should look at.
- **The judge's key:** its own virtual key (`vk-judge`) rather than `vk-eval`, and either keep labelled choices (tool
  calls) or have the gateway refuse an unsupported `response_format` for that key instead of dropping it.
- **Phoenix on Postgres** (D2, `PHOENIX_SQL_DATABASE_URL`), and Phoenix's upgrades tested with the calibration set: it
  moved from 20.22 to 21.0 in two weeks, and its client is at 3.x. Pin both, as here.
- `ops/evals.py`'s own REST calls to Phoenix can move to Phoenix's client, as `exam.py` uses it.

## What was not tested

- **Langfuse.** Not run; the verdict is that Phoenix did everything asked, not that Langfuse is worse.
- A person labelling **in Phoenix's UI** (annotations on experiment runs) and the owner's thumbs from the app as labels:
  here labels live in the dataset's reference output. Stage 6 needs the annotation path.
- **Real exam cases** of the work side, and real results of the stack's change runs: only made-up ones and the
  benchmark's answers.
- Phoenix on **Postgres** (design D2): the spike used Phoenix's default SQLite in the container.
- Server-side evaluators configured in Phoenix's UI (Phoenix 20 has them); the judge here runs in the client.
- **Prompt versions** in Phoenix (the rubric is a file in git here) and the gate reading a verdict (§7).
- Phoenix with **authentication** on: the spike's Phoenix had none (127.0.0.1 only); at work it sits behind the app's gate.
- Scale: 18 and 25 cases; nothing about thousands of examples or many parallel experiments.

## Checks

On the branch: `ops/req.py check` (816 requirements, 0 problems), `ops/limits.py check` (225 limits, 0 problems),
`ops/truncation.py check`, the ruff line of `ops/check.sh`, shellcheck on the spike's scripts, and the full suite in the
builder image: 1,880 passed, 1 skipped.

## Containers

The spike's containers (`spike-eval-phoenix`, the `spike-eval-exam-*` runs, which remove themselves) and its network
`spike-eval-net` were removed at the end (`sh spikes/eval/phoenix.sh stop`).

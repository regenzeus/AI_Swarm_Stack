# The `stack` command line and the stack MCP tools (WAY-01 to WAY-08)

Phase A of the factory design (11 Nov 2026): all work is a workflow run, people act through Asks, and an agent on a
site (a Claude Code session working there, or the stack's own assistant) works through the system instead of around it.
Before this, an agent on a site had no way in except editing files and running scripts.

| Part | File |
|---|---|
| The command | `ops/stack_cli.py` (installed as `~/.local/bin/stack` by `python3 ops/stack_cli.py install`) |
| The app's side | `images/mission-control/server.stack.py`: the command line's rule in `/api/request`, the reads under `/api/stack/`, the MCP server `stack` (port 8100) |
| The runner's side | `ops/stack_requests.py`: `workflow_run`, `pack_ask`, `stack_doctor` |
| A gate's refusal | `ops/asks.py` `_not_gate`: an answer, a dismissal or a later by `cli` or `mcp` at a gate is refused |

## Commands

```
stack workflows                          every workflow: its trigger, on or off, its agents, its last run
stack agents                             every agent and the workflows that have a step with it
stack runs [--workflow W] [--status S]   the newest runs, newest first (S: running, waiting, done, failed)
stack run <workflow> [--input k=v ...]   start a run now through its Run now trigger; its id once its first step reports
stack run show <id>                      one run: its steps, the Asks it waits on, its place in n8n
stack asks [--all]                       the open Asks (Needs you); --all: the put-off ones too
stack answer <ask> <choice|"words">      answer an Ask that is no gate; a gate is refused with the reason
stack pack approve <pack> <commit>       ask for a pack commit's approval: a gate Ask a person taps in the app
stack doctor                             what keeps this site from running as its deployment says (exit 1)
stack install                            put the command at ~/.local/bin/stack
```

Human-readable by default; `--json` prints what the app answered, for agents. Exit 0 when it did what was asked, 1 when
it was refused or failed (the reason on stderr; with `--json` also `{"ok": false, "error": ...}` on stdout), 2 for a
command it does not know. An Ask is named by its id or its first four or more characters; a workflow by its file name,
its n8n id or its name, in any case.

## How it talks to the site

- **The same API as the app.** It calls the app on this machine (`STACK_URL`, default `http://127.0.0.1:8090`, the
  app's published port: the path the owner's browser takes, so the trust boundary of SEC-24 holds). Reads are
  `GET /api/stack/workflows`, `/runs`, `/run/<id>`, `/agents` and `/asks`, shaped from the same files the app's pages
  read (`public/workflows-runs.json`, `public/step-catalog.json`, the Asks in `state.json`). Actions are
  `POST /api/request`, into the runner's inbox, as every action of the app.
- **It names itself.** Every call carries `X-Aistack-Via: cli`. The header only takes rights away: `/api/request` then
  takes only `workflow_run`, `ask_answer` (with a `reply`, never a standing rule) and `pack_ask`, and refuses everything
  else with the reason (approvals, deploys, purchases, standing rules, the stop switch, builds). The runner gets the
  request with `source: cli, via: cli`; a `via` in the body is never believed.
- **Who.** The person is the sign-in, as for the app: the login the command line sends (`STACK_OPERATOR` in the
  environment or the deployment's `deployment.env`, else `operator@this-pc`) behind the tailnet gate, or the local
  gate's owner (`APP_GATE=local`). The deployment's roles decide what that login may answer (ASK-04).
- **A gate is a tap.** `ops/asks.py` refuses any answer, dismissal or later that comes by `cli` or `mcp` at a gate; the
  app refuses it before it reaches the runner, with the role that answers it. A private Ask shows no figure through the
  command line or the tools and is answered in the app (ASK-07).
- **The trust boundary.** A program on this PC that leaves the header out, or writes into the runner's inbox, is the
  accepted local-spoofing risk of `docs/SECURITY.md`: anything that can do that can read the files directly. The
  command line is the honest way in, not a new boundary.

## Starting a run

`workflow_run` finds the workflow among the deployment's (`ops/n8n_jobs.py`) and the running packs', checks the stop
switch (ASK-08), that it is switched on and that it has a Run now trigger (a Webhook named Run now, or at `run/...`,
WFL-13), and posts to `http://127.0.0.1:5678/webhook/<path>` with the runner's header `X-Aistack-Hook` (SEC-27) and the
body `{"input": {name: value}, "by": <login>, "via": "cli" | "mcp"}`. A workflow reads its inputs from the webhook's
body (`$json.body.input`). The activity says who started it and how. n8n answers a webhook before the run has an id, so
the command waits up to 30 s for the run to show in the runner's view (its first step reports) and names it.

## Asking for a pack's approval

`pack_ask` checks out the commit (`ops/domain/packs.py`, read-only, refused when it is not in the pack's repository or
the pack is not in `packs.txt`), and says so when it is approved or refused already, or when the pinned commit's own Ask
from the decision queue waits. Otherwise it opens one gate Ask of the kind `pack-commit` (a security floor,
`config/autonomy.yaml`) with what the commit brings, Approve (its act: `pack_approve` as the person who tapped it),
Not now, and Look (the Stack page). The command line and the tools never send `pack_approve` themselves.

## The doctor

`stack doctor` runs the site's doctor, `python3 ops/deployment.py doctor` (P3 of phase A: missing or unapproved packs,
untagged workflows, a dead runner, workflows not imported). On a site that does not have it yet, it runs the checks
there are and says so: `python3 ops/deployment.py check` (the deployment's values), and through the app the runner's
state and the packs that wait for approval or were refused. Exit 1 when anything is wrong. The tool `stack_doctor`
asks the runner, which runs the same doctor without the app's part.

## The MCP tools (server `stack`, port 8100)

`stack_workflows`, `stack_agents`, `stack_runs`, `stack_run_show`, `stack_run`, `stack_asks`, `stack_answer`,
`stack_pack_approve`, `stack_doctor`: the same reads and actions for agents, through LiteLLM's MCP gateway. The server
answers only LiteLLM with its own token `MCP_TOKEN_STACK` (SEC-26), and a key gets it by its grant in `ops/keys.sh`
(today `vk-main`, the owner's assistant). Its requests reach the runner as `source: mcp, via: mcp` by the login
`stack-agents`; at home every role is the owner's, so the assistant may answer an Ask that is no gate, and a work
site's roles file decides.

## Landing (the lead's steps)

1. `make trust-keys` makes `MCP_TOKEN_STACK` once (the other tokens are kept).
2. Land; the deploy recreates LiteLLM (its config and environment) and the app (port 8100), and the runner restarts.
3. Grant the existing key: `sops exec-env secrets/secrets.enc.yaml 'sops exec-env secrets/agent-keys.enc.yaml "python3 ops/update-keys.py"'`
   (`ops/keys.sh` creates only missing keys).
4. Put the command in place: `python3 ops/stack_cli.py install` (the deploy is to run it on every site).

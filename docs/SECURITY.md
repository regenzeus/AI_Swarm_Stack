# Security model

One owner, one PC, reachable only over the tailnet. The main threat is not an outside attacker but **prompt
injection**: untrusted text (web pages, news, filings, uploaded documents) steering an agent into leaking private
data or doing damage. The design keeps the "lethal trifecta" (untrusted input + private data + a way out) apart.

## Boundaries

| Boundary | Enforcement |
|---|---|
| Network exposure | All UIs bind 127.0.0.1; `tailscale serve` (tailnet only, no funnel). No router port forwarding. |
| App auth | One sign-in: the `Tailscale-User-Login` header that `tailscale serve` adds for your devices. Mission Control checks it itself, Open WebUI trusts it (`WEBUI_AUTH_TRUSTED_EMAIL_HEADER`), and the Hermes dashboard and the code map sit behind gates that require it (`config/gate`); OpenCode and Phoenix have no login (tailnet only). Forgejo on the NAS keeps its own accounts. |
| Model spend | No paid model is configured in LiteLLM; every agent key lists subscription models only (paid model → HTTP 403). |
| Per-agent rights | One LiteLLM virtual key per agent with its own model list, daily budget and MCP grants (`ops/keys.sh`). |
| Web content | Only the `scout` profile reads the web; questions pass a privacy guard (patterns, private-terms list, model check, fail-closed); pages are read by `fetch` in an isolated network with an egress firewall (no LAN, no Tailscale ranges). Results are labelled untrusted. The federal job board's search (`jobs`, MIS-21) runs in the same container as the same user; only search words, a place and a radius leave the house, and only `vk-scout` holds it. |
| Code execution (Claude engine) | For Claude Code builds the runner passes `CLAUDE_CODE_OAUTH_TOKEN` into the builder for that one run (`docker exec -e`); the builder's own proxy (`pkgproxy-builder`) allows npm, PyPI and `api.anthropic.com` only. OpenCode's proxy is unchanged. |
| Code execution | Only the `builder` has a shell, inside its own container: sees `/work` only, no vault, secrets, SSH keys or Docker socket; networks: LiteLLM + npm/PyPI proxy. It cannot push or deploy. |
| Deploys | Only the host runner merges and deploys, and only after the owner taps Approve; smoke test + automatic rollback. |
| Secrets | sops + age; decrypted into a process environment per command (`make`, systemd units), never written to disk or printed. Age key copies: NAS, `F:\AI-backup`, OneDrive (separate folder). |
| Requests from the app / chat | The runner validates every request (allow-listed actions, slugs, schedules, sizes); e-mail goes only to the owner's address. |

### n8n, the step service and the frames (as built on 11 Nov 2026)

The review of 10 Nov 2026 found the workflow pillar missing from this model and the app owner-equivalent to anything on
its networks (O1-O4 in [REVIEW-2026-11-10.md](REVIEW-2026-11-10.md)). This is the boundary built for it (SEC-24 to
SEC-28). The app-side refusals start in **log mode**: they refuse nothing and log what they would refuse, until the lead
switches them on (below).

| Part | What holds it |
|---|---|
| The app's port 8090 (SEC-24) | Answers only what comes through its published port, the path the owner's browser takes (tailscale serve → Windows' `127.0.0.1:8090` → wslrelay → WSL's `127.0.0.1:8090` → Docker's published port). The identity header (or the local gate's loopback host) of any other peer is never believed: in `on` mode such a request is refused whole (403). The rule is the gateway of the app's default route, read from its own route table (`server.trust.py`). |
| The MCP servers 8091, 8092, 8094, 8096, 8097, 8098, 8100 (SEC-26) | Answer only LiteLLM (Docker's DNS names the peer: `litellm` resolves to it, or its address is `<project>-litellm-<n>`) with the server's own bearer token (`MCP_TOKEN_<SERVER>`, sops), which LiteLLM sends (`auth_type: bearer_token` in `config/litellm`). They still listen on every network of the app: Docker numbers its networks when it makes them, and binding to one address would need LiteLLM up before the app; the refusal by peer and token is the same boundary one layer up. |
| The step service (`server.flows.py`, :8099, SEC-25) | Only on `stepnet` (n8n and the app), only the Host `mission-control`, and only with its token (`AISTACK_STEP_TOKEN`, sops), which the AI Stack step node sends from n8n's environment. It stays in the app's process: a container of its own would not take n8n off the app's networks (the editor inside the app needs `stepnet`), so the peer rule and the token are the boundary; what remains is that a fault in the step service is a fault in the owner's API process. |
| n8n's webhooks (SEC-27) | Every Webhook trigger (Run now `run/<stem>`, the items' `item/<...>`, the inbox, the self-test, a pack's) takes only a call with the runner's header `X-Aistack-Hook` (n8n's Header Auth credential "AI Stack runner", written by every import from the secret `N8N_HOOK_TOKEN`); the runner and the tracker poller send it. An import without the secret stops before it changes anything. n8n's resume links (`/webhook-waiting/...`) are signed by n8n itself. |
| n8n's networks and ports (SEC-27) | `n8ndb` (its database in Postgres, internal), `flows` (the integrations it is given) and `stepnet` (the step service); no longer the flat `backend` with the builder's sandbox. Its port 5678 is on 127.0.0.1 for the runner; the tailnet port 8450 serves only `/webhook-waiting` (`ops/windows/host-setup.ps1`); the editor is inside the app behind its gate. |
| n8n itself (SEC-28) | Pinned by digest; read-only root (`/tmp` and its compile cache in memory), every capability dropped, no new privileges, its public API off (nothing uses it: the runner uses its command line; on 2.44.7 that means no API key is accepted and its routes answer 401, and its docs page is off); its own owner login; Execute Command off; its credentials encrypted with `N8N_ENCRYPTION_KEY` (sops). **Open:** the SSH and Git nodes are on at home; Postgres' superuser (LiteLLM's role) owns n8n's database (moving it is a live migration, left for a maintenance window). |
| The frames (`server.frames.py`) | n8n and Phoenix are served on the app's own origin, behind its gate; the AI phone is refused; the tools' own policy is kept (all but its framing rule), and a page a workflow wrote is sandboxed (SEC-23). **Open:** one origin for app and tools. |
| `APP_GATE=local` (work) | The app is on 127.0.0.1 only and a request naming a loopback host or `mission-control` is the owner's (WFL-16), and only through the published port (SEC-24): a container naming the app is not this PC. |
| Tracker text | Reaches agents inside an untrusted label (WFL-25). |
| The `stack` command line (WAY-03, [CLI.md](CLI.md)) | Calls the app through its published port like the owner's browser, with the header `X-Aistack-Via: cli`, which only takes rights away: `/api/request` then takes only starting a run, answering an Ask that is no gate and asking for a pack's approval, recorded as via cli. A gate refuses an answer, a dismissal or a later by the command line or an agent's stack tool (WAY-07); a private Ask shows them no figure. A program on the PC that leaves the header out is the local spoofing below, not a new door. |

**What the app sees, measured on the home PC on 11 Nov 2026** (rootless Docker 29.9.2, rootlesskit's builtin port
driver, docker-proxy on; read from `/proc/net/tcp` inside the app while each connection was held open):

| Path | Source address the app sees |
|---|---|
| WSL's `127.0.0.1:8090` and `:8093` (the runner, deploy's health check) | 172.27.0.1, the gateway of `mcui`, the app's default route |
| Windows' `127.0.0.1:8090` (wslrelay) and tailscale serve `https://<pc>:8447` | 172.27.0.1 |
| A container with `--network host` (rootlesskit's namespace: the journeys browser) | 172.27.0.1 |
| n8n on `stepnet` (to 8090 and 8099) | an address of its own on stepnet |
| Phoenix on `obs` | 172.22.0.2 |
| LiteLLM on `mcnet` (to 8090 and 8091) | 172.26.0.4 |
| The builder (on `backend`) | no route to the app at all |

Docker publishes a container's ports on the network of its default route and connects from that network's gateway, so
the rule holds when Docker renumbers its networks; a root-mode Docker with docker-proxy behaves the same way. A setup
where the source differs (a Docker without docker-proxy, IPv6 publishing) shows it in log mode first: every refusal it
would make is logged with the peer and the published port's address.

#### Switching the trust boundary on (the lead's steps, in order)

1. **Secrets, before landing:** `make trust-keys` (makes `AISTACK_STEP_TOKEN`, `N8N_HOOK_TOKEN` and the six
   `MCP_TOKEN_*` once, in `secrets/secrets.enc.yaml`; values never printed). Without `N8N_HOOK_TOKEN` the landing
   deploy's n8n import stops, and the deploy fails and rolls back.
2. **Land in log mode** (the default, `APP_TRUST` unset): the deploy recreates n8n (networks, hardening), LiteLLM and
   the app, imports the workflows with their header and writes n8n's credential; the runner restarts and sends the
   header. Then on Windows run the two 8450 lines of `ops/windows/host-setup.ps1` (an owner step).
3. **Watch the log for a day:** `docker logs aistack-mission-control-1 2>&1 | grep -E "^trust"`. The first line says the
   mode, the published port's address (172.27.0.1 at home) and any token that is missing; a line "would refuse"
   names what, the peer and the path. Expect none: open the app from the phone and the PC, start a crew job from the
   app, a chat that uses a tool (missions, memory, house), and the Workflows and Traces pages.
4. **Switch on:** `APP_TRUST=on` in `deployments/home/deployment.env`, land it (a deploy recreates the app). Check the
   app from the phone at once.
5. **Back off in one step** (the owner locked out, or tools refused): `APP_TRUST=log make up` puts the app back in log
   mode at once without a landing; then revert the line in git. n8n's webhook header and its network move are not part
   of the switch: rolling those back is a revert of the branch and a deploy.

### The Swarm service (phases 1 to 4)

- **No way in from outside:** no published port and no internet. The MCP tools sit on the internal network `swarmmcp`, which
  LiteLLM and Mission Control join. Mission Control reads through a separate door (:8096) with its own token, and that door
  only reads (SWM-11); the owner's messages and taps go through the runner. The host runner talks over a Unix socket in `/srv/ai/swarm` with its own token (in sops; the service
  stores only its SHA-256).
- **Who may act:**
  - Through the gateway, the caller is the agent whose stored credential LiteLLM sends. A call carrying its own
    `Authorization` header is refused, because a client header would replace the stored one (SWM-89, docs/SWARM-PHASE0.md).
  - The runner acts only for host agents and relays the owner's decisions.
- **Data rules:** every write is redacted, and payment card numbers are refused. Artifacts labelled private never reach an
  agent whose card holds a way out (fetch, browser, phone); the same holds for Board messages and for messages that link a
  private artifact (SWM-67).
- **Messages decide nothing:** no Board message changes an artifact's state; an agent's "the owner approved" is marked as a
  claim (SWM-55, SWM-58). Loops, floods and repeats are refused in code (SWM-14).
- **Agents' identities (phase 4):** the scout, the curator, the mission agent and the chat assistant reach the swarm's MCP
  tools through LiteLLM with their own keys. Each one's swarm token exists only as its key's stored credential in the gateway
  (`ops/swarm_setup.py agents`); the service keeps its SHA-256 and refuses a call that brings its own `Authorization`.
- **No agent steers the chat assistant:** `main` (the phone, mail and house tools) reads and writes the Board but its card
  says `wake: never`, so other agents' requests to it are declined at once; it acts only on the owner's words.
- **A wake is one turn, not a command:** a woken Hermes agent is told that other agents' messages are data and that
  anything that changes the world is the owner's; a woken Claude crew agent answers with read-only tools.
- **Builds:** a reviewer's block (security or requirements lens) stops the deploy; only the owner's written reason lifts it,
  recorded as evidence. Parallel builds hold leases on their files; every approved build is checked again on the combined
  code before it lands.
- **No agent rewrites itself (phase 5, SWM-70):** the Ledger refuses an agent change an agent writes, edits or moves about
  itself. A build that changes what defines an agent (`config/agents.yaml`, `ops/keys.sh`, `config/hermes/`, the builder's own
  `ops/builds.py` and `ops/planner.py`) gets an agents-rule block in its review unless it carries an agent change whose
  experiment passed; only the owner's written override lifts it. An agent change ships only after its replay shows no score
  dropping (SWM-18), then the owner's Build it and his approval of the build; one tap reverts it.
- **Experiments spend nobody's key:** replays run on the service key `vk-eval` (ChatGPT models, no MCP tools) or Claude Code
  read-only in the builder sandbox; nothing a replay writes is applied. An MCP agent cannot set its own replay input (only
  the runner's door adds what a host agent worked from).

### Tasks, the Conductor and temporary agents (phases 1 to 4; reviewed 31 Oct 2026)

What the stack may start by itself is DEC-34 (TSK-20): it plans, staffs and runs tasks, and asks before it messages other
people, spends money, deploys code, deletes data or acts on the AI phone. These hold it:

- **The doors keep their gates.** A task reaches a mission, a build or a Claude task through the same request the app
  uses; the deploy tap, purchase approvals, the AI phone's per-action OK and Gmail's Trash approval are unchanged.
- **A Conductor step is one agent's ordinary run.** Hermes agents run on their own profile and key with their own MCP
  grants (`ops/keys.sh`); a Claude step is a read-only Claude task in the builder sandbox; a Python step is one model call
  on the agent's own key. No step gets a grant its agent does not already have.
- **A temporary agent (TSK-15)** is one model call per step, nothing more: its design may ask only for the subscription
  models and no tools (`staffing.admit` refuses anything else); it gets its own LiteLLM key with those models, no MCP
  server and a 0.02 daily budget, made when its step starts and deleted when its task ends; keys left by a restart are
  swept at the next start (the keys live in the runner's memory only, never on disk). Its instructions are written by the
  intake model from the task's own text, so they carry whatever the task carries: like any agent run, its answer is data
  for the next step and the owner, never an instruction to the stack. It cannot become permanent by itself: a design
  that met three tasks becomes an idea, which the owner reviews, the builder makes and a replay tests (TSK-16).
- **Rules (TSK-11)** start tasks only within their cooldown and, if the owner set one, after a model check; web, Forgejo
  and inbox sources are read only while a rule asks for them; the AI phone cannot make, change or rate rules or tasks.
- **Judging (TSK-17)** reads a task's own result on the evaluation key (`vk-eval`, no tools) and changes nothing.

### The AI phone

- Typing text and opening a web address are ways for private data to leave (FND-02). They ask the owner unless a task he
  approved names that exact text or app (PHN-18), or he opened free mode and the text or address holds no e-mail
  address, phone number, IBAN, key or IP address (PHN-19, DEC-38, superseding DEC-23). Inside a purchase the owner
  approved, its own steps don't ask again. Money, passwords and blocked apps are never covered; the Home Assistant app
  opens only inside a task that names it (VOI-07).

### The voice gateway

- Home Assistant on the NAS reaches Hermes through the app's voice gateway (VOI-03): its own port, only the model list
  and the chat, a key (sops `VOICE_KEY`, held by Home Assistant) instead of Tailscale, because the NAS is not on the
  tailnet. On the PC it listens on 127.0.0.1:11435; Windows passes the LAN's port 11434 to it from the NAS's
  address only.
- A spoken turn is untrusted input like a chat message, and anyone in the room (or the TV) can be heard: the voice
  prompt says purchases, deploys, deletions, e-mail to others and the NAS and the network are never done by voice, and
  mail, calendar details and money are not read aloud. The approvals that guard them are unchanged.
- **Newsletters on a watched topic (MIS-28)** reach a topic's report, and through it the topic's wiki. Only mail with a
  List-Unsubscribe header goes there, never a person's mail, a protected one or the stack's own briefing. The digest finds the
  topic's names in the text without a model, and one model call with mail tools nowhere near it judges the matches. The desk reads
  each mail framed as untrusted data, without triage: a mail's text never decides what is fetched, and its links are never
  opened. The worst a mail can do is put a false claim into a report, as a web page can; the report names the sender as its source.

## Accepted risks (deliberate, revisit when the setup changes)

- **Private data the free-mode check does not recognise** (DEC-38). In the owner's free mode on the AI phone, an agent
  tricked by text in a page or an e-mail could type something private that is not an e-mail address, phone number,
  IBAN, key or IP address (a name, an address, a note) into a web form. The owner chose fewer approvals; free mode is
  time-limited, every action is logged with the screen, and a task approval names its exact texts instead.

- **Local spoofing of the identity header.** A process on the PC can call `127.0.0.1:8090` (and the gates on 9119/5173, Open WebUI on 3080) with a forged
  `Tailscale-User-Login`. Anything that can do that can already read the files directly.
- **Prompt-injected tool calls by the main assistant.** Hermes main reads research results (labelled untrusted)
  and can call mission tools. Worst cases: an extra mission (costs $0, visible, archivable), an e-mail to the
  owner, a build assignment (cannot deploy without the tap). No tool can send data to third parties.
- **Claude token inside the sandbox during Claude builds.** A prompt injected through repository content could try to
  leak it, but the only reachable hosts are the package registries (no anonymous publishing) and Anthropic itself.
  Revoke it on claude.ai if in doubt and run `make claude-connect` again.
- **Package supply chain in the builder.** The builder can install npm/PyPI packages; a malicious package runs
  inside the sandbox only (no secrets, no LAN, no deploy rights). The diff review is the control.
- **Hermes dashboard password** is shown to the owner through Mission Control (tailnet-authenticated).
- **`/srv/ai/workbench` is world-writable** (umask 000) so the builder (another host uid) and the runner can share it.

## Hard rules

- **What a deployment forbids never reaches git (SEC-22).** `/srv/ai/private/never-in-git.txt` (in no repository) lists
  what must never be committed or pushed. The stack's repository runs `ops/git-hooks` (installed by every deploy), which
  refuse a commit whose changed lines, file names or message match the list and a push of any commit that does; the
  runner's own pushes from the builder's clones, which run no hook, check the same list (`ops/builds.py`). A match is
  named by its line in the list, never printed. The public snapshot has its own scan on top (`docs/PUBLISHING.md`).

Never delete NAS data or Docker volumes without explicit approval; never alter RAID/SHR, storage pools or
unrelated shares; never expose services publicly or touch router port forwarding without approval; never weaken
NAS security; never print, commit or store credentials unencrypted; never bypass authentication or MFA; never
deploy without the owner's explicit approval.

## An agent's tools changed in the app (TSK-29)

Swarm → Team → Settings can propose a change to an agent's tools. Nothing is applied from the app: the change becomes
an agent change in the Ledger, is replayed on the agent's past runs (no score may drop), and ships only through the
owner's Build it and deploy tap, with Revert on the build. A tool **added** widens the agent's key grants (ops/keys.sh,
its Hermes profile), so the app asks for an explicit grant tick and the change carries `plan.security.adds` and a
"security change" evidence line in its history; the agents rule (SWM-70, builds.agent_gate) still holds the build until
the change's experiment passed. A tool removed narrows the grants and needs only the replay. An agent can never file such
a change about itself (the Ledger refuses it).

## Outside agents over A2A (TSK-19)

Off by default (`/srv/ai/missions/app/a2a.json`, mode 600). When on, `/.well-known/agent-card.json` and `/a2a`
(JSON-RPC) answer only requests that came through Tailscale serve (the tailnet identity header) and carry a bearer token
of an agent the owner added; tokens are made by the web server, shown to the owner once, and kept only as SHA-256 hashes;
the comparison is constant-time. Each message becomes a task with source `a2a:<name>` whose autonomy is forced to "ask"
(ops/tasks.py), so nothing runs before the owner's Start it; an agent reads only its own tasks; ten tasks an hour per
agent. Adding, switching and revoking are refused from the AI phone, and `a2a_token` is refused through the generic
request path. The calendar's iCal address is a secret link: it lives in /srv/ai/private/calendar.json (mode 600), is
never logged, and the app shows only its host.


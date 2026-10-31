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
| Web content | Only the `scout` profile reads the web; questions pass a privacy guard (patterns, private-terms list, model check, fail-closed); pages are read by `fetch` in an isolated network with an egress firewall (no LAN, no Tailscale ranges). Results are labelled untrusted. |
| Code execution (Claude engine) | For Claude Code builds the runner passes `CLAUDE_CODE_OAUTH_TOKEN` into the builder for that one run (`docker exec -e`); the builder's own proxy (`pkgproxy-builder`) allows npm, PyPI and `api.anthropic.com` only. OpenCode's proxy is unchanged. |
| Code execution | Only the `builder` has a shell, inside its own container: sees `/work` only, no vault, secrets, SSH keys or Docker socket; networks: LiteLLM + npm/PyPI proxy. It cannot push or deploy. |
| Deploys | Only the host runner merges and deploys, and only after the owner taps Approve; smoke test + automatic rollback. |
| Secrets | sops + age; decrypted into a process environment per command (`make`, systemd units), never written to disk or printed. Age key copies: NAS, `F:\AI-backup`, OneDrive (separate folder). |
| Requests from the app / chat | The runner validates every request (allow-listed actions, slugs, schedules, sizes); e-mail goes only to the owner's address. |

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

### The AI phone

- Typing text, opening a web address and opening an app always ask the owner, even inside a time window: they are ways for
  private data to leave (DEC-23, FND-02). Inside a purchase the owner approved, its own steps don't ask again.

## Accepted risks (deliberate, revisit when the setup changes)

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

Never delete NAS data or Docker volumes without explicit approval; never alter RAID/SHR, storage pools or
unrelated shares; never expose services publicly or touch router port forwarding without approval; never weaken
NAS security; never print, commit or store credentials unencrypted; never bypass authentication or MFA; never
deploy without the owner's explicit approval.

---
title: Technology and versions
kicker: What it's built from
part: Under the hood
icon: bolt
minutes: 7
summary: The open-source parts of the stack, how they fit together, and which versions are running right now.
views: []
---
The stack is built from open-source components, pinned to exact versions and upgraded deliberately once a month.
This chapter is for the curious: you don't need it to use anything.

## The layers

**Hosts.** A Windows 10 PC runs Linux (WSL2) with Docker, so every service is a container. A Synology NAS
runs the git server (Forgejo) with the automatic tests, and stores the encrypted backups. Tailscale connects your
devices privately. Nothing is open to the internet.

**Model gateway (LiteLLM).** Every model call from every agent goes through one gateway. Each agent has its own
key, with its own allowed models, daily limits and tools. The gateway also connects agents to tools (MCP servers)
and records every call, which is where the token counts in this app come from. Its only models use the ChatGPT
subscription; the builder's second engine, Claude Code, runs on your Claude subscription outside it.

**Agents (Hermes Agent).** Hermes runs in several profiles: *main* (chat, Telegram), *scout* (web research),
*curator* (tidies the vault and wiki), *mission* (mission runs) and the separate *builder*.

**Knowledge.** *qmd* searches the vault (keyword and meaning-based search). *Hindsight* is the long-term memory,
running local models. *Graphify* holds code graphs.

**Mission Control.** This app, and the runner on the PC behind it, which schedules missions, watches triggers,
runs builds and measures resources. The app never runs anything itself. It drops requests into an inbox that the
runner checks and carries out.

**Observability.** *Phoenix* shows a trace of every model call: what was asked, which tools ran, how long it took.

## Tools agents can use

Agents reach tools through the gateway, and each agent only gets the ones it needs:

| Tool server | Gives agents |
|---|---|
| **qmd** | search over the vault, reports, wikis, code summaries, mail and chat exports |
| **research** | web research through the privacy guard and the scout |
| **fetch** | the isolated page reader (HTML and PDF) |
| **missions** | Mission Control's tools (listed in the Chat chapter) |
| **graphify** | the code graph |
| **claude** | Claude Code, read-only, for questions about code and documents (Claude tasks) |
| **mail** | your Gmail, only under the grants you give (Connections) |
| **phone** | the AI phone, every change with your OK |
| **house** | Home Assistant: lights, plugs, shutters and the Echos |
| **browser** | the scout's isolated browser for shops and prices (it only looks) |

## Running versions

Read live from the stack's version file:

```live
versions
```

## Apps you can open

```live
apps
```

```try
label: Look at a trace in Phoenix
app: 8443
note: Opens Phoenix. Pick the latest trace to see every step of a recent answer.
```

```try
label: Open Hermes' admin
app: 8448
note: Hermes' own dashboard (skills, sessions, logs). No password: your Tailscale login is the only sign-in.
```

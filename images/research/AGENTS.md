# images/research/: the research tool

`server.py` is an MCP server with one tool, `research(question)`. It runs the Hermes **scout** profile as an agent
and returns its cited answer, labelled as untrusted web content. Every question first passes the privacy guard:
patterns, the private-terms list (`ops/private-terms.sh`) and a model check. If the guard is unsure, the
question is blocked (fail-closed).

Reached by LiteLLM's MCP gateway (granted per key in `ops/keys.sh`), never directly by an agent.

## Rules

- This is a security boundary (`docs/SECURITY.md`): the scout has no access to the vault, memory or e-mail, and
  this server must not add any. Don't relax the guard to "make research work". Improve the question instead.
- Results stay labelled as untrusted all the way to Hermes.
- Long research must finish within Hermes' MCP timeout (`mcp_servers.vault.timeout`, 600 s, in
  `config/hermes/configure.sh`).
- Questions are length-limited (`MAX_QUESTION`) and the guard model call uses its own key (`LITELLM_GUARD_KEY`).
- The scout's brief and the privacy check's prompt are prompts/scout.md BRIEF and prompts/guard.md PRIVATE, mounted
  read-only at /prompts and read at each call; an unreadable file refuses the call (prompts/AGENTS.md, MEM-13).

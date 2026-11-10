# tests/fixtures/packs/toy: the toy pack (GEN-21)

A whole pack in the format of docs/AI-STACK.md, used by the tests (copied outside the repository and made a git
repository there): a Claude Code plugin manifest, two agents, a skill, MCP servers in `.mcp.json` (one on a host off
any egress list), `stack.yaml` (harness, model, grants), a job kind of the worker protocol, two n8n workflows
(`workflows/*.json`, as n8n exports them, named `toy/<name>`) and an exam set with known outcomes. Generic on purpose:
no real system's names.

# images/graphify/: code knowledge graphs

Graphify builds deterministic code graphs (tree-sitter, no model calls) and serves an MCP query server that Hermes
and the builder use. Graphs are refreshed by `ops/graphify-sync.sh` (timer) and `make understand`.
`ops/graph_repos.py` adds the repository nodes Graphify lacks.

Internal network only. Pin Graphify's version in the `Dockerfile`.

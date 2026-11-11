# images/graphify/: code knowledge graphs

Graphify builds deterministic code graphs (tree-sitter, no model calls) and serves an MCP query server that Hermes
and the builder use. Graphs are refreshed by `ops/graphify-sync.sh` (its n8n workflow every minute, and at once by an
onboarding, `ops/onboard.py`). The merged graph is rebuilt only when a repository's graph changed in content (its
`built_at_commit` stamp aside) or a repository came or went, in a container capped at 3 GB of RAM and 6 GB with swap
(BLD-40); `ops/graph_repos.py` adds the repository nodes Graphify lacks, inside the same cap.

Internal network only. Pin Graphify's version in the `Dockerfile`.

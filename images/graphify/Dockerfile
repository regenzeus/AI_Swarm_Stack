# Graphify: deterministic code knowledge graphs (tree-sitter, no LLM) + MCP query server.
# Code-only use: no semantic/LLM pass, no network needed after build.
FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends git && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "graphifyy[mcp,leiden]==0.9.85" mcp-proxy==0.13.0
ENV GRAPHIFY_QUERY_LOG_DISABLE=1 GRAPHIFY_BACKEND=none
WORKDIR /code

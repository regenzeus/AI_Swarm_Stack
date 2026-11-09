# images/qmd/: vault search

qmd, a local hybrid search (BM25 + vectors + rerank), indexes the vault, topics and reports, missions (their results
and wikis), the agents' memory journals, specs, code digests and imported mail and chats, and serves an MCP server for LiteLLM. `start.sh` sets up the collections and starts the
server. Indexing runs on a timer (`ops/vault-ingest.sh`, `vault-ingest.timer`) and after mission runs.

No network access beyond the internal network. Measure retrieval quality with `make retrieval`
(`eval/retrieval.py`) before and after changing collections or models.

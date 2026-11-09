# qmd: local hybrid search (BM25 + vectors + rerank) and MCP server over the vault.
FROM node:22-bookworm-slim
ARG QMD_VERSION=2.8.3
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends ca-certificates git && rm -rf /var/lib/apt/lists/* \
 && npm install -g @tobilu/qmd@${QMD_VERSION} && npm cache clean --force
# Reranking runs a 0.6B model over every candidate chunk: ~2 min per query on this CPU vs 0.3 s without.
# Default the MCP tool's `rerank` parameter to false; a caller can still pass rerank:true explicitly.
# Whether reranking earns its cost per collection is measured against qrels in MVP 6.
RUN f=$(grep -rl 'z.boolean().optional().default(true).describe("Rerank' "$(npm root -g)/@tobilu/qmd/dist") \
 && sed -i 's/z.boolean().optional().default(true).describe("Rerank/z.boolean().optional().default(false).describe("Rerank/' $f \
 && grep -q 'default(false).describe("Rerank' $f
ENV XDG_CACHE_HOME=/data/cache \
    QMD_CONFIG_DIR=/data/config \
    QMD_FORCE_CPU=1 \
    QMD_EMBED_MODEL=hf:Qwen/Qwen3-Embedding-0.6B-GGUF/Qwen3-Embedding-0.6B-Q8_0.gguf
COPY start.sh /start.sh
ENTRYPOINT ["sh", "/start.sh"]

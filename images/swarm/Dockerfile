# The Swarm service (images/swarm/swarm.py): the agent swarm's Ledger. No port, no internet: MCP for agents on the internal
# network swarmmcp (LiteLLM only), the host runner's API on the Unix socket /data/runner.sock. See AGENTS.md.
FROM python:3.12-slim
RUN pip install --no-cache-dir mcp==2.3.0 pyyaml==6.0.3 \
 && useradd -r -u 10012 -M swarm
COPY ledger.py ledger.*.py swarm.py textcap.py /app/
WORKDIR /app
USER swarm
CMD ["python", "/app/swarm.py"]

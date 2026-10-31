# MCP adapter exposing the Hermes scout profile as one tool, research(question). See server.py.
FROM python:3.12-slim
RUN pip install --no-cache-dir mcp==2.3.0 httpx \
 && useradd -r -u 10002 research
COPY server.py /app/server.py
USER research
EXPOSE 8000
CMD ["python", "/app/server.py"]

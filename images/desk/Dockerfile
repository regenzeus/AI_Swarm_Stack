# Topic Desk: nightly news collection and briefing per focus topic (desk.py). Runs on the "webonly" network:
# internet and LiteLLM, nothing else of the stack; it also refuses URLs that resolve to private addresses.
# Its prompts are not baked in: prompts/ of the repository is mounted read-only at /prompts (MEM-13).
FROM python:3.12-slim
RUN pip install --no-cache-dir feedparser==6.0.12 trafilatura==2.0.0 pyyaml==6.0.3 markdown==3.7 \
      googlenewsdecoder==0.1.7 selectolax==0.4.13 \
 && useradd -r -u 10005 desk
COPY desk.py /app/desk.py
COPY textcap.py /app/textcap.py
USER desk
ENTRYPOINT ["python", "/app/desk.py"]

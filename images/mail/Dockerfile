# The Gmail connector (images/mail/mail.py): search, read, organize and move to Trash for the stack's agents, only while
# The owner has granted it in Mission Control. Sealed: entrypoint.sh allows IMAPS (993) only; it cannot send mail.
FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends iptables util-linux && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir mcp==2.3.0 \
 && useradd -r -u 10008 -M conn
COPY entrypoint.sh /entrypoint.sh
COPY mail.py /app/mail.py
EXPOSE 8000
ENTRYPOINT ["sh", "/entrypoint.sh"]

# The AI phone (images/phone/phone.py): Hermes' hands on the old test phone through ADB over Tailscale, as MCP tools
# behind the owner's approval, a block list and a Stop switch. Sealed: entrypoint.sh lets it reach that one phone only.
# ADB comes from Google's platform-tools (Debian's adb is too old for wireless-debugging pairing), checksum-pinned.
FROM python:3.12-slim
ARG PLATFORM_TOOLS=37.0.1
ARG PLATFORM_TOOLS_SHA256=d230f13842f60f782a8645f9c813f8f845bf36089ea7289f28c48f17979313f1
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends iptables util-linux curl unzip \
 && curl -fsSL -o /tmp/pt.zip https://dl.google.com/android/repository/platform-tools_r${PLATFORM_TOOLS}-linux.zip \
 && echo "${PLATFORM_TOOLS_SHA256}  /tmp/pt.zip" | sha256sum -c - \
 && unzip -q /tmp/pt.zip -d /opt && ln -s /opt/platform-tools/adb /usr/local/bin/adb && rm /tmp/pt.zip \
 && apt-get purge -y -qq curl unzip && apt-get autoremove -y -qq && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir mcp==2.3.0 pillow==11.0.0 \
 && useradd -r -u 10007 phone && adb version
COPY entrypoint.sh /entrypoint.sh
COPY phone.py /app/phone.py
EXPOSE 8000
ENTRYPOINT ["sh", "/entrypoint.sh"]

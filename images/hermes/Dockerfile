# Hermes 0.22.5 plus ddgs (DuckDuckGo metasearch), the keyless web_search backend the scout profile uses (until
# Hermes makes its own dependency environment; configure-scout.sh installs the ddgs extra there, FND-10),
# and the Python deps of the hindsight memory-provider plugin (long-term memory; the plugin itself is installed
# into HERMES_HOME at its catalog pin by config/hermes/configure.sh).
# Page reading is NOT in this image: it runs in the isolated "fetch" container (images/fetch).
FROM nousresearch/hermes-agent:v0.22.5
RUN /opt/hermes/.venv/bin/python -m ensurepip \
 && /opt/hermes/.venv/bin/python -m pip install -q --no-cache-dir ddgs==9.16.0 \
      hindsight-client==0.10.3 hindsight-embed==0.10.3 aiohttp-retry==2.9.1 \
 && /opt/hermes/.venv/bin/python -c "import ddgs, hindsight_client"

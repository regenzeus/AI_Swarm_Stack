#!/bin/sh
# Install (or refresh) the aistack-runtime plugin (config/hermes/plugins/aistack-runtime) into one Hermes home and
# enable it: every model call, tool call and run end of that profile goes to Mission Control's live run view.
#   sh /config/install-runtime-plugin.sh            the current HERMES_HOME (main profile; the builder's own home)
#   sh /config/install-runtime-plugin.sh mission    a named profile under /opt/data/profiles
set -e
P="${1:-}"
if [ -n "$P" ]; then home="/opt/data/profiles/$P"; else home="${HERMES_HOME:-/opt/data}"; fi
mkdir -p "$home/plugins"
rm -rf "$home/plugins/aistack-runtime"
cp -r /config/plugins/aistack-runtime "$home/plugins/aistack-runtime"
if [ -n "$P" ]; then hermes -p "$P" plugins enable aistack-runtime >/dev/null 2>&1 || true
else hermes plugins enable aistack-runtime >/dev/null 2>&1 || true; fi
echo "runtime plugin: ${P:-$(basename "$home")}"

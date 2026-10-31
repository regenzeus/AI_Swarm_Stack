#!/usr/bin/env bash
# Write the private-identifier list the research tool refuses to send to web search
# (/srv/ai/research-terms/private-terms.txt, mounted read-only into the research container). Re-run when it changes;
# vault-ingest.sh runs it after each ingest so new own-project names are added.
# The owner's identifiers come from /srv/ai/private/research-terms.txt, which no repository holds (SEC-19: the public
# snapshot names none of them). Without that file this fails, so the guard never runs on a list missing them.
set -euo pipefail
OWN=/srv/ai/private/research-terms.txt
OUT=/srv/ai/research-terms/private-terms.txt; mkdir -p /srv/ai/research-terms
[ -s "$OWN" ] || { echo "private-terms: $OWN is missing; the research guard keeps its last list" >&2; exit 1; }
{
  echo "# private identifiers: never part of a public web search (ops/private-terms.sh)"
  grep -v '^#' "$OWN" | grep -v '^[[:space:]]*$'
  # own projects in the vault (wiki/projects = "one of the owner's own projects")
  for f in /srv/vault/wiki/projects/*.md; do [ -f "$f" ] && basename "$f" .md; done
} > "$OUT.tmp"
mv "$OUT.tmp" "$OUT"

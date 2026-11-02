#!/bin/sh
# Register the vault collections once, then serve MCP over HTTP on the internal network.
set -e
mkdir -p /data/cache /data/config
qmd collection list 2>/dev/null | grep -q vault-wiki || qmd collection add /vault/wiki --name vault-wiki --mask "**/*.md"
qmd collection list 2>/dev/null | grep -q vault-raw  || qmd collection add /vault/raw  --name vault-raw  --mask "**/*.md"
qmd context add qmd://vault-wiki "Compiled wiki pages maintained by the curator: concepts, entities, projects, how-tos, answers. Cite these first." 2>/dev/null || true
qmd context add qmd://vault-raw  "Immutable raw sources (articles, papers, notes, clips) the wiki was compiled from." 2>/dev/null || true
mkdir -p /bulk/mail /bulk/chats 2>/dev/null || true
qmd collection list 2>/dev/null | grep -q bulk-mail  || qmd collection add /bulk/mail  --name bulk-mail  --mask "**/*.md"
qmd collection list 2>/dev/null | grep -q bulk-chats || qmd collection add /bulk/chats --name bulk-chats --mask "**/*.md"
qmd context add qmd://bulk-mail  "Your e-mail, one file per message (sender, date, subject in the heading). Search-only, not compiled into the wiki." 2>/dev/null || true
qmd context add qmd://bulk-chats "Your past ChatGPT and Claude conversations, one file per conversation." 2>/dev/null || true
qmd collection list 2>/dev/null | grep -q code-docs || qmd collection add /code-docs --name code-docs --mask "**/*.md"
qmd collection list 2>/dev/null | grep -q "^topics " || qmd collection add /vault/topics --name topics --mask "**/*.md"
qmd context add qmd://topics "Focus topics of the Topic Desk: each topic's brief (TOPIC.md) and its daily news briefings (reports/YYYY/MM/DATE.md) with numbered sources. Use for questions about recent news on a topic; say the briefing date." 2>/dev/null || true
qmd collection list 2>/dev/null | grep -q "^missions " || qmd collection add /vault/missions --name missions --mask "**/*.md"
qmd context add qmd://missions "Missions (agents) the owner set up: each mission's brief (MISSION.md), working notes, its results (log/YYYY/MM/*.md: research reports, shopping and cleanup analyses) and its LLM wiki (wiki/entities, concepts, projects, events). Use for questions about what a mission found; say the result's date." 2>/dev/null || true
qmd collection list 2>/dev/null | grep -q "^tasks " || qmd collection add /vault/tasks --name tasks --mask "**/*.md"
qmd context add qmd://tasks "The answers of the tasks given in the app or started by the owner's rules (tasks/<id>-<name>.md, one per run of a recurring task): what was asked, the answer with its sources. Use for questions about something a task found or an alert said; give the task number and date." 2>/dev/null || true
qmd collection list 2>/dev/null | grep -q "^agents " || qmd collection add /vault/agents --name agents --mask "**/*.md"
qmd context add qmd://agents "Each agent's own memory journal (agents/<agent>/MEMORY.md): standing notes and dated entries of what it found, what failed and what is still open." 2>/dev/null || true
qmd collection list 2>/dev/null | grep -q "^specs " || qmd collection add /specs --name specs --mask "*/model/pages/*.md"
qmd context add qmd://specs "Specifications and standards, one page per section with its numbered requirements (spec/ingest.py). Cite section number and requirement ID." 2>/dev/null || true
qmd context add qmd://code-docs "Digests of code repositories in ~/code written by Understand Anything: what each repo does, its layers, key files and functions with summaries." 2>/dev/null || true
# Warm-up: load the embedding model now, not on the user's first question.
cat > /tmp/warmup.js <<'JS'
setTimeout(async () => {
  const s = Date.now();
  try {
    const r = await fetch("http://127.0.0.1:8181/query", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ searches: [{ type: "vec", query: "warm up" }], limit: 1, rerank: false }) });
    console.log(`warm-up done: HTTP ${r.status} in ${((Date.now() - s) / 1000).toFixed(1)}s`);
  } catch (e) { console.log("warm-up failed:", e.message); }
}, 5000);
JS
node /tmp/warmup.js &
exec qmd mcp --http --host 0.0.0.0 --port 8181

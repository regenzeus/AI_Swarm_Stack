"""Compile a mission's LLM wiki from all of its results so far, oldest first (normally the runner does this after
every run; use this for missions that existed before their wiki, or after deleting a wiki to rebuild it).
  python3 ops/wiki_rebuild.py <mission-slug>        (make wiki-rebuild MISSION=slug; needs VK_DESK / VK_MISSION)"""
import os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import missions as M
import mission_extras as X

X.M = M
os.umask(0)
m = M.load_missions()[sys.argv[1]]
if m["type"] == "briefing":
    t = M.VAULT / "topics" / m.get("topic", m["slug"])
    results = sorted([*(t / "reports").rglob("*.md"), *(t / "alerts").rglob("*.md")], key=lambda p: p.name)
    key = os.environ["VK_DESK"]
else:
    results = sorted((M.MISSIONS / m["slug"] / "log").rglob("*.md"))
    key = os.environ["VK_MISSION"]
for p in results:
    rel = str(p.relative_to(M.VAULT))
    n = X.compile_wiki(m, rel, p.read_text(), key)
    print(f"{rel}: {n} pages updated", flush=True)
M.vault_commit([X.wiki_root(m)], f"wiki: rebuild {m['slug']} from {len(results)} results")
M.reindex()
print("wiki:", X.wiki_root(m))

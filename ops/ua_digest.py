"""Turn an Understand Anything knowledge graph into one readable Markdown page for qmd (collection code-docs).
  python3 ops/ua_digest.py <repo>/.ua/knowledge-graph.json <repo-name> > /srv/ai/code-docs/<repo-name>.md
Sections: what the repo is, its layers, the guided tour, then every file with its functions/classes and their
summaries (path:lines, so answers can cite the exact place)."""
import json, sys
from collections import defaultdict

g = json.load(open(sys.argv[1]))
repo = sys.argv[2]
p = g.get("project", {})
nodes = {n["id"]: n for n in g.get("nodes", [])}
children = defaultdict(list)
for e in g.get("edges", []):
    if e.get("type") == "contains" and e["source"] in nodes and e["target"] in nodes:
        children[e["source"]].append(nodes[e["target"]])


def where(n):
    path = n.get("filePath") or ""
    lr = n.get("lineRange")
    return f"{repo}/{path}" + (f":{lr[0]}-{lr[1]}" if lr else "")


out = [f"# {repo}: code map", "",
       f"{p.get('description', '').strip()}", "",
       f"- Languages: {', '.join(p.get('languages', [])) or '-'}; frameworks: {', '.join(p.get('frameworks', [])) or '-'}",
       f"- Analysed {p.get('analyzedAt', '?')} at commit {str(p.get('gitCommitHash', '?'))[:10]} by Understand Anything",
       f"- Source: ~/code/{repo} (dashboard: make understand-dashboard REPO={repo})", ""]
if g.get("layers"):
    out += ["## Layers", ""]
    for l in g["layers"]:
        files = [nodes[i]["name"] for i in l.get("nodeIds", []) if i in nodes][:12]
        out.append(f"- **{l['name']}**: {l.get('description', '').strip()} ({', '.join(files)})")
    out.append("")
if g.get("tour"):
    out += ["## Guided tour", ""]
    for t in sorted(g["tour"], key=lambda t: t.get("order", 0)):
        out.append(f"{t.get('order', '')}. **{t['title']}**: {t.get('description', '').strip()}")
    out.append("")
out += ["## Files", ""]
for n in sorted((n for n in nodes.values() if n["type"] == "file"), key=lambda n: n.get("filePath") or n["name"]):
    out += [f"### {n.get('filePath') or n['name']}", "", f"{n.get('summary', '').strip()}"]
    if n.get("tags"):
        out.append(f"Tags: {', '.join(n['tags'])}")
    for c in sorted(children.get(n["id"], []), key=lambda c: (c.get("lineRange") or [0])[0]):
        out.append(f"- `{c['name']}` ({c['type']}, {where(c)}): {c.get('summary', '').strip()}")
    out.append("")
print("\n".join(out))

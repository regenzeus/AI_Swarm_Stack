"""Add repository nodes to the merged code graph (Graphify has none): one node per repo that `contains` its
file nodes, plus one "code repositories" node linking every repo. Without them a tiny repo (hello-world: one
file, no functions) is nearly invisible to graph search, and "which repos do I have?" has no answer in the graph.
  python3 ops/graph_repos.py /home/owner/code/.graphify/merged-graph.json      (run by graphify-sync.sh)"""
import json, os, sys
from collections import defaultdict

path = sys.argv[1]
g = json.load(open(path))
g["nodes"] = [n for n in g["nodes"] if n.get("_origin") != "repos"]
g["links"] = [l for l in g["links"] if l.get("_origin") != "repos"]
files = defaultdict(list)
for n in g["nodes"]:
    if n.get("repo") and n.get("source_file") and n.get("label") == os.path.basename(n["source_file"]):
        files[n["repo"]].append(n["id"])
community = max((n.get("community", 0) for n in g["nodes"]), default=0) + 1


def node(id_, label):
    return {"id": id_, "label": label, "norm_label": label.lower(), "file_type": "code", "_origin": "repos",
            "community": community, "community_name": "code repositories", "source_file": "", "source_location": ""}


def link(src, dst):
    return {"relation": "contains", "_origin": "repos", "confidence": "EXTRACTED", "confidence_score": 1.0,
            "weight": 1.0, "source_file": "", "source_location": "", "source": src, "target": dst}


g["nodes"].append(node("repos", "code repositories (all repos in ~/code)"))
for repo, ids in sorted(files.items()):
    g["nodes"].append(dict(node(f"repo::{repo}", f"{repo} (repository, {len(ids)} files)"), repo=repo))
    g["links"].append(link("repos", f"repo::{repo}"))
    g["links"] += [link(f"repo::{repo}", i) for i in ids]
tmp = path + ".tmp"
json.dump(g, open(tmp, "w"))
os.replace(tmp, path)
print(f"repo nodes: {', '.join(f'{r} ({len(i)} files)' for r, i in sorted(files.items()))}")

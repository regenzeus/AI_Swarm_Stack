#!/usr/bin/env python3
"""The code map as fixed steps (BLD-26, onboarding step 4), run inside the Understand Anything container by ops/ua_map.py.
No agent decides anything here: the plugin's own deterministic scripts do the scan, the batching and the structure, this
script turns the structure into nodes and edges, and the plugin's merge script normalises them.

  1 scan       scan-project.mjs: every file with its language and category (.ua/intermediate/scan-result.json)
  2 batches    compute-batches.mjs: files grouped by their import graph, with each file's resolved imports
  3 structure  extract-structure.mjs per batch (tree-sitter): functions, classes, call graph, exports
  4 nodes      one node per file (file, config, document, service), one per function and class with its lines; edges
               for contains, imports (1:1 from the resolved imports) and calls (callee resolved in the file, then
               through the exports of the other files); every summary is the placeholder "(not yet explained)", which
               ops/ua_enrich.py fills from the code with a model, one batch of files per call
  5 merge      merge-batch-graphs.py -> assembled-graph.json; then knowledge-graph.json (layers: top-level folders, the
               enrichment reshapes and describes them), fingerprints and meta.json for the viewer. An earlier map's
               explanations are kept for every file git says is unchanged since that map's commit (an update after new
               commits costs the model only the changed files); its layer descriptions and tour stay where they still fit
  6 report     .ua/intermediate/map-report.json: files, nodes, edges, symbols, skipped files, seconds

  python3 ua_map_in.py <project root>        (stdlib only; node and the plugin at /opt/ua)
The repository is data: nothing in it is run, built or installed; only its text is read.
"""
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

SKILL = Path(os.environ.get("UA_SKILL", "/opt/ua/skills/understand"))
PLACEHOLDER = "(not yet explained)"                 # ops/ua_enrich.py PLACEHOLDER knows this exact text
FILE_TYPE = {"code": "file", "test": "file", "script": "file", "config": "config", "data": "config", "docs": "document", "infra": "service"}
SERVICE_FILES = ("dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
NODE_TIMEOUT = 1800     # limit: stops, s for one plugin script (the structure of one batch, the merge of all); counts as a failed try


def say(msg):
    print(f"[ua-map] {msg}", flush=True)


def node(script, *args, timeout=NODE_TIMEOUT):
    p = subprocess.run(["node", str(SKILL / script), *args], capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"{script} failed ({p.returncode}), its last words: … {(p.stderr or p.stdout)[-2000:]}")  # cap: store
    return p.stdout


def complexity(lines):
    return "simple" if lines < 80 else "moderate" if lines < 400 else "complex"


def file_node(f):
    path, cat = f["path"], f.get("fileCategory") or "code"
    ftype = FILE_TYPE.get(cat, "file")
    if ftype == "file" and Path(path).name.lower() in SERVICE_FILES:
        ftype = "service"
    return {"id": f"{ftype}:{path}", "type": ftype, "name": Path(path).name, "filePath": path, "summary": PLACEHOLDER, "tags": [cat],
            "complexity": complexity(int(f.get("sizeLines") or 0))}


def symbol_nodes(path, fid, r):
    """A file's functions and classes from the structure -> (nodes, edges, {name: id})."""
    nodes, edges, own = [], [], {}
    for kind, items in (("function", r.get("functions") or []), ("class", r.get("classes") or [])):
        for s in items:
            nid = f"{kind}:{path}:{s['name']}"
            own[s["name"]] = nid
            start, end = int(s.get("startLine") or 1), int(s.get("endLine") or s.get("startLine") or 1)
            tags = [str(m) for m in (s.get("methods") or [])[:12]] if kind == "class" else []  # cap: list (a class's first methods as tags; the code has them all)
            nodes.append({"id": nid, "type": kind, "name": s["name"], "filePath": path, "lineRange": [start, end], "summary": PLACEHOLDER, "tags": tags,
                          "complexity": complexity(end - start)})
            edges.append({"source": fid, "target": nid, "type": "contains", "direction": "forward", "weight": 1})
    return nodes, edges, own


def call_edges(fid, r, own, exporters):
    """The structure's call graph -> calls edges to the repository's own functions (a library call is none)."""
    out = []
    for call in r.get("callGraph") or []:
        callee = str(call.get("callee") or "").split(".")[-1]
        src = own.get(str(call.get("caller") or ""), fid)
        if callee in own:
            tgt = own[callee]
        elif callee in exporters:
            tgt = f"function:{exporters[callee][0]}:{callee}"   # the first file exporting it; the merge drops a target that is no node
        else:
            continue
        if tgt != src:
            out.append({"source": src, "target": tgt, "type": "calls", "direction": "forward", "weight": 0.8})
    return out


def earlier(ua, root):
    """The earlier map (the current file, or the one a redo set aside) and the files changed since its commit -> (map, changed,
    all_changed). all_changed: no earlier map, or its commit is unknown to git: nothing is kept."""
    for name in ("knowledge-graph.json", "knowledge-graph.previous.json"):
        try:
            old = json.loads((ua / name).read_text())
            break
        except (OSError, ValueError):
            old = None
    if not old or not old.get("nodes"):
        return None, set(), True
    sha = str((old.get("project") or {}).get("gitCommitHash") or "")
    if not sha:
        return old, set(), True
    p = subprocess.run(["git", "-C", str(root), "diff", "--name-only", sha, "HEAD"], capture_output=True, text=True, timeout=120)
    if p.returncode:
        return old, set(), True
    changed = {x.strip() for x in p.stdout.splitlines() if x.strip()}
    u = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True, timeout=120)
    changed |= {x[3:].strip() for x in u.stdout.splitlines() if len(x) > 3}
    return old, changed, False


def keep_explained(kg, old, changed, all_changed):
    """Carry an earlier map's explanations over to the new nodes of unchanged files -> how many nodes kept theirs."""
    if not old or all_changed:
        return 0
    by_id = {n["id"]: n for n in old.get("nodes") or []}
    kept = 0
    for n in kg["nodes"]:
        o = by_id.get(n["id"])
        if not o or str(n.get("filePath") or "") in changed or str(o.get("summary") or "") in ("", PLACEHOLDER) or str(o.get("summary", "")).startswith("Auto-generated node for"):
            continue
        for k in ("summary", "tags", "complexity", "languageNotes"):
            if o.get(k) not in (None, "", []):
                n[k] = o[k]
        kept += 1
    desc = {l.get("name"): l.get("description") for l in old.get("layers") or [] if l.get("description")}
    for l in kg["layers"]:
        if l["name"] in desc:
            l["description"] = desc[l["name"]]
    ids = {n["id"] for n in kg["nodes"]}
    tour = [t for t in old.get("tour") or [] if all(i in ids for i in t.get("nodeIds") or [])]
    if tour:
        kg["tour"] = tour
    return kept


def main(root):
    t0 = time.time()
    root = Path(root).resolve()
    ua = root / (".understand-anything" if (root / ".understand-anything").is_dir() else ".ua")
    inter = ua / "intermediate"
    inter.mkdir(parents=True, exist_ok=True)
    old, changed, all_changed = earlier(ua, root)
    if old:
        say(f"earlier map found: {'every file counts as changed' if all_changed else f'{len(changed)} files changed since its commit, the rest keep their explanations'}")
    for stale in inter.glob("batch-*.json"):
        stale.unlink()
    say("1/6 scan")
    node("scan-project.mjs", str(root), str(inter / "scan-result.json"), "--exclude-analysis-data")
    scan = json.loads((inter / "scan-result.json").read_text())
    files = scan.get("files") or []
    if not files:
        raise RuntimeError("the scan found no files")
    say(f"2/6 batches ({len(files)} files)")
    node("compute-batches.mjs", str(root))
    bj = json.loads((inter / "batches.json").read_text())
    batches = bj.get("batches") or []
    exporters = {}                                  # symbol name -> files exporting it (the call graph's cross-file targets)
    for path, names in (bj.get("exportsByPath") or {}).items():
        for n in names or []:
            exporters.setdefault(str(n), []).append(path)
    say(f"3/6 structure ({len(batches)} batches)")
    stats, skipped, unreadable = Counter(), set(), set()
    for b in batches:
        i, bfiles, imports = b["batchIndex"], b.get("files") or [], b.get("batchImportData") or {}
        inp, out = inter / f"ua-in-{i}.json", inter / f"ua-out-{i}.json"
        inp.write_text(json.dumps({"projectRoot": str(root), "batchFiles": bfiles, "batchImportData": imports}))
        try:
            node("extract-structure.mjs", str(inp), str(out))
            res = json.loads(out.read_text()) if out.exists() else {}
        except RuntimeError as e:                   # one batch's structure lost: its files still get their nodes, said in the report
            say(f"batch {i}: {str(e)[:300]} …")  # cap: preview
            res = {}
        skipped |= {str(x) for x in res.get("filesSkipped") or []}
        unreadable |= {str(x) for x in res.get("filesUnreadable") or []}
        by_path = {r["path"]: r for r in res.get("results") or [] if r.get("path")}
        nodes, edges = [], []
        for f in bfiles:
            fn = file_node(f)
            nodes.append(fn)
            stats[fn["type"]] += 1
            edges += [{"source": fn["id"], "target": f"file:{imp}", "type": "imports", "direction": "forward", "weight": 0.7} for imp in imports.get(f["path"]) or []]
            r = by_path.get(f["path"])
            if r:
                sn, se, own = symbol_nodes(f["path"], fn["id"], r)
                nodes += sn
                edges += se + call_edges(fn["id"], r, own, exporters)
                stats["symbols"] += len(sn)
        (inter / f"batch-{i}.json").write_text(json.dumps({"nodes": nodes, "edges": edges}))
        inp.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
    say("4/6 nodes written; 5/6 merge")
    p = subprocess.run(["python3", str(SKILL / "merge-batch-graphs.py"), str(root)], capture_output=True, text=True, timeout=NODE_TIMEOUT)
    if p.returncode or not (inter / "assembled-graph.json").exists():
        raise RuntimeError(f"merge-batch-graphs.py failed ({p.returncode}), its last words: … {(p.stderr or p.stdout)[-2000:]}")  # cap: store
    g = json.loads((inter / "assembled-graph.json").read_text())
    nodes, edges = g.get("nodes") or [], g.get("edges") or []
    try:
        sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception:
        sha = ""
    layers = {}
    for n in nodes:
        path = str(n.get("filePath") or "")
        if path and "lineRange" not in n:
            layers.setdefault(path.split("/")[0] if "/" in path else "(root)", []).append(n["id"])
    readme = next((n["id"] for n in nodes if str(n.get("filePath", "")).lower() in ("readme.md", "readme.rst", "readme")), None)
    when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    kg = {"version": "1.0.0",
          "project": {"name": root.name, "languages": sorted({str(f.get("language")) for f in files if f.get("language") and f["language"] != "unknown"}),
                      "frameworks": [], "description": "", "analyzedAt": when, "gitCommitHash": sha},
          "nodes": nodes, "edges": edges,
          "layers": [{"id": f"layer:{k}", "name": "Repository root" if k == "(root)" else k, "description": "", "nodeIds": v}
                     for k, v in sorted(layers.items(), key=lambda kv: (kv[0] == "(root)", kv[0]))],
          "tour": [{"order": 1, "title": "Start here", "description": "The project's own introduction.", "nodeIds": [readme]}] if readme else []}
    kept = keep_explained(kg, old, changed, all_changed)
    (ua / "knowledge-graph.json").write_text(json.dumps(kg, ensure_ascii=False))
    try:                                            # the viewer's incremental features; the map stands without them
        (inter / "fingerprint-input.json").write_text(json.dumps({"projectRoot": str(root), "filePaths": [f["path"] for f in files], "gitCommitHash": sha}))
        node("build-fingerprints.mjs", str(inter / "fingerprint-input.json"))
    except Exception as e:
        say(f"fingerprints not built: {str(e)[:300]} …")  # cap: preview
    (ua / "meta.json").write_text(json.dumps({"lastAnalyzedAt": when, "gitCommitHash": sha, "version": "1.0.0", "analyzedFiles": len(files)}))
    report = {"files": len(files), "batches": len(batches), "nodes": len(nodes), "edges": len(edges), "symbols": stats["symbols"],
              "by_type": {k: v for k, v in stats.items() if k != "symbols"}, "edge_types": dict(Counter(e.get("type") for e in edges)),
              "skipped": len(skipped), "unreadable": sorted(unreadable), "placeholder": PLACEHOLDER, "seconds": round(time.time() - t0), "commit": sha,
              "kept": kept, "changed_files": len(changed) if not all_changed else None}
    (inter / "map-report.json").write_text(json.dumps(report))
    say(f"6/6 done: {report['files']} files, {report['nodes']} nodes, {report['edges']} edges, {report['symbols']} symbols, {kept} kept their explanation, in {report['seconds']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))

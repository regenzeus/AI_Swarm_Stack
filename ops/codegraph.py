#!/usr/bin/env python3
"""The code graph's view of the files a build touches (SWM-94): who calls them, what they call, the tests that cover them
and the requirements traced to those tests. The builder gets it before it changes code; the review page and both
reviewers see the same blast radius for the files the build really changed.

  python3 ops/codegraph.py <repo dir> <repo name> <file>...     the context pack as JSON

Sources: Graphify's merged graph of the repos' main branches (~/code/.graphify/merged-graph.json, kept by
ops/graphify-sync.sh), the repo's tests/test_*.py and requirements/*.yaml (ops/req.py). Reads only; stdlib + PyYAML.
"""
import json
import os
import re
import sys
from pathlib import Path
import textcap as TC                              # visible caps (AGENTS.md, truncation)
import deployment as DEPLOY                        # this deployment's hosts and paths (config/deployment.env)

GRAPH = Path(os.environ.get("CODE_GRAPH", f"{DEPLOY.CODE_DIR}/.graphify/merged-graph.json"))
EDGES = {"calls", "imports", "imports_from", "references", "indirect_call", "uses", "inherits"}
TOP = 8
_cache = {"mtime": None, "edges": {}}


def file_edges(repo, graph=GRAPH):
    """{(from file, to file): edge count} between different files of one repo, from the merged graph (cached)."""
    try:
        mtime = graph.stat().st_mtime
    except OSError:
        return {}
    if _cache["mtime"] != mtime:
        g = json.loads(graph.read_text())
        where = {n["id"]: (n.get("repo"), n.get("source_file")) for n in g.get("nodes") or []}
        by_repo = {}
        for e in g.get("links") or g.get("edges") or []:
            if e.get("relation") not in EDGES:
                continue
            (r1, f1), (r2, f2) = where.get(e.get("source"), (None, None)), where.get(e.get("target"), (None, None))
            if r1 and r1 == r2 and f1 and f2 and f1 != f2:
                d = by_repo.setdefault(r1, {})
                d[(f1, f2)] = d.get((f1, f2), 0) + 1
        _cache.update(mtime=mtime, edges=by_repo)
    return _cache["edges"].get(repo, {})


def module_of(path):
    """ops/builds.py -> builds; images/swarm/ledger.py -> ledger; a .js file -> its file name."""
    p = Path(path)
    return p.stem if p.suffix == ".py" else p.name


def tests_for(root, files):
    """{file: [tests/test_x.py, ...]}: test files that import the file's module or name its path."""
    tests = sorted((Path(root) / "tests").glob("test_*.py"))
    texts = {f"tests/{t.name}": t.read_text(errors="replace") for t in tests}
    out = {}
    for f in files:
        mod = re.escape(module_of(f))
        pat = re.compile(rf"(^\s*(import|from)\s+{mod}\b|\bimport\s+[\w, ]*\b{mod}\b|{re.escape(f)}|[\"']{mod}[\"'])", re.M)
        out[f] = sorted(t for t, s in texts.items() if t == f or pat.search(s))
    return out


def requirements_for(root, test_files, files):
    """Requirement ids whose verification names one of these test files or files (inspection by a path)."""
    try:
        sys.path.insert(0, str(Path(root) / "ops"))
        import req as R
        _, records, _ = R.load(Path(root))
    except Exception:
        return {}
    out = {}
    for rid, r in records.items():
        by = (r.get("verify") or {}).get("by") or [] if isinstance(r.get("verify"), dict) else []
        for b in by:
            path = str(b).split("::")[0]
            if path in test_files or path in files:
                out.setdefault(path, set()).add(rid)
    return {k: sorted(v) for k, v in out.items()}


def pack(root, repo, files, graph=GRAPH):
    """The context pack: per file its callers, callees, tests and requirements, and the totals."""
    files = TC.first([f for f in dict.fromkeys(str(x) for x in files or []) if f and f != "*"], 30, "files for a context pack")  # cap: untrusted
    edges = file_edges(repo, graph)
    tests = tests_for(root, files)
    alltests = sorted({t for v in tests.values() for t in v})
    reqs = requirements_for(root, set(alltests), set(files))
    per = {}
    for f in files:
        callers = sorted(((n, a) for (a, b), n in edges.items() if b == f), key=lambda x: (-x[0], x[1]))    # most edges first
        callees = sorted(((n, b) for (a, b), n in edges.items() if a == f), key=lambda x: (-x[0], x[1]))
        rs = sorted(set(reqs.get(f, [])) | {x for t in tests.get(f, []) for x in reqs.get(t, [])})
        per[f] = {"callers": [p for _, p in callers[:TOP]], "callees": [p for _, p in callees[:TOP]], "tests": tests.get(f, []),  # cap: list (more_callers counts the rest)
                  "requirements": rs, "more_callers": max(0, len(callers) - TOP)}
    return {"repo": repo, "files": per, "tests": alltests, "requirements": sorted({x for v in per.values() for x in v["requirements"]}),
            "graph": bool(edges)}


def text(p, title="Blast radius (from the code graph of main)"):
    """The pack in a few lines for a prompt."""
    if not p or not p.get("files"):
        return ""
    rows = [f"## {title}"]
    for f, d in p["files"].items():
        bits = []
        if d["callers"]:
            bits.append("used by " + ", ".join(d["callers"]) + (f" (+{d['more_callers']})" if d.get("more_callers") else ""))
        if d["callees"]:
            bits.append("uses " + ", ".join(d["callees"]))
        bits.append("tests: " + (", ".join(d["tests"]) or "none found"))
        if d["requirements"]:
            bits.append("requirements: " + ", ".join(d["requirements"]))
        rows.append(f"- {f}: " + "; ".join(bits))
    if not p.get("graph"):
        rows.append("(the code graph has no entry for this repo yet: callers and callees are missing)")
    return "\n".join(rows)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(2)
    print(json.dumps(pack(sys.argv[1], sys.argv[2], sys.argv[3:]), indent=1))

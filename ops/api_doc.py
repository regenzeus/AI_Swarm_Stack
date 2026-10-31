#!/usr/bin/env python3
"""docs/API.md, drawn from images/mission-control/server.py (QA-19): every HTTP route of the app and of the run
record's ingest, with its methods and the first sentence of its handler's docstring, and every MCP tool the app
offers. A route without a docstring is a problem; tests/test_docs.py fails when docs/API.md is stale.

  python3 ops/api_doc.py           write docs/API.md
  python3 ops/api_doc.py check     exit 1 when it is stale or a route has no docstring
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "images/mission-control/server.py"
OUT = ROOT / "docs/API.md"
APPS = {"app": ("Mission Control (port 8090, behind `tailscale serve`)",
                "Every `/api/` and `/share` route needs the `Tailscale-User-Login` header that `tailscale serve` adds "
                "(`TailnetOnly`); a request without it gets 403. Answers are never cached (APP-09). Only `/api/request` "
                "acts, through the runner's inbox; the writes the app does itself are the documented exceptions of SEC-12 "
                "(chat, the run record, the owner's phone and connection answers, push subscriptions, client errors)."),
        "rt_app": ("Run record ingest (port 8093, published to 127.0.0.1 only)",
                   "For the stack's own writers (the runner, Hermes' runtime plugin, Claude's hook). `/ingest` and "
                   "`/problems` need `Authorization: Bearer` with Hermes' API key, which the app and these writers share.")}


def first(doc):
    return " ".join((doc or "").strip().split("\n\n")[0].split())


def routes(tree, funcs):
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in APPS:
            rows = []
            for r in ast.walk(node.value):
                if isinstance(r, ast.Call) and getattr(r.func, "id", "") == "Route" and isinstance(r.args[0], ast.Constant):
                    h = r.args[1]
                    methods = next((ast.literal_eval(k.value) for k in r.keywords if k.arg == "methods"), ["GET"])
                    if isinstance(h, ast.Lambda):
                        doc = "Liveness: answers ok."
                    else:
                        doc = first(ast.get_docstring(funcs[h.id])) if h.id in funcs else ""
                    rows.append((r.args[0].value, methods, getattr(h, "id", "lambda"), doc))
            out[node.targets[0].id] = rows
    return out


def tools(tree, funcs):
    rows = []
    for f in funcs.values():
        for d in f.decorator_list:
            if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool":
                name = next((k.value.value for k in d.keywords if k.arg == "name" and isinstance(k.value, ast.Constant)), f.name)
                desc = next((k.value for k in d.keywords if k.arg == "description"), None)
                text = desc.value if isinstance(desc, ast.Constant) else first(ast.get_docstring(f)) or ""
                server = getattr(d.func.value, "id", "")
                rows.append((server, name, " ".join(str(text).split())))
    return sorted(set(rows))


def build():
    tree = ast.parse(SERVER.read_text())
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    rs, problems = routes(tree, funcs), []
    md = ["# Mission Control API", "",
          "Drawn from `images/mission-control/server.py` by `python3 ops/api_doc.py`; `tests/test_docs.py` fails when",
          "this file is stale. Do not edit it by hand: change the handler's docstring and run the script.", ""]
    for app, (title, intro) in APPS.items():
        md += [f"## {title}", "", intro, "", "| Route | Methods | What it does |", "|---|---|---|"]
        for path, methods, handler, doc in rs.get(app, []):
            if not doc:
                problems.append(f"{path}: {handler} has no docstring")
            md.append(f"| `{path}` | {', '.join(methods)} | {doc.replace('|', '/')} |")
        md.append("")
    md += ["## MCP tools", "", "Offered to the agents through LiteLLM's MCP gateway, each under its server's key grants "
           "(`config/litellm/config.yaml`).", "", "| Server | Tool | What it does |", "|---|---|---|"]
    md += [f"| {s} | `{n}` | {t.replace('|', '/')} |" for s, n, t in tools(tree, funcs)]
    return "\n".join(md) + "\n", problems


def main():
    text, problems = build()
    if sys.argv[1:] == ["check"]:
        stale = not OUT.exists() or OUT.read_text() != text
        for p in problems + (["docs/API.md is stale: run python3 ops/api_doc.py"] if stale else []):
            print("  ", p)
        return 1 if problems or stale else 0
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)}" + (f" ({len(problems)} routes without a docstring)" if problems else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""docs/API.md, drawn from images/mission-control/server.py (QA-19): every HTTP route of the app and of the run
record's ingest, with its methods and the first sentence of its handler's docstring, and every MCP tool the app
offers. A route without a docstring is a problem; tests/test_docs.py fails when docs/API.md is stale.

  python3 ops/api_doc.py           write docs/API.md
  python3 ops/api_doc.py check     exit 1 when it is stale or a route has no docstring
"""
import ast
import re
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
                   "`/problems` need `Authorization: Bearer` with Hermes' API key, which the app and these writers share."),
        "voice_app": ("Voice gateway (port 8095, published to 127.0.0.1:11435 only)",
                      "Ollama's API for Home Assistant's Ollama integration on the NAS (VOI-03, docs/HOME-VOICE.md). Every "
                      "route but `/api/version` needs `Authorization: Bearer` with `VOICE_KEY`; with no key set, all refuse.")}


def first(doc):
    return " ".join((doc or "").strip().split("\n\n")[0].split())


PART = re.compile(r'^_part\("([^"]+)"\).*$', re.M)


def joined(path):
    """A Python file kept in parts (PLT-25) as one text: each part in place of its _part(...) line."""
    return PART.sub(lambda m: path.with_name(m.group(1)).read_text().rstrip("\n"), path.read_text())


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


def text_of(node, consts):
    """A description as the code builds it: a string, a module constant, a + of them, an f-string of them (review APP-R13:
    only a plain string was read, so five tools showed an empty description)."""
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Name):
        return consts.get(node.id, "")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return text_of(node.left, consts) + text_of(node.right, consts)
    if isinstance(node, ast.JoinedStr):
        return "".join(text_of(v.value if isinstance(v, ast.FormattedValue) else v, consts) for v in node.values)
    return ""


def servers_of(tree):
    """{variable: [server names]}: X = MCPServer("name"), and a factory's server under every name it is called with
    (memory_server("memory", ...) and memory_server("memorypublic", ...) build one set of tools twice)."""
    out, factories = {}, {}
    for f in ast.walk(tree):
        if isinstance(f, ast.FunctionDef):
            for n in ast.walk(f):
                if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "MCPServer"
                        and n.value.args and isinstance(n.value.args[0], ast.Name)):
                    factories[f.name] = (n.targets[0].id, [a.arg for a in f.args.args].index(n.value.args[0].id))
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
            fn = getattr(n.value.func, "id", "")
            if fn == "MCPServer" and n.value.args and isinstance(n.value.args[0], ast.Constant):
                out.setdefault(n.targets[0].id, []).append(n.value.args[0].value)
            elif fn in factories:
                var, i = factories[fn]
                if len(n.value.args) > i and isinstance(n.value.args[i], ast.Constant):
                    out.setdefault(var, []).append(n.value.args[i].value)
    return out


def tools(tree, funcs):
    consts = {n.targets[0].id: text_of(n.value, {}) for n in tree.body
              if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
              and isinstance(n.value, (ast.Constant, ast.BinOp, ast.JoinedStr))}
    names = servers_of(tree)
    rows = []
    for f in funcs.values():
        for d in f.decorator_list:
            if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool":
                name = next((k.value.value for k in d.keywords if k.arg == "name" and isinstance(k.value, ast.Constant)), f.name)
                desc = next((k.value for k in d.keywords if k.arg == "description"), None)
                text = (text_of(desc, consts) if desc is not None else "") or first(ast.get_docstring(f)) or ""
                var = getattr(d.func.value, "id", "")
                for server in names.get(var) or [var]:
                    rows.append((server, name, " ".join(str(text).split())))
    return sorted(set(rows))


def build():
    tree = ast.parse(joined(SERVER))                   # PLT-25: server.py with its parts in place, as it runs
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
    for s_, n, t in tools(tree, funcs):
        if not t:
            problems.append(f"MCP tool {n} ({s_}) has no description")
        md.append(f"| {s_} | `{n}` | {t.replace('|', '/')} |")
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

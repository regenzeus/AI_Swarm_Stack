"""Fill in the code map where Understand Anything only wrote placeholders.

When `opencode run` can't hand files to the plugin's analyser agents, Understand Anything falls back to a structural
graph: every node exists, but files say "python code file in the <repo> repository.", functions "Function defined in
<path>.", and layers are plain top-level folders. This pass makes that graph worth reading:
  1. drops nodes of tool output that is not the project (graphify-out/, .ua/, node_modules/), with their edges
  2. explains every file and its functions/classes from the code itself (gpt-sub-fast, several small files per call)
  3. splits oversized folder layers into their sub-folders, gathers single root files, and describes each layer
It only rewrites placeholders, saves after every call (an interrupted run resumes where it stopped), keeps the
structural graph as knowledge-graph.fallback.json, and writes its progress to /srv/ai/state/ua-enrich-<repo>.json
(shown on the repo page). The code is read, never run; text in it is data for the model, not instructions.
  python3 ops/ua_enrich.py <repo dir> <repo name>       (key: VK_CODE, as make understand sets it; ops/onboard.py runs it as a step)
Exit 75 = stopped on the ChatGPT usage limit (resume later: make ua-enrich REPO=<name>).
"""
import json
import textcap as TC                              # visible caps (AGENTS.md, truncation)
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md

LITELLM = os.environ.get("LITELLM_URL", "http://127.0.0.1:4000/v1/chat/completions")
MODEL = "gpt-sub-fast"
STATE = Path(os.environ.get("UA_ENRICH_STATE", "/srv/ai/state"))
IGNORE = ("graphify-out/", ".ua/", "node_modules/", ".git/", "__pycache__/", ".venv/")
PLACEHOLDER = re.compile(r"(?:^\(not yet explained\)$|^Auto-generated node for |"                           # ops/ua_map_in.py's own, and a plugin fallback's
                         r"file in the [\w.-]+ repository\.$|^(?:Function|Class|Method|Interface|Type|Variable) defined in |"
                         r"^Project files and components under |^\s*$|"
                         r"^[\w+#. -]{1,30} (?:code|config|docs|infra|script|data|test) file(?:;.*)?\.$|"   # "go code file; 1 functions."
                         r"^Python project module providing |^Implements [\w.]+ within [\w./-]+\.$|^Project configuration for |"
                         r"^Not (?:shown|present|enough|visible|included)\b)")                            # an excerpt that missed it
BATCH_CHARS = 26000                                  # code per call; one big file is cut into symbol excerpts
FILE_CHARS = 14000
SPLIT_OVER = 30                                      # a folder layer with more nodes than this becomes its sub-folders

EMPTY = "An empty file: nothing in it to explain."
EMPTY_PY = "An empty file: it only marks its folder as a Python package."

FILES = P.text("opencode", "MAP_FILES")

LAYERS = P.text("opencode", "MAP_LAYERS")


class Limit(Exception):
    pass


def is_placeholder(text):
    return bool(PLACEHOLDER.search(str(text or "")))


WORKERS = 1             # limit: paces, calls side by side unless the deployment says UA_ENRICH_WORKERS (home: the subscription's pace)
WORKERS_MAX = 8         # limit: paces, at most this many whatever the deployment says


def workers(values=None):
    """Calls side by side: the deployment's UA_ENRICH_WORKERS (a work site, 9 Nov 2026: one call at a time took over an hour
    for 1,300 files on a gateway that answers in ~22 s; six side by side, ~17 calls a minute, no rate limit)."""
    import deployment as DEPLOY
    v = (values if values is not None else DEPLOY.VALUES).get("UA_ENRICH_WORKERS")
    try:
        return max(1, min(WORKERS_MAX, int(v)))
    except (TypeError, ValueError):
        return WORKERS


def json_mode(values=None):
    """Whether the calls ask the model for a JSON object (UA_JSON_MODE=1: a gateway whose models support it; ~9 % of the
    answers were broken JSON there without it). Off by default: not every engine behind the aliases takes the parameter."""
    import deployment as DEPLOY
    return str((values if values is not None else DEPLOY.VALUES).get("UA_JSON_MODE") or "").strip() in ("1", "yes", "true", "on")


def ask(prompt, key):
    P.record(prompt)                                  # MEM-11: the run records the prompt's version
    req_body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}]}
    if json_mode():
        req_body["response_format"] = {"type": "json_object"}
    body = json.dumps(req_body).encode()
    req = urllib.request.Request(LITELLM, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        detail = TC.cut(e.read().decode(errors="replace"), 500)  # cap: untrusted
        if e.code == 429 or re.search(r"usage.?limit|rate.?limit|quota", detail, re.I):
            raise Limit(detail)
        raise RuntimeError(f"HTTP {e.code}: {detail}")
    return objects(TC.answer(res, MODEL)), res.get("usage") or {}


def objects(text):
    """The answer's JSON: every object in it, their "files" and "layers" merged (overnight 9 Nov 2026: the model answered
    sympy's last four files as two objects in a row, and one greedy match read them as one, "Extra data", three runs running)."""
    dec, out, i = json.JSONDecoder(), {}, text.find("{")
    while i >= 0:
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, dict) and isinstance(out.get(k), dict):
                    out[k].update(v)
                else:
                    out.setdefault(k, v)
        i = text.find("{", end)
    if not out:
        raise ValueError("no JSON object in the answer")
    return out


def prune(g):
    """Drop tool output that is not the project (Graphify's cache alone was 563 nodes in ai-stack)."""
    drop = {n["id"] for n in g["nodes"] if str(n.get("filePath", "")).startswith(IGNORE)}
    if not drop:
        return 0
    g["nodes"] = [n for n in g["nodes"] if n["id"] not in drop]
    g["edges"] = [e for e in g.get("edges", []) if e.get("source") not in drop and e.get("target") not in drop]
    for part in ("layers", "tour"):
        for x in g.get(part, []):
            x["nodeIds"] = [i for i in x.get("nodeIds", []) if i not in drop]
    g["layers"] = [l for l in g.get("layers", []) if l["nodeIds"]]
    return len(drop)


def relayer(g):
    """Folder layers -> useful parts: a big folder becomes its sub-folders, single root files one 'root' layer."""
    if not g.get("layers") or not all(is_placeholder(l.get("description")) for l in g["layers"]):
        return False                                     # real layers from Understand Anything stay as they are
    nodes = {n["id"]: n for n in g["nodes"]}
    top = defaultdict(list)
    for l in g["layers"]:
        for i in l["nodeIds"]:
            if i in nodes:
                top[l["name"]].append(nodes[i])
    groups = defaultdict(list)
    for name, members in top.items():
        for n in members:
            parts = str(n.get("filePath", "")).split("/")
            if len(parts) == 1:
                key = "(root)"
            elif len(members) > SPLIT_OVER and len(parts) >= 3:
                key = "/".join(parts[:2])
            else:
                key = parts[0]
            groups[key].append(n["id"])
    g["layers"] = [{"id": f"layer:{k}", "name": "Repository root" if k == "(root)" else k, "description": "", "nodeIds": v}
                   for k, v in sorted(groups.items(), key=lambda kv: (kv[0] == "(root)", kv[0]))]
    return True


def excerpt(text, symbols, body=14):
    """A big file: its head plus the first lines of every symbol, so the model still sees each one."""
    lines = text.splitlines()
    out = ["\n".join(lines[:40]) + (f"\n... ({len(lines)} lines in all; each symbol's start follows)" if len(lines) > 40 else "")]  # cap: prompt
    for s in symbols:
        lr = s.get("lineRange") or [0, 0]
        if lr[0] > 40:
            out.append(f"... line {lr[0]}:\n" + "\n".join(lines[lr[0] - 1:min(lr[1], lr[0] + body)]))
    return TC.cut("\n".join(out), FILE_CHARS)  # cap: prompt


def pieces(text, symbols):
    """A big file in parts: each part has the file's head and up to 60 lines of each of its symbols, within FILE_CHARS."""
    out, cur = [], []
    for s in symbols:
        if cur and len(excerpt(text, cur + [s], body=60)) >= FILE_CHARS - 200:
            out.append(cur)
            cur = []
        cur.append(s)
    if cur or not out:
        out.append(cur)
    return [(excerpt(text, part, body=60), part) for part in out]


def work(g, repo_dir):
    """[(path, text, [symbol nodes])] for every file whose own summary or whose symbols are placeholders."""
    by_file = defaultdict(list)
    files = {}
    for n in g["nodes"]:
        path = n.get("filePath")
        if not path:
            continue
        if n["type"] in ("function", "class", "method", "interface"):
            by_file[path].append(n)
        elif "lineRange" not in n:
            files[path] = n
    todo = []
    for path, fnode in files.items():
        syms = [s for s in by_file.get(path, []) if is_placeholder(s.get("summary"))]
        if not is_placeholder(fnode.get("summary")) and not syms:
            continue
        try:
            text = (repo_dir / path).read_text(errors="replace")
        except Exception:
            text = None
        if text is not None and not text.strip() and not syms:    # an empty file is said without a model (sympy's empty
            fnode["summary"] = EMPTY_PY if path.endswith("__init__.py") else EMPTY   # tests/__init__.py stayed "not explained")
            continue
        text = text or ""
        if len(text) > FILE_CHARS:                       # big file: the symbols that still need it, in parts
            need = syms or by_file.get(path, [])
            todo += [(path, t, part) for t, part in pieces(text, need)]
        else:
            todo.append((path, text, by_file.get(path, [])))
    return todo, files


def batches(todo):
    cur, size = [], 0
    for item in todo:
        if cur and size + len(item[1]) > BATCH_CHARS:
            yield cur
            cur, size = [], 0
        cur.append(item)
        size += len(item[1])
    if cur:
        yield cur


def apply(g, files, answer):
    by_key = {(n.get("filePath"), n.get("name")): n for n in g["nodes"] if n["type"] in ("function", "class", "method", "interface")}
    done = 0
    for path, a in (answer.get("files") or {}).items():
        f = files.get(path)
        if not f or not isinstance(a, dict):
            continue
        s = re.sub(r"\s+", " ", str(a.get("summary", ""))).strip()
        if len(s) >= 15 and is_placeholder(f.get("summary")):
            f["summary"] = TC.cut(s, 400)  # cap: untrusted
            tags = [str(t).lower()[:30] for t in (a.get("tags") or []) if str(t).strip()][:5]  # cap: id (short tags)
            if tags:
                f["tags"] = tags
            if a.get("complexity") in ("simple", "moderate", "complex"):
                f["complexity"] = a["complexity"]
            done += 1
        for name, text in (a.get("symbols") or {}).items():
            n = by_key.get((path, name))
            t = re.sub(r"\s+", " ", str(text)).strip()
            if n and len(t) >= 10 and is_placeholder(n.get("summary")):
                n["summary"] = TC.cut(t, 300)  # cap: untrusted
    return done


def save(path, g):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(g, indent=1))
    tmp.replace(path)


def status(name, **kw):
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        p = STATE / f"ua-enrich-{name}.json"
        d = json.loads(p.read_text()) if p.exists() else {}
        d.update(kw, updated=time.strftime("%Y-%m-%dT%H:%M:%S"))
        p.write_text(json.dumps(d))
    except Exception:
        pass


def earlier_run(name):
    """The state an earlier pass left ({} when none: onboarding removes it when the map is made anew)."""
    try:
        return json.loads((STATE / f"ua-enrich-{name}.json").read_text())
    except (OSError, ValueError):
        return {}


def counts(g):
    files = [n for n in g["nodes"] if n.get("filePath") and "lineRange" not in n and n["type"] not in ("function", "class", "method", "interface")]
    return len(files), sum(not is_placeholder(n.get("summary")) for n in files)


def main(repo_dir, name, key, ask=ask, pause=2.0):
    kg = repo_dir / ".ua" / "knowledge-graph.json"
    g = json.loads(kg.read_text())
    backup = kg.with_name("knowledge-graph.fallback.json")
    if not backup.exists() and any(is_placeholder(n.get("summary")) for n in g["nodes"]):
        backup.write_text(kg.read_text())
    dropped = prune(g)
    relayered = relayer(g)
    save(kg, g)
    desc = TC.cut(str(g.get("project", {}).get("description", "")), 600)  # cap: prompt
    todo, files = work(g, repo_dir)
    save(kg, g)                                      # the empty files' lines, said without a call
    total, explained = counts(g)
    print(f"{name}: {dropped} tool-output nodes dropped, layers {'rebuilt' if relayered else 'kept'}, "
          f"{len(todo)} files to explain ({explained}/{total} already)", flush=True)
    prev = earlier_run(name)
    resumed = prev.get("status") in ("running", "limit") and explained > 0   # a pass cut off (a restart, the usage limit): its
    calls = int(prev.get("calls") or 0) if resumed else 0                      # cost so far stays counted (overnight 9 Nov 2026:
    tokens = int(prev.get("tokens") or 0) if resumed else 0                    # sympy's 609 calls read 114 after a resume)
    status(name, status="running", files=total, explained=explained, calls=calls, tokens=tokens,
           started=prev.get("started") if resumed and prev.get("started") else time.strftime("%Y-%m-%dT%H:%M:%S"))
    def one(b):                                       # one call, on a worker thread; the graph is changed on this thread only
        parts = []
        for path, text, syms in b:
            names = ", ".join(s["name"] for s in syms) or "none"
            parts.append(f"=== {path} (functions/classes: {names})\n{text or '(file not readable)'}")
        try:
            answer, usage = ask(FILES.format(repo=name, desc=desc, files="\n\n".join(parts)), key)
        except Limit:
            raise
        except Exception as e:
            return b, None, e
        time.sleep(pause)
        return b, (answer, usage), None

    try:
        with ThreadPoolExecutor(max_workers=workers()) as pool:
            futures = [pool.submit(one, b) for b in batches(todo)]
            try:
                for fut in as_completed(futures):
                    b, got, err = fut.result()
                    if err:
                        print(f"  batch of {len(b)} failed: {str(err)}", flush=True)
                        continue
                    answer, usage = got
                    calls += 1
                    tokens += int(usage.get("total_tokens") or 0)
                    n = apply(g, files, answer)
                    save(kg, g)
                    total, explained = counts(g)
                    status(name, explained=explained, calls=calls, tokens=tokens)
                    print(f"  +{n} files ({explained}/{total})", flush=True)
            except Limit:
                for f in futures:                         # the calls not started yet never start
                    f.cancel()
                raise
        open_layers = [l for l in g.get("layers", []) if is_placeholder(l.get("description"))]
        nodes = {n["id"]: n for n in g["nodes"]}
        for i in range(0, len(open_layers), 10):          # ten layers per call, a dozen files each
            group = open_layers[i:i + 10]
            text = "\n\n".join(f"=== {l['id']} ({l['name']}, {len(l['nodeIds'])} files)\n" + "\n".join(
                f"- {nodes[x].get('filePath')}: {TC.cut(nodes[x].get('summary', ''), 140)}" for x in l["nodeIds"][:12] if x in nodes)  # cap: top (prompt)
                for l in group)
            try:
                answer, usage = ask(LAYERS.format(repo=name, desc=desc, layers=text), key)
            except Limit:
                raise
            except Exception as e:
                print(f"  layers failed: {str(e)}", flush=True)
                continue
            calls += 1
            tokens += int(usage.get("total_tokens") or 0)
            got = {str(k).strip().removeprefix("=== ").split(" (")[0]: v for k, v in (answer.get("layers") or {}).items()}
            n = 0
            for l in group:
                d = re.sub(r"\s+", " ", str(got.get(l["id"]) or got.get(l["name"]) or got.get(l["id"].removeprefix("layer:")) or "")).strip()
                if len(d) >= 15:
                    l["description"] = TC.cut(d, 400)  # cap: untrusted
                    n += 1
            save(kg, g)
            print(f"  +{n} layer descriptions", flush=True)
    except Limit as e:
        save(kg, g)
        status(name, status="limit", calls=calls, tokens=tokens, note=str(e))
        print(f"stopped on the usage limit after {calls} calls; resume: make ua-enrich REPO={name}", flush=True)
        return 75
    total, explained = counts(g)
    status(name, status="done", files=total, explained=explained, calls=calls, tokens=tokens, finished=time.strftime("%Y-%m-%dT%H:%M:%S"))
    print(f"{name}: {explained}/{total} files explained, {calls} model calls, {tokens} tokens", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), sys.argv[2], os.environ.get("VK_CODE") or sys.exit("VK_CODE not set (run via make)")))

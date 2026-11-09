"""Templates for the builder (GEN-34, docs/AI-STACK.md §5): what the Templates screen lists, checks, saves and test-runs.

A template is YAML in its canonical form (engine/graph.py). The builder edits its structure as JSON, the same shape the
YAML has; save() checks it with the graph model's own load() and writes the canonical YAML, so what the builder saved
is exactly what review reads. Until packs exist (WP8), a saved template is a draft in DRAFTS; its commit to a pack and
the owner's approval come with packs.

    listing()        every template: the repository's (config/templates) and the drafts, each with its spec or its problem
    agents()         the agents a block may name: the stack's cards that can do a step
    save(spec, layout) -> {"ok", "name", "yaml"} or {"ok": False, "error"}, the error in the graph model's own words;
                     the editor's block positions go to <name>.layout.json beside it, never into the template
    describe(text, name, ask)  a template drafted from the owner's description by the intake's model (the prompt
                     intake/TEMPLATE), checked by the graph model, asked once more with the refusal, and saved as a draft
    handle(req)      the runner's actions: template_save, template_test, template_describe
"""
import json
import os
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import graph as G  # noqa: E402
import prompts as P  # noqa: E402
import textcap as TC  # noqa: E402

TRIES = 2                       # limit: stops, a description is drafted twice at most: the second time with the first's refusal

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT / "config/templates"
DRAFTS = Path(os.environ.get("AISTACK_TEMPLATE_DRAFTS") or "/srv/ai/templates/drafts")


def _file_name(name):
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") + ".yaml"


def _layout(path):
    try:
        d = json.loads(path.with_suffix(".layout.json").read_text(encoding="utf-8"))
        return {k: {"x": float(v["x"]), "y": float(v["y"])} for k, v in d.items()} if isinstance(d, dict) else {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _one(path, source):
    text = path.read_text(encoding="utf-8")
    try:
        g = G.canonical(text)
        return {"name": g.name, "source": source, "about": g.about, "yaml": text, "spec": yaml.safe_load(text), "nodes": len(g.nodes),
                "layout": _layout(path)}
    except ValueError as e:                        # shown with its reason, never hidden, and still opens to be mended
        try:
            spec = yaml.safe_load(text)
        except yaml.YAMLError:
            spec = None
        ok = isinstance(spec, dict) and isinstance(spec.get("nodes"), dict) and spec["nodes"]
        return {"name": str(spec.get("template") or path.stem) if ok else path.stem, "source": source, "problem": str(e).splitlines()[0],
                "yaml": text, **({"spec": spec, "layout": _layout(path), "nodes": len(spec["nodes"])} if ok else {})}


def listing(drafts=None, packs=()):
    """Every template: the repository's, each running pack's (at its approved commit), and the drafts."""
    drafts = Path(drafts or DRAFTS)
    out = [_one(p, "repository") for p in sorted(REPO.rglob("*.yaml"))]
    out += [{**_one(Path(t["path"]), f"pack {p['name']} @ {p['commit'][:8]}"), "pack": p["name"]} for p in packs or () for t in p["templates"]]
    if drafts.is_dir():
        out += [_one(p, "draft") for p in sorted(drafts.glob("*.yaml"))]
    return out


def agents(packs=()):
    """The cards a block may name: the stack's (config/agents.yaml, those that can do a step) and each running pack's
    (<pack>:<agent>), by id with their harness and purpose."""
    try:
        reg = yaml.safe_load((ROOT / "config/agents.yaml").read_text())
    except OSError:
        reg = {}
    core = [{"id": a["id"], "name": a.get("name") or a["id"], "harness": a.get("harness", ""), "purpose": a.get("purpose", "")}
            for a in reg.get("agents") or [] if G.runs_steps(a)]
    return core + [{k: a[k] for k in ("id", "name", "harness", "purpose", "pack")} for p in packs or () for a in p["agents"]]


def save(spec, drafts=None, layout=None):
    """Checks the editor's template with the graph model and writes its canonical YAML as a draft, and the blocks'
    positions, of the blocks it has, beside it."""
    drafts = Path(drafts or DRAFTS)
    try:
        text = yaml.safe_dump(spec, sort_keys=False, allow_unicode=True)
        g = G.load(text)
    except (ValueError, yaml.YAMLError, TypeError, AttributeError, KeyError) as e:
        return {"ok": False, "error": str(e).splitlines()[0]}
    canon = G.dump(g)
    drafts.mkdir(parents=True, exist_ok=True)
    path = drafts / _file_name(g.name)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(canon, encoding="utf-8")
    tmp.replace(path)
    ids = {n.id for n in g.nodes}
    try:
        pos = {k: {"x": round(float(v["x"])), "y": round(float(v["y"]))} for k, v in (layout or {}).items() if k in ids}
    except (KeyError, TypeError, ValueError, AttributeError):
        pos = {}
    lay = path.with_suffix(".layout.json")
    tmp = lay.with_suffix(".tmp")
    tmp.write_text(json.dumps(pos, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(lay)
    return {"ok": True, "name": g.name, "yaml": canon, "path": str(path)}


def _ask(prompt):
    """The intake's own model and key, as every other intake prompt (ops/missions.py ask_json)."""
    import missions as M
    return M.ask_json(prompt, os.environ["VK_INTAKE"])


def describe(text, name, ask=None, drafts=None):
    """The owner's description -> a drafted template, saved as a draft like any other, or why not. The model's answer
    is untrusted: only the template's own fields pass, and the graph model checks it before anything is written."""
    text, name = str(text or "").strip(), str(name or "").strip()
    if not text:
        return {"ok": False, "error": "say in a sentence or two what the template should do"}
    if not G.NAME.fullmatch(name):
        return {"ok": False, "error": "give it a name of letters, digits and dashes, e.g. weekly-review"}
    cards = "\n".join(f"- {a['id']}: {a.get('purpose') or a.get('name')}" for a in agents())
    earlier, why = "", ""
    for _ in range(TRIES):
        prompt = P.text("intake", "TEMPLATE").format(text=TC.cut(text, 4000), name=name, agents=cards, earlier=earlier)   # cap: prompt
        try:
            raw = (ask or _ask)(prompt)
        except Exception as e:                       # the model or its gateway: said, not hidden
            return {"ok": False, "error": f"the model did not answer: {type(e).__name__}: {TC.cut(str(e), 200)}"}   # cap: preview
        spec = {"template": name, "about": TC.cut(str((raw or {}).get("about") or ""), 300),   # cap: untrusted
                "nodes": (raw or {}).get("nodes") or {}, "edges": (raw or {}).get("edges") or []}
        r = save(spec, drafts)
        if r.get("ok"):
            return {**r, "spec": yaml.safe_load(r["yaml"]), "drafted": True}
        why = r["error"]
        earlier = (f"Your first draft was refused: {why}\nIt was:\n{TC.cut(json.dumps(raw, ensure_ascii=False), 6000)}\n"   # cap: prompt
                   "Draft it again so that this cannot happen.")
    return {"ok": False, "error": f"the drafts were refused: {why}"}


def path_of(name, drafts=None, packs=()):
    """A template's file by its name: a draft first, then the repository's, then a running pack's."""
    for p in [Path(drafts or DRAFTS) / _file_name(name), *REPO.rglob("*.yaml"), *(Path(t["path"]) for pk in packs or () for t in pk["templates"])]:
        if p.is_file():
            try:
                if p.parent == Path(drafts or DRAFTS) or G.load(p.read_text(encoding="utf-8")).name == name:
                    return p
            except ValueError:
                continue
    return None


def handle(req, start=None, drafts=None, ask=None, packs=None):
    """The runner's template actions. start(name, path) -> run id starts a test run on the engine (None: not running);
    ask(prompt) -> the model's JSON (default: the intake's model)."""
    a = req.get("action")
    if a == "template_describe":
        return describe(req.get("text"), req.get("name"), ask, drafts)
    if a == "template_save":
        return save(req.get("spec") or {}, drafts, req.get("layout"))
    if a == "template_test":
        if packs is None:
            from engine import packs as PK
            packs = PK.load()["packs"]
        p = path_of(str(req.get("name") or ""), drafts, packs)
        if p is None:
            return {"ok": False, "error": "save the template first: a test run starts from what was saved"}
        if start is None:
            return {"ok": False, "error": "the engine does not run on this deployment yet (ENGINE=conductor): test runs start in the preview"}
        return {"ok": True, "run": start(str(req.get("name")), str(p))}
    return {"ok": False, "error": f"unknown template action {a}"}

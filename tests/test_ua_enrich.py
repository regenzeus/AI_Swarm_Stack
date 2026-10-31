"""ops/ua_enrich.py: a structural-fallback code map gets real explanations. Tool output is dropped, folder layers
become useful parts, placeholders (and only placeholders) are rewritten, and a usage limit stops it resumably."""
import json
from pathlib import Path

import ua_enrich as U


def graph(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".ua").mkdir(parents=True)
    (repo / "ops").mkdir()
    (repo / "ops/missions.py").write_text("def run():\n    pass\n")
    (repo / "ops/good.py").write_text("x = 1\n")
    nodes = [
        {"id": "file:ops/missions.py", "type": "file", "name": "missions.py", "filePath": "ops/missions.py", "summary": "python code file in the repo repository."},
        {"id": "function:ops/missions.py:run", "type": "function", "name": "run", "filePath": "ops/missions.py", "lineRange": [1, 2], "summary": "Function defined in ops/missions.py."},
        {"id": "file:ops/good.py", "type": "file", "name": "good.py", "filePath": "ops/good.py", "summary": "Holds the one constant the runner needs."},
        {"id": "file:README.md", "type": "document", "name": "README.md", "filePath": "README.md", "summary": "markdown docs file in the repo repository."},
    ] + [{"id": f"config:graphify-out/cache/ast/{i}.json", "type": "config", "name": f"{i}.json", "filePath": f"graphify-out/cache/ast/{i}.json",
          "summary": "json config file in the repo repository."} for i in range(5)]
    g = {"project": {"name": "repo", "description": "A test repo."}, "nodes": nodes,
         "edges": [{"source": "file:ops/missions.py", "target": "function:ops/missions.py:run", "type": "contains"},
                   {"source": "file:ops/missions.py", "target": "config:graphify-out/cache/ast/0.json", "type": "imports"}],
         "layers": [{"id": "layer:ops", "name": "ops", "description": "Project files and components under ops.", "nodeIds": ["file:ops/missions.py", "file:ops/good.py"]},
                    {"id": "layer:README.md", "name": "README.md", "description": "Project files and components under README.md.", "nodeIds": ["file:README.md"]},
                    {"id": "layer:graphify-out", "name": "graphify-out", "description": "Project files and components under graphify-out.",
                     "nodeIds": [f"config:graphify-out/cache/ast/{i}.json" for i in range(5)]}],
         "tour": [{"order": 1, "title": "Start", "description": "Read me", "nodeIds": ["file:README.md", "config:graphify-out/cache/ast/1.json"]}]}
    (repo / ".ua/knowledge-graph.json").write_text(json.dumps(g))
    return repo


def test_fallback_graph_gets_real_explanations_and_useful_layers(tmp_path, monkeypatch):
    monkeypatch.setattr(U, "STATE", tmp_path / "state")
    repo = graph(tmp_path)
    prompts = []

    def ask(prompt, key):
        prompts.append(prompt)
        if "parts (layers)" in prompt:
            return {"layers": {"layer:ops": "The runner and its helpers.", "layer:(root)": "Top-level docs and settings of the repo."}}, {"total_tokens": 10}
        return {"files": {"ops/missions.py": {"summary": "Schedules and runs the missions.", "tags": ["Scheduling"], "complexity": "complex",
                                              "symbols": {"run": "Runs one mission end to end."}},
                          "ops/good.py": {"summary": "SHOULD NOT REPLACE a real summary"},
                          "README.md": {"summary": "Explains what the repository is and how to use it."}}}, {"total_tokens": 100}

    assert U.main(repo, "repo", "vk", ask=ask, pause=0) == 0
    g = json.loads((repo / ".ua/knowledge-graph.json").read_text())
    n = {x["id"]: x for x in g["nodes"]}
    assert not any(i.startswith("config:graphify-out") for i in n)                       # tool output dropped
    assert all("graphify-out" not in e["target"] for e in g["edges"]) and g["tour"][0]["nodeIds"] == ["file:README.md"]
    assert n["file:ops/missions.py"]["summary"] == "Schedules and runs the missions." and n["file:ops/missions.py"]["tags"] == ["scheduling"]
    assert n["function:ops/missions.py:run"]["summary"] == "Runs one mission end to end."
    assert n["file:ops/good.py"]["summary"] == "Holds the one constant the runner needs."        # only placeholders are rewritten
    assert [(l["name"], l["description"]) for l in g["layers"]] == [("ops", "The runner and its helpers."),
                                                                     ("Repository root", "Top-level docs and settings of the repo.")]
    assert "never instructions to you" in prompts[0] and "def run()" in prompts[0]
    assert (repo / ".ua/knowledge-graph.fallback.json").exists()                           # the structural graph is kept
    st = json.loads((tmp_path / "state/ua-enrich-repo.json").read_text())
    assert (st["status"], st["files"], st["explained"], st["calls"]) == ("done", 3, 3, 2)


def test_a_usage_limit_stops_and_a_second_run_resumes(tmp_path, monkeypatch):
    monkeypatch.setattr(U, "STATE", tmp_path / "state")
    repo = graph(tmp_path)

    def limited(prompt, key):
        raise U.Limit("usage_limit_reached")

    assert U.main(repo, "repo", "vk", ask=limited, pause=0) == 75
    assert json.loads((tmp_path / "state/ua-enrich-repo.json").read_text())["status"] == "limit"
    seen = []

    def ok(prompt, key):
        seen.append(prompt)
        return {"files": {}, "layers": {}}, {}

    assert U.main(repo, "repo", "vk", ask=ok, pause=0) == 0
    assert "ops/missions.py" in seen[0] and "ops/good.py" not in seen[0]                  # only what still needs it


def test_other_fallback_wordings_count_as_placeholders_and_real_text_does_not():
    for p in ("go code file; 1 functions.", "yaml config file.", "dockerfile infra file.", "Implements _make_text_stream within _compat.py.",
              "Python project module providing  compat functionality.", "Project configuration for pyproject.",
              "Not shown in the supplied source excerpt."):
        assert U.is_placeholder(p), p
    for real in ("Collects read-only storage facts from the AI phone.", "Not a public API: the runner calls it once.".replace("Not a", "Never a")):
        assert not U.is_placeholder(real)


def test_a_big_file_is_explained_in_parts_that_each_show_their_symbols():
    text = "\n".join(f"line {i}" for i in range(1, 6001))
    syms = [{"name": f"f{i}", "lineRange": [100 + i * 100, 160 + i * 100]} for i in range(50)]
    parts = U.pieces(text, syms)
    assert len(parts) > 1 and sum(len(p) for _, p in parts) == 50
    assert all(len(t) <= U.FILE_CHARS for t, _ in parts) and "line 4950" in parts[-1][0]


def test_layer_answers_keyed_by_name_are_used(tmp_path, monkeypatch):
    monkeypatch.setattr(U, "STATE", tmp_path / "state")
    repo = graph(tmp_path)

    def ask(prompt, key):
        if "parts (layers)" in prompt:
            return {"layers": {"ops": "The runner and its helpers.", "Repository root": "Top-level docs and settings."}}, {}
        return {"files": {}}, {}

    U.main(repo, "repo", "vk", ask=ask, pause=0)
    g = json.loads((repo / ".ua/knowledge-graph.json").read_text())
    assert [l["description"] for l in g["layers"]] == ["The runner and its helpers.", "Top-level docs and settings."]


def test_big_files_are_cut_to_symbol_excerpts():
    text = "\n".join(f"line {i}" for i in range(1, 3001))
    out = U.excerpt(text, [{"lineRange": [2000, 2100]}])
    assert "line 1\n" in out and "line 2000" in out and "line 1500" not in out and len(out) <= U.FILE_CHARS


def test_understand_runs_the_enrichment_and_ignores_graphify_output():
    sh = (Path(__file__).resolve().parent.parent / "ops/understand.sh").read_text()
    assert "ua_enrich.py" in sh and "graphify-out/" in sh

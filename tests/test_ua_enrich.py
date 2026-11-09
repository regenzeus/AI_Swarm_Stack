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
    job = (Path(__file__).resolve().parent.parent / "ops/onboard.py").read_text()
    assert "ua_enrich.py" in job and "graphify-out/" in job


def test_a_resumed_pass_keeps_counting_its_cost(tmp_path, monkeypatch):
    """Overnight exercise, 9 Nov 2026: sympy's explanation pass resumed after a restart and its 609 calls read 114: the
    checklist under-reported what the step cost."""
    monkeypatch.setattr(U, "STATE", tmp_path)
    (tmp_path / "ua-enrich-demo.json").write_text(json.dumps({"status": "running", "calls": 609, "tokens": 5504004, "started": "2026-11-08T21:22:49"}))
    assert U.earlier_run("demo")["calls"] == 609
    src = Path(U.__file__).read_text()
    assert 'resumed = prev.get("status") in ("running", "limit") and explained > 0' in src
    assert 'calls = int(prev.get("calls") or 0) if resumed else 0' in src
    assert U.earlier_run("nothing") == {}


def test_two_json_objects_in_one_answer_are_both_read_and_an_empty_file_needs_no_model(tmp_path):
    """Overnight 9 Nov 2026: sympy's last four files failed three runs running ("Extra data": the model answered with two
    objects in a row), and its empty tests/__init__.py could never be explained, so onboarding stayed "not yet"."""
    two = 'Here: {"files": {"a.py": {"summary": "Reads the notes file."}}}\n{"files": {"b.py": {"summary": "Writes the notes file."}}, "layers": {}}'
    got = U.objects(two)
    assert set(got["files"]) == {"a.py", "b.py"} and got["layers"] == {}
    assert U.objects('{"files": {}} trailing words') == {"files": {}}
    import pytest
    with pytest.raises(ValueError):
        U.objects("no object here")
    repo = tmp_path / "r"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg/__init__.py").write_text("")
    (repo / "pkg/blank.txt").write_text("\n\n")
    g = {"nodes": [{"id": "f1", "type": "file", "filePath": "pkg/__init__.py", "summary": "python code file in the r repository."},
                   {"id": "f2", "type": "file", "filePath": "pkg/blank.txt", "summary": ""}]}
    todo, files = U.work(g, repo)
    assert todo == [] and files["pkg/__init__.py"]["summary"] == U.EMPTY_PY and files["pkg/blank.txt"]["summary"] == U.EMPTY
    assert not U.is_placeholder(U.EMPTY) and not U.is_placeholder(U.EMPTY_PY)


def test_calls_run_side_by_side_when_the_deployment_says_so_and_json_mode_is_its_choice(tmp_path, monkeypatch):
    """A work site, 9 Nov 2026: one call at a time took over an hour for 1,300 files at ~22 s an answer. UA_ENRICH_WORKERS
    runs a few side by side (at most 8; home stays at one), every answer is applied on one thread, and UA_JSON_MODE asks
    the model for a JSON object."""
    import threading
    assert U.workers({}) == 1 and U.workers({"UA_ENRICH_WORKERS": "6"}) == 6 and U.workers({"UA_ENRICH_WORKERS": "99"}) == 8
    assert U.workers({"UA_ENRICH_WORKERS": "x"}) == 1 and U.json_mode({"UA_JSON_MODE": "1"}) and not U.json_mode({})
    repo = tmp_path / "repo"
    (repo / ".ua").mkdir(parents=True)
    nodes = []
    for i in range(12):
        (repo / f"f{i}.py").write_text("x = 1\n")
        nodes.append({"id": f"file:f{i}.py", "type": "file", "name": f"f{i}.py", "filePath": f"f{i}.py", "summary": "python code file in the repo repository."})
    (repo / ".ua/knowledge-graph.json").write_text(json.dumps({"project": {"name": "repo", "description": "d"}, "nodes": nodes, "edges": [], "layers": []}))
    monkeypatch.setattr(U, "STATE", tmp_path / "state")
    monkeypatch.setattr(U, "workers", lambda values=None: 4)
    monkeypatch.setattr(U, "BATCH_CHARS", 1)                      # each file its own call
    live, peak, lock = [0], [0], threading.Lock()

    def ask(prompt, key):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        import time as _t
        _t.sleep(0.05)
        with lock:
            live[0] -= 1
        path = prompt.split("=== ", 1)[1].split(" ", 1)[0]
        return {"files": {path: {"summary": f"Explains {path} in a sentence."}}}, {"total_tokens": 10}

    assert U.main(repo, "repo", "k", ask=ask, pause=0) in (0, None)
    g = json.loads((repo / ".ua/knowledge-graph.json").read_text())
    assert all(n["summary"].startswith("Explains ") for n in g["nodes"]) and 1 < peak[0] <= 4


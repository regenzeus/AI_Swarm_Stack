"""ops/repos.py and the Code tab's endpoints: repo info from graph and code map files, request validation, the Forgejo
token requirement, and the graph reduced for drawing."""
import webjs
import json
import subprocess

import pytest
from starlette.testclient import TestClient

H = {"Tailscale-User-Login": "owner@test"}


def graph(n):
    nodes = [{"id": f"n{i}", "label": f"Node {i}", "community": i % 3, "community_name": f"group {i % 3}", "source_file": f"f{i}.py",
              "source_location": "L1"} for i in range(n)]
    links = [{"source": "n0", "target": f"n{i}", "relation": "calls"} for i in range(1, n)]
    return {"nodes": nodes, "links": links}


@pytest.fixture
def code(tmp_path):
    root = tmp_path / "code"
    repo = root / "tool"
    (repo / "graphify-out").mkdir(parents=True)
    (repo / "graphify-out" / "graph.json").write_text(json.dumps(graph(12)))
    (repo / ".ua").mkdir()
    (repo / ".ua" / "knowledge-graph.json").write_text("{}")
    (repo / "README.md").write_text("# Tool\n\nDoes things.")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-qm", "first commit"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return root


@pytest.fixture
def R(runner, code, monkeypatch, tmp_path):
    import repos
    import builds
    repos.M, repos.B = runner, builds
    monkeypatch.setattr(repos, "CODE", code)
    monkeypatch.setattr(repos, "DOCS", tmp_path / "docs")
    monkeypatch.setattr(repos, "codemap_repo", lambda: None)
    monkeypatch.setattr(builds, "repos", lambda: ["ai-stack"])
    monkeypatch.setattr(builds, "origin", lambda r: "https://user:secret@github.com/x/tool.git")
    repos._cache["t"] = 0
    return repos


def test_repo_info_from_graph_and_code_map(R):
    info = R.one("tool")
    assert (info["buildable"], info["codemap"], info["digest"]) == (False, True, False)
    assert info["graph"]["nodes"] == 12 and info["graph"]["communities"] == 3
    assert info["source"] == "https://github.com/x/tool.git"          # credentials never shown
    assert info["last"]["subject"] == "first commit" and info["files"] == 3


def test_requests_are_validated(R, monkeypatch):
    with pytest.raises(ValueError, match="no code map"):
        R.handle({"action": "codemap", "repo": "other"}, None)
    monkeypatch.delenv("FORGEJO_TOKEN", raising=False)
    monkeypatch.delenv("FORGEJO_PR_TOKEN", raising=False)
    with pytest.raises(ValueError, match="Forgejo token"):
        R.handle({"action": "repo_create", "name": "new-one"}, None)
    monkeypatch.setenv("FORGEJO_TOKEN", "t")
    monkeypatch.setattr(R.B, "forgejo", lambda *a, **k: {"login": "owner"})
    for bad in ("X", "ai-stack", "tool", "a b"):
        with pytest.raises(ValueError):
            R.handle({"action": "repo_create", "name": bad}, None)
    with pytest.raises(ValueError):
        R.handle({"action": "repo_buildable", "repo": "ai-stack"}, None)


@pytest.fixture
def app(code, tmp_path, monkeypatch):
    import server as S
    monkeypatch.setattr(S, "CODE", code)
    monkeypatch.setattr(S, "CODE_DOCS", tmp_path / "code-docs")
    S._graph_cache.clear()
    return S


def test_graph_is_reduced_for_drawing(app, monkeypatch):
    big = graph(500)
    (app.CODE / "tool" / "graphify-out" / "graph.json").write_text(json.dumps(big))
    d = TestClient(app.app).get("/api/repo/tool/graph", headers=H).json()
    assert (d["total"], d["shown"]) == (500, 200) and d["nodes"][0]["id"] == "n0"          # best connected first
    ids = {n["id"] for n in d["nodes"]}
    assert all(ln["source"] in ids and ln["target"] in ids for ln in d["links"])
    assert TestClient(app.app).get("/api/repo/../graph", headers=H).status_code == 404
    assert TestClient(app.app).get("/api/repo/nope/graph", headers=H).status_code == 404


def test_the_facts_route_has_one_shape_with_or_without_facts(app):
    c = TestClient(app.app)
    keys = {"repo", "available", "at", "commit", "commits", "hotspots", "coupling", "ownership", "code_age", "health", "left_out", "errors"}
    none = c.get("/api/repo/tool/facts", headers=H).json()
    assert set(none) == keys and none["available"] is False and none["hotspots"] == [] and none["health"] == {"sections": []}
    assert c.get("/api/repo/nope/facts", headers=H).status_code == 404
    app.CODE_DOCS.mkdir()
    (app.CODE_DOCS / "tool.facts.json").write_text(json.dumps({"at": "2026-11-07T10:00:00", "commit": "abc", "commits": 3, "hotspots": [{"path": "a.py"}], "errors": [{"tool": "repowise", "analysis": "health", "error": "no"}]}))
    got = c.get("/api/repo/tool/facts", headers=H).json()
    assert set(got) == keys and got["available"] is True and got["hotspots"] == [{"path": "a.py"}] and got["coupling"] == [] and got["errors"][0]["tool"] == "repowise"
    (app.CODE_DOCS / "tool.facts.json").write_text("{broken")
    bad = c.get("/api/repo/tool/facts", headers=H).json()
    assert bad["available"] is False and "cannot be read" in bad["errors"][0]["error"]


def test_overview_prefers_the_code_map_digest(app):
    c = TestClient(app.app)
    assert c.get("/api/repo/tool/overview", headers=H).json() == {"source": "README.md", "markdown": "# Tool\n\nDoes things.", "analysis": ""}
    app.CODE_DOCS.mkdir()
    (app.CODE_DOCS / "tool.md").write_text("# Tool, explained")
    assert c.get("/api/repo/tool/overview", headers=H).json()["source"] == "code map digest"
    (app.CODE_DOCS / "tool.analysis.md").write_text("# Tool: analysis")          # BLD-26: the written analysis comes with it
    assert c.get("/api/repo/tool/overview", headers=H).json()["analysis"] == "# Tool: analysis"


def test_node_details_have_source_links_and_code_map(app):
    repo = app.CODE / "tool"
    (repo / "f1.py").write_text("\n".join(f"line {i}" for i in range(1, 60)))
    (repo / ".ua" / "knowledge-graph.json").write_text(json.dumps({"project": {"name": "tool", "description": "A tool."},
        "tour": [{"order": 1, "title": "Start", "description": "Read f1.", "nodeIds": ["file:f1.py"]}], "layers": [],
        "nodes": [{"id": "file:f1.py", "type": "file", "name": "f1.py", "filePath": "f1.py", "summary": "The first file."}]}))
    c = TestClient(app.app)
    n = c.get("/api/repo/tool/node", headers=H, params={"id": "n1"}).json()
    assert (n["label"], n["file"], n["line"]) == ("Node 1", "f1.py", 1)
    assert n["incoming"] == [{"id": "n0", "label": "Node 0", "relation": "calls", "file": "f0.py", "inferred": False}]
    assert n["code"]["start"] == 1 and n["code"]["text"].startswith("line 1\nline 2")
    assert n["about_file"]["summary"] == "The first file."
    assert c.get("/api/repo/tool/node", headers=H, params={"id": "nope"}).status_code == 404
    m = c.get("/api/repo/tool/map", headers=H).json()
    assert m["project"]["description"] == "A tool." and m["tour"][0]["title"] == "Start" and m["nodes"][0]["summary"] == "The first file."


def test_source_snippets_stay_inside_the_repo(app):
    assert app.snippet("tool", "../../etc/passwd", 1) is None
    assert app.snippet("tool", "README.md", 1)["text"].startswith("# Tool")


def test_remove_takes_the_repo_out_but_never_ai_stack(R, code, monkeypatch, runner):
    import builds
    c = runner.db()
    builds.table(c)
    real = R.subprocess.run
    monkeypatch.setattr(R.subprocess, "run", lambda cmd, **k: R.subprocess.CompletedProcess(cmd, 0) if cmd[0] == "docker" else real(cmd, **k))
    with pytest.raises(ValueError, match="ai-stack"):
        R.handle({"action": "repo_remove", "repo": "ai-stack"}, c)
    c.execute("insert into builds (id, repo, title, status) values (9, 'tool', 't', 'working')")
    with pytest.raises(ValueError, match="still running"):
        R.handle({"action": "repo_remove", "repo": "tool"}, c)
    c.execute("update builds set status='deployed'")
    assert R.handle({"action": "repo_remove", "repo": "tool"}, c) == {"removed": "tool", "still_on_forgejo": False}
    assert not (code / "tool").exists()


def test_every_repo_with_a_code_map_shows_it_clean_and_without_the_minimap():
    """The owner's review of 2026-10-30: only the repo opened last showed its map, the viewer warned about files that
    are not the project's, about corrections it made itself, and its minimap covered the view."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    app = webjs.app_js()
    assert "if (r.codemap) {\n    repoSwitchMap(name);" in app and "Show it here" not in app                  # on opening its Map tab (APP-51)
    assert 'if (cmSwitching === name) return;' in app                                                       # one switch at a time
    sync = (root / "ops/graphify-sync.sh").read_text()
    assert 'echo "graphify-out/" >> "$repo/.git/info/exclude"' in sync                                    # no "working-tree changes" from our cache
    assert "ua_fix.mjs" in (root / "ops/onboard.py").read_text()
    fix = (root / "ops/ua_fix.mjs").read_text()
    assert "autoFixGraph" in fix and "fs.writeFileSync(file" in fix                                       # the viewer's corrections, saved
    docker = (root / "images/opencode/Dockerfile").read_text()
    assert "COPY viewer.css /opt/ua/packages/viewer/dist/aistack.css" in docker and "grep -q aistack.css" in docker
    assert ".react-flow__minimap { display: none !important; }" in (root / "images/opencode/viewer.css").read_text()


def test_a_code_graph_the_update_cannot_read_is_built_anew_and_a_failure_is_logged_once_per_commit():
    from pathlib import Path
    sync = (Path(__file__).resolve().parent.parent / "ops/graphify-sync.sh").read_text()
    assert '|| $G graphify extract "/code/$name" --code-only' in sync                 # a broken graph.json is rebuilt
    assert 'graph FAILED: $name' in sync and '"$STATE/$name.failed"' in sync         # not silent, and not every minute
    assert 'mv "$gj" "$gj.broken-' in sync                                              # an unreadable one is set aside, not deleted


def test_the_graph_view_ranks_the_repository_s_own_code_and_the_source_pane_is_whole(app):
    """BLD-32, DEC-48: the graph's 200 are classes and functions defined in the repository's own non-test files, ranked by
    the links that hold code together (a framework type with 13,000 type mentions is no longer on top); the source pane
    says which lines of how many it shows, and the whole file is one request away, inside the repository only."""
    nodes = [{"id": f"own{i}", "label": f"Own {i}", "community": i % 4, "community_name": f"group {i % 4}", "source_file": f"src/f{i}.py", "source_location": "L1"} for i in range(260)]
    nodes += [{"id": f"ext{i}", "label": f"External {i}", "community": 9, "community_name": "framework", "source_file": "", "source_location": ""} for i in range(20)]
    nodes += [{"id": f"test{i}", "label": f"assertThing{i}", "community": 8, "community_name": "tests", "source_file": f"tests/test_{i}.py", "source_location": "L1"} for i in range(20)]
    links = [{"source": f"own{i}", "target": "ext0", "relation": "references"} for i in range(260)]          # the framework type everyone mentions
    links += [{"source": f"own{i}", "target": "test0", "relation": "calls"} for i in range(100)]                # a test helper everyone calls
    links += [{"source": f"own{i}", "target": "own1", "relation": "calls"} for i in range(2, 60)]               # the repository's own hub
    links += [{"source": "own0", "target": f"own{i}", "relation": "references"} for i in range(2, 200)]        # mentions only: no rank
    (app.CODE / "tool" / "graphify-out" / "graph.json").write_text(json.dumps({"nodes": nodes, "links": links}))
    app._graph_cache.clear()
    c = TestClient(app.app)
    d = c.get("/api/repo/tool/graph", headers=H).json()
    ids = [n["id"] for n in d["nodes"]]
    assert (d["total"], d["shown"]) == (260, 200) and not any(i.startswith(("ext", "test")) for i in ids)
    assert ids[0] == "own1" and d["nodes"][0]["degree"] == 58                                           # ranked by calls, not by type mentions
    o0 = next((n for n in d["nodes"] if n["id"] == "own0"), None)
    assert o0 is None or o0["degree"] == 0                                                              # references, and calls to test helpers, count for nothing
    assert all(ln["source"] in set(ids) and ln["target"] in set(ids) for ln in d["links"])
    (app.CODE / "tool" / "big.py").write_text("\n".join(f"line {i}" for i in range(1, 201)))
    s = app.snippet("tool", "big.py", 100)
    assert (s["start"], s["end"], s["total"]) == (97, 128, 200) and s["text"].startswith("line 97")       # the pane says lines 97 to 128 of 200
    f = c.get("/api/repo/tool/file", headers=H, params={"path": "big.py"}).json()
    assert f["total"] == 200 and f["text"].endswith("line 200")
    assert c.get("/api/repo/tool/file", headers=H, params={"path": "../../etc/passwd"}).status_code == 404


def test_an_explaining_docstring_is_shown_whole(tmp_path, monkeypatch):
    """The owner, 9 Nov 2026: the code graph cuts a docstring with "..."; the node panel shows the whole one from the file."""
    import pysrc
    src = pysrc.server()
    assert 'if o.get("file_type") == "rationale":' in src and "docstring_at(name, o.get(\"source_file\", \"\"), o.get(\"source_location\", \"\"))" in src
    ns = {}
    code = src.split("def docstring_at(name, rel, loc):", 1)[1].split("\ndef ", 1)[0]
    exec("import re\ndef docstring_at(name, rel, loc):" + code, ns)  # nosemgrep: python-eval-exec -- the server's own function, from its source
    d = tmp_path / "r"
    d.mkdir()
    (d / "m.py").write_text('x = 1\ndef f():\n    """Integrate functions by rewriting them.\n\n    There are three of them.\n    """\n')
    ns["repo_dir"] = lambda name: d
    assert ns["docstring_at"]("r", "m.py", "L3") == "Integrate functions by rewriting them. There are three of them."
    assert ns["docstring_at"]("r", "../etc/passwd", "L1") is None


"""BLD-40 (review O9): ops/graphify-sync.sh merges the code graphs only when what goes into the merge changed (a graph's
content without its build stamp, or the set of graphs), never for a pull that changes no code, and runs the merge under
its memory cap; a merge ended there leaves the served graph as it was, says why, and is not tried again every minute.
Docker is a fake that plays graphify on real git repositories in a temp folder."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GIT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "test@example.com"}
FAKE = r'''#!PYTHON
"""docker run ... aistack/graphify:0.9.85 <command>: graphify's update, extract and merge-graphs on the mounted folders."""
import json, os, subprocess, sys
a = sys.argv[1:]
i = a.index("aistack/graphify:0.9.85")
flags, cmd, mounts = a[:i], a[i + 1:], {}
for k, v in zip(flags, flags[1:]):
    if k == "-v":
        src, dst = v.split(":")[:2]
        mounts[dst] = src
def host(p):
    for dst, src in sorted(mounts.items(), key=lambda m: -len(m[0])):
        if p == dst or p.startswith(dst + "/"):
            return src + p[len(dst):]
    return p
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"flags": flags, "cmd": cmd}) + "\n")
if cmd[:2] == ["graphify", "merge-graphs"]:
    rc = int(os.environ.get("FAKE_MERGE_RC", "0"))
    if rc:
        print("Killed", file=sys.stderr)
        sys.exit(rc)
    out = host(cmd[cmd.index("--out") + 1])
    nodes = [n for g in cmd[2:cmd.index("--out")] for n in json.load(open(host(g)))["nodes"]]
    json.dump({"nodes": nodes, "links": []}, open(out, "w"))
elif cmd[:2] == ["graphify", "update"] or cmd[:2] == ["graphify", "extract"]:
    repo = host(cmd[2])
    code = open(os.path.join(repo, "code.txt")).read().strip()
    if not code:
        print("graph is empty")
        sys.exit(1)
    head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    name = os.path.basename(repo)
    os.makedirs(os.path.join(repo, "graphify-out"), exist_ok=True)
    g = {"nodes": [{"id": f"{name}_{code}", "label": f"{code}.py", "source_file": f"{code}.py", "repo": name}], "links": [],
         "built_at_commit": head}
    json.dump(g, open(os.path.join(repo, "graphify-out", "graph.json"), "w"))
elif cmd[:1] == ["python3"]:
    sys.exit(subprocess.run([sys.executable, host(cmd[1]), *[host(x) for x in cmd[2:]]]).returncode)
'''


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env={**os.environ, **GIT})


def commit(repo, code=None, doc=None):
    if code is not None:
        (repo / "code.txt").write_text(code)
    if doc is not None:
        (repo / "README.md").write_text(doc)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "change")


@pytest.fixture
def sync(tmp_path):
    bin_, code, stack, state = tmp_path / "bin", tmp_path / "code", tmp_path / "stack", tmp_path / "state"
    for d in (bin_, code, stack / "ops"):
        d.mkdir(parents=True)
    (bin_ / "docker").write_text(FAKE.replace("PYTHON", sys.executable, 1))
    (bin_ / "docker").chmod(0o755)
    (stack / "ops/graph_repos.py").write_text((ROOT / "ops/graph_repos.py").read_text())
    git(stack, "init", "-q")
    commit(stack, code="runner")
    lib = code / "lib"
    lib.mkdir()
    git(lib, "init", "-q")
    commit(lib, code="parser")
    log = tmp_path / "docker.jsonl"
    env = {**os.environ, **GIT, "PATH": f"{bin_}:{Path(sys.executable).parent}:{os.environ['PATH']}", "CODE_DIR": str(code),
           "STACK_DIR": str(stack), "GRAPHIFY_STATE": str(state), "FAKE_LOG": str(log)}

    def run(**extra):
        log.write_text("")
        p = subprocess.run(["bash", str(ROOT / "ops/graphify-sync.sh")], capture_output=True, text=True, env={**env, **extra})
        calls = [json.loads(x) for x in log.read_text().splitlines()]
        merges = [c for c in calls if c["cmd"][:2] == ["graphify", "merge-graphs"]]
        return p, merges, calls
    run.stack, run.lib, run.code, run.state = stack, lib, code, state
    return run


def test_the_merge_runs_only_when_a_graph_changed_in_content_never_for_a_pull_that_changes_no_code(sync):
    p, merges, _ = sync()
    assert p.returncode == 0, p.stderr
    assert len(merges) == 1 and "merged graph rebuilt (2 repos)" in p.stdout
    served = json.loads((sync.code / ".graphify/merged-graph.json").read_text())
    assert {"repo::ai-stack", "repo::lib"} <= {n["id"] for n in served["nodes"]}         # the repository nodes were added
    assert not (sync.code / ".graphify/merged-graph.next.json").exists()

    p, merges, calls = sync()                                                          # nothing moved: no graphify at all
    assert p.returncode == 0 and calls == []

    commit(sync.stack, doc="a docs change")                                             # the mirror pulls it, the graph is rebuilt...
    p, merges, calls = sync()
    assert [c["cmd"][1] for c in calls] == ["update"] and merges == []                  # ...and equal but for its stamp: no merge
    assert "graph unchanged: ai-stack" in p.stdout and p.returncode == 0

    commit(sync.lib, code="lexer")                                                      # a code change: merged again
    p, merges, _ = sync()
    assert len(merges) == 1 and "graph updated: lib" in p.stdout

    subprocess.run(["rm", "-rf", str(sync.lib)], check=True)                            # a repository removed: merged without it
    p, merges, _ = sync()
    assert len(merges) == 1 and "(1 repos)" in p.stdout
    assert [g for g in merges[0]["cmd"] if g.endswith("graph.json")] == ["/code/ai-stack/graphify-out/graph.json"]


def test_the_merge_runs_under_its_memory_cap_and_one_ended_there_keeps_the_old_graph_and_waits_for_a_change(sync):
    assert sync()[0].returncode == 0
    before = (sync.code / ".graphify/merged-graph.json").read_text()
    commit(sync.lib, code="lexer")
    p, merges, calls = sync(FAKE_MERGE_RC="137")
    flags = merges[0]["flags"]
    assert flags[flags.index("--memory") + 1] == "3g" and flags[flags.index("--memory-swap") + 1] == "6g"
    assert all("--memory" not in c["flags"] for c in calls if c["cmd"][1] in ("update", "extract"))
    assert p.returncode == 1 and "merged graph FAILED (ended at its memory cap of 3g RAM and 6g with swap" in p.stderr
    assert "Killed" in p.stderr and "the old one is still served" in p.stderr
    assert (sync.code / ".graphify/merged-graph.json").read_text() == before            # the served graph is untouched
    assert not (sync.code / ".graphify/merged-graph.next.json").exists()

    p, merges, _ = sync(FAKE_MERGE_RC="137")                                           # the same inputs: not every minute
    assert merges == [] and p.returncode == 0
    commit(sync.lib, code="tokens")                                                     # a graph changed: tried again
    p, merges, _ = sync()
    assert len(merges) == 1 and p.returncode == 0 and "lexer" not in (sync.code / ".graphify/merged-graph.json").read_text()

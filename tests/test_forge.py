"""The forge (GEN-04): one interface, Forgejo at home as before and Bitbucket Data Center for a work deployment, tested
against a stand-in server; a deployment that never merges opens drafts and refuses the merge into main."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import deployment as DEPLOY
import forge as F

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def server():
    seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def answer(self, body):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def handle_any(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n)) if n else None
            seen.append((self.command, self.path, self.headers.get("Authorization"), body))
            if self.path.endswith("/pull-requests") and self.command == "POST":
                return self.answer({"id": 7, "links": {"self": [{"href": "https://bb/pr/7"}]}})
            if "/pull-requests/7" in self.path and self.command == "GET":
                return self.answer({"id": 7, "state": "OPEN", "version": 3})
            if "/build-status/" in self.path:
                return self.answer({"values": [{"state": "SUCCESSFUL"}, {"state": "INPROGRESS"}]})
            if self.path.endswith("/pulls") and self.command == "POST":
                return self.answer({"number": 5, "html_url": "https://forgejo/pr/5"})
            return self.answer({})
        do_GET = do_POST = do_PATCH = handle_any

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", seen
    srv.shutdown()


def test_bitbucket_dc_opens_a_draft_comments_reads_state_and_ci_and_declines(server):
    url, seen = server
    bb = F.BitbucketDC(url, token="t")
    origin = "ssh://bitbucket.example.com:7999/PROJ/work_plugin.git"
    assert bb.repo_of(origin) == ("PROJ", "work_plugin")
    assert bb.repo_of("https://bitbucket.example.com/scm/PROJ/work_plugin.git") == ("PROJ", "work_plugin")
    pr = bb.open_pr(origin, "build-12", "develop", "Build #12: fix", "the change")
    assert pr == {"url": "https://bb/pr/7", "number": 7}
    method, path, auth, body = seen[0]
    assert method == "POST" and path == "/rest/api/1.0/projects/PROJ/repos/work_plugin/pull-requests" and auth == "Bearer t"
    assert body["draft"] is True and body["fromRef"] == {"id": "refs/heads/build-12"} and body["toRef"] == {"id": "refs/heads/develop"}
    bb.comment(origin, 7, "rejected")
    assert seen[-1][:2] == ("POST", "/rest/api/1.0/projects/PROJ/repos/work_plugin/pull-requests/7/comments") and seen[-1][3] == {"text": "rejected"}
    assert bb.state(origin, 7) == "open" and bb.ci("work_plugin", "a" * 40) == "pending"
    bb.close(origin, 7)
    assert seen[-1][:2] == ("POST", "/rest/api/1.0/projects/PROJ/repos/work_plugin/pull-requests/7/decline?version=3")
    assert not any("/merge" in p for _, p, _, _ in seen)                          # nothing here can merge
    bb.open_pr(origin, "ai/build-13", "develop", "Build #13", "x", from_repo=("~OWNER", "work_plugin"))   # GEN-04: from a fork
    assert seen[-1][3]["fromRef"] == {"id": "refs/heads/ai/build-13", "repository": {"slug": "work_plugin", "project": {"key": "~OWNER"}}}


def test_forgejo_is_home_as_before_and_no_token_means_no_call(server, monkeypatch):
    url, seen = server
    for k in ("FORGEJO_TOKEN", "FORGEJO_PR_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    fj = F.Forgejo(url, "owner", token="t")
    assert fj.open_pr("forgejo:owner/ai-stack.git", "b1", "main", "Build #1", "x") == {"url": "https://forgejo/pr/5", "number": 5}
    assert seen[0][:3] == ("POST", "/api/v1/repos/owner/ai-stack/pulls", "token t") and seen[0][3]["title"] == "Build #1"
    assert fj.open_pr("forgejo:owner/ai-stack.git", "b1", "main", "Build #1", "x", draft=True) and seen[-1][3]["title"] == "WIP: Build #1"
    calls = len(seen)
    assert F.Forgejo(url, "owner", token="").open_pr("forgejo:owner/x.git", "b", "main", "t", "x") is None and len(seen) == calls
    home = F.of(DEPLOY.load(ROOT / "deployments/home/deployment.env", env={}))
    assert isinstance(home, F.Forgejo) and F.may_merge(DEPLOY.load(ROOT / "deployments/home/deployment.env", env={}))


def test_the_work_example_uses_bitbucket_and_never_merges_and_a_build_is_not_merged_there(monkeypatch):
    work = DEPLOY.load(ROOT / "deployments/example-work/deployment.env", env={})
    assert isinstance(F.of(work), F.BitbucketDC) and not F.may_merge(work)
    import builds as B
    monkeypatch.setattr(B.FG, "may_merge", lambda values=None: False)
    put = {}
    monkeypatch.setattr(B, "put", lambda c, bid, **k: put.update(k))
    monkeypatch.setattr(B, "clone", lambda repo: pytest.fail("a deployment that never merges must not even clone for a merge"))
    B.deploy(None, {"id": 9, "repo": "work_plugin", "pr": "https://bb/pr/7"})
    assert put["status"] == "review" and "never merges" in put["error"] and "https://bb/pr/7" in put["error"]

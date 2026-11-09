"""The forge (GEN-04, DEC-45, docs/PLATFORM.md §7): one interface for what the stack asks of the place its repositories
live, with Forgejo (home) and Bitbucket Data Center (a work deployment) behind it.

    import forge as F
    pr = F.FORGE.open_pr(origin, head, base, title, body)     -> {"url", "number"}, or None without a token
    F.FORGE.comment(origin, number, text); F.FORGE.close(origin, number); F.FORGE.state(origin, number)
    F.FORGE.comments(origin, number)                          -> [{"id", "author", "body"}]: a pull request's comments (GEN-26)
    F.FORGE.ci(origin, sha)                                   -> success | failure | pending | none
    F.may_merge()                                             -> whether this deployment ever merges into a main branch

The deployment says which (deployments/<name>/deployment.env): FORGE=forgejo (home, the default) with FORGEJO_URL, or
FORGE=bitbucket-dc with FORGE_URL; MERGE=owner (home: on the owner's tap, as before) or never (a work deployment: its
change is a draft pull request, and the stack never merges it). A pull request on a deployment that never merges is
always a draft. Tokens are secrets (sops), never in the deployment file: FORGEJO_TOKEN, BITBUCKET_TOKEN."""
import json
import os
import re
import urllib.parse
import urllib.request

import deployment as DEPLOY


def may_merge(values=None):
    return (values or DEPLOY.VALUES).get("MERGE", "owner") != "never"


class Forgejo:
    def __init__(self, url, owner, token=None):
        self.api, self.owner, self._token = f"{url}/api/v1", owner, token

    def token(self):
        return self._token or os.environ.get("FORGEJO_TOKEN") or os.environ.get("FORGEJO_PR_TOKEN", "")

    def call(self, method, path, body=None, token=None):
        tok = token if token is not None else self.token()
        if not tok:
            return None
        req = urllib.request.Request(self.api + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"token {tok}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
        return json.loads(raw) if raw else {}

    @staticmethod
    def repo_of(origin):
        m = re.match(r"^forgejo:([^/]+)/(.+?)(?:\.git)?$", origin or "")
        return f"{m[1]}/{m[2]}" if m else None

    def open_pr(self, origin, head, base, title, body, draft=False, from_repo=None):
        name = self.repo_of(origin)
        if not name:
            return None
        pr = self.call("POST", f"/repos/{name}/pulls", {"head": head, "base": base, "title": f"WIP: {title}" if draft else title, "body": body})
        return {"url": pr.get("html_url"), "number": pr.get("number")} if pr else None

    def comment(self, origin, number, text):
        name = self.repo_of(origin)
        return name and self.call("POST", f"/repos/{name}/issues/{number}/comments", {"body": text})

    def close(self, origin, number):
        name = self.repo_of(origin)
        return name and self.call("PATCH", f"/repos/{name}/pulls/{number}", {"state": "closed"})

    def comments(self, origin, number):
        name = self.repo_of(origin)
        got = (name and self.call("GET", f"/repos/{name}/issues/{number}/comments")) or []
        return [{"id": c["id"], "author": (c.get("user") or {}).get("login", ""), "body": c.get("body", "")} for c in got]

    def state(self, origin, number):
        name = self.repo_of(origin)
        pr = name and self.call("GET", f"/repos/{name}/pulls/{number}")
        return None if not pr else "merged" if pr.get("merged") else pr.get("state")

    def ci(self, repo, sha):
        """The CI run of a commit on the deployment's own repositories (FORGEJO_OWNER/repo)."""
        tok = os.environ.get("FORGEJO_TOKEN") or os.environ.get("FORGEJO_STATUS_TOKEN", "")      # one token is enough
        runs = (self.call("GET", f"/repos/{self.owner}/{repo}/actions/tasks?limit=30", token=tok) or {}).get("workflow_runs") or []
        mine = [r for r in runs if r.get("head_sha") == sha]
        return mine[0]["status"] if mine else ("none" if not runs or not any(r.get("head_sha") for r in runs) else "pending")


class BitbucketDC:
    """Bitbucket Data Center, REST 1.0, with an HTTP access token (Bearer)."""
    STATES = {"OPEN": "open", "DECLINED": "closed", "MERGED": "merged"}
    CI = {"SUCCESSFUL": "success", "FAILED": "failure", "INPROGRESS": "pending"}

    def __init__(self, url, token=None):
        self.url, self._token = url.rstrip("/"), token

    def token(self):
        return self._token or os.environ.get("BITBUCKET_TOKEN", "")

    def call(self, method, path, body=None):
        tok = self.token()
        if not tok:
            return None
        req = urllib.request.Request(self.url + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
        return json.loads(raw) if raw else {}

    @staticmethod
    def repo_of(origin):
        """(project, repository) of an origin: ssh://host:7999/PROJ/repo.git (a user before the host is fine too) or https://host/scm/PROJ/repo.git."""
        m = re.match(r"^(?:ssh://[^/]+|https?://[^/]+(?:/scm)?)/([^/]+)/([^/]+?)(?:\.git)?/?$", origin or "")
        return (m[1], m[2]) if m else None

    def base(self, origin):
        pr = self.repo_of(origin)
        return pr and f"/rest/api/1.0/projects/{urllib.parse.quote(pr[0])}/repos/{urllib.parse.quote(pr[1])}"

    def open_pr(self, origin, head, base, title, body, draft=True, from_repo=None):
        """from_repo: (project, slug) of the fork the branch was pushed to; none: the branch is in the repository itself."""
        b = self.base(origin)
        if not b:
            return None
        src = {"id": f"refs/heads/{head}"}
        if from_repo:                                     # a work site, 9 Nov 2026: without it only branches of the same repository worked
            src["repository"] = {"slug": from_repo[1], "project": {"key": from_repo[0]}}
        pr = self.call("POST", f"{b}/pull-requests", {"title": title, "description": body, "draft": bool(draft),
                                                       "fromRef": src, "toRef": {"id": f"refs/heads/{base}"}})
        if not pr:
            return None
        links = (pr.get("links") or {}).get("self") or [{}]
        return {"url": links[0].get("href"), "number": pr.get("id")}

    def comment(self, origin, number, text):
        b = self.base(origin)
        return b and self.call("POST", f"{b}/pull-requests/{number}/comments", {"text": text})

    def comments(self, origin, number):
        b = self.base(origin)
        got = (b and self.call("GET", f"{b}/pull-requests/{number}/activities?limit=100")) or {}
        return [{"id": v["comment"]["id"], "author": (v["comment"].get("author") or {}).get("name", ""), "body": v["comment"].get("text", "")}
                for v in got.get("values") or [] if v.get("action") == "COMMENTED" and v.get("comment")]

    def close(self, origin, number):
        b = self.base(origin)
        pr = b and self.call("GET", f"{b}/pull-requests/{number}")
        return pr and self.call("POST", f"{b}/pull-requests/{number}/decline?version={pr.get('version', 0)}", {})

    def state(self, origin, number):
        b = self.base(origin)
        pr = b and self.call("GET", f"{b}/pull-requests/{number}")
        return pr and self.STATES.get(pr.get("state"), str(pr.get("state")).lower())

    def ci(self, repo, sha):
        got = self.call("GET", f"/rest/build-status/1.0/commits/{sha}") or {}
        states = [self.CI.get(v.get("state"), "pending") for v in got.get("values") or []]
        return "none" if not states else "failure" if "failure" in states else "pending" if "pending" in states else "success"


def of(values=None):
    v = values or DEPLOY.VALUES
    kind = v.get("FORGE", "forgejo")
    if kind == "forgejo":
        return Forgejo(v.get("FORGEJO_URL", ""), v.get("FORGEJO_OWNER", ""))
    if kind == "bitbucket-dc":
        return BitbucketDC(v.get("FORGE_URL", ""))
    raise SystemExit(f"FORGE={kind}: forgejo or bitbucket-dc (ops/forge.py)")


FORGE = of()

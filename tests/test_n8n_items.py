"""WFL-19 to WFL-21, GEN-26, GEN-27: tracker items start and wake runs in n8n. A stand-in item starts its workflow
through the webhook item/<pack>/<name> once, however often its event comes; a comment by someone else wakes the run
that waits on it and the stack's own change does not; a wait that times out is an outcome the workflow branches on, to
a reminder in shadow and a second wait; a change for an item starts at its tag and goes out as a draft pull request
whose review comment wakes the run; a question for a role says who may answer, refuses anyone else and records who did."""
import json
import subprocess
import types
import urllib.error
from pathlib import Path

import pytest

import flows as FW
import runreg as RR
from domain import forgework as FWK
from domain import trackers as TR

ROOT = Path(__file__).resolve().parents[1]
RESUME = "https://pc.example.ts.net:8450/webhook-waiting/41/w1"


class Resp:
    def __init__(self, status=200, body=b""):
        self.status, self.body = status, body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def W(tmp_path, monkeypatch):
    """A stand-in tracker (test, starting toy/ticket), the run register, the step service's folders and a stand-in n8n."""
    store = tmp_path / "standin.json"
    store.write_text(json.dumps({"items": {}}))
    cfg = tmp_path / "trackers.yaml"
    cfg.write_text(f"shadow_needed: 2\npoll_minutes: 5\ntrackers:\n  - {{name: test, kind: standin, path: {store}, workflow: toy/ticket, start: 2026-01-01}}\n")
    monkeypatch.setenv("AISTACK_TRACKERS", str(cfg))
    monkeypatch.setenv("N8N_HOOK_TOKEN", "hook-test")          # SEC-27: the runner's header for n8n's webhooks
    monkeypatch.setenv("AISTACK_TRACKER_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("AISTACK_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setattr(RR, "ROOT", tmp_path / "register")
    for name in ("PENDING", "DONE", "ASKS", "BUILDS"):
        monkeypatch.setattr(FW, name, tmp_path / "flows" / name.lower())
    FW.PENDING.mkdir(parents=True)
    told = []
    FW.M = types.SimpleNamespace(stop=__import__("threading").Event(), log=print, notify=lambda text, *a: told.append(text), db=None,
                                 event=lambda *a, **k: None)
    started, resumed = [], []

    def n8n(req, timeout=30):                       # n8n: a webhook starts a run, a resume URL takes an answer
        if "/webhook/item/" in req.full_url and req.get_header("X-aistack-hook") != "hook-test":
            raise urllib.error.HTTPError(req.full_url, 403, "Authorization data is wrong!", {}, None)   # n8n's Header Auth (SEC-27)
        (started if "/webhook/item/" in req.full_url else resumed).append((req.full_url, json.loads(req.data)))
        return Resp(body=json.dumps({"execution": str(40 + len(started))}).encode() if "/webhook/item/" in req.full_url else b"")

    def item(key, updated, comments=()):
        db = json.loads(store.read_text())
        db["items"][key] = {"updated": updated, "title": f"ticket {key}", "comments": [{"id": i + 1, "author": a, "body": b} for i, (a, b) in enumerate(comments)]}
        store.write_text(json.dumps(db))

    clock = {"now": 1_800_000_000.0}

    def poll(status=lambda ex: "running", post=None, forge=None):
        clock["now"] += 600                          # every pass is due (poll_minutes 5)
        return RR.poll(forge=forge or types.SimpleNamespace(), post=post or n8n, status=status, now=clock["now"])

    def step(rid, **req):
        p = FW.PENDING / f"{rid}.json"
        p.write_text(json.dumps({"resume_url": RESUME, "workflow": "wf1", "workflow_name": "toy/ticket", "execution": "41", **req}))
        FW.handle(rid, p, cards={}, crew={}, post=n8n, sleep=lambda s: None)
        return p
    return types.SimpleNamespace(item=item, poll=poll, step=step, started=started, resumed=resumed, told=told, store=store, tmp=tmp_path,
                                 cfg=cfg, n8n=n8n, clock=clock)


def test_a_new_item_starts_its_workflow_once_through_its_webhook_even_when_its_event_comes_twice(W):
    W.item("T-1", "2026-11-10T09:00:00")
    assert W.poll()["said"] == {"started": 1}
    url, body = W.started[0]
    assert url == "http://127.0.0.1:5678/webhook/item/toy/ticket"                     # n8n's root, never under /n8n/
    assert body == {"tracker": "test", "key": "T-1", "run": "toy/ticket:test/T-1", "ref": "item:test/T-1@2026-11-10T09:00:00", "comments": []}
    (W.tmp / "state/test.json").unlink()                                             # the tracker hands the same change on again
    assert W.poll()["said"] == {"seen": 1} and len(W.started) == 1                  # the ledger knows it: one run, never two
    W.item("T-1", "2026-11-10T09:10:00")                                             # a later change of an item that has its run
    assert W.poll()["said"] == {"recorded": 1} and len(W.started) == 1
    assert RR.item("test", "T-1")["runs"][0]["by"] == "an event"
    assert RR.item("test", "T-1")["runs"][0]["execution"] == "41"                  # the trigger answered with its run's execution


def test_a_comment_from_someone_else_wakes_the_waiting_run_and_the_stacks_own_change_does_not(W):
    W.item("T-2", "2026-11-10T09:00:00")
    W.poll()
    p = W.step("w1", kind="wait_item", tracker="test", key="T-2", timeout_hours=72)
    assert p.exists() and W.resumed == [] and RR.item("test", "T-2")["runs"][0]["execution"] == "41"   # the run's execution learnt
    W.item("T-2", "2026-11-10T09:05:00", [("ai-stack", "Could you attach the log?")])   # the stack's own write changes the item
    assert W.poll()["said"] == {"recorded": 1}
    W.step("w1", kind="wait_item", tracker="test", key="T-2", timeout_hours=72)
    assert W.resumed == []                                                            # no new comment from anyone else: still waiting
    W.item("T-2", "2026-11-10T10:00:00", [("ai-stack", "Could you attach the log?"), ("reporter", "attached")])
    assert W.poll()["said"] == {"woke": 1}
    W.step("w1", kind="wait_item", tracker="test", key="T-2", timeout_hours=72)
    assert not p.exists() and W.resumed[0][1]["status"] == "done" and W.resumed[0][1]["outcome"] == "reply"
    assert W.resumed[0][1]["comments"] == ["comment:test/T-2/2"] and len(W.started) == 1


def test_a_comment_while_the_run_is_busy_elsewhere_answers_its_next_wait_at_once(W):
    W.item("T-3", "2026-11-10T09:00:00")
    W.poll()
    W.item("T-3", "2026-11-10T09:30:00", [("reporter", "one more detail")])
    assert W.poll()["said"] == {"recorded": 1}
    W.step("w2", kind="wait_item", tracker="test", key="T-3", timeout_hours=1)
    assert W.resumed[0][1]["outcome"] == "reply" and W.resumed[0][1]["comments"] == ["comment:test/T-3/1"]


def test_a_wait_that_times_out_is_an_outcome_and_the_run_reminds_in_shadow_and_waits_again(W, monkeypatch):
    W.item("T-4", "2026-11-10T09:00:00")
    W.poll()
    t0 = W.clock["now"]
    monkeypatch.setattr(RR, "_now", lambda: t0)
    W.step("w3", kind="wait_item", tracker="test", key="T-4", timeout_hours=24)
    assert W.resumed == []
    monkeypatch.setattr(RR, "_now", lambda: t0 + 24 * 3600 + 1)
    W.step("w3", kind="wait_item", tracker="test", key="T-4", timeout_hours=24)
    a = W.resumed[-1][1]
    assert a["status"] == "done" and a["outcome"] == "timeout" and a["comments"] == [] and a["waited_hours"] >= 24
    W.step("r1", kind="tracker", tracker="test", key="T-4", write="comment", body="A reminder: could you attach the log?")
    r = W.resumed[-1][1]
    assert r["status"] == "done" and r["shadow"] is True and r["ref"] == "shadow:comment/n8n/r1"
    assert json.loads(W.store.read_text())["items"]["T-4"]["comments"] == []        # in shadow: nothing left the stack
    W.step("w4", kind="wait_item", tracker="test", key="T-4", timeout_hours=24)       # the second wait
    assert RR.item("test", "T-4")["wait"]["rid"] == "w4" and len(W.resumed) == 2


def test_an_ended_run_is_not_started_again_unless_its_tracker_says_restart_on_comment(W):
    W.item("T-5", "2026-11-10T09:00:00")
    W.poll()
    RR.learn({"tracker": "test", "key": "T-5", "execution": "41"})
    W.item("T-5", "2026-11-10T11:00:00", [("reporter", "it is back")])
    assert W.poll(status=lambda ex: "success")["said"] == {"recorded": 1} and len(W.started) == 1   # restart: never (the default)
    W.cfg.write_text(W.cfg.read_text().replace("start: 2026-01-01}", "start: 2026-01-01, restart: on_comment}"))
    W.item("T-5", "2026-11-10T12:00:00", [("reporter", "it is back"), ("ai-stack", "noted")])
    assert W.poll(status=lambda ex: "success")["said"] == {"recorded": 1}            # no new comment from others: no new run
    W.item("T-5", "2026-11-10T13:00:00", [("reporter", "it is back"), ("ai-stack", "noted"), ("reporter", "and again")])
    assert W.poll(status=lambda ex: "running")["said"] == {"recorded": 1}             # its run still goes on: recorded for its wait
    W.item("T-5", "2026-11-10T14:00:00", [("reporter", "it is back"), ("ai-stack", "noted"), ("reporter", "and again"), ("reporter", "now?")])
    assert W.poll(status=lambda ex: "success")["said"] == {"started": 1}
    assert len(W.started) == 2 and W.started[1][1]["comments"] == ["comment:test/T-5/4"]
    assert TR.view()["trackers"][0]["refused"] == "" and TR.view()["trackers"][0]["restart"] == "on_comment"


def test_an_event_n8n_could_not_take_stays_in_the_outbox_and_starts_its_run_on_the_next_pass(W):
    W.item("T-6", "2026-11-10T09:00:00")

    def down(req, timeout=30):
        raise OSError("HTTP Error 404: the workflow is not published")
    assert W.poll(post=down)["said"] == {"kept": 1} and RR.item("test", "T-6")["runs"] == []
    assert W.poll()["said"] == {"started": 1} and len(W.started) == 1                # the tracker's cursor had moved: the outbox kept it


def test_the_poller_is_a_crew_job_on_n8ns_minute_and_asks_the_trackers_every_poll_minutes(W):
    import crew as CR
    assert CR.BY_ID["tracker-poll"]["unit"] == "tracker-poll"
    unit = (ROOT / "ops/systemd/tracker-poll.service").read_text()
    assert "ops/runreg.py poll" in unit and "[Install]" not in unit and not (ROOT / "ops/systemd/tracker-poll.timer").exists()
    wf = json.loads((ROOT / "n8n/workflows/crew-tracker-poll.json").read_text())
    step = next(n for n in wf["nodes"] if n["type"] == "CUSTOM.aistackStep")
    assert step["parameters"]["job"] == "tracker-poll" and "* * * * *" in json.dumps(wf)     # published by a deployment with trackers (n8n_switch.py)
    cfg = TR.config()
    assert cfg["poll_minutes"] == 5 and RR.due(cfg, now=1000.0)
    RR._write(RR.ROOT / "poller.json", {"last": 1000.0})
    assert not RR.due(cfg, now=1000.0 + 120) and RR.due(cfg, now=1000.0 + 300)
    assert RR.poll(TR.config(), now=1000.0 + 120)["result"] == "not due (every 5 minutes)"
    assert RR.poll({"trackers": [], "poll_minutes": 5})["result"] == "no trackers in this deployment"


def test_a_tracker_write_step_answers_with_its_shadow_reference_and_once_live_with_the_live_one(W):
    W.item("T-7", "2026-11-10T09:00:00")
    W.step("t1", kind="tracker", tracker="test", key="T-7", write="summary", body="Triaged: a bug in the export")
    assert W.resumed[-1][1]["ref"] == "shadow:summary/n8n/t1" and W.resumed[-1][1]["shadow"] is True
    TR.handle({"action": "tracker_live", "kind": "summary", "live": True})
    W.step("t2", kind="tracker", tracker="test", key="T-7", write="summary", body="Fixed on the release branch")
    a = W.resumed[-1][1]
    assert a["shadow"] is False and a["ref"] == "tracker:test/T-7/summary/n8n/t2"
    assert "Fixed on the release branch" in json.loads(W.store.read_text())["items"]["T-7"]["comments"][0]["body"]


def test_a_tracker_write_takes_an_earlier_steps_whole_text_from_the_run_register(W):
    """WFL-21: from_step adds the whole answer of an earlier step of the same run, from the run register, so n8n (which
    holds only a summary in a customer deployment) never carries the text the stack writes."""
    whole = "1. Which file size?\n2. Which version?\n" + "More detail. " * 60
    RR.step_begin("a9", {"execution": "41", "kind": "agent", "node": "Triage"})
    RR.step_end("a9", {"execution": "41"}, {"status": "done", "output": whole})
    W.step("t9", kind="tracker", tracker="test", key="T-9", write="comment", body="To reproduce it we need:", from_step="Triage", node="Ask")
    assert W.resumed[-1][1]["status"] == "done" and W.resumed[-1][1]["shadow"] is True
    held = next(i for i in TR._shadow()["comment"]["items"] if i["id"] == "n8n/t9")
    assert held["body"] == "To reproduce it we need:\n\n" + whole
    W.step("t10", kind="tracker", tracker="test", key="T-9", write="comment", body="", from_step="Nowhere")
    assert W.resumed[-1][1] == {"status": "refused", "error": "no step 'Nowhere' with an answer in this run"}
    assert "text" in FW.validate({"kind": "tracker", "tracker": "test", "key": "T-9", "write": "comment", "body": " "}, {}, {})
    assert FW.validate({"kind": "tracker", "tracker": "test", "key": "T-9", "write": "comment", "body": "", "from_step": "Triage"}, {}, {}) == ""


def test_the_item_steps_are_checked_before_anything_runs(W):
    ok = {"kind": "wait_item", "tracker": "test", "key": "T-1", "timeout_hours": 2}
    assert FW.validate(ok, {}, {}) == ""
    assert "no tracker 'nope'" in FW.validate({**ok, "tracker": "nope"}, {}, {})
    assert "key" in FW.validate({**ok, "key": "../x"}, {}, {})
    assert "timeout_hours" in FW.validate({**ok, "timeout_hours": -1}, {}, {})
    w = {"kind": "tracker", "tracker": "test", "key": "T-1", "write": "comment", "body": "hello"}
    assert FW.validate(w, {}, {}) == "" and "one of" in FW.validate({**w, "write": "delete"}, {}, {})
    assert "text" in FW.validate({**w, "body": "x" * (TR.BODY_CHARS + 1)}, {}, {})
    b = {"kind": "build", "repo": "toy", "brief": "Fix the export at 2 GB", "item": "test/T-1", "base": "v1.0", "target": "release/1"}
    assert FW.validate(b, {}, {}, repos=["toy"]) == ""
    assert "base" in FW.validate({**b, "base": "v1..0"}, {}, {}, repos=["toy"])
    assert "<tracker>/<key>" in FW.validate({**b, "item": "nope/T-1"}, {}, {}, repos=["toy"])
    assert "role" in FW.validate({"kind": "ask", "question": "Go?", "role": "a b"}, {}, {})
    for kind in ("wait_item", "tracker"):
        assert kind in FW.KINDS


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@localhost", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Forge:
    """The Bitbucket stand-in: the pull requests it was asked to open, and a reviewer's comment."""

    def __init__(self):
        self.opened, self.cs = [], []

    @staticmethod
    def repo_of(origin):
        return tuple(str(origin).rstrip("/").removesuffix(".git").split("/")[-2:])

    def open_pr(self, origin, head, base, title, body, draft=False, from_repo=None):
        self.opened.append({"origin": origin, "head": head, "base": base, "draft": draft, "title": title, "from_repo": from_repo})
        return {"number": 7, "url": "https://bitbucket.example/projects/P/repos/toy/pull-requests/7"}

    def comments(self, origin, number):
        return self.cs


def builds_standin(W, conn):
    """builds.py as item_build uses it: a clone of the upstream, build_assign, and a builder that commits onto the branch."""
    up, clone = W.tmp / "upstream.git", W.tmp / "clone"
    seed = W.tmp / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    (seed / "a.txt").write_text("one\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "one")
    git(seed, "tag", "v1.0")
    (seed / "a.txt").write_text("two\n")
    git(seed, "commit", "-q", "-am", "two")
    git(W.tmp, "clone", "-q", "--bare", str(seed), str(up))
    git(W.tmp, "clone", "-q", str(up), str(clone))
    conn.execute("create table builds (id integer primary key, repo text, title text, status text, branch text, summary text, error text, pr text, pr_number integer, onto text)")
    B = types.SimpleNamespace(assigned=[])
    B.clone = lambda repo: clone
    B.git = lambda path, *a, timeout=300, check=True: git(path, *a)
    B.origin = lambda repo: "ssh://bitbucket.example:7999/P/toy.git"
    B.put = lambda c, bid, **kw: [c.execute(f"update builds set {k}=? where id=?", (v, bid)) for k, v in kw.items()]

    def handle(req, c):
        B.assigned.append(req)
        cur = c.execute("insert into builds (repo, title, status, onto) values (?,?,?,?)", (req["repo"], req["title"], "queued", req["onto"]))
        bid = cur.lastrowid
        c.execute("update builds set branch=? where id=?", (f"builder/{bid}-fix", bid))
        return {"id": bid}
    B.handle = handle

    def work(bid):                                   # the builder: a commit onto its branch, from the item's branch, then review
        w = W.tmp / f"work{bid}"
        git(W.tmp, "clone", "-q", str(up), str(w))
        git(w, "checkout", "-q", "-B", f"builder/{bid}-fix", f"origin/{B.assigned[-1]['onto']}")
        (w / "a.txt").write_text("one, fixed\n")
        git(w, "commit", "-q", "-am", "fix the export")
        git(w, "push", "-q", "origin", f"builder/{bid}-fix")
        conn.execute("update builds set status='review', summary='Fixed the export at 2 GB' where id=?", (bid,))
    return B, up, work


def test_a_change_for_an_item_starts_at_its_tag_and_goes_out_as_a_draft_whose_review_comment_wakes_the_run(W):
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    B, up, work = builds_standin(W, conn)
    forge = Forge()
    req = {"kind": "build", "repo": "toy", "brief": "Fix the export at 2 GB", "item": "test/T-8", "base": "v1.0", "target": "release/1",
           "execution": "41", "workflow": "wf1"}
    naps = []

    def sleep(s):                                    # the builder works while the step waits
        naps.append(s)
        work(1)
    push = str(W.tmp / "fork.git")
    git(W.tmp, "init", "-q", "--bare", push)
    a = FW.item_build(conn, "b1", req, B=B, forge=forge, values={"FORGE_PUSH": push}, sleep=sleep)
    branch = "ai/T-8-fix-the-export-at-2-gb"
    assert B.assigned[0]["onto"] == branch and git(up, "rev-parse", f"{branch}") == git(up, "rev-parse", "v1.0^{commit}")   # from the tag
    assert a["status"] == "done" and a["pr"].endswith("/pull-requests/7") and a["draft"] is True and a["branch"] == branch
    assert forge.opened[0]["head"] == branch and forge.opened[0]["base"] == "release/1" and forge.opened[0]["draft"] is True
    assert git(push, "log", "-1", "--format=%s", branch) == "fix the export"                       # pushed through FORGE_PUSH
    assert conn.execute("select pr_number from builds where id=1").fetchone()[0] == 7
    assert FW.item_build(conn, "b1", req, B=B, forge=forge, values={"FORGE_PUSH": push}, sleep=sleep)["pr"] == a["pr"] and len(forge.opened) == 1
    W.item("T-8", "2026-11-10T09:00:00")
    W.poll(forge=forge)
    W.step("w8", kind="wait_item", tracker="test", key="T-8", timeout_hours=72, on="pr")      # a wait for the review (WFL-32)
    forge.cs = [{"id": 1, "author": "ai-stack", "body": "opened"}, {"id": 2, "author": "reviewer", "body": "please add a test"}]
    assert FWK.poll_prs(forge, hand=RR.hand) and RR.drain(TR.config(), W.n8n, lambda ex: "running") == {"woke": 1}
    W.step("w8", kind="wait_item", tracker="test", key="T-8", timeout_hours=72, on="pr")
    assert W.resumed[-1][1]["outcome"] == "reply" and W.resumed[-1][1]["comments"] == ["pr-comment:7/2"]
    assert "merge" not in json.dumps(B.assigned).lower()                                             # the stack never merges


def test_without_forge_push_a_change_for_an_item_waits_for_the_owner_in_the_app(W):
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    B, up, work = builds_standin(W, conn)
    forge = Forge()
    a = FW.item_build(conn, "b2", {"kind": "build", "repo": "toy", "brief": "Fix it", "item": "test/T-9", "base": "v1.0", "target": "release/1"},
                      B=B, forge=forge, values={}, sleep=lambda s: work(1))
    assert a["status"] == "done" and a["pr"] == "" and "waits for the owner" in a["note"] and forge.opened == []


def test_a_question_for_a_role_says_who_may_answer_refuses_anyone_else_and_records_who_did(W, monkeypatch):
    import decisions as D
    roles = W.tmp / "roles.yaml"
    roles.write_text("default: [lead]\nroles: {reviewer: [lena, lars]}\n")
    monkeypatch.setenv("AISTACK_ROLES", str(roles))
    W.step("q1", kind="ask", question="Ship the fix?", answers=["Ship", "Hold"], role="reviewer")
    item = next(d for d in D._flows({}) if d["id"] == "flow:q1")
    assert "Who may answer: lena, lars (reviewer)" in item["why"] and W.told == ["A workflow asks lena, lars: Ship the fix? (Needs you)"]
    assert FW.answer({"id": "q1", "answer": "Ship", "who": "lead"}) == {"ok": False, "error": "only lena, lars may answer this (reviewer)"}
    assert FW.answer({"id": "q1", "answer": "Ship", "who": "lars"}) == {"ok": True, "answer": "Ship", "who": "lars"}
    W.step("q1", kind="ask", question="Ship the fix?", answers=["Ship", "Hold"], role="reviewer")
    assert W.resumed[-1][1]["answer"] == "Ship" and W.resumed[-1][1]["by"] == "lars" and W.resumed[-1][1]["role"] == "reviewer"
    src = (ROOT / "images/mission-control/server.py").read_text()
    assert 'body["who"] = request.headers.get("tailscale-user-login") or "owner"' in src             # who, from the sign-in


def test_with_no_map_of_roles_a_question_for_a_role_is_the_owners(W, monkeypatch):
    monkeypatch.setenv("AISTACK_ROLES", str(W.tmp / "none.yaml"))
    W.step("q2", kind="ask", question="Go?", role="reviewer")
    assert W.told == ["A workflow asks you: Go? (Needs you)"]
    assert FW.answer({"id": "q2", "answer": "Yes", "who": "owner@example"})["ok"]


def test_the_node_waits_on_an_item_writes_to_it_and_a_timeout_is_a_result_while_a_failure_still_fails():
    """WFL-20, WFL-21 in the node. Shown on a throwaway n8n 2.44.7 on 10 Nov 2026 (its own Postgres, a private network,
    a stand-in step service): webhook item/toy/bug started the run and answered its execution; the wait answered
    outcome timeout, the IF node sent the run to the reminder (a tracker write) and a second wait, which got a reply, and
    the run ended in success; an agent step answered failed and its run ended in error ("The step failed: two attempts
    failed")."""
    js = (ROOT / "n8n/custom/AistackStep.node.js").read_text()
    assert "if (kind === 'wait_item') Object.assign(body, { tracker: p('tracker'), key: String(p('key')), timeout_hours: Number(p('timeout_hours', 0)) });" in js
    assert "if (kind === 'tracker') Object.assign(body, { tracker: p('tracker'), key: String(p('key')), write: p('write'), body: p('body', ''), from_step: p('from_step', '') || undefined });" in js
    assert "if (!succeeded(answer)) failOnResume(this, answer);" in js
    assert "async getTrackers() { return pick(this, 'trackers'); }" in js and "loadOptionsMethod: 'getRoles'" in js
    assert "workflow_name: this.getWorkflow().name," in js and "node: this.getNode().name," in js
    assert "role: p('role', '') || undefined" in js and "item: p('item'), base: p('base', ''), target: p('target', '')" in js
    for write in TR.KINDS:
        assert f"'{write}'" in js


# ---------- tracker items a run can work with (the CR of 10 Nov 2026): WFL-26 to WFL-28, WFL-32, WFL-33 ----------
def test_a_new_tracker_with_three_matching_items_starts_nothing_and_one_run_when_one_of_them_gets_a_comment(W):
    """WFL-27 (B3): start: now, the default for a new tracker."""
    W.cfg.write_text(W.cfg.read_text().replace(", start: 2026-01-01", ""))
    for n in (1, 2, 3):
        W.item(f"T-{n}", f"2026-11-10T0{n}:00:00")
    assert W.poll()["said"] == {} and W.started == []
    W.item("T-2", "2026-11-10T09:00:00", [("reporter", "it is still there")])
    assert W.poll()["said"] == {"started": 1} and [b["key"] for _, b in W.started] == ["T-2"]
    assert W.started[0][1]["comments"] == ["comment:test/T-2/1"] and RR.item("test", "T-1") is None


def test_with_me_unset_the_stacks_own_comment_and_summary_do_not_wake_a_wait_and_a_persons_comment_does(W, monkeypatch):
    """WFL-26 (B2): the tracker names no me; every comment has one author, the stack's end with its write mark."""
    monkeypatch.setattr(FW, "lean_answers", lambda *a: False)               # whole answers, as at home
    assert "me" not in TR.find("test")
    W.item("T-13", "2026-11-10T09:00:00")
    W.poll()
    W.step("w13", kind="wait_item", tracker="test", key="T-13", timeout_hours=72)
    own = [("owner", f"Three questions.\n{TR.WRITE_MARK.format(id='n8n/a')}"), ("owner", f"{TR.SUMMARY_MARK}\nWhere it stands.\n{TR.WRITE_MARK.format(id='n8n/s')}")]
    W.item("T-13", "2026-11-10T09:05:00", own)
    assert W.poll()["said"] == {"recorded": 1}
    W.step("w13", kind="wait_item", tracker="test", key="T-13", timeout_hours=72)
    assert W.resumed == []
    W.item("T-13", "2026-11-10T09:10:00", [*own, ("owner", "Here are the answers.")])
    assert W.poll()["said"] == {"woke": 1}
    W.step("w13", kind="wait_item", tracker="test", key="T-13", timeout_hours=72)
    assert W.resumed[-1][1]["comments"] == ["comment:test/T-13/3"] and W.resumed[-1][1]["replies"][0]["text"] == "Here are the answers."


def test_a_wait_is_answered_only_from_its_source_and_says_which_it_was(W, monkeypatch):
    """WFL-32 (B4): a wait on the item is not woken by a pull request comment, which waits for a wait on the pull
    request; on: any takes both. The answer says its source and carries the comments' texts."""
    monkeypatch.setattr(FW, "lean_answers", lambda *a: False)               # whole answers, as at home
    W.item("T-14", "2026-11-10T09:00:00")
    W.poll()
    W.step("w14", kind="wait_item", tracker="test", key="T-14", timeout_hours=0)          # on: item, the default
    pr = {"run": "toy/ticket:test/T-14", "key": "test/T-14", "ref": "pr:7", "comments": ["pr-comment:7/2"],
          "said": [{"ref": "pr-comment:7/2", "author": "reviewer", "at": "", "text": "please add a test"}]}
    RR.hand([pr])
    assert RR.drain(TR.config(), W.n8n, lambda ex: "running") == {"recorded": 1}
    W.step("w14", kind="wait_item", tracker="test", key="T-14", timeout_hours=0)
    assert W.resumed == [] and RR.item("test", "T-14")["unread"] == ["pr-comment:7/2"]
    W.item("T-14", "2026-11-10T09:30:00", [("reporter", "2.4 GB")])
    assert W.poll()["said"] == {"woke": 1}
    W.step("w14", kind="wait_item", tracker="test", key="T-14", timeout_hours=0)
    a = W.resumed[-1][1]
    assert (a["outcome"], a["source"], a["comments"]) == ("reply", "item", ["comment:test/T-14/1"]) and a["replies"][0]["text"] == "2.4 GB"
    assert a["output"] == "reporter:\n2.4 GB" and a["summary"] == "1 new comment on the item"
    W.step("w15", kind="wait_item", tracker="test", key="T-14", timeout_hours=0, on="pr")  # the review comment that came before
    a = W.resumed[-1][1]
    assert (a["source"], a["comments"], a["replies"][0]["text"]) == ("pr", ["pr-comment:7/2"], "please add a test")
    W.step("w16", kind="wait_item", tracker="test", key="T-14", timeout_hours=0, on="any")
    W.item("T-14", "2026-11-10T10:00:00", [("reporter", "2.4 GB"), ("reporter", "and 3 GB")])
    assert W.poll()["said"] == {"woke": 1}
    W.step("w16", kind="wait_item", tracker="test", key="T-14", timeout_hours=0, on="any")
    assert W.resumed[-1][1]["source"] == "item" and RR.item("test", "T-14")["unread"] == []
    assert "a wait is on item, pr, any" in FW.validate({"kind": "wait_item", "tracker": "test", "key": "T-14", "on": "mail"}, {}, {})


def test_a_waits_answer_says_how_often_it_timed_out_before_so_a_workflow_can_stop_reminding(W, monkeypatch):
    """WFL-33 (G3): reminded counts the timeouts of the run's waits of one node; a reply carries it and starts it again."""
    W.item("T-15", "2026-11-10T09:00:00")
    W.poll()
    now = {"t": W.clock["now"]}
    monkeypatch.setattr(RR, "_now", lambda: now["t"])
    said = []
    for rid in ("w1", "w2", "w3"):
        W.step(rid, kind="wait_item", tracker="test", key="T-15", timeout_hours=1, node="Wait for the reply")
        now["t"] += 3601
        W.step(rid, kind="wait_item", tracker="test", key="T-15", timeout_hours=1, node="Wait for the reply")
        said.append((W.resumed[-1][1]["outcome"], W.resumed[-1][1]["reminded"]))
    assert said == [("timeout", 0), ("timeout", 1), ("timeout", 2)]
    W.step("w4", kind="wait_item", tracker="test", key="T-15", timeout_hours=1, node="Wait for the reply")
    W.item("T-15", "2026-11-10T10:00:00", [("reporter", "here")])
    W.poll()
    W.step("w4", kind="wait_item", tracker="test", key="T-15", timeout_hours=1, node="Wait for the reply")
    assert (W.resumed[-1][1]["outcome"], W.resumed[-1][1]["reminded"]) == ("reply", 3)
    W.step("w5", kind="wait_item", tracker="test", key="T-15", timeout_hours=1, node="Wait for the reply")
    now["t"] += 3601
    W.step("w5", kind="wait_item", tracker="test", key="T-15", timeout_hours=1, node="Wait for the reply")
    assert W.resumed[-1][1]["reminded"] == 0                                         # after a reply the count starts again


def test_an_item_step_reads_the_item_and_fetches_its_attachments_by_artifact_id_within_its_caps(W, monkeypatch):
    """WFL-28 (G1): the item through its adapter (title, text, status, labels, comments with the stack's own marked,
    attachments); attach_to saves the named files into the artifact store with the deployment's data class and answers
    their ids; more than ATTACH_COUNT, one over ATTACH_MB, or a name the item does not have are refused or fail."""
    monkeypatch.setattr(FW, "lean_answers", lambda *a: False)               # whole answers, as at home
    from domain import artifacts as AR
    W.item("T-16", "2026-11-10T09:00:00", [("reporter", "the log is attached"), ("ai-stack", "thanks")])
    db = json.loads(W.store.read_text())
    db["items"]["T-16"].update(body="It stops at 1.2 GB.", status="Open", labels=["export"],
                               attachments=[{"id": "1", "name": "crash.log", "content": "MemoryError\n"}, {"id": "2", "name": "big.bin", "size": 99 * 2 ** 20}])
    W.store.write_text(json.dumps(db))
    W.step("i1", kind="item", tracker="test", key="T-16", node="Read the item")
    a = W.resumed[-1][1]
    assert (a["status"], a["title"], a["body"], a["item_status"], a["labels"]) == ("done", "ticket T-16", "It stops at 1.2 GB.", "Open", ["export"])
    assert [(c["author"], c["own"], c["text"]) for c in a["thread"]] == [("reporter", False, "the log is attached"), ("ai-stack", True, "thanks")]
    assert a["attachments"] == [{"id": "1", "name": "crash.log", "size": 12}, {"id": "2", "name": "big.bin", "size": 99 * 2 ** 20}] and "artifact_ids" not in a
    assert "Labels: export" in a["output"] and "Its attachments: crash.log, big.bin" in a["output"]
    W.step("i2", kind="item", tracker="test", key="T-16", attach_to="wsl-host", attachments=["crash.log"])
    a = W.resumed[-1][1]
    (aid,) = a["artifact_ids"]
    assert AR.path_of(aid).read_bytes() == b"MemoryError\n" and AR.records(aid)[0]["name"] == "crash.log" and a["data_class"] == FW.data_class()
    lean = FW.lean(a)
    assert lean["artifact_ids"] == [aid] and lean["summary"] == "2 comments, 2 attachments" and not {"body", "title", "thread", "output"} & set(lean)
    W.step("i3", kind="item", tracker="test", key="T-16", attach_to="wsl-host")
    assert W.resumed[-1][1]["status"] == "refused" and W.resumed[-1][1]["error"] == "big.bin is 99 MB; an attachment is fetched up to 50 MB"
    W.step("i4", kind="item", tracker="test", key="T-16", attach_to="wsl-host", attachments=["nope.txt"])
    assert W.resumed[-1][1]["error"] == "the item has no attachment 'nope.txt'"
    assert "at most 10" in FW.validate({"kind": "item", "tracker": "test", "key": "T-16", "attach_to": "wsl-host", "attachments": [f"f{n}" for n in range(11)]}, {}, {})
    assert "attach_to is a place" in FW.validate({"kind": "item", "tracker": "test", "key": "T-16", "attach_to": "mars"}, {}, {})
    values, files = FW.job_files({"input": aid, "seconds": 2}, {"params": {"input": {"type": "file", "max_kb": 64}, "seconds": {"type": "int"}}})
    assert values == {"input": "crash.log", "seconds": 2} and files == {"crash.log": b"MemoryError\n"}   # a command gets it by its id
    with pytest.raises(ValueError, match="no saved file"):
        FW.job_files({"input": "artifact:" + "0" * 64}, {"params": {"input": {"type": "file", "max_kb": 64}}})


def test_the_node_reads_an_item_waits_on_its_source_and_says_from_item():
    js = (ROOT / "n8n/custom/AistackStep.node.js").read_text()
    assert "{ name: 'Read the item', value: 'item'," in js and "if (kind === 'wait_item') body.on = p('on', 'item');" in js
    assert "if (kind === 'item') Object.assign(body, { tracker: p('tracker'), key: String(p('key')), attach_to: p('attach_to', '') || undefined," in js
    assert "async getAttachPlaces() { return [{ name: 'No files', value: '' }, ...(await pick(this, 'places'))]; }," in js
    assert "if (kind === 'agent' && p('tracker', '')) body.from_item = true;" in js

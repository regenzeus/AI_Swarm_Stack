"""Trackers and the forge (GEN-25, GEN-26, docs/AI-STACK.md), on stand-ins: a changed item is handed on once for the
run named after it, and a restart hands nothing on twice; the summary comment is edited across three updates; shadow
mode writes nothing outward until the owner lets a kind go live; a change starts at a tag, opens a draft into a release
branch, and a reviewer's comment is handed on once."""
import datetime as dt
import json
import subprocess

import pytest

from domain import forgework as FW
from domain import trackers as TR


@pytest.fixture
def world(tmp_path, monkeypatch):
    store = tmp_path / "standin.json"
    store.write_text(json.dumps({"items": {}}))
    cfg = tmp_path / "trackers.yaml"
    cfg.write_text(f"shadow_needed: 2\ntrackers:\n  - {{name: test, kind: standin, path: {store}, workflow: toy/ask}}\n")
    monkeypatch.setenv("AISTACK_TRACKERS", str(cfg))
    monkeypatch.setenv("AISTACK_TRACKER_STATE", str(tmp_path / "state"))

    def item(key, updated, comments=()):
        db = json.loads(store.read_text())
        db["items"][key] = {"updated": updated, "title": f"ticket {key}", "comments": [{"id": i + 1, "author": a, "body": b} for i, (a, b) in enumerate(comments)]}
        store.write_text(json.dumps(db))
    return {"store": store, "item": item, "tmp": tmp_path}


def test_a_changed_item_is_handed_on_once_for_the_run_named_after_it_and_a_restart_hands_on_nothing_twice(world):
    world["item"]("T-1", "2026-11-09T10:00:00")
    ev = TR.poll()
    assert ev == [{"tracker": "test", "key": "T-1", "run": "toy/ask:test/T-1", "ref": "item:test/T-1@2026-11-09T10:00:00", "comments": []}]
    assert TR.poll() == []                                                               # the cursor holds across passes and restarts
    world["item"]("T-1", "2026-11-09T11:00:00")
    assert [(e["run"], e["ref"]) for e in TR.poll()] == [("toy/ask:test/T-1", "item:test/T-1@2026-11-09T11:00:00")]   # one item, one run's name
    (world["tmp"] / "state/test.json").unlink()                                          # a restart that lost the cursor hands the item on again,
    assert [e["run"] for e in TR.poll()] == ["toy/ask:test/T-1"]                         # under the same name, so its run is found, not doubled
    assert json.loads(world["store"].read_text())["items"]["T-1"]["comments"] == []      # reading writes nothing back


def test_a_comment_from_someone_else_is_handed_on_once(world):
    world["item"]("T-2", "2026-11-09T10:00:00", [("reporter", "it breaks at 2 GB"), ("ai-stack", "noted")])
    assert [e["comments"] for e in TR.poll()] == [["comment:test/T-2/1"]]               # the stack's own comment is no event
    world["item"]("T-2", "2026-11-09T10:05:00", [("reporter", "it breaks at 2 GB"), ("ai-stack", "noted"), ("reporter", "also at 3 GB")])
    assert [e["comments"] for e in TR.poll()] == [["comment:test/T-2/3"]]


def test_shadow_writes_nothing_outward_until_the_owner_lets_a_kind_go_live_after_its_measure(world):
    world["item"]("T-3", "2026-11-09T10:00:00")
    r = TR.write({"tracker": "test", "kind": "comment", "key": "T-3", "body": "Reproduced on the large input", "write_id": "run/n/r0"})
    assert r["shadow"] and json.loads(world["store"].read_text())["items"]["T-3"]["comments"] == []
    make = lambda *a, **k: {"id": a[0], "cls": a[1], **k}                                # noqa: E731
    assert [d["id"] for d in TR.decisions(make)] == ["shadow:comment:run/n/r0"]
    TR.write({"tracker": "test", "kind": "comment", "key": "T-3", "body": "again", "write_id": "run/n/r1"})
    for wid in ("run/n/r0", "run/n/r1"):
        assert TR.handle({"action": "tracker_shadow_approve", "kind": "comment", "id": wid})["ok"]
    live = [d for d in TR.decisions(make) if d["id"] == "tracker-live:comment"]
    assert live and live[0]["cls"] == "tracker-comment"                                  # the measure (2) is met: the owner may
    assert TR.handle({"action": "tracker_live", "kind": "comment", "live": True})["live"]
    TR.write({"tracker": "test", "kind": "comment", "key": "T-3", "body": "Fixed on the release branch", "write_id": "run/n/r2"})
    TR.write({"tracker": "test", "kind": "comment", "key": "T-3", "body": "Fixed on the release branch", "write_id": "run/n/r2"})   # a retry
    cs = json.loads(world["store"].read_text())["items"]["T-3"]["comments"]
    assert len(cs) == 1 and cs[0]["body"].startswith("Fixed on the release branch")
    k = TR.view()["kinds"][0]
    assert k["kind"] == "comment" and k["live"] and k["approved"] == 2
    r = TR.write({"tracker": "test", "kind": "transition", "key": "T-3", "body": "Done", "write_id": "w9"})
    assert r.get("shadow") is True and "status" not in json.loads(world["store"].read_text())["items"]["T-3"]   # each kind on its own


def test_the_one_summary_comment_is_edited_across_three_updates(world):
    world["item"]("T-4", "2026-11-09T10:00:00")
    TR.handle({"action": "tracker_live", "kind": "summary", "live": True})
    for n in range(3):
        TR.write({"tracker": "test", "kind": "summary", "key": "T-4", "body": f"Update {n + 1}", "write_id": f"run/sum/r{n}"})
    cs = json.loads(world["store"].read_text())["items"]["T-4"]["comments"]
    assert len(cs) == 1 and "Update 3" in cs[0]["body"] and TR.SUMMARY_MARK in cs[0]["body"] and cs[0].get("edited")


def test_a_write_to_an_unknown_tracker_or_of_an_unknown_kind_is_refused_with_the_reason(world):
    assert "no tracker 'nope'" in TR.write({"tracker": "nope", "kind": "comment", "key": "x", "write_id": "w"})["why"]
    assert "a tracker write is one of" in TR.write({"tracker": "test", "kind": "shout", "key": "x", "write_id": "w"})["why"]


class FakeJira:
    """Jira Data Center as the adapter sees it: JQL read to the minute in the token user's time zone, pages of at most
    `limit` issues, and the stack's one summary comment."""

    def __init__(self, issues=(), zone="Europe/Berlin"):
        self.issues, self.zone, self.jqls, self.edited = list(issues), zone, [], []
        self.cs = [{"id": "7", "author": {"name": "ai-stack"}, "body": f"{TR.SUMMARY_MARK}\nold"}]

    def myself(self):
        return {"name": "ai-stack", "timeZone": self.zone}

    def jql(self, q, start=0, limit=50, fields=""):
        import re
        from zoneinfo import ZoneInfo
        self.jqls.append(q)
        m = re.search(r'updated >= "(.+?)"', q)
        since = dt.datetime.strptime(m[1], "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(self.zone)) if m else None
        hits = sorted((i for i in self.issues if since is None or TR._when(i[1]) >= since), key=lambda i: TR._when(i[1]))
        return {"total": len(hits), "issues": [{"key": k, "fields": {"updated": u, "summary": "s", "status": {"name": "Open"}, "labels": []}}
                                               for k, u in hits[start:start + limit]]}

    def issue_get_comments(self, key):
        return {"comments": self.cs}

    def issue_edit_comment(self, key, cid, text):
        self.edited.append((key, cid, text))

    def issue_add_comment(self, key, text):
        raise AssertionError("the summary is edited, never added again")


def test_jira_reads_by_jql_with_its_cursor_and_edits_its_one_summary():
    fake = FakeJira([("DEMO-1", "2026-11-09T10:00:00.000+0000")])
    j = TR.Jira({"query": "project = DEMO"}, client=fake)
    items, cur = j.changes({"at": "2026-11-09T09:00:00.000+0000", "seen": []})
    assert fake.jqls == ['(project = DEMO) AND updated >= "2026-11-09 10:00" ORDER BY updated ASC']   # 09:00 UTC is 10:00 in Berlin
    assert [i["key"] for i in items] == ["DEMO-1"] and cur == {"at": "2026-11-09T10:00:00.000+0000", "seen": [["DEMO-1", "2026-11-09T10:00:00.000+0000"]]}
    j.put("DEMO-1", "summary", "new", "w1")
    assert fake.edited[0][:2] == ("DEMO-1", "7") and "new" in fake.edited[0][2]


def test_jira_reads_its_cursor_in_the_token_users_time_zone_not_the_servers():
    fake = FakeJira([("DEMO-2", "2026-11-09T10:05:10.000+0100"), ("DEMO-3", "2026-11-09T10:07:00.000+0100")], zone="America/New_York")
    j = TR.Jira({"query": "project = DEMO"}, client=fake)
    items, cur = j.changes({"at": "2026-11-09T10:05:10.000+0100", "seen": [["DEMO-2", "2026-11-09T10:05:10.000+0100"]]})
    assert 'updated >= "2026-11-09 04:05"' in fake.jqls[0]                     # the server's 10:05 +0100 is 04:05 for the user
    assert [i["key"] for i in items] == ["DEMO-3"] and cur["at"] == "2026-11-09T10:07:00.000+0100"


def test_jira_hands_on_60_items_of_one_minute_once_and_its_cursor_moves_on():
    fake = FakeJira([(f"DEMO-{n}", f"2026-11-09T10:05:{n % 60:02d}.000+0000") for n in range(1, 61)], zone="UTC")
    j = TR.Jira({"query": "project = DEMO"}, client=fake)
    items, cur = j.changes("")
    assert len(items) == 60 and len({i["key"] for i in items}) == 60 and len(fake.jqls) == 2   # two pages of at most 50
    again, cur2 = j.changes(cur)
    assert again == [] and cur2["at"] == cur["at"]                               # the minute comes back; nothing twice
    fake.issues.append(("DEMO-61", "2026-11-09T10:06:01.000+0000"))
    later, cur3 = j.changes(cur2)
    assert [i["key"] for i in later] == ["DEMO-61"] and cur3 == {"at": "2026-11-09T10:06:01.000+0000", "seen": [["DEMO-61", "2026-11-09T10:06:01.000+0000"]]}


def test_jira_builds_its_query_without_an_empty_clause_and_refuses_one_with_its_own_order(world):
    fake = FakeJira([("DEMO-4", "2026-11-09T10:00:00.000+0000")], zone="UTC")
    j = TR.Jira({"query": "  "}, client=fake)
    assert j.jql("") == "ORDER BY updated ASC"
    assert j.jql({"at": "2026-11-09T10:00:00.000+0000"}) == 'updated >= "2026-11-09 10:00" ORDER BY updated ASC'
    with pytest.raises(ValueError, match="its own ORDER BY"):
        TR.Jira({"name": "bugs", "query": "project = DEMO order by created DESC"}, client=fake)
    world["tmp"].joinpath("trackers.yaml").write_text(
        "trackers:\n  - {name: bugs, kind: jira, url: https://jira.example, query: 'project = DEMO ORDER BY created'}\n"
        f"  - {{name: test, kind: standin, path: {world['store']}, workflow: toy/ask}}\n")
    assert TR.problems() == ["bugs: its query has its own ORDER BY; the stack orders by updated itself to keep its cursor, so leave the order out of the query"]
    world["item"]("T-9", "2026-11-09T10:00:00")
    assert [e["tracker"] for e in TR.poll()] == ["test"]                          # the refused tracker is not asked
    assert TR.view()["trackers"][0]["refused"].startswith("bugs: its query has its own ORDER BY")


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@localhost", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Forge:
    """The Bitbucket stand-in: what the stack asked of it, and a reviewer's comment."""

    def __init__(self):
        self.opened, self.cs = [], []

    def open_pr(self, origin, head, base, title, body, draft=False, from_repo=None):
        self.opened.append({"head": head, "base": base, "draft": draft})
        return {"number": 42, "url": "https://bitbucket.example/pr/42"}

    def comments(self, origin, number):
        return self.cs


def test_a_change_starts_at_a_tag_opens_a_draft_into_a_release_branch_and_a_reviewers_comment_is_handed_on_once(world):
    up = world["tmp"] / "upstream.git"
    work = world["tmp"] / "seed"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    (work / "a.txt").write_text("one\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "one")
    git(work, "tag", "v1.0")
    git(work, "branch", "release/1")
    (work / "a.txt").write_text("two\n")
    git(work, "commit", "-q", "-am", "two")
    tagged = git(work, "rev-parse", "v1.0")
    git(world["tmp"], "clone", "-q", "--bare", str(work), str(up))
    clone = world["tmp"] / "clone"
    git(world["tmp"], "clone", "-q", str(up), str(clone))
    branch = FW.branch_name("T-5", "Fix the export at 2 GB")
    assert branch == "ai/T-5-fix-the-export-at-2-gb" and FW.start(clone, "v1.0", branch) == tagged      # from the tag, not main
    forge = Forge()
    pr = FW.publish(clone, branch, str(up), forge, "ssh://bitbucket.example/PROJ/repo.git", "release/1", "Fix it", "body", "toy/ask:test/T-5", "test/T-5")
    assert pr["number"] == 42 and forge.opened == [{"head": branch, "base": "release/1", "draft": True}]
    assert git(up, "rev-parse", branch) == tagged                                          # pushed through FORGE_PUSH
    assert FW.poll_prs(forge) == []                                                        # no comment yet: nothing to hand on
    forge.cs = [{"id": 1, "author": "ai-stack", "body": "opened"}, {"id": 2, "author": "reviewer", "body": "please add a test"}]
    assert FW.poll_prs(forge) == [{"run": "toy/ask:test/T-5", "key": "test/T-5", "ref": "pr:42", "comments": ["pr-comment:42/2"]}]
    assert FW.poll_prs(forge) == []                                                        # a comment is handed on once


def test_trackers_are_the_apps_and_the_queues():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    js = (root / "images/mission-control/web/static/app.js").read_text()          # the Stack page's Packs and trackers
    assert "function trackersHtml(" in js and 'data-tk="tracker_shadow_approve"' in js and 'action: "tracker_live"' in js and "t.workflow" in js
    assert '"tracker_shadow_approve", "tracker_shadow_reject", "tracker_live"' in (root / "images/mission-control/server.py").read_text()
    import decisions as DQ
    assert DQ._trackers in DQ.SOURCES
    cls = __import__("yaml").safe_load((root / "config/autonomy.yaml").read_text())["classes"]
    assert all(f"tracker-{k}" in cls for k in TR.KINDS) and cls["tracker-transition"]["floor"] == "people" and cls["tracker-attach"]["floor"] == "people"
    assert [t["workflow"] for t in TR.view({"shadow_needed": 5, "trackers": [{"name": "t", "kind": "standin", "workflow": "toy/ticket"}]})["trackers"]] == ["toy/ticket"]


# ---------- one account for the stack and the owner (home's Forgejo token is the owner's): WFL-26 ----------
MARK = TR.WRITE_MARK.format(id="n8n/a1")


def test_the_stacks_own_comment_is_known_by_its_write_mark_where_it_writes_with_the_owners_account(world):
    """Where the stack writes with the owner's own account, author is no help: the stack's comment ends with its write
    mark and is its own; the owner's reply (also one that quotes the stack's comment) is someone else's."""
    world["item"]("T-6", "2026-11-09T10:00:00", [
        ("owner", "Which backups ran last night?"),
        ("owner", f"Three ran, all passed.\n{MARK}"),                                     # the stack's answer
        ("owner", f"{TR.SUMMARY_MARK}\nDone.\n{TR.WRITE_MARK.format(id='n8n/s1')}"),   # its summary
        ("owner", f"> Three ran, all passed.\n> {MARK}\n\nAnd the one before?"),          # a reply quoting it
        ("owner", f"See above:\n> {MARK}")])                                              # a reply ending in the quoted mark
    assert [e["comments"] for e in TR.poll()] == [["comment:test/T-6/1", "comment:test/T-6/4", "comment:test/T-6/5"]]
    assert TR.own({"author": "ai-stack", "body": "no mark"}, "ai-stack")                   # by its author, where it has its own account
    assert not TR.own({"author": "owner", "body": "<!-- ai-stack:write n8n/a1 --> in the middle\nof a text"}, "ai-stack")


def test_jira_and_pull_request_comments_follow_the_same_rule_on_one_account(world):
    fake = FakeJira([("DEMO-9", "2026-11-09T10:00:00.000+0000")])
    fake.cs = [{"id": "1", "author": {"name": "owner"}, "body": f"Answered.\n{MARK}"}, {"id": "2", "author": {"name": "owner"}, "body": "Thanks, and?"}]
    cfg = {"shadow_needed": 5, "poll_minutes": 5, "trackers": [{"name": "j", "kind": "jira", "query": "project = DEMO", "workflow": "demo/bug"}]}
    assert [e["comments"] for e in TR.poll(cfg, ad={"j": TR.Jira({"query": "project = DEMO"}, client=fake)})] == [["comment:j/DEMO-9/2"]]
    FW._save([{"run": "demo/bug:j/DEMO-9", "key": "j/DEMO-9", "origin": "forgejo:owner/repo", "number": 3, "seen": []}])
    forge = type("F", (), {"comments": lambda self, o, n: [{"id": 1, "author": "owner", "body": f"Opened.\n{MARK}"},
                                                           {"id": 2, "author": "owner", "body": "please add a test"}]})()
    assert FW.poll_prs(forge) == [{"run": "demo/bug:j/DEMO-9", "key": "j/DEMO-9", "ref": "pr:3", "comments": ["pr-comment:3/2"]}]


def test_an_agent_step_reads_its_item_with_the_stacks_own_comments_marked_as_its_own(world):
    """WFL-25: the item's title, status, text and comments in order; the stack's own as yours, its marks left out."""
    world["item"]("T-7", "2026-11-09T10:00:00", [("owner", "Which backups ran?"), ("owner", f"Three ran.\n{MARK}"), ("owner", "And before?")])
    db = json.loads(world["store"].read_text())
    db["items"]["T-7"].update(body="Please list last night's backups.", status="open")
    world["store"].write_text(json.dumps(db))
    text = TR.item_text("test", "T-7")
    assert text.startswith("The item test/T-7, as its tracker holds it now:\n\nTitle: ticket T-7\nStatus: open\n\nPlease list last night's backups.")
    assert "--- owner:\nWhich backups ran?\n\n--- You (the AI Stack):\nThree ran.\n\n--- owner:\nAnd before?" in text and "ai-stack:write" not in text
    with pytest.raises(ValueError, match="no tracker 'nope'"):
        TR.item_text("nope", "T-7")


def test_a_trackers_entry_may_name_a_value_of_its_deployment_and_one_it_does_not_set_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("AISTACK_TRACKER_STATE", str(tmp_path / "state"))
    (tmp_path / "deployment.env").write_text("FORGEJO_OWNER=someone\n")
    (tmp_path / "trackers.yaml").write_text("trackers:\n  - {name: inbox, kind: forgejo, repo: '${FORGEJO_OWNER}/inbox', workflow: home/inbox}\n"
                                            "  - {name: other, kind: forgejo, repo: '${NO_SUCH}/x', workflow: home/x}\n")
    cfg = TR.config(tmp_path / "trackers.yaml")
    assert cfg["trackers"][0]["repo"] == "someone/inbox" and TR.refused(cfg["trackers"][0]) == ""
    assert TR.problems(cfg) == ["other: it names ${NO_SUCH}, which the deployment.env does not set"]
    assert TR.poll(cfg, ad={"inbox": type("A", (), {"me": "x", "changes": lambda self, c: ([], c)})()}) == []   # the refused one is not asked

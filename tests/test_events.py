"""The event bus (TSK-10 to TSK-12): every source records its events (a first look only as a baseline), a rule fires a
task from a matching event within its cooldown and after its check, every firing is recorded, and breaking news is a
story that three publishers report within 30 minutes. Each source fires here with a fake in its real shape."""
import webjs
import datetime as dt
import json
import sqlite3
import threading
import types

import pytest

import events as EV

UTC = dt.timezone.utc


@pytest.fixture
def B(tmp_path, monkeypatch):
    db = tmp_path / "m.sqlite"

    def conn():
        c = sqlite3.connect(db, timeout=5)
        c.row_factory = sqlite3.Row
        return c
    c = conn()
    EV.table(c)
    import missions as MM
    made, feed = [], []
    EV.M = types.SimpleNamespace(db=conn, event=lambda *a, **k: feed.append(a), log=print, valid_schedule=MM.valid_schedule, stop=threading.Event())
    EV._status.clear()
    create = lambda req, c: made.append(req) or {"task": 100 + len(made)}
    return types.SimpleNamespace(c=c, made=made, feed=feed, create=create, tmp=tmp_path)


def rule(B, source, **kw):                       # as the app sends it: "when", and source=app stamped by the server
    return EV.save_rule(B.c, {"name": kw.pop("name", "a rule"), "task": kw.pop("task", "Tell me about {title} ({url})"), "when": source,
                              "source": "app", **kw})


def fired(B):
    return [dict(r) for r in B.c.execute("select * from firings order by id").fetchall()]


def test_the_web_sources_baseline_first_then_fire_their_rules(B):
    rule(B, source="news", param="copper supply")
    rule(B, source="feed", param="https://example.com/feed.xml")
    rule(B, source="github", param="regenzeus/AI_Swarm_Stack")
    rule(B, source="price", param="ACME:8")
    rule(B, source="filing", param="ACME")
    item = lambda i: {"id": f"n{i}", "title": f"Story {i}", "url": f"https://x/{i}", "source": "Reuters", "published": "2026-10-31T10:00:00+00:00"}
    look = lambda items, pct: lambda spec: {"news": {"copper supply": items}, "feeds": {"https://example.com/feed.xml": items},
                                           "github": {"regenzeus/AI_Swarm_Stack": [{"id": i["id"], "title": "Watch by someone: started", "url": "https://github.com/r",
                                                                                    "published": i["published"]} for i in items]},
                                           "prices": {"ACME": {"last": 60.0, "prev": 50.0, "pct": pct, "currency": "USD", "date": "2026-10-31"}},
                                           "sec": {"ACME": [{"id": i["id"], "form": "6-K", "title": f"Acme Mining filed 6-K {i['id']}", "url": "https://sec/x", "filed": i["published"]} for i in items]}}
    EV.web(B.c, look=look([item(1)], 2.0), create=B.create)
    assert B.made == [] and B.c.execute("select count(*) from bus where baseline=1").fetchone()[0] == 4      # news, feed, github, filing: baseline
    EV.web(B.c, look=look([item(1), item(2)], 20.0), create=B.create)
    srcs = sorted(r["source"] for r in B.c.execute("select source from bus where baseline=0").fetchall())
    assert srcs == ["feed", "filing", "github", "news", "price"] and len(B.made) == 5
    assert B.made[0]["text"] == "Tell me about Story 2 (https://x/2)" and B.made[0]["source"].startswith("rule:")
    assert EV.state(B.c)["bus"]["sources"]["news"]["found"] == 1 and EV.state(B.c)["bus"]["sources"]["breaking"]["off"]
    EV.web(B.c, look=look([item(3)], 2.0), create=B.create)
    assert EV.state(B.c)["bus"]["sources"]["feed"]["found"] == 1
    EV.web(B.c, look=lambda spec: (_ for _ in ()).throw(RuntimeError("no network")), create=B.create)
    assert "no network" in EV.state(B.c)["bus"]["sources"]["feed"]["error"]


def test_the_local_sources_each_fire(B, monkeypatch):
    import builds as Bu
    import inbox as IN
    import tasks as TK
    monkeypatch.setattr(TK, "create", B.create)                                    # task and mission events start tasks the usual way
    for src, param in (("forgejo", "ai-stack"), ("mail", "invoice"), ("house", "front door"), ("file", ".pdf"), ("schedule", "every 1h"), ("task", ""), ("mission", "")):
        rule(B, source=src, param=param, name=f"on {src}")
    monkeypatch.setenv("FORGEJO_TOKEN", "x")
    monkeypatch.setattr(Bu, "repos", lambda: ["ai-stack"])
    monkeypatch.setattr(Bu, "origin", lambda r: "forgejo:regenzeus/ai-stack.git")
    commits = [[{"sha": "a1", "commit": {"message": "first", "author": {"date": "2026-10-31T09:00:00Z"}}, "html_url": "u"}]]
    get = lambda path: commits[-1] if "/commits" in path else []
    EV.forgejo(B.c, get=get, create=B.create)                                     # baseline
    commits.append([{"sha": "b2", "commit": {"message": "Fix the wiki map\n\nmore", "author": {"date": "2026-10-31T10:00:00Z"}}, "html_url": "u"}] + commits[0])
    EV.forgejo(B.c, get=get, create=B.create)
    monkeypatch.setattr(IN, "granted", lambda scope="read": True)
    rows = ["- id m1 · 31 Oct · Shop <a@b.c> · Your order · 3 KB"]
    search = lambda tool, args: "\n".join(rows)
    EV.mail(B.c, search=search, create=B.create)                                  # baseline
    rows.append("- id m2 · 31 Oct · Billing <invoice@b.c> · Invoice 42 · 5 KB")
    EV.mail(B.c, search=search, create=B.create)
    door = {"entity_id": "binary_sensor.front_door", "name": "Front door", "domain": "binary_sensor", "area": "Hall"}
    EV.house(B.c, things=[{**door, "state": "off"}], create=B.create)
    EV.house(B.c, things=[{**door, "state": "on"}], create=B.create)
    d = B.tmp / "exports"
    d.mkdir()
    (d / "old.txt").write_text("x")
    EV.files(B.c, folder=d, create=B.create)                                      # baseline
    (d / "scan.pdf").write_text("x")
    EV.files(B.c, folder=d, create=B.create)
    EV.schedules(B.c, create=B.create)
    EV.task_done(B.c, {"id": 7, "title": "RAM check", "goal": "g"}, "done")
    EV.mission_event(B.c, "copper", {"kind": "news", "trigger": "News about copper", "summary": "3 new articles"})
    srcs = [r["source"] for r in B.c.execute("select source from bus where baseline=0 order by id").fetchall()]
    assert srcs == ["forgejo", "mail", "house", "file", "schedule", "task", "mission"]
    assert [f["decision"] for f in fired(B)] == ["fired"] * 7 and len(B.made) == 7
    titles = [r["title"] for r in B.c.execute("select title from bus where baseline=0 order by id").fetchall()]
    assert titles[:4] == ["ai-stack: Fix the wiki map", "Invoice 42", "Front door: off → on", "scan.pdf"]
    monkeypatch.setattr(IN, "granted", lambda scope="read": False)
    EV.mail(B.c, search=search, create=B.create)
    assert "not granted" in EV.state(B.c)["bus"]["sources"]["mail"]["off"]


def test_mail_and_forgejo_are_read_only_while_a_rule_asks_and_a_baseline_is_not_new(B, monkeypatch):
    calls = []
    for f in ("schedules", "house", "files", "forgejo", "mail"):
        monkeypatch.setattr(EV, f, lambda c, f=f: calls.append(f))
    EV._last.update(local=0, mail=0, web=10 ** 12)
    EV.tick(B.c)
    assert calls == ["schedules", "house", "files"] and EV.state(B.c)["bus"]["sources"]["mail"]["off"] == "no rule asks for it"
    rule(B, source="mail", param="invoice")
    EV._last.update(local=0)
    EV.tick(B.c)
    assert calls[-1] == "mail"
    EV._last.update(local=0)
    EV.tick(B.c)
    assert calls[-1] == "files"                                                  # mail again only after 5 minutes


def test_a_rule_waits_out_its_cooldown_runs_its_check_and_records_every_firing(B):
    rule(B, source="news", param="acme-mining", words="contract", cooldown_min=60, check="a new supply contract, not a rumour")
    no = lambda p: {"match": False, "why": "a rumour"}
    yes = lambda p: {"match": True, "why": "a signed contract"}
    ev = lambda k, title: EV.emit(B.c, "news", "article", k, title, ask=yes if "signed" in title else no, create=B.create, param="acme-mining")
    ev("1", "Acme Mining shares rise")                                                 # no 'contract': not even checked
    ev("2", "Acme Mining contract rumour")
    ev("3", "Acme Mining signed contract with utility")
    ev("4", "Acme Mining signed contract, more details")
    assert [(f["decision"], f["task"]) for f in fired(B)] == [("rejected by its check", None), ("fired", 101), ("cooldown", None)]
    assert "rumour" in fired(B)[0]["why"] and "cooldown 60 min" in fired(B)[2]["why"] and B.feed and "fired" in B.feed[0][2]
    err = lambda p: (_ for _ in ()).throw(RuntimeError("RateLimitError: usage_limit_reached"))
    B.c.execute("update rules set last_fired=null"); B.c.commit()
    EV.emit(B.c, "news", "article", "5", "Acme Mining signed contract again", ask=err, create=B.create, param="acme-mining")
    assert fired(B)[-1]["decision"] == "check failed" and "usage_limit" in fired(B)[-1]["why"]


def item(i, source, minute, title="Acme Mining signs 20-year copper supply contract with US utility"):
    return {"id": f"b{i}", "title": f"{title} - {source}", "url": f"https://{i}", "source": source,
            "published": (dt.datetime(2026, 10, 31, 10, 0, tzinfo=UTC) + dt.timedelta(minutes=minute)).isoformat()}


def test_breaking_news_is_three_publishers_on_one_new_story_within_30_minutes(B):
    rule(B, source="breaking", param="Acme Mining", task="What does {title} mean for me? Sources: {detail}")
    t = dt.datetime(2026, 10, 31, 10, 40, tzinfo=UTC)
    two = [item(1, "Reuters", 0), item(2, "Bloomberg", 10)]
    assert EV.breaking(B.c, "Acme Mining", two, now_t=t, create=B.create) == []
    other = item(3, "Mining.com", 12, "Acme Mining to report third-quarter results next week")
    late = item(4, "FT", 45)                                                      # the third publisher, but 45 min after the first
    assert EV.breaking(B.c, "Acme Mining", [other, late], now_t=t, create=B.create) == []
    raised = EV.breaking(B.c, "Acme Mining", [item(5, "WSJ", 25)], now_t=t, create=B.create)
    assert len(raised) == 1 and len(B.made) == 1 and "Reuters" in B.made[0]["text"] and "WSJ" in B.made[0]["text"]
    EV.breaking(B.c, "Acme Mining", [item(6, "CNBC", 50)], now_t=t, create=B.create)  # attaches, raises nothing new
    ev = dict(B.c.execute("select * from bus where id=?", (raised[0],)).fetchone())
    assert "CNBC" in ev["detail"] and len(B.made) == 1 and json.loads(ev["data"])["publishers"] == ["Bloomberg", "FT", "Reuters", "WSJ"]
    old = [item(10 + i, s, i) for i, s in enumerate(["AP", "AFP", "DPA"])]
    assert EV.breaking(B.c, "Acme Mining", [{**x, "title": "Acme Mining opens new mine in Saskatchewan"} for x in old],
                       now_t=t + dt.timedelta(hours=5), create=B.create) == []      # three publishers, but 5 h old: not breaking
    assert EV.breaking(B.c, "Copper", [item(20 + i, s, i) for i, s in enumerate(["A", "B", "C"])], now_t=t, create=B.create, baseline=True) == []
    EV.handle({"action": "event_rate", "id": raised[0], "rating": 1}, B.c)
    assert EV.state(B.c)["bus"]["ratings"] == {"right": 1, "not_news": 0, "raised": 1}


def test_rules_are_checked_when_saved_and_schedules_come_due():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    EV.table(c)
    import missions as MM
    EV.M = types.SimpleNamespace(valid_schedule=MM.valid_schedule)
    for bad in ({"source": "radio"}, {"source": "news", "param": "x"}, {"source": "feed", "param": "example.com"},
                {"source": "price", "param": "ACME"}, {"source": "schedule", "param": "at noon"}, {"source": "news", "param": "copper", "task": "go"}):
        with pytest.raises(ValueError):
            EV.save_rule(c, {"name": "x rule", "task": "Tell me about it", **{("when" if k == "source" else k): v for k, v in bad.items()}})
    t = dt.datetime(2026, 11, 2, 7, 5).astimezone()                               # a Monday
    assert EV.due("weekdays 07:00", None, t) and not EV.due("weekdays 07:00", t.isoformat(), t)
    assert not EV.due("weekly sat,sun 07:00", None, t) and EV.due("every 6h", (t - dt.timedelta(hours=7)).isoformat(), t)
    assert not EV.due("daily 08:00", None, t)
    app = "".join(webjs.app_js().split("rule_save")[1:2])
    assert "when: f.source.value" in app[:200]                                    # the form sends "when", which the server leaves alone

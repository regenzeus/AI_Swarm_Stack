"""The decision queue and its shadow (ops/decisions.py, AUT-03, AUT-05, AUT-07): every source's waits in one ranked
list with what, why, the stack's recommendation and the answers; the shadow records what it would decide and the
owner's outcome; the queue's numbers; the floor classes stay at ask. No services: a fake state and a temporary log."""
import importlib
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "images/mission-control/web/static/app.js").read_text()
T0 = 1793600000.0


@pytest.fixture
def DQ(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMY_LOG", str(tmp_path / "autonomy.jsonl"))
    import decisions
    m = importlib.reload(decisions)
    m._seen.clear(); m._loaded["t"] = 0
    return m


def state(**kw):
    st = {"builds": [{"id": 4, "status": "review", "title": "Fix the map", "checks_ok": True, "checks": "x", "ci": "success",
                      "ai_review": {"verdict": "approve"}, "updated": T0 - 3600},
                     {"id": 5, "status": "working", "title": "Busy"}],
          "shopping": {"proposals": [{"id": "p-1", "slug": "ram", "status": "proposed", "item": "RAM kit", "total_eur": 99, "shop": "Alternate",
                                      "deadline": T0 + 3600, "created": T0 - 60},
                                     {"id": "p-2", "slug": "ram", "status": "watching", "item": "Other", "total_eur": 189}]},
          "crew": [{"id": "phone-cleanup", "actions": [{"id": "a1", "status": "open", "kind": "cache", "title": "Empty all app caches", "size": 2e9},
                                                       {"id": "a2", "status": "open", "kind": "uninstall", "title": "Uninstall com.whatsapp"},
                                                       {"id": "a3", "status": "done", "kind": "cache"}]}],
          "system": {"pending_memory": [{"id": "m1", "text": "The owner prefers English"}]},
          "tasks": [{"id": 9, "status": "waiting_approval", "kind": "research", "title": "Compare two NAS"},
                    {"id": 10, "status": "needs_answer", "title": "Build it", "questions": ["Which repository?"]},
                    {"id": 11, "status": "running", "title": "At work"}],
          "swarm": {"owner_requests": [{"id": 3, "sender": "coach", "text": "May I?", "context": "c1"}],
                    "board": {"open": [{"id": 16, "kind": "idea", "title": "Exempt no-argument tools", "priority": 4.8, "effort": "small"},
                                       {"id": 17, "kind": "dispute", "title": "Two founding years"}], "recent": []},
                    "changes": [{"id": "scout", "agent": "scout", "version": 3, "state": "ready", "experiment": {"passed": True, "version": 3}}]}}
    st.update(kw)
    return st


def test_every_source_s_waits_are_one_ranked_list_with_what_why_and_a_recommendation(DQ):
    ds = DQ.gather(state(), now=T0)
    ids = [d["id"] for d in ds]
    assert set(ids) == {"build:4", "shop:p-1", "phone-step:a1", "phone-step:a2", "memory:m1", "task:9", "task-q:10", "ask:3",
                        "idea:16", "idea:17", "change:scout:3"}             # working builds, watched prices, running tasks are not decisions
    assert ids[0] == "shop:p-1"                                            # it expires within two hours: first
    assert ids.index("build:4") < ids.index("idea:16")                     # a deploy costs more to delay than an idea
    by = {d["id"]: d for d in ds}
    assert by["build:4"]["recommend"] == {"answer": "yes", "why": "its checks, CI and AI review all passed"} and by["build:4"]["cls"] == "coding-low-risk"
    assert by["phone-step:a1"]["recommend"]["answer"] == "yes" and by["phone-step:a2"]["recommend"]["answer"] == "no"   # an app is the owner's to remove
    assert by["phone-step:a1"]["routine"] and not by["phone-step:a2"]["routine"]      # so it is never in an "Approve all"
    assert by["phone-step:a2"]["answers"][1] == {"label": "Keep it", "act": {"action": "phone_cleanup_dismiss", "id": "a2"}}   # a no is one tap too
    assert by["task-q:10"]["recommend"] is None and "Which repository?" in by["task-q:10"]["why"]                       # words, not a yes or no
    assert by["idea:17"]["cls"] == "memory" and by["idea:17"]["what"].startswith("Which is true?")
    assert by["task:9"]["answers"][0] == {"label": "Start", "act": {"action": "task_approve", "id": 9}}
    assert all(d["what"] and d["href"] and "unanswered" in d for d in ds)


def test_the_shadow_records_once_and_then_the_owner_s_outcome(DQ):
    st = state()
    DQ.shadow(DQ.gather(st, T0), st, T0)
    DQ.shadow(DQ.gather(st, T0 + 60), st, T0 + 60)                           # seen once, not every pass
    seen = [r for r in DQ._records() if r["event"] == "seen"]
    assert len(seen) == 11 and all(r.get("backlog") for r in seen)          # what waited before the record began is a backlog
    after = state(builds=[{"id": 4, "status": "deployed"}], shopping={"proposals": [{"id": "p-1", "status": "rejected"}]},
                  tasks=[{"id": 9, "status": "running"}, {"id": 10, "status": "needs_answer", "questions": ["Which repository?"]}])
    after["crew"][0]["actions"][1]["status"] = "dismissed"
    DQ.shadow(DQ.gather(after, T0 + 7200), after, T0 + 7200)
    out = {r["id"]: r for r in DQ._records() if r["event"] == "answered"}
    assert out["build:4"]["owner"] == "yes" and out["build:4"]["would"] == "yes"
    assert out["shop:p-1"]["owner"] == "no" and out["shop:p-1"]["would"] == "yes" and out["task:9"]["owner"] == "yes"
    assert out["phone-step:a2"]["owner"] == "no" and out["build:4"]["secs"] == 7200
    s = DQ.stats(T0 + 7200)
    assert s["agreement"]["coding-low-risk"] == {"n": 1, "agreed": 1, "unsafe": 0}
    assert s["agreement"]["shopping-buy"] == {"n": 1, "agreed": 0, "unsafe": 1}       # it would have bought what the owner refused
    assert s["per_day"] == 0 and s["answered"] == 0                                    # the backlog counts for neither


def test_the_queue_s_numbers_a_day_the_median_and_the_expired(DQ):
    recs = [{"t": T0 + i * 3600, "event": "seen", "id": f"x{i}", "cls": "ideas"} for i in range(6)]
    recs += [{"t": T0 + 86400, "event": "answered", "id": "x0", "cls": "ideas", "owner": "yes", "would": "yes", "secs": 3600},
             {"t": T0 + 86400, "event": "answered", "id": "x1", "cls": "ideas", "owner": "no", "would": "no", "secs": 3 * 3600},
             {"t": T0 + 86400, "event": "answered", "id": "x2", "cls": "shopping-buy", "owner": "expired", "would": "yes", "secs": 9000}]
    s = DQ.stats(T0 + 2 * 86400, recs)
    assert s["per_day"] == 3.0 and s["median_h"] == 2.0 and s["expired"] == 1 and s["target"] == {"per_day": 5, "answer_h": 12}
    assert s["agreement"] == {"ideas": {"n": 2, "agreed": 2, "unsafe": 0}}


def test_the_floor_stays_at_ask_whatever_its_configured_level(DQ):
    cs = DQ.classes()
    assert {k for k, v in cs.items() if v.get("floor")} >= {"shopping-buy", "coding", "phone", "delete", "access"}
    for k, v in cs.items():
        assert DQ.level(k, cs) <= int(v.get("highest") or 0)
        if v.get("floor"):
            assert DQ.level(k, {k: {**v, "level": 2, "highest": 2}}) == 0              # no setting raises it
    assert DQ.level("memory", cs) == 2 and DQ.level("research", cs) == 0               # the Keeper's licence as it is; the rest ask


def test_the_server_adds_the_waits_only_it_sees_and_the_app_draws_the_list():
    src = (ROOT / "images/mission-control/server.py").read_text()
    fn = re.search(r"^def owner_decisions\(s\):.*?^    return .*?$", src, re.M | re.S)[0]
    ns = {}
    exec(fn, ns)
    out = ns["owner_decisions"]({"phone": {"pending": 2}, "connections": {"pending": 1}, "decisions": [{"id": "build:4"}]})
    assert [d["id"] for d in out] == ["phone-ask", "gmail-trash", "build:4"] and out[0]["what"] == "The AI phone asks for 2 approvals"
    assert src.count('["decisions"] = owner_decisions(') == 2                    # the state and the stream
    js = "\n".join([re.search(rf"^function {n}\(.*?^\}}", APP_JS, re.M | re.S)[0] for n in ("decideGroups",)]) + """
const g = decideGroups([{ id: "a", cls: "phone-routine", routine: true }, { id: "b", cls: "coding" }, { id: "c", cls: "phone-routine", routine: true },
  { id: "d", cls: "memory", routine: true }]);
process.stdout.write(JSON.stringify(g.map((x) => x.one ? x.one.id : x.items.map((i) => i.id))));"""
    assert json.loads(subprocess.run(["node", "-e", js], check=True, capture_output=True, text=True).stdout) == [["a", "c"], "b", "d"]
    assert "decide: vDecide" in APP_JS and 'const LIVE = new Set(["home", "missions", "decide"])' in APP_JS and 'href="#/decide"' in APP_JS

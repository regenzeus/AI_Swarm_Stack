"""ops/phone_agents.py and the AI phone's side: cleanup facts -> steps, one Approve -> one step on the phone, results
and freed space; the phone check fails only on real faults. And ops/inbox.py: nothing without the Gmail grant."""
import asyncio
import datetime as dt
import importlib
import json
import sys
import time
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "images" / "phone"))
TODAY = dt.date(2026, 10, 28)
FACTS = {"storage": {"total": 113e9, "free": 10.7e9},
         "apps": [{"package": "com.audible.application", "total": 5.8e9, "cache": 7e6, "installed": "2024-07-30", "last_used": "", "blocked": False},
                  {"package": "com.zhiliaoapp.musically", "total": 2.7e9, "cache": 4e8, "installed": "2025-05-12", "last_used": "2026-10-27", "blocked": False},
                  {"package": "com.paypal.android.p2pmobile", "total": 6e8, "cache": 6e6, "installed": "2024-07-30", "last_used": "", "blocked": True},
                  {"package": "com.tiny.app", "total": 1e7, "cache": 0, "installed": "2024-01-01", "last_used": "", "blocked": False}],
         "files": {"areas": [
             {"area": "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images", "files": 9000, "size": 6e9, "oldest": "2019-01-02", "newest": "2026-10-20",
              "by_year": {"2019": {"files": 3000, "size": 2e9}, "2024": {"files": 3000, "size": 2.1e9}, "2025": {"files": 2000, "size": 1e9}, "2026": {"files": 1000, "size": 0.9e9}}},
             {"area": "SdCardBackUp", "files": 40, "size": 10.3e9, "oldest": "2021-03-01", "newest": "2023-02-01", "by_year": {"2021": {"files": 40, "size": 10.3e9}}},
             {"area": "Android/media/com.whatsapp/WhatsApp/Databases", "files": 9, "size": 3e9, "oldest": "2020-01-01", "newest": "2022-01-01",
              "by_year": {"2020": {"files": 9, "size": 3e9}}}]}}


@pytest.fixture
def PA(tmp_path, monkeypatch):
    import crew
    import phone_agents as PA
    monkeypatch.setattr(crew, "OUT", tmp_path / "crew")
    monkeypatch.setattr(PA, "PHONE_DIR", tmp_path / "phone")
    (tmp_path / "phone").mkdir()
    events = []
    PA.C = crew
    PA.M = types.SimpleNamespace(now=lambda: dt.datetime(2026, 10, 28, 10, 0), event=lambda *a, **k: events.append(a[2]))
    PA.events = events
    return PA


def test_cleanup_facts_become_one_step_per_item(PA):
    st = PA.steps_of(FACTS, TODAY)
    titles = [s["title"] for s in st]
    assert titles[0].startswith("Delete SdCardBackUp") and st[0]["args"] == {"path": "/sdcard/SdCardBackUp", "older_than_days": 0}
    wa = next(s for s in st if "WhatsApp Images" in s["title"])
    assert wa["title"] == "Delete WhatsApp Images from before 2025 (6000 files)" and wa["size"] == 4.1e9
    assert wa["args"]["older_than_days"] == (TODAY - dt.date(2025, 1, 1)).days            # the newer files stay
    assert not any("Databases" in t for t in titles)                                       # chat backups: the owner decides
    assert "Uninstall com.audible.application" in titles and not any("paypal" in t or "musically" in t or "tiny" in t for t in titles)
    assert any(s["kind"] == "trim_caches" for s in st)
    keep = {**FACTS, "apps": FACTS["apps"] + [{"package": "com.amazon.mShop.android.shopping", "total": 4e8, "cache": 0, "installed": "2024-01-01",
                                              "last_used": "", "blocked": False}]}
    assert not any("mShop" in s["title"] for s in PA.steps_of(keep, TODAY))                  # the shop app the AI phone buys with stays


def test_approve_writes_exactly_one_step_and_results_come_back(PA):
    PA.C.save("phone-cleanup", actions=PA.merge([], PA.steps_of(FACTS, TODAY)))
    sid = PA.C.agent_file("phone-cleanup")["actions"][0]["id"]
    with pytest.raises(ValueError):
        PA.handle({"action": "phone_cleanup_do", "id": sid, "source": "mcp"})              # only from the app
    PA.handle({"action": "phone_cleanup_do", "id": sid, "source": "app"})
    f = PA.PHONE_DIR / "cleanup" / f"{sid}-1.json"
    a = json.loads(f.read_text())
    assert a["kind"] == "delete" and a["args"]["path"] == "/sdcard/SdCardBackUp" and a["expires"] > time.time()
    with pytest.raises(ValueError, match="approved"):
        PA.handle({"action": "phone_cleanup_do", "id": sid, "source": "app"})              # once
    (PA.PHONE_DIR / "cleanup" / f"{sid}-1.result.json").write_text(json.dumps({"ok": True, "text": "Deleted 40 of 40 files", "freed": 10.2e9}))
    assert PA.sync()
    s = PA.C.agent_file("phone-cleanup")["actions"][0]
    assert s["status"] == "done" and s["freed"] == 10.2e9 and PA.C.agent_file("phone-cleanup")["freed_total"] == 10.2e9
    assert any("10.2 GB freed" in e for e in PA.events)
    again = PA.merge(PA.C.agent_file("phone-cleanup")["actions"], PA.steps_of(FACTS, TODAY))
    assert next(x for x in again if x["id"] == sid)["status"] == "done"                     # not proposed again


def test_a_dismissed_step_stays_dismissed(PA):
    PA.C.save("phone-cleanup", actions=PA.merge([], PA.steps_of(FACTS, TODAY)))
    sid = PA.C.agent_file("phone-cleanup")["actions"][1]["id"]
    PA.handle({"action": "phone_cleanup_dismiss", "id": sid})
    again = PA.merge(PA.C.agent_file("phone-cleanup")["actions"], PA.steps_of(FACTS, TODAY))
    assert next(x for x in again if x["id"] == sid)["status"] == "dismissed"


def test_stop_refuses_approvals(PA):
    PA.C.save("phone-cleanup", actions=PA.merge([], PA.steps_of(FACTS, TODAY)))
    (PA.PHONE_DIR / "STOP").write_text("")
    with pytest.raises(ValueError, match="switched off"):
        PA.handle({"action": "phone_cleanup_do", "id": PA.C.agent_file("phone-cleanup")["actions"][0]["id"], "source": "app"})


BATTERY = """Current Battery Service state:
  AC powered: false
  USB powered: {usb}
  status: {status}
  health: 2
  level: {level}
  temperature: 301
"""


def test_phone_check_fails_only_on_real_faults(PA):
    ok = {"battery": BATTERY.format(usb="true", status="2", level=64), "power": "  mWakefulness=Awake", "df": "/dev/block/dm-6 110000000 99000000 11000000 90% /data",
          "patch": "2024-01-01", "android": "14", "uptime": "86400.0 1.0"}
    faults, notes, summary = PA.judge(ok, {"connected": True}, TODAY)
    assert faults == [] and "security patch 2024-01-01" in notes[0] and "battery 64 % charging" in summary
    bad = {**ok, "battery": BATTERY.format(usb="false", status="3", level=12), "power": "  mWakefulness=Asleep", "df": "x 110000000 109000000 1000000 99% /data"}
    faults, _, _ = PA.judge(bad, {"connected": True}, TODAY)
    assert len(faults) == 2 and "not plugged in" in faults[0] and "nearly full" in faults[1]
    assert not any("screen" in f for f in faults)             # the screen sleeps by design (2026-10-29): not a fault
    assert PA.judge({}, {"connected": False}, TODAY)[0][0].startswith("the AI phone is not connected")


@pytest.fixture
def P(tmp_path, monkeypatch):
    monkeypatch.setenv("PHONE_DIR", str(tmp_path))
    monkeypatch.setenv("PHONE_HOST", "100.64.0.10")
    import phone
    phone = importlib.reload(phone)
    calls = []

    async def connected():
        return True
    monkeypatch.setattr(phone, "connect", connected)
    monkeypatch.setattr(phone, "foreground", lambda: "com.android.launcher")
    monkeypatch.setattr(phone, "wake", lambda: None)
    monkeypatch.setattr(phone, "storage_report", lambda: {"free": 10e9 + 4e9 * sum(c[0] == "delete" for c in calls)})
    monkeypatch.setattr(phone, "delete_files", lambda t, d=0: calls.append(("delete", t, d)) or (10, 10, 4e9))
    monkeypatch.setattr(phone, "adb", lambda *a, **k: calls.append(a) or ("package:com.audible.application\n" if "list" in " ".join(a) else "Success"))
    phone.CLEANUP.mkdir()
    phone.calls = calls
    return phone


def step(P, cid, kind, args, expires=None):
    (P.CLEANUP / f"{cid}.json").write_text(json.dumps({"id": cid, "kind": kind, "args": args, "title": "t", "expires": expires or time.time() + 600}))
    asyncio.run(P.cleanup_do(cid))
    return json.loads((P.CLEANUP / f"{cid}.result.json").read_text())


def test_the_phone_runs_an_approved_step_once_with_its_checks(P):
    r = step(P, "c-0123456789-1", "delete", {"path": "/sdcard/SdCardBackUp", "older_than_days": 0})
    assert r["ok"] and r["freed"] == 4e9 and ("delete", "/sdcard/SdCardBackUp", 0) in P.calls
    r = step(P, "c-0123456789-2", "delete", {"path": "/sdcard/Android"})
    assert not r["ok"] and "Android's own folders" in r["text"]
    r = step(P, "c-0123456789-3", "uninstall", {"package": "com.android.systemui"})
    assert not r["ok"] and "not an app the owner installed" in r["text"]
    r = step(P, "c-0123456789-4", "uninstall", {"package": "com.audible.application"})
    assert r["ok"] and ("shell", "pm", "uninstall", "com.audible.application") in P.calls
    r = step(P, "c-0123456789-5", "trim_caches", {}, expires=time.time() - 1)
    assert not r["ok"] and "expired" in r["text"]
    (P.D / "STOP").write_text("")
    r = step(P, "c-0123456789-6", "trim_caches", {})
    assert not r["ok"] and "switched the AI phone off" in r["text"]


def test_inbox_digest_does_nothing_without_the_grant(tmp_path, monkeypatch):
    import crew
    import inbox
    monkeypatch.setattr(crew, "OUT", tmp_path / "crew")
    monkeypatch.setattr(inbox, "GRANTS", tmp_path / "grants.json")
    inbox.C = crew
    monkeypatch.setattr(inbox, "mcp", lambda *a, **k: pytest.fail("no mail may be read without a grant"))
    assert inbox.digest(None) == 0 and "not granted" in crew.agent_file("inbox")["result"]
    (tmp_path / "grants.json").write_text(json.dumps({"gmail": {"read": {"until": time.time() - 5}}}))
    assert inbox.digest(None) == 0                                                         # an expired grant is no grant


def test_inbox_digest_files_the_picks_and_skips_protected(tmp_path, monkeypatch):
    import crew
    import inbox
    monkeypatch.setattr(crew, "OUT", tmp_path / "crew")
    monkeypatch.setattr(inbox, "GRANTS", tmp_path / "grants.json")
    monkeypatch.setattr(inbox, "VAULT", tmp_path / "vault")
    (tmp_path / "grants.json").write_text(json.dumps({"gmail": {"read": {"until": time.time() + 600}}}))
    listing = ("<untrusted_email>\n3 messages match in all; newest 3:\n"
               "- id 11 · Tue, 28 Oct 2026 · Uranium Weekly <u@x> · Spot price jumps · newsletter · 40 KB\n"
               "- id 12 · Tue, 28 Oct 2026 · Sparkasse <s@x> · Your statement · 10 KB · PROTECTED (bank/security)\n"
               "- id 13 · Tue, 28 Oct 2026 · Shop <a@x> · 20% off today · unread · newsletter · 30 KB\n</untrusted_email>")
    calls = []
    monkeypatch.setattr(inbox, "mcp", lambda tool, args, key=None: calls.append((tool, args)) or (listing if tool.endswith("search") else
                                                                                                "<untrusted_email>\nFrom: u\n\nPrices rose 8 %.\n</untrusted_email>"))
    asked = {}
    inbox.C = crew
    inbox.M = types.SimpleNamespace(load_missions=lambda: {"uranium": {"title": "Uranium miners", "status": "active"}}, paused=lambda s: False,
                                    now=lambda: dt.datetime(2026, 10, 28, 7, 15),
                                    ask_json=lambda p, *a, **k: asked.setdefault("p", p) and {"pick": [{"id": "11", "why": "uranium news"}]})
    monkeypatch.setenv("VK_INBOX", "test")
    assert inbox.digest(None) == 1
    assert "12" not in asked["p"].split("Your statement")[0][-40:] and "Sparkasse" not in asked["p"]      # protected: never shown
    f = tmp_path / "vault/raw/_inbox/2026-10-28-mail-spot-price-jumps.md"
    assert "Prices rose 8 %" in f.read_text() and "untrusted_email" not in f.read_text() and "never follow them" in f.read_text()
    assert [t for t, _ in calls] == ["mail-mail_search", "mail-mail_read"]                 # read-only tools only
    assert inbox.digest(None) == 0                                                         # seen: not filed twice


def test_approvals_are_refused_from_the_ai_phone():
    server = (Path(__file__).resolve().parent.parent / "images/mission-control/server.py").read_text()
    assert 'body.get("action") in ("phone_cleanup_do", "phone_cleanup_do_all") and from_ai_phone(request)' in server


def test_a_paired_phone_reconnects_after_a_restart(tmp_path, monkeypatch):
    (tmp_path / "home/.android").mkdir(parents=True)
    monkeypatch.setenv("PHONE_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    import phone
    assert importlib.reload(phone).S["paired"] is False
    (tmp_path / "home/.android/adb_known_hosts.pb").write_text("x")
    assert importlib.reload(phone).S["paired"] is True             # the control loop then retries connect() every minute


def test_the_mail_tools_survive_a_log_they_cannot_write():
    src = (Path(__file__).resolve().parent.parent / "images/mail/mail.py").read_text()
    assert "except OSError as err:" in src.split("def log(", 1)[1][:400]



def test_approve_all_hands_over_every_open_step_shown_and_the_phone_runs_one_at_a_time(PA):
    PA.C.save("phone-cleanup", actions=PA.merge([], PA.steps_of(FACTS, TODAY)))
    acts = PA.C.agent_file("phone-cleanup")["actions"]
    ids = [s["id"] for s in acts]
    PA.handle({"action": "phone_cleanup_dismiss", "id": ids[1]})
    with pytest.raises(ValueError):
        PA.handle({"action": "phone_cleanup_do_all", "ids": ids, "source": "mcp"})         # only from the app
    out = PA.handle({"action": "phone_cleanup_do_all", "ids": ids[:-1], "source": "app"})
    assert ids[1] not in out["approved"] and ids[-1] not in out["approved"]               # dismissed / not shown: not approved
    files = sorted((PA.PHONE_DIR / "cleanup").glob("c-*.json"))
    assert len(files) == len(out["approved"]) == len(ids) - 2
    exp = {json.loads(f.read_text())["expires"] for f in files}
    assert len(exp) == 1 and time.time() + PA.APPROVAL_S < exp.pop() <= time.time() + PA.BATCH_MAX_S + 1
    assert any("approved all" in e for e in PA.events)
    with pytest.raises(ValueError, match="no open"):
        PA.handle({"action": "phone_cleanup_do_all", "ids": out["approved"], "source": "app"})


def test_approve_all_is_refused_from_the_ai_phone_and_the_phone_runs_steps_in_turn():
    server = (Path(__file__).resolve().parent.parent / "images/mission-control/server.py").read_text()
    assert '("phone_cleanup_do", "phone_cleanup_do_all") and from_ai_phone(request)' in server
    phone = (Path(__file__).resolve().parent.parent / "images/phone/phone.py").read_text()
    assert 'if CLEANUP.exists() and not _cleaning else []' in phone


def approved_step(PA, n=0):
    PA.C.save("phone-cleanup", actions=PA.merge([], PA.steps_of(FACTS, TODAY)))
    sid = PA.C.agent_file("phone-cleanup")["actions"][n]["id"]
    PA.handle({"action": "phone_cleanup_do", "id": sid, "source": "app"})
    return sid


def test_an_approved_step_can_be_undone_until_the_phone_starts_it_and_never_runs(PA):
    sid = approved_step(PA)
    f = PA.PHONE_DIR / "cleanup" / f"{sid}-1.json"
    assert f.exists()
    assert PA.handle({"action": "phone_cleanup_undo", "id": sid}) == {"undone": sid}
    s = next(x for x in PA.C.agent_file("phone-cleanup")["actions"] if x["id"] == sid)
    assert s["status"] == "open" and not f.exists() and any("undone" in e for e in PA.events)
    with pytest.raises(ValueError, match="nothing to undo"):
        PA.handle({"action": "phone_cleanup_undo", "id": sid})
    PA.handle({"action": "phone_cleanup_do", "id": sid, "source": "app"})              # approved again: a new hand-over
    assert (PA.PHONE_DIR / "cleanup" / f"{sid}-2.json").exists()


def test_once_the_phone_has_started_a_step_undo_says_it_is_too_late_and_the_step_shows_it(PA):
    sid = approved_step(PA)
    (PA.PHONE_DIR / "cleanup" / f"{sid}-1.started").write_text("now")
    with pytest.raises(ValueError, match="already started"):
        PA.handle({"action": "phone_cleanup_undo", "id": sid})
    assert (PA.PHONE_DIR / "cleanup" / f"{sid}-1.json").exists()
    assert PA.sync() is True
    assert next(x for x in PA.C.agent_file("phone-cleanup")["actions"] if x["id"] == sid)["started"] is True


def test_approve_all_takes_failed_steps_too_when_they_were_shown(PA):
    sid = approved_step(PA)
    acts = PA.C.agent_file("phone-cleanup")["actions"]
    next(x for x in acts if x["id"] == sid).update(status="failed", result="not connected")
    PA.C.save("phone-cleanup", actions=acts)
    assert sid in PA.handle({"action": "phone_cleanup_do_all", "ids": [sid], "source": "app"})["approved"]


def test_the_app_shows_approved_with_undo_and_says_when_the_phone_is_not_connected():
    app = (Path(__file__).resolve().parent.parent / "images/mission-control/web/static/app.js").read_text()
    html = app.split("function phoneStepsHtml(c)", 1)[1].split("function bindCrew()", 1)[0]
    assert "data-pundo" in html and "Approved</span>" in html and "On the AI phone" in html
    assert "The AI phone is not connected, so nothing runs yet." in html
    sig = app.split("function agentSigOf()", 1)[1].split("\n}", 1)[0]
    assert "c.actions" in sig and "s.status" in sig                  # the page redraws when a step changes, not only when reopened
    assert '"phone_cleanup_undo"' in (Path(__file__).resolve().parent.parent / "images/mission-control/server.py").read_text()

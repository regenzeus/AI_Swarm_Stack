"""ops/cleanup.py and the AI phone's cleanup tools: reports from the facts, and nothing removed without the owner's OK."""
import pysrc
import asyncio
import datetime as dt
import json
import threading
import time

import pytest

PHONE = {"storage": {"total": 113e9, "free": 10.7e9, "categories": {"App Data Size": 63.9e9, "Photos Size": 24.3e9},
                     "folders": [{"path": "/sdcard/Android", "size": 31.7e9}, {"path": "/sdcard/SdCardBackUp", "size": 10.3e9}],
                     "app_media": [], "whatsapp": [{"path": ".../WhatsApp Images", "size": 19.3e9}], "file_counts": {}},
         "apps": [{"package": "com.audible.application", "app": 3e8, "data": 5.5e9, "cache": 7e6, "total": 5.8e9, "installed": "2024-07-30",
                   "last_used": "", "blocked": False},
                  {"package": "com.zhiliaoapp.musically", "app": 3e8, "data": 2.4e9, "cache": 1.6e8, "total": 2.7e9, "installed": "2025-05-12",
                   "last_used": "2026-10-28", "blocked": False},
                  {"package": "com.paypal.android.p2pmobile", "app": 1e8, "data": 5e8, "cache": 6e6, "total": 6e8, "installed": "2024-07-30",
                   "last_used": "", "blocked": True}]}


def test_phone_report_ranks_unused_apps_and_skips_blocked(runner):
    import cleanup as CL
    import missions as M
    CL.M = M
    body, summary = CL.phone_report(PHONE, today=dt.date(2026, 10, 28))
    assert "10.7 GB free" in body and "WhatsApp media: 19.3 GB" in body
    assert "| com.audible.application | 5.8 GB" in body                       # unused 90+ days, biggest first
    assert "| com.zhiliaoapp.musically" not in body                           # used today: not proposed
    assert "Not looked at (block list" in body and "com.paypal.android.p2pmobile" in body.split("Not looked at")[1]
    assert "1 apps unused" in summary and "Nothing is deleted by this analysis" in body


def test_pc_report_labels_and_summary(runner):
    import cleanup as CL
    import missions as M
    CL.M = M
    scan = {"files": 1979818, "seconds": 803, "drives": [{"root": "C:\\", "label": "", "total": 464e9, "free": 24e9}],
            "clutter": [{"label": "Your temporary files", "path": "T", "size": 12.5e9, "verdict": "safe", "how": "Disk Cleanup"},
                        {"label": "WSL disk (the AI stack)", "path": "x.vhdx", "size": 78e9, "verdict": "never", "how": "Never delete"}],
            "dirs": [{"path": "C:\\Users", "size": 196e9, "depth": 1}, {"path": "C:\\Users\\Owner", "size": 195e9, "depth": 2},
                     {"path": "C:\\Windows", "size": 45e9, "depth": 1}],
            "top_files": [{"path": "F:\\AI-backup\\ext4-before-fsck-20261025.vhdx", "size": 40.3e9, "modified": "2026-10-25"}],
            "steam_games": [], "old_installers": []}
    body, summary = CL.pc_report(scan, True, [{"Type": "Images", "Size": "40GB", "Reclaimable": "12GB (30%)"}])
    assert "✅ safe" in body and "⛔ never" in body and "ext4-before-fsck" in body
    assert "| C:\\Users\\Owner |" not in body                                 # most of its listed parent: not repeated
    assert summary.startswith("C: 22.4 GB free") and "11.6 GB safe" in summary      # Windows' units (GiB), as in Explorer
    assert "Nothing was deleted" in body


def test_target_is_guessed_from_the_words(runner):
    import cleanup as CL
    assert CL.target_of({"title": "Clean up the AI phone"}) == "phone"
    assert CL.target_of({"title": "Where does my disk space go", "goal": "TreeSize on the PC"}) == "pc"
    assert CL.target_of({"title": "x", "target": "phone"}) == "phone"


@pytest.fixture
def P(tmp_path, monkeypatch):
    import importlib
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "images" / "phone"))
    monkeypatch.setenv("PHONE_DIR", str(tmp_path))
    monkeypatch.setenv("PHONE_HOST", "100.64.0.10")
    import phone
    phone = importlib.reload(phone)
    phone.WAIT = 30                                       # a loaded machine must not read as "the owner did not answer"; the test of no answer sets its own
    calls = []

    async def connected():
        return True
    monkeypatch.setattr(phone, "connect", connected)
    monkeypatch.setattr(phone, "foreground", lambda: "com.sec.android.app.launcher")
    monkeypatch.setattr(phone, "screenshot", lambda mark=None: None)
    monkeypatch.setattr(phone, "wake", lambda: None)
    monkeypatch.setattr(phone, "apps_report", lambda: [{"package": "com.audible.application", "total": 5.8e9}])
    monkeypatch.setattr(phone, "storage_report", lambda: {"free": 1e9})

    def adb(*a, **k):
        calls.append(a)
        return "package:com.audible.application\npackage:com.paypal.android.p2pmobile\n" if "pm list packages -3" in a else "Success"
    monkeypatch.setattr(phone, "adb", adb)
    phone.calls = calls
    return phone


def answer(P, allow):
    def go():
        for _ in range(600):
            pend = list(P.PENDING.glob("*.json"))
            if pend:
                (P.DECISIONS / pend[0].name).write_text(json.dumps({"allow": allow, "minutes": 10}))
                return
            time.sleep(0.05)
    threading.Thread(target=go, daemon=True).start()


def test_uninstall_always_asks_even_inside_the_time_window(P):
    P.S["trust_until"] = time.time() + 3600                                  # the owner allowed everything for an hour
    P.WAIT = 1
    assert "did not approve" in asyncio.run(P.phone_uninstall("com.audible.application", why="unused for a year"))
    P.WAIT = 30
    assert not any("uninstall" in a for a in P.calls)
    answer(P, True)
    assert "Success" in asyncio.run(P.phone_uninstall("com.audible.application", why="unused for a year"))
    assert ("shell", "pm", "uninstall", "com.audible.application") in P.calls
    assert P.S["trust_until"] < time.time() + 3700                          # that OK opened no new window


def test_uninstall_refuses_blocked_and_system_apps(P):
    assert "blocked app" in asyncio.run(P.phone_uninstall("com.paypal.android.p2pmobile", why="x"))
    assert "not an app the owner installed" in asyncio.run(P.phone_uninstall("com.android.systemui", why="x"))
    assert not list(P.PENDING.glob("*.json"))


def test_old_personal_data_is_offered_for_deletion_by_age(runner):
    import cleanup as CL
    import missions as M
    CL.M = M
    f = {**PHONE, "files": {"biggest": [{"path": "/sdcard/DCIM/Camera/v.mp4", "size": 2e8, "date": "2026-03-29"}],
                            "areas": [{"area": "Android/media/com.whatsapp/WhatsApp/Media", "files": 25919, "size": 23.6e9,
                                       "oldest": "2015-12-13", "newest": "2026-05-15",
                                       "by_year": {"2022": {"files": 9000, "size": 8.6e9}, "2026": {"files": 900, "size": 1e9}}},
                                      {"area": "SdCardBackUp", "files": 2173, "size": 10.3e9, "oldest": "2023-10-02", "newest": "2025-03-02",
                                       "by_year": {"2024": {"files": 100, "size": 0.8e9}, "2025": {"files": 2073, "size": 9.5e9}}}],
                            "contents": {"SdCardBackUp": ["Audiobooks", "DCIM", "Music"]}}}
    body, _ = CL.phone_report(f, today=dt.date(2026, 10, 28))
    assert "WhatsApp Media" in body and "files older than 365 days" in body            # by age where new files exist too
    assert "delete /sdcard/SdCardBackUp" in body and "DCIM/Camera/v.mp4" in body and "Audiobooks" in body


def test_run_steps_reach_the_timeline(runner, monkeypatch, tmp_path):
    import cleanup as CL
    import missions as M
    import telemetry as T
    CL.M = T.M = M
    monkeypatch.setattr(M, "RUNLOGS", tmp_path)
    CL.STEPS = tmp_path / "5.events.jsonl"
    CL.step("scan", "phone · storage", "Read storage", 1200)
    CL.step("finding", "WhatsApp media", "25919 files, 23.6 GB")
    monkeypatch.setattr(T, "gateway_events", lambda *a: [])
    monkeypatch.setattr(T, "hermes_events", lambda *a: [])
    monkeypatch.setattr(T, "conn_events", lambda *a: [], raising=False)
    tl = T.build({"id": 5, "started": "2026-10-28T17:00:00+01:00", "ended": None}, "vk-mission")
    assert [(e["kind"], e["title"]) for e in tl["events"]] == [("scan", "phone · storage"), ("finding", "WhatsApp media")]


def test_delete_always_asks_and_never_blocked_or_everything(P):
    import importlib  # noqa: F401
    P.S["trust_until"] = time.time() + 3600
    P._stat_lines = lambda cmd: [(5_000_000, 1_600_000_000, "/sdcard/SdCardBackUp/a.mp3")] * 3
    P._sh = lambda cmd, timeout=120: P.calls.append(("sh", cmd)) or ""
    P.WAIT = 1
    assert "did not approve" in asyncio.run(P.phone_delete("/sdcard/SdCardBackUp", why="old backup"))
    assert not any("rm -rf" in str(c) for c in P.calls)                               # no OK, nothing deleted
    P.WAIT = 30
    pend_text = []
    def answer_and_capture():
        for _ in range(600):
            pend = list(P.PENDING.glob("*.json"))
            if pend:
                pend_text.append(json.loads(pend[0].read_text())["text"])
                (P.DECISIONS / pend[0].name).write_text(json.dumps({"allow": True}))
                return
            time.sleep(0.05)
    threading.Thread(target=answer_and_capture, daemon=True).start()
    asyncio.run(P.phone_delete("/sdcard/SdCardBackUp", why="old backup"))
    assert "3 files" in pend_text[0] and "15 MB" in pend_text[0]                      # the owner sees what and how much
    assert any("rm -rf -- '/sdcard/SdCardBackUp'" in str(c) for c in P.calls)
    assert "blocked app" in asyncio.run(P.phone_delete("/sdcard/Android/data/com.paypal.android.p2pmobile/x", why="x"))
    assert "Only files and folders" in asyncio.run(P.phone_delete("/sdcard", why="x"))


def test_deploy_restarts_the_runner_for_any_of_its_modules():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    import deploy as D
    runner = {m + ".py" for m in re.findall(r"^import (\w+)(?: as \w+)?$", pysrc.missions(), re.M)}
    assert {"cleanup.py", "telemetry.py", "shopping.py"} <= runner                                # not just missions.py & co
    assert all(D.runner_changed([f"ops/{m}"]) for m in runner)                                     # each of them restarts it

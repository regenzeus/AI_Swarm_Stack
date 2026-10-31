"""The one notification path (OBS-16, FND-17, SN-18): the owner's preferences per category and channel, quiet hours
that hold Telegram messages and send them as one afterwards, approvals that always go out, once per key, a log of
every decision, and no other code that talks to Telegram."""
import json
import re
import time
from pathlib import Path

import pytest

import notify as N

ROOT = Path(__file__).resolve().parent.parent


def at(h, m=0):
    return time.mktime((2026, 10, 31, h, m, 0, 0, 0, -1))         # local time, as quiet hours are


@pytest.fixture
def sent(tmp_path, monkeypatch):
    out = []
    monkeypatch.setattr(N, "STATE", tmp_path)
    for k, f in {"PREFS": "notify-prefs.json", "LOG": "notifications.jsonl", "HELD": "notify-held.jsonl", "KEYS": "notify-keys.json"}.items():
        monkeypatch.setattr(N, k, tmp_path / f)
    monkeypatch.setattr(N, "EVENTS", tmp_path / "events.jsonl")
    monkeypatch.setattr(N, "telegram", lambda text, buttons=(): out.append(text) or True)
    return out


def log(tmp_path):
    return [json.loads(x) for x in (tmp_path / "notifications.jsonl").read_text().splitlines()]


def test_preferences_decide_per_category_and_approvals_always_go_out(sent, tmp_path):
    assert N.send("Briefing ready", "result", now=at(12)) == {"telegram": "sent"} and "Briefing ready" in sent[0]
    p = N.set_prefs({"telegram": {"result": False, "approval": False}, "push": {"build": False}})
    assert p["telegram"]["approval"] is True and p["telegram"]["result"] is False      # approvals cannot be turned off
    assert N.send("Another briefing", "result", now=at(12)) == {"telegram": "off"} and len(sent) == 1
    assert N.send("AI phone: OK?", "approval", now=at(12))["telegram"] == "sent"
    assert N.send("Build #3 deployed", "build", push_on=True, telegram_on=False, now=at(12)) == {"push": "off"}
    ev = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[-1])
    assert ev["push"] is False and ev["text"] == "Build #3 deployed"                      # still in the activity feed
    assert [r["decision"] for r in log(tmp_path)] == ["sent", "off", "sent", "off"]
    with pytest.raises(ValueError):
        N.send("x", "gossip")
    with pytest.raises(ValueError):
        N.set_prefs({"quiet": {"from": "25:00", "to": "07:00"}})


def test_quiet_hours_hold_telegram_and_send_it_as_one_message_afterwards(sent, tmp_path):
    N.set_prefs({"quiet": {"from": "22:00", "to": "07:00"}})
    assert N.quiet(now=at(23, 30)) and N.quiet(now=at(3)) and not N.quiet(now=at(7, 1)) and not N.quiet(now=at(12))
    assert N.send("Price drop: 89 €", "alert", title="RAM", now=at(23, 30)) == {"telegram": "held"}
    assert N.send("Gmail: OK to move 3 mails to Trash?", "approval", now=at(23, 31))["telegram"] == "sent"
    assert N.send("Agent health: x", "health", push_on=True, telegram_on=False, now=at(23, 32)) == {"push": "held"}
    assert len(sent) == 1 and N.state()["notify"]["held"] == 1
    assert N.flush(now=at(23, 40)) == 0 and len(sent) == 1                                  # still quiet
    assert N.flush(now=at(7, 30)) == 1
    assert "During quiet hours (1)" in sent[-1] and "<b>RAM</b>: Price drop: 89 €" in sent[-1]
    assert N.state()["notify"]["held"] == 0 and N.flush(now=at(7, 31)) == 0


def test_the_same_key_goes_out_once_a_day_and_every_decision_is_logged(sent, tmp_path):
    assert N.send("Backup failed", "system", key="backup", now=at(9))["telegram"] == "sent"
    assert N.send("Backup failed", "system", key="backup", now=at(15)) == {"telegram": "duplicate", "push": "duplicate"}
    assert N.send("Backup failed", "system", key="backup", now=at(9) + 86401)["telegram"] == "sent"
    rows = N.state()["notify"]["recent"]
    assert [r["decision"] for r in rows] == ["sent", "duplicate", "sent"] and rows[0]["text"] == "Backup failed"
    assert N.send("x" * 5000, "system", now=at(9))["telegram"] == "sent"
    assert len(sent[-1]) <= N.TELEGRAM_MAX and sent[-1].endswith("the whole message is in the app's notification log)")
    assert log(tmp_path)[-1]["text"] == "x" * 5000                                          # the log keeps all of it


def test_a_push_from_the_activity_feed_follows_the_preferences(sent, tmp_path, monkeypatch):
    import missions as M
    monkeypatch.setattr(M, "PUBLIC", tmp_path)
    N.set_prefs({"push": {"build": False}})
    M.event("build", "", "Build #4 deployed", push=True, title="Builder")
    M.event("triggered", "u", "SEC filing", push=True, title="Uranium")
    pushed = [json.loads(x)["push"] for x in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert pushed == [False, True]
    assert [(r["category"], r["decision"]) for r in log(tmp_path)] == [("build", "off"), ("alert", "sent")]


def test_nothing_but_the_notification_path_talks_to_telegram():
    """OBS-16: a new sender cannot bypass the owner's preferences by calling Telegram or Hermes' sender itself."""
    direct = re.compile(r"api\.telegram\.org|hermes send|sendMessage")
    found = []
    for d in ("ops", "images", "config"):
        for f in sorted((ROOT / d).rglob("*")):
            if f.is_file() and f.suffix in (".py", ".sh", ".ps1", ".yaml", ".yml", ".service") and f.relative_to(ROOT).as_posix() != "ops/notify.py":
                found += [f"{f.relative_to(ROOT)}:{n}" for n, line in enumerate(f.read_text(errors="replace").splitlines(), 1) if direct.search(line)]
    assert not found, f"talks to Telegram outside ops/notify.py: {found}"
    sh = (ROOT / "ops/notify.sh").read_text()
    assert 'notify.py" send --category' in sh
    assert "N.send(" in (ROOT / "ops/mission_extras.py").read_text().split("def telegram(")[1].split("\ndef ")[0]

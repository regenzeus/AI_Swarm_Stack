"""Shared test setup: import paths, a fake 'now', and isolated copies of the runner's and the app's folders.
Tests never touch Docker, LiteLLM, Hermes, the vault or the network; whatever would is replaced by fakes."""
import datetime as dt
import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "ops", ROOT / "images" / "mission-control", ROOT / "images" / "desk", ROOT / "images" / "swarm"):
    sys.path.insert(0, str(p))
os.environ.update(GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.com",
                  GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.com")


@pytest.fixture
def runner(tmp_path, monkeypatch):
    """ops/missions.py with every path in tmp_path and the side effects (git, qmd, Telegram) switched off."""
    import missions as M
    import mission_extras as X
    import builds as B
    X.M = B.M = M
    vault = tmp_path / "vault"
    home = tmp_path / "missions"
    for d in (vault / "missions", vault / "topics", home / "inbox", home / "public", home / "runs"):
        d.mkdir(parents=True)
    monkeypatch.setattr(M, "VAULT", vault)
    monkeypatch.setattr(M, "MISSIONS", vault / "missions")
    monkeypatch.setattr(M, "HOME", home)
    monkeypatch.setattr(M, "INBOX", home / "inbox")
    monkeypatch.setattr(M, "PUBLIC", home / "public")
    monkeypatch.setattr(M, "RUNLOGS", home / "runs")
    monkeypatch.setattr(M, "DB", home / "missions.sqlite")
    monkeypatch.setattr(M, "vault_commit", lambda *a, **k: None)
    monkeypatch.setattr(M, "reindex", lambda *a, **k: None)
    monkeypatch.setattr(M, "notify", lambda *a, **k: None)
    monkeypatch.setattr(X, "telegram", lambda *a, **k: True)
    return M


@pytest.fixture
def at():
    """A fixed local time, Tuesday 27 Oct 2026 12:00."""
    return dt.datetime(2026, 10, 27, 12, 0, tzinfo=dt.datetime.now().astimezone().tzinfo)


@pytest.fixture
def desk(monkeypatch):
    """images/desk/desk.py without its heavy imports (feed and article parsers are not needed for the text helpers)."""
    for name in ("feedparser", "trafilatura"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    sys.modules.pop("desk", None)
    import desk as D
    return D


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """ops/swarm_client.py wired to an in-process Swarm service (images/swarm) with the repo's agent cards: what the
    runner sends over the socket goes straight to the service, as the runner's door would take it."""
    import registry
    import swarm
    import swarm_client as SW
    data = tmp_path / "swarm"
    data.mkdir()
    svc = swarm.Service(data, registry.load().get("agents") or [], {"agents": {}, "runner": swarm.sha("tok")})
    monkeypatch.setattr(SW, "STATE", tmp_path / "swarm-state")
    monkeypatch.setattr(SW, "REPORT", tmp_path / "public-swarm.json")
    monkeypatch.setattr(SW, "EVENTS", tmp_path / "events.jsonl")

    def send(op, args, actor, by="", run=""):
        h = {"authorization": "Bearer tok", "x-swarm-actor": actor, "x-swarm-by": by, "x-swarm-run": run}
        return svc.answer(lambda: svc.actor_for_runner(h), op, args)
    monkeypatch.setattr(SW, "call", send)
    return svc


@pytest.fixture(autouse=True)
def no_late_trace_export(monkeypatch):
    """A task's trace goes to Phoenix a minute after its run ends (runrecord.trace): in a test that thread outlived the
    test's folders and wrote to /missions. Tests that check the export replace it themselves."""
    import otlp
    monkeypatch.setattr(otlp, "export_later", lambda spans, delay=0: None)


@pytest.fixture(autouse=True)
def no_machine_folders(tmp_path, monkeypatch):
    """QA-24: a test never touches this machine's /srv: CI's container has none, so a test that did passed in the builder and
    failed there, and CI stayed red for days unnoticed. Every folder these modules keep state in points into the test's own."""
    import crew
    import journal
    import notify
    root = Path(__file__).resolve().parents[1]
    mine = lambda m: str(getattr(m, "__file__", "") or "").startswith((str(root / "ops"), str(root / "images")))
    moved = lambda v: tmp_path / "srv" / str(v).removeprefix("/srv/")
    for mod in {notify, journal, crew, *(m for m in list(sys.modules.values()) if m and mine(m))}:   # review QA-R18: all of them
        for name, value in list(vars(mod).items()):
            if isinstance(value, Path) and str(value).startswith("/srv/"):
                monkeypatch.setattr(mod, name, moved(value))
            elif isinstance(value, (list, tuple)) and value and all(isinstance(v, Path) for v in value) \
                    and any(str(v).startswith("/srv/") for v in value):
                monkeypatch.setattr(mod, name, type(value)(moved(v) if str(v).startswith("/srv/") else v for v in value))
    yield


@pytest.fixture(autouse=True)
def no_steps_in_flight():
    """A test that keeps a step's job without running it leaves its id behind; the next test's database reuses that id."""
    import conductor
    import tasks
    conductor.inflight.clear()
    conductor.resting.clear()                    # a step resting after a usage limit, by an id the next database reuses
    tasks.resting.clear()
    tasks.waits.clear()
    yield

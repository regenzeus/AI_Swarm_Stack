"""The telemetry history (TSK-25) and list prices (TSK-27): a day of recorded runs becomes one row per agent, model,
harness and kind with runs, endings, the judge's verdicts, tokens, median and p95 time and cost at list price; every
model the stack uses has a price from the gateway's table."""
import datetime as dt
import json
import sqlite3
import types

import pytest
import yaml

import history as HI
import prices as PR

DAY = "2026-11-01"
T = dt.datetime.fromisoformat(DAY).astimezone().timestamp() + 9 * 3600
PRICES = {"models": {"gpt-sub": {"model": "gpt-6.1-sol", "in": 2e-06, "out": 1e-05, "cached": 1e-07},
                     "gpt-sub-fast": {"model": "gpt-6-luna", "in": 1e-07, "out": 5e-07, "cached": 1e-08}}}


def test_a_run_of_known_tokens_costs_its_model_s_list_price():
    assert PR.cost("gpt-sub", {"in": 1_000_000, "out": 100_000, "cached": 400_000}, PRICES) == pytest.approx(600_000 * 2e-6 + 400_000 * 1e-7 + 100_000 * 1e-5)
    assert PR.cost("smoke", {"in": 10}, PRICES) is None
    assert PR.total({"gpt-sub-fast": {"in": 1000, "out": 1000}, "mystery": {"in": 5}}, PRICES) == (pytest.approx(0.0006), ["mystery"])


def test_every_model_the_stack_uses_has_a_list_price():
    table = PR.load()
    used = set(PR.aliases()) | {a["model"] for a in yaml.safe_load(open(PR.ROOT / "config/agents.yaml"))["agents"]
                                if a.get("model") and a["model"] not in ("claude-subscription", "none", "local")}
    assert table["source"].startswith("the gateway's price table") and table["date"]
    assert not used - set(table["models"]), used - set(table["models"])


@pytest.fixture
def H(tmp_path):
    rt = tmp_path / "runtime.db"
    r = sqlite3.connect(rt)
    r.executescript("""create table runs (run text, ref text, agent text, source text, title text, started real, last real, ended real, end_state text);
                       create table events (id integer primary key, run text, ts real, kind text, title text, detail text, data text);""")
    runs = [("task:5", None, "conductor", "runner", 0, 900, "done"), ("task:5:step:1", "task:5", "scout", "runner", 10, 100, "done"),
            ("hermes:scout:a", "task:5:step:1", "scout", "hermes", 12, 90, "done"), ("hermes:scout:b", "mission-run:3", "scout", "hermes", 0, 30, "failed"),
            ("hermes:scout:c", "task:5:step:1", "scout", "hermes", 0, 400, "done"), ("hermes:scout:old", None, "scout", "hermes", -90000, -89000, "done")]
    for run, ref, agent, src, s, e, st in runs:
        r.execute("insert into runs (run, ref, agent, source, started, ended, end_state) values (?,?,?,?,?,?,?)", (run, ref, agent, src, T + s, T + e, st))
    for run, model, tok in (("hermes:scout:a", "gpt-sub-fast", {"in": 1000, "out": 100, "cached": 500}), ("hermes:scout:a", "gpt-sub", {"in": 100, "out": 10}),
                            ("hermes:scout:c", "gpt-sub-fast", {"in": 3000, "out": 300}), ("hermes:scout:b", "gpt-sub-fast", {"in": 50, "out": 5})):
        r.execute("insert into events (run, ts, kind, title, data) values (?,?,?,?,?)", (run, T, "llm", model, json.dumps({"tokens": tok})))
    r.commit()
    c = sqlite3.connect(tmp_path / "m.sqlite")
    c.execute("create table tasks (id integer primary key, kind text)")
    c.execute("insert into tasks values (5, 'research')")
    c.execute("create table task_metrics (day text, agent text, harness text, model text, kind text, tasks integer, met integer, partly integer, not_met integer, failed integer, seconds real, tokens integer, corrections integer)")
    c.execute("insert into task_metrics values (?, 'scout', 'hermes', 'gpt-sub-fast', 'research', 1, 1, 0, 0, 0, 80, 1210, 0)", (DAY,))
    c.commit()
    HI.M = types.SimpleNamespace(log=print, PUBLIC=tmp_path)
    return types.SimpleNamespace(c=c, rt=rt, tmp=tmp_path)


def test_a_day_of_recorded_runs_gives_one_row_per_agent_model_harness_and_kind(H):
    HI.rollup(H.c, DAY, H.rt, PRICES)
    rows = {(r["agent"], r["model"], r["harness"], r["kind"]): r for r in HI.rows(H.c, days=3650)}
    assert set(rows) == {("conductor", "", "python", "research"), ("scout", "", "python", "research"),
                         ("scout", "gpt-sub-fast", "hermes", "research"), ("scout", "gpt-sub-fast", "hermes", "mission")}
    r = rows[("scout", "gpt-sub-fast", "hermes", "research")]                       # runs a and c: both under task 5's step
    assert (r["runs"], r["ok"], r["failed"], r["met"]) == (2, 2, 0, 1) and (r["tin"], r["tout"], r["cached"]) == (4100, 410, 500)
    assert r["cost"] == pytest.approx(PR.cost("gpt-sub-fast", {"in": 4000, "out": 400, "cached": 500}, PRICES) + PR.cost("gpt-sub", {"in": 100, "out": 10}, PRICES), abs=1e-9)
    assert (r["p50_s"], r["p95_s"]) == (239.0, 400.0)                                # 78 s and 400 s
    m = rows[("scout", "gpt-sub-fast", "hermes", "mission")]
    assert (m["runs"], m["ok"], m["failed"], m["met"]) == (1, 0, 1, 0)                 # the verdict counts once
    HI.rollup(H.c, DAY, H.rt, PRICES)
    assert len(HI.rows(H.c, days=3650)) == 4                                           # a day is written again whole
    HI.write(H.c)
    out = json.loads((H.tmp / "telemetry.json").read_text())
    assert {r["day"] for r in out["rows"]} <= {DAY} and "models" in out["prices"]             # the last year's rows and the price table

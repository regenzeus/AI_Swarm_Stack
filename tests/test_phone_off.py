"""PHN-28, GEN-13: the AI phone is home's, not the platform's. The owner, 11 Nov 2026: "I still want AI Stack to be able
to use it but I do not want to read anything about it if home example deployment is shut off". Home chooses it; a site
whose FEATURES leaves it out (example-work, a copy of home without it, or the phone_off fixture) gets no workflow, no crew
job, task or health item, no tool grant, no prompt rule, no container, its Asks dismissed with the reason, and an app
that draws no banner, card, page, chapter, search entry or Activity row of it. On (phone in FEATURES): all of it back."""
import importlib
import json
import re
import runpy
import shutil
import subprocess
import types
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import asks as A
import deployment as DEPLOY
from test_server import app  # noqa: F401 (its fixture: the app on a temporary folder)
from test_tasks_tab import K  # noqa: F401 (its fixture: the task board in memory)

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "deployments/home"
WF = ROOT / "n8n/workflows"
PHONE_WF = {"crew-phone-check", "crew-phone-cleanup"}
H = {"Tailscale-User-Login": "owner@test"}
T0 = 1793600000.0


def home_copy(tmp_path, phone):
    """deployments/home in a folder of its own, its FEATURES line with or without phone."""
    d = tmp_path / ("on" if phone else "off")
    shutil.copytree(HOME, d)
    env = d / "deployment.env"
    line = next(x for x in env.read_text().splitlines() if x.startswith("FEATURES="))
    names = [f for f in line.removeprefix("FEATURES=").split(",") if f != "phone"] + (["phone"] if phone else [])
    env.write_text(env.read_text().replace(line, "FEATURES=" + ",".join(names)))
    return d


def test_home_chooses_the_ai_phone_and_a_site_without_it_runs_none_of_its_workflows(tmp_path):
    assert "phone" in DEPLOY.features(DEPLOY.load(HOME / "deployment.env", env={}))  # home's
    work = ROOT / "deployments/example-work"
    assert "phone" not in DEPLOY.features(DEPLOY.load(work / "deployment.env", env={})) and PHONE_WF.isdisjoint(DEPLOY.workflow_names(work))
    assert "COMPOSE_PROFILES=${FEATURES}" in (HOME / "deployment.env").read_text()   # so compose starts no phone container without it
    listed = set((HOME / "workflows.yaml").read_text().split())
    assert {"crew-phone-check", "crew-phone-cleanup"} <= listed                     # the list keeps them: the feature decides
    off, on = home_copy(tmp_path, False), home_copy(tmp_path, True)
    assert PHONE_WF.isdisjoint(DEPLOY.workflow_names(off)) and PHONE_WF <= set(DEPLOY.workflow_names(on))
    assert set(DEPLOY.workflow_names(on)) - set(DEPLOY.workflow_names(off)) == PHONE_WF
    assert {DEPLOY.workflow_feature(WF / f"{n}.json") for n in PHONE_WF} == {"phone"}
    assert DEPLOY.workflow_problems(off) == []


def test_a_deploy_unpublishes_the_phone_workflows_n8n_still_has(tmp_path, monkeypatch, phone_off):
    """The import publishes the deployment's workflows and unpublishes each one n8n has published that is not among them:
    on a site that leaves the AI phone out, its two go off with the next deploy."""
    import n8n_sync as NS
    monkeypatch.setattr(NS, "sync_packs", lambda *a, **k: [])
    monkeypatch.setenv("N8N_HOOK_TOKEN", "hook-test")
    ids = {json.loads((WF / f"{n}.json").read_text())["id"]: n for n in PHONE_WF}
    calls = []

    def run(cmd, **k):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="\n".join(ids) if "list:workflow" in cmd else "ok", stderr="")
    assert NS.import_all(run=run, made=tmp_path) == 0
    copied = calls[1][-1]
    assert not any(f"{n}.json" in copied for n in PHONE_WF) and "crew-postmaster.json" in copied
    ex = ["docker", "exec", "-u", "node", "aistack-n8n-1", "n8n"]
    assert all(ex + ["unpublish:workflow", f"--id={i}"] in calls for i in ids)
    assert not [c for c in calls if c[6:7] == ["publish:workflow"] and c[7] in {f"--id={i}" for i in ids}]


def test_a_workflow_says_the_feature_of_its_crew_jobs_and_an_export_keeps_it(tmp_path):
    """n8n_gen writes the feature of the crew job a workflow runs; n8n's export carries no area or feature, so the file in
    git keeps its own (a canvas export must not switch the phone's workflows back on)."""
    import n8n_gen as G
    import n8n_sync as NS
    assert G.feature_of("crew", "phone-check") == {"feature": "phone"} and G.feature_of("crew", "postmaster") == {"feature": "mail"}
    assert G.feature_of("crew", "checker") == {} and G.feature_of("task", "12") == {}
    for p in WF.glob("*.json"):                       # every workflow that runs a crew job of a feature names it
        wf = json.loads(p.read_text())
        jobs = [n["parameters"]["job"] for n in wf["nodes"] if (n.get("parameters") or {}).get("kind") == "crew"]
        want = {G.feature_of("crew", j).get("feature") for j in jobs} - {None}
        assert want == {DEPLOY.workflow_feature(wf)} - {"core"}, p.name
    dest, exp = tmp_path / "git", tmp_path / "export"
    dest.mkdir(), exp.mkdir()
    mine = json.loads((WF / "crew-phone-check.json").read_text())
    (dest / "crew-phone-check.json").write_text(json.dumps(mine))
    (exp / "x.json").write_text(json.dumps({k: v for k, v in mine.items() if k not in ("area", "feature")}))
    NS.write_stable([exp / "x.json"], dest)
    back = json.loads((dest / "crew-phone-check.json").read_text())
    assert back["feature"] == "phone" and back["area"] == "phone"


def test_off_its_crew_jobs_are_gone_and_refused_and_on_they_are_back(tmp_path, monkeypatch, capsys):
    import crew as CR
    on = DEPLOY.ON | {"phone"}
    off = DEPLOY.ON - {"phone"}
    assert {"phone-check", "phone-cleanup"} <= {a["id"] for a in CR.jobs(on)}
    assert {"phone-check", "phone-cleanup"}.isdisjoint(a["id"] for a in CR.jobs(off))
    assert CR.off_ids(off) >= {"phone-check", "phone-cleanup", "ai-phone"} and not CR.off_ids(on) & {"phone-check", "ai-phone"}
    assert CR.BY_ID["phone-check"]["name"] == "Phone check"                     # its runs on record keep their name
    monkeypatch.setattr(DEPLOY, "ON", off)
    CR.run("phone-check")                                                        # a unit started by hand: stops at once
    assert "not configured: the feature phone is off" in capsys.readouterr().out
    with pytest.raises(ValueError, match="not configured, the feature phone is off"):
        CR.handle({"action": "crew_run", "id": "phone-cleanup"}, None)
    with pytest.raises(ValueError, match="the AI phone is switched off"):
        CR.handle({"action": "phone_cleanup_do", "id": "c-0123456789"}, None)
    d = tmp_path / "phone"
    d.mkdir()
    (d / "state.json").write_text(json.dumps({"connected": False}))
    import os
    os.utime(d / "state.json", (T0 - 3 * 3600, T0 - 3 * 3600))                 # silent for 3 hours: an alert while it is on
    assert CR.phone_down(T0, d) is None
    monkeypatch.setattr(DEPLOY, "ON", on)
    assert CR.phone_down(T0, d)["kind"] == "phone-down"


def test_off_no_task_of_it_shows_and_the_planner_offers_neither_its_tool_nor_its_agents(K, monkeypatch, phone_off):  # noqa: F811
    import crew as CR
    import tasks as TK
    monkeypatch.setattr(CR, "status", lambda: [])
    for a in CR.CREW:                                  # the duties as they were before the switch: phone-check among them
        TK.register(K, "crew", a["id"], a["what"], a["name"], rhythm={"type": "schedule", "schedule": "weekly"}, status="scheduled", source="crew")
    K.commit()
    board = {t["ref"] for t in TK.state(K)["tasks"] if t["door"] == "crew"}
    assert {"phone-check", "phone-cleanup"}.isdisjoint(board) and "memory" in board
    assert K.execute("select count(*) from tasks where door='crew' and ref='phone-check'").fetchone()[0] == 1   # kept
    cards = TK.cards()
    assert "phone-check" not in cards and "phone-cleanup" not in cards and "AI phone" not in cards["main"]
    monkeypatch.setattr(DEPLOY, "ON", DEPLOY.ON | {"phone"})
    board = {t["ref"] for t in TK.state(K)["tasks"] if t["door"] == "crew"}
    assert {"phone-check", "phone-cleanup"} <= board
    assert "the AI phone" in TK.cards()["main"] and "phone-check" in TK.cards()


@pytest.fixture
def DQ(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMY_LOG", str(tmp_path / "autonomy.jsonl"))
    monkeypatch.setattr(A, "TYPES", {})
    import decisions
    m = importlib.reload(decisions)
    m._seen.clear(); m._loaded["t"] = 0
    return m


def test_off_its_asks_are_dismissed_with_the_reason_kept_and_on_they_ask_again(DQ, monkeypatch):
    st = {"crew": [{"id": "phone-cleanup", "actions": [{"id": "a1", "status": "open", "kind": "cache", "title": "Empty all app caches", "size": 2e9}]}]}
    aid = A.ask_id("dq:phone-step:a1")
    monkeypatch.setattr(DEPLOY, "ON", DEPLOY.ON | {"phone"})
    DQ.asks_sync(DQ.gather(st, now=T0), now=T0)
    assert A.get(aid)["status"] == "open"
    monkeypatch.setattr(DEPLOY, "ON", DEPLOY.ON - {"phone"})
    out = DQ.asks_sync(DQ.gather(st, now=T0 + 10), now=T0 + 10)
    a = A.get(aid)
    assert not [d for d in out if d["id"].startswith("phone-step:")]
    assert a["status"] == "dismissed" and a["answer"]["words"] == "the AI phone is switched off" and a["answer"]["person"] == A.STACK
    assert [h["event"] for h in A.history(aid)][-1] == "dismissed" and A.history(aid)[-1]["words"] == "the AI phone is switched off"
    monkeypatch.setattr(DEPLOY, "ON", DEPLOY.ON | {"phone"})
    DQ.asks_sync(DQ.gather(st, now=T0 + 20), now=T0 + 20)
    assert A.get(aid)["status"] == "open" and "again" in [h["event"] for h in A.history(aid)]


def test_off_the_gateway_grants_no_phone_tool_and_the_assistant_s_prompt_has_no_phone_rule(phone_off):
    keys = runpy.run_path(str(ROOT / "ops/update-keys.py"), run_name="update_keys")
    main = next(m for a, _, _, m in keys["spec"]() if a == "vk-main")
    assert "phone" in main.split(",")                                            # ops/keys.sh keeps the grant for when it is on
    assert "phone" not in keys["granted"](main) and "mail" in keys["granted"](main) and "swarm" in keys["granted"](main)
    assert "phone" in keys["granted"](main, DEPLOY.ON | {"phone"})
    import deploy as D
    import prompts as P
    _, env = D.soul("config/hermes/configure.sh")
    assert env["SOUL_PHONE"] == "" and env["SOUL_WEB"] == P.sections("main")["WEB_RULE"]
    assert D.soul("config/hermes/configure.sh", DEPLOY.ON | {"phone"})[1]["SOUL_PHONE"] == P.sections("main")["PHONE_RULE"]
    conf = (ROOT / "config/hermes/configure.sh").read_text()
    assert '[ -n "$v" ] || { echo "$r rule removed: its feature is off"; continue; }' in conf
    env_file = str(DEPLOY.FILE.relative_to(ROOT))
    assert D.features_changed([env_file]) and "config/hermes/configure.sh" in D.configure_scripts([env_file])
    assert D.off_services() == ["phone"] and D.off_services() == sorted(D.off_services())
    deploy = (ROOT / "ops/deploy.py").read_text()
    assert 'run(*COMPOSE, "rm", "--stop", "--force", *off)' in deploy and "or features_changed(changed):" in deploy


def test_on_the_deploy_stops_nothing_of_it(monkeypatch, phone_on):
    import deploy as D
    assert "phone" not in D.off_services()


def test_off_shopping_offers_buy_it_yourself_and_a_cleanup_reads_the_pc(monkeypatch, phone_off):
    import cleanup as CL
    import shopping as SH
    assert CL.target_of({"title": "Clean up the phone", "goal": "free space on my android"}) == "pc"
    with pytest.raises(RuntimeError, match="the AI phone is switched off"):
        CL.phone_facts()
    with pytest.raises(ValueError, match="the AI phone is switched off: buy it yourself"):
        monkeypatch.setattr(SH, "limits", lambda: {"per_purchase_eur": 150, "per_month_eur": 300, "address_words": ["12345"], "shops": []})
        monkeypatch.setattr(SH, "over_limit", lambda *a: "")
        SH.approve({"status": "proposed", "total_eur": 20, "shop": "amazon.de", "match": {"item": ["ram"]}}, {"status": "active"}, "owner", None)
    said = []
    monkeypatch.setattr(SH, "M", types.SimpleNamespace(X=types.SimpleNamespace(APP="https://app", telegram=lambda t, b, **k: said.append(b)),
                                                       event=lambda *a, **k: None))
    monkeypatch.setattr(SH, "step", lambda *a, **k: None)
    SH.tell({"slug": "ram", "title": "RAM"}, {"id": "p1", "status": "proposed", "item": "RAM", "shop": "amazon.de", "total_eur": 20,
                                              "price_eur": 18, "shipping_eur": 2, "address": "home", "url": "https://shop.example/ram"})
    labels = [label for row in said[0] for label, _ in row]
    assert "🛒 Buy it yourself" in labels and "✅ Approve purchase" not in labels


@pytest.fixture
def phone_app(app, tmp_path, monkeypatch):  # noqa: F811
    S = app
    monkeypatch.setattr(S, "PHONE", tmp_path / "phone")
    (tmp_path / "phone/pending").mkdir(parents=True)
    (tmp_path / "phone/state.json").write_text(json.dumps({"connected": False, "model": "SM-S901B"}))
    (tmp_path / "phone/pending/r1.json").write_text(json.dumps({"id": "r1", "text": "open Chrome", "why": "a job"}))
    S._guide["key"] = None
    return S


def switch(S, monkeypatch, phone):
    monkeypatch.setattr(S, "FEATURES", (set(DEPLOY.KNOWN) - {"phone"}) | ({"phone"} if phone else set()))


def test_off_the_app_draws_no_phone_banner_card_question_page_or_chapter_and_on_it_does(phone_app, monkeypatch):
    S = phone_app
    c = TestClient(S.app)
    switch(S, monkeypatch, False)
    st = c.get("/api/state", headers=H).json()
    assert st["phone"] is None and not [d for d in st["decisions"] if d["id"] == "phone-ask"]
    assert c.get("/api/phone", headers=H).json() == {"installed": False, "off": True}
    assert c.post("/api/phone/control", headers=H, json={"do": "connect"}).status_code == 409
    assert "ai-phone" not in [ch["id"] for ch in c.get("/api/guide", headers=H).json()]
    page = c.get("/", headers=H).text
    assert '"FEATURES": [' in page and '"phone"' not in re.search(r'"FEATURES": \[[^\]]*\]', page).group(0)
    switch(S, monkeypatch, True)
    st = c.get("/api/state", headers=H).json()
    assert st["phone"]["pending"] == 1 and [d for d in st["decisions"] if d["id"] == "phone-ask"]
    assert c.get("/api/phone", headers=H).json()["installed"] is True
    assert "ai-phone" in [ch["id"] for ch in c.get("/api/guide", headers=H).json()]


def test_off_activity_and_the_team_show_nothing_of_it(phone_app, monkeypatch):
    S = phone_app
    c = TestClient(S.app)
    seen = []
    monkeypatch.setattr(S.IX, "build", lambda *a, **k: seen.append(k["hide"]) or {"since": 0, "now": 0, "lines": [], "edges": [], "nodes": [],
                                                                                  "runs": [], "coverage": {}, "sources": {}})
    monkeypatch.setattr(S, "_swarm_app", lambda op, args: {"ok": True, "result": [
        {"id": "main", "tools": ["memory", "phone", "mail"]}, {"id": "phone-check", "tools": []}, {"id": "scout", "tools": []}]})
    switch(S, monkeypatch, False)
    S._picture.clear()
    c.get("/api/swarm/interactions", headers=H)
    assert seen[-1] == {"phone", "ai-phone", "phone-check", "phone-cleanup"}
    who = c.post("/api/swarm", headers=H, json={"op": "who"}).json()["result"]
    assert [a["id"] for a in who] == ["main", "scout"] and who[0]["tools"] == ["memory", "mail"]
    switch(S, monkeypatch, True)
    S._picture.clear()
    c.get("/api/swarm/interactions", headers=H)
    assert seen[-1] == frozenset()
    assert len(c.post("/api/swarm", headers=H, json={"op": "who"}).json()["result"]) == 3


def test_the_app_and_the_runner_name_the_same_parts_of_the_phone():
    import crew as CR
    import server as S
    assert S.FEATURE_IDS["phone"] >= CR.off_ids(DEPLOY.ON - {"phone"}) - CR.off_ids(DEPLOY.ON | {"phone"}) | {"phone"}
    agents = {a["id"] for a in __import__("registry").load()["agents"] if a.get("jobs") and all(
        DEPLOY.workflow_feature(WF / f"{j}.json") == "phone" for j in a["jobs"])}
    assert agents == {"phone-check", "phone-cleanup"} <= S.FEATURE_IDS["phone"]


def test_off_the_front_end_finds_no_phone_page_and_its_links_land_on_home():
    import webjs
    js = webjs.app_js()
    defs = [re.search(r"^const featureOn = .*$", js, re.M).group(0), re.search(r"^const PAGE_FEATURE = .*$", js, re.M).group(0),
            re.search(r"^const toolsHere = [\s\S]*?\}\);", js, re.M).group(0)]
    phone = re.search(r'^  phone: \(\) => .*$', js, re.M).group(0).split("//")[0].strip().rstrip(",")
    pages = json.loads((ROOT / "images/mission-control/web/static/tools.json").read_text())["pages"]
    script = (f"const out = {{}}; for (const F of [{json.dumps(sorted(set(DEPLOY.KNOWN) - {'phone'}))}, null]) {{"
              f" const DEPLOY = {{ FEATURES: F }};\n{chr(10).join(defs)}\nconst MOVED = {{ {phone} }};"
              f" out[F ? 'off' : 'on'] = {{ pages: toolsHere({{ pages: {json.dumps(pages)} }}).pages.map((p) => p[1]), moved: MOVED.phone() }}; }}"
              " console.log(JSON.stringify(out));")
    r = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60, check=True).stdout)
    assert "#/phone" not in r["off"]["pages"] and r["off"]["moved"] == "#/"
    assert "#/phone" in r["on"]["pages"] and r["on"]["moved"] == ""
    shop = (ROOT / "images/mission-control/web/static/shop.js").read_text()
    assert 'const buys = featureOn("phone");' in shop and '${buys ? `<button class="btn primary" data-shop="approve:' in shop

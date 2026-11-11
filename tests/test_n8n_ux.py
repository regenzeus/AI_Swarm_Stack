"""WFL-11: n8n in the app's pages. On the desk the menu's Workflows opens n8n's editor inside the app (#/workflows, a
frame beside the menu); a phone gets a plain list of the workflows from the runner's view and no menu entry; a task's
and a crew job's page show where it runs (its workflow, its run, its state, its step; on the desk the run's canvas); an
agent's page lists every workflow it is in; the Stack page's tools and the Go-to search know n8n's pages."""
import json
import re
from pathlib import Path

import webjs

STATIC = Path(__file__).resolve().parents[1] / "images/mission-control/web/static"


def test_n8n_s_editor_opens_inside_the_app_from_workflows_and_the_stack():
    """APP-69, WFL-11: Workflows is a place on the phone and the desk alike (the app's own list); n8n's editor is a page of
    the app (#/n8n), one tap from Workflows on the desk ("Edit in n8n") and from the Stack page."""
    js = (STATIC / "app-base.js").read_text()
    assert '["workflows", "#/workflows", "Workflows", ic.flow]' in js and "bottom" not in js.split("function navHtml(", 1)[1].split("\n}", 1)[0]
    assert ":8450" not in js and "n8nUrl" not in js and "n8n: vN8n" in js and "  flow: I(" in js
    wf = (STATIC / "app-workflows.js").read_text()
    assert 'const wfDesk = () => matchMedia("(min-width: 960px)").matches;' in wf and "function vN8n()" in wf
    assert '<iframe class="tool-frame" data-src="${esc(src)}" src="${esc(src)}"' in wf     # n8n inside the app
    assert 'id === "executions" ? "/n8n/home/executions"' in wf and '`/n8n/workflow/${encodeURIComponent(id)}' in wf
    assert 'href="#/n8n">${ic.edit}Edit in n8n</a>' in webjs.app_js() and 'href="#/n8n">${ic.flow}n8n</a>' in webjs.app_js()
    assert "app-workflows.js" in webjs.APP_PARTS
    css = (STATIC / "app.css").read_text()
    assert 'body[data-page="n8n"] .view, body[data-page="traces"] .view { max-width: none; padding-bottom: 0; }' in css and ".tool-frame {" in css and "ellipsis" not in css[css.index(".tool-frame {"):]


def test_the_list_shows_each_workflow_with_its_trigger_and_last_run():
    """WFL-11, APP-71: the Workflows list (phone and desk) shows each workflow's trigger and last run from the runner's
    view through the app's own read API; ?open=<id> from before opens that workflow's page."""
    js = webjs.app_js()
    assert 'api("/api/factory")' in js and '"workflows-runs.json"' in (STATIC.parents[1] / "server.workflows.py").read_text()
    card = re.search(r"^function wfCardHtml\(w\) \{.*?^\}$", js, re.M | re.S)[0]
    for part in ("triggerWords(w)", "runPill(r.state)", "last ${esc(when(r.started))}"):
        assert part in card, part
    assert 'if (open) return location.replace(`#/workflow/${encodeURIComponent(open)}`);' in js


def test_task_and_crew_pages_show_where_they_run():
    wf = (STATIC / "app-workflows.js").read_text()
    assert 'const m = t.door === "workflow" ? /^n8n:([^/]+)\\/(.*)$/.exec(t.ref || "") : null;' in wf   # a task the step service made
    assert "S?.workflows?.jobs?.[`task:${t.id}`]" in wf and "S?.workflows?.jobs?.[`crew:${id}`]" in wf
    assert '<iframe class="tool-frame run"' in wf and ": r || w ? wfStepsHtml(w, r)" in wf   # desk: the run's canvas; phone: its steps
    assert "wfRunLine(r)" in wf and '` · at “${esc(r.on)}”`' in wf                         # its state and the step it is on
    task = (STATIC / "task.js").read_text()
    assert "wfWhereInto($(\"#wfwhere\"), wf.wid, wf.ex, null, keepWf)" in task and "wfLink" not in task
    tasks = (STATIC / "app-tasks.js").read_text()
    assert 'if (kind === "crew") wfCrewInto($("#wfwhere"), id, keepWf);' in tasks and "wfLink" not in tasks


def test_an_agents_page_lists_every_workflow_it_is_in():
    wf = (STATIC / "app-workflows.js").read_text()
    assert '(kind === "crew" ? w.crew : w.agents)?.includes(id)' in wf
    assert '`<a class="tag" href="#/workflow/${encodeURIComponent(w.id)}">${ic.flow}${esc(w.name)}</a>`' in wf
    assert 'if (!crew && tile) wfInInto($("#swwfin", box), "agent", id);' in (STATIC / "swarm.js").read_text()   # its own page lists Used in (APP-76)


def test_the_stack_pages_tools_know_n8ns_pages_inside_the_app():
    j = json.loads((STATIC / "tools.json").read_text())
    n = {t["id"]: t for t in j["tools"]}["n8n"]
    assert n["host"] == "app" and [m["path"] for m in n["menus"]] == ["/#/n8n", "/#/n8n?open=executions", "/n8n/home/workflows"]
    assert ["n8n", "#/n8n", "n8n workflow editor canvas executions"] in j["pages"] and any(p[1] == "#/workflows" for p in j["pages"])
    app = (STATIC / "app.js").read_text()
    assert 'const toolUrl = (t, m) => (t.host === "app" ? m.path : toolBase(t) + m.path);' in app

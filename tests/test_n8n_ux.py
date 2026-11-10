"""WFL-11: n8n in the app's pages. On the desk the menu's Workflows opens n8n's editor inside the app (#/workflows, a
frame beside the menu); a phone gets a plain list of the workflows from the runner's view and no menu entry; a task's
and a crew job's page show where it runs (its workflow, its run, its state, its step; on the desk the run's canvas); an
agent's page lists every workflow it is in; the Stack page's tools and the Go-to search know n8n's pages."""
import json
from pathlib import Path

import webjs

STATIC = Path(__file__).resolve().parents[1] / "images/mission-control/web/static"


def test_the_desk_menu_opens_n8n_inside_the_app_and_the_phone_menu_does_not_show_it():
    js = (STATIC / "app-base.js").read_text()
    assert '["workflows", "#/workflows", "Workflows", ic.flow]' in js
    assert 'if (k === "workflows" && bottom) return "";' in js and ":8450" not in js and "n8nUrl" not in js
    assert "workflows: vWorkflows, traces: vTraces }[route.name]" in js and "  flow: I(" in js
    wf = (STATIC / "app-workflows.js").read_text()
    assert 'const wfDesk = () => matchMedia("(min-width: 960px)").matches;' in wf
    assert "if (!wfDesk()) return wfList(open);" in wf                                   # a phone: the list
    assert '<iframe class="tool-frame" data-src="${esc(src)}" src="${esc(src)}"' in wf     # the desk: n8n inside the app
    assert 'id === "executions" ? "/n8n/home/executions"' in wf and '`/n8n/workflow/${encodeURIComponent(id)}' in wf
    assert "app-workflows.js" in webjs.APP_PARTS
    css = (STATIC / "app.css").read_text()
    assert 'body[data-page="workflows"] .view, body[data-page="traces"] .view { max-width: none; padding-bottom: 0; }' in css and ".tool-frame {" in css and "ellipsis" not in css[css.index(".tool-frame {"):]


def test_the_phone_lists_each_workflow_with_its_schedule_and_last_run():
    wf = (STATIC / "app-workflows.js").read_text()
    assert 'api("/api/workflows")' in wf
    for part in ("wfOnPill(w)", "esc(w.schedule)", "last run ${wfStatePill(r.state)} ${esc(when(r.started))}", "wfStepsHtml(w, x)"):
        assert part in wf, part
    assert 'if (open) $(`[data-wf="${CSS.escape(open)}"]`)?.scrollIntoView' in wf      # ?open=<id> on a phone: that workflow


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
    assert '`<a class="tag" href="#/workflows?open=${encodeURIComponent(w.id)}">${ic.flow}${esc(w.name)}</a>`' in wf
    assert 'if (!crew) wfInInto($("#swwfin", box), "agent", id);' in (STATIC / "swarm.js").read_text()


def test_the_stack_pages_tools_know_n8ns_pages_inside_the_app():
    j = json.loads((STATIC / "tools.json").read_text())
    n = {t["id"]: t for t in j["tools"]}["n8n"]
    assert n["host"] == "app" and [m["path"] for m in n["menus"]] == ["/#/workflows", "/#/workflows?open=executions", "/n8n/home/workflows"]
    assert ["Workflows", "#/workflows", "n8n workflow schedule runs executions canvas"] in j["pages"]
    app = (STATIC / "app.js").read_text()
    assert 'const toolUrl = (t, m) => (t.host === "app" ? m.path : toolBase(t) + m.path);' in app

"""The record of a run and a pack's exams (GEN-31, docs/AI-STACK.md).

Export: one zip a person can follow without the app. It holds the run as JSON (each step's state, start, end, answer
and decider), the orchestrator's own history of it when there is one (n8n's execution), the files its steps made (from
the artifact store, by their ids), and an HTML page that reads as the chain: the item, then each step in order with
what it did, who decided each question and which way each decision went, then how it ended.

Exams: a pack's exam set (exams/<set>.yaml) names the workflow that answers and where its answer is read:
    workflow: toy/triage
    outcome: route.branch            # <step>.<field of its answer>
    cases:
      - {ticket: "The export stops at 2 GB", outcome: bug}
Each case runs the workflow with the case's text as its item; its answer is compared with the known outcome, and the
set scores the share it got right, with every case's answer kept, so a person sees which it got wrong.

    export(run, out, history=None)     -> the zip's path; run: {id, task, workflow, status, started, ended, why, nodes}
    exam(pack, set, run_case)          -> {"set", "score", "right", "cases": [...]}; run_case(workflow, item, case) -> a run
"""
import datetime as dt
import html
import json
import zipfile
from pathlib import Path

import yaml

from domain import artifacts as AR


def _page(run, nodes, history=None):
    extra = ", history.json the orchestrator's own history" if history is not None else ""
    rows = []
    for n in nodes:
        a = n.get("answer") or {}
        bits = [f"<b>{html.escape(n.get('title') or n['id'])}</b> <small>{html.escape(n.get('block', ''))}"
                f"{' · ' + html.escape(n['agent']) if n.get('agent') else ''}</small>",
                f"{html.escape(n.get('status', ''))} · {html.escape(n.get('started', '') or '–')} → {html.escape(n.get('ended', '') or '–')}"]
        if a.get("who"):
            bits.append(f"decided by {html.escape(str(a['who']))}")
        if a.get("branch"):
            bits.append(f"went “{html.escape(str(a['branch']))}”")
        if a.get("ref"):
            bits.append(f"answer: <code>{html.escape(str(a['ref']))}</code>")
        for x in a.get("artifacts") or []:
            bits.append(f"made <a href='artifacts/{html.escape(x.removeprefix('artifact:'))}'>{html.escape(x)}</a>")
        if n.get("error"):
            bits.append(f"<span style='color:#b00'>{html.escape(n['error'])}</span>")
        rows.append("<li>" + "<br>".join(bits) + "</li>")
    return f"""<!doctype html><meta charset="utf-8"><title>{html.escape(run['id'])}</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:860px;margin:2em auto;padding:0 1em}}li{{margin:.8em 0}}code{{font-size:13px}}</style>
<h1>{html.escape(run['id'])}</h1>
<p>Item <b>{html.escape(run.get('task', ''))}</b> · workflow {html.escape(run.get('workflow', ''))} · {html.escape(run.get('status', ''))}
· started {html.escape(run.get('started', ''))} · ended {html.escape(run.get('ended', '') or '–')}</p>
<p>{html.escape(run.get('why', '') or '')}</p>
<ol>{''.join(rows)}</ol>
<p><small>Exported {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}: run.json holds the same as data{extra}.</small></p>"""


def export(run, out, history=None):
    """The finished run as one zip: run.json, index.html, its artifacts, and history.json when the orchestrator gave
    its own history of the run. run["nodes"] are its steps in order, each {id, title, block, agent, status, started,
    ended, answer, error}."""
    nodes = list(run.get("nodes") or [])
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("run.json", json.dumps(run, indent=1, ensure_ascii=False))
        if history is not None:
            z.writestr("history.json", json.dumps(history, indent=1, ensure_ascii=False))
        z.writestr("index.html", _page(run, nodes, history))
        for n in nodes:
            for x in (n.get("answer") or {}).get("artifacts") or []:
                p = AR.path_of(x)
                if p:
                    z.write(p, f"artifacts/{x.removeprefix('artifact:')}")
    return out


def exam(pack, set_name, run_case):
    """Runs a pack's exam set: each case through the workflow it names; run_case(workflow, item, case) -> the finished
    run, {status, nodes: {<step>: {answer}}}. The score is the share whose answer is the case's known outcome."""
    spec = yaml.safe_load((Path(pack["dir"]) / "exams" / f"{set_name}.yaml").read_text()) or {}
    node, _, field = str(spec.get("outcome") or "").partition(".")
    if not spec.get("workflow") or not node or not field:
        return {"set": set_name, "error": "an exam set names its workflow and where its answer is read (outcome: <step>.<field>)"}
    cases = []
    for i, c in enumerate(spec.get("cases") or []):
        out = run_case(spec["workflow"], f"exam/{pack['name']}/{set_name}/{i}", c) or {}
        got = ((out.get("nodes") or {}).get(node) or {}).get("answer", {}).get(field)
        cases.append({"case": c, "got": got, "right": got == c.get("outcome"), "status": out.get("status")})
    right = sum(c["right"] for c in cases)
    return {"set": set_name, "workflow": spec["workflow"], "right": right, "of": len(cases), "score": right / len(cases) if cases else 0.0,
            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "cases": cases}

"""The record of a run and a pack's exams (GEN-31, docs/AI-STACK.md §11).

Export: one zip a person can follow without the app. It holds the run as JSON (its graph, each block's state, start,
end, answer and decider), Temporal's history of it, the files its steps made (from the artifact store, by their ids),
and an HTML page that reads as the chain: the item, then each block in order with what it did, who decided each gate
and which way each decision went, then how it ended.

Exams: a pack's exam set (exams/<set>.yaml) names the template that answers and where its answer is read:
    template: toy/triage
    outcome: route.branch            # <block>.<field of its answer>
    cases:
      - {ticket: "The export stops at 2 GB", outcome: bug}
Each case runs the template with the case's text as its item; its answer is compared with the known outcome, and the
set scores the share it got right, with every case's answer kept, so a person sees which it got wrong.

    await export(client, run_id, out)          -> the zip's path
    await exam(client, pack, set, start)       -> {"set", "score", "right", "cases": [...]}
"""
import datetime as dt
import html
import json
import zipfile
from pathlib import Path

import yaml

from engine import artifacts as AR


def _page(run, nodes):
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
<p>Item <b>{html.escape(run.get('task', ''))}</b> · template {html.escape(run.get('graph', ''))} · {html.escape(run.get('status', ''))}
· started {html.escape(run.get('started', ''))} · ended {html.escape(run.get('ended', '') or '–')}</p>
<p>{html.escape(run.get('why', '') or '')}</p>
<ol>{''.join(rows)}</ol>
<p><small>Exported {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}: run.json holds the same as data, history.json Temporal's history.</small></p>"""


async def export(client, run_id, out):
    """The finished run as one zip: run.json, history.json, index.html and its artifacts."""
    from engine import runner as R
    h = client.get_workflow_handle(run_id)
    desc = await h.describe()
    st = await h.query(R.GraphRun.state)
    hist = await h.fetch_history()
    shape = {s["id"]: s for s in st.get("shape") or []}
    nodes = [{**shape[k], **v, "id": k} for k, v in (st.get("nodes") or {}).items() if k in shape]
    order = [s["id"] for s in st.get("shape") or []]
    nodes.sort(key=lambda n: order.index(n["id"]))
    run = {"id": run_id, "run_id": desc.run_id, "task": (desc.memo and "") or "", "graph": st.get("graph", ""), "source": st.get("source", ""),
           "status": desc.status.name.lower() if desc.status else "", "started": desc.start_time.isoformat() if desc.start_time else "",
           "ended": desc.close_time.isoformat() if desc.close_time else "", "nodes": nodes}
    first = next(iter(hist.events), None)
    if first is not None and first.workflow_execution_started_event_attributes.input.payloads:
        run["task"] = json.loads(first.workflow_execution_started_event_attributes.input.payloads[0].data or b"{}").get("task", "")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("run.json", json.dumps(run, indent=1, ensure_ascii=False))
        z.writestr("history.json", hist.to_json())
        z.writestr("index.html", _page(run, nodes))
        for n in nodes:
            for x in (n.get("answer") or {}).get("artifacts") or []:
                p = AR.path_of(x)
                if p:
                    z.write(p, f"artifacts/{x.removeprefix('artifact:')}")
    return out


async def exam(client, pack, set_name, start):
    """Runs a pack's exam set: each case through the template it names; start(template, item) -> a started run's
    handle. The score is the share whose answer is the case's known outcome."""
    spec = yaml.safe_load((Path(pack["dir"]) / "exams" / f"{set_name}.yaml").read_text()) or {}
    node, _, field = str(spec.get("outcome") or "").partition(".")
    if not spec.get("template") or not node or not field:
        return {"set": set_name, "error": "an exam set names its template and where its answer is read (outcome: <block>.<field>)"}
    cases = []
    for i, c in enumerate(spec.get("cases") or []):
        h = await start(spec["template"], f"exam/{pack['name']}/{set_name}/{i}", c)
        out = await h.result()
        got = ((out.get("nodes") or {}).get(node) or {}).get("answer", {}).get(field)
        cases.append({"case": c, "got": got, "right": got == c.get("outcome"), "status": out.get("status")})
    right = sum(c["right"] for c in cases)
    return {"set": set_name, "template": spec["template"], "right": right, "of": len(cases), "score": right / len(cases) if cases else 0.0,
            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "cases": cases}

"""The record of a run and a pack's exams (GEN-31, docs/AI-STACK.md).

Export: one zip a person can follow without the app. It holds the run as JSON (each step's state, start, end, answer
and decider), the workflow's shape (its steps and how they connect, from git or the pack cache), the files its steps
made (from the artifact store, by their ids), and an HTML page that reads as the chain: the item, then each step in
order with what it did, who decided each question and which way each decision went, then how it ended. A run n8n drove
comes from the run register (ops/runreg.py, export_run), the stack's own record of it; n8n gives only time and order.

Exams: a pack's exam set (exams/<set>.yaml) names the workflow that answers and where its answer is read:
    workflow: demo/triage
    outcome: route.branch            # <step>.<field of its answer>
    cases:
      - {ticket: "The export stops at 2 GB", outcome: bug}
Each case runs the workflow with the case's text as its item; its answer is compared with the known outcome, and the
set scores the share it got right, with every case's answer kept, so a person sees which it got wrong.

    export(run, out, history=None, shape=None)   -> the zip's path; run: {id, task, workflow, status, started, ended, why, nodes}
    export_run(execution, out, db=None)          a run n8n drove, from the run register (ops/runreg.py): its steps,
                                                 their task records, files, tracker writes and pull request, and the
                                                 workflow's shape from git or the pack cache, never n8n's internal API
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


def export(run, out, history=None, shape=None):
    """The finished run as one zip: run.json, index.html, its artifacts, history.json when the orchestrator gave its own
    history of the run, and workflow.json, the workflow's shape, when given. run["nodes"] are its steps in order, each
    {id, title, block, agent, status, started, ended, answer, error}."""
    nodes = list(run.get("nodes") or [])
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("run.json", json.dumps(run, indent=1, ensure_ascii=False))
        if history is not None:
            z.writestr("history.json", json.dumps(history, indent=1, ensure_ascii=False))
        if shape is not None:
            z.writestr("workflow.json", json.dumps(shape, indent=1, ensure_ascii=False))
        z.writestr("index.html", _page(run, nodes, history))
        for n in nodes:
            for x in (n.get("answer") or {}).get("artifacts") or []:
                p = AR.path_of(x)
                if p:
                    z.write(p, f"artifacts/{x.removeprefix('artifact:')}")
    return out


REPO_WORKFLOWS = Path(__file__).resolve().parents[2] / "n8n/workflows"


def shape_of(workflow_id, name, repo=REPO_WORKFLOWS, packs=None):
    """The workflow's shape, its steps and how they connect, from the workflow file in git (by its id) or in a pack's
    cache (by its name <pack>/<name>); never from n8n's internal API. -> {name, source, nodes, connections} or None."""
    found = None
    for f in sorted(Path(repo).glob("*.json")):
        wf = json.loads(f.read_text())
        if workflow_id and wf.get("id") == workflow_id:
            found = (wf, f"git: n8n/workflows/{f.name}")
            break
    if found is None and name:
        if packs is None:
            try:
                from domain import packs as PK
                packs = PK.load()["packs"]
            except Exception:                        # no packs here: the shape is left out, the steps are whole
                packs = []
        for p in packs:
            for w in p.get("workflows") or []:
                if w["name"] == name:
                    found = (json.loads(Path(w["path"]).read_text()), f"pack {p.get('name', '')}: {Path(w['path']).name}")
    if found is None:
        return None
    wf, src = found
    return {"name": wf.get("name", ""), "source": src,
            "nodes": [{"name": n["name"], "type": n["type"], **({"kind": n["parameters"].get("kind")} if n.get("parameters", {}).get("kind") else {})}
                      for n in wf.get("nodes") or []],
            "connections": {a: [t["node"] for out in (c.get("main") or []) for t in out or []] for a, c in (wf.get("connections") or {}).items()}}


def _view(kind, a):
    """What the page shows of an answer: who decided, which way, its reference, the files it made."""
    v = {}
    if a.get("by"):
        v["who"] = a["by"]
    if kind == "ask" and a.get("answer"):
        v["branch"] = a["answer"]
    if kind == "wait_item" and a.get("outcome"):
        v["branch"] = a["outcome"]
    if a.get("ref") or a.get("pr"):
        v["ref"] = a.get("ref") or a.get("pr")
    if a.get("artifact_ids"):
        v["artifacts"] = list(a["artifact_ids"])
    return v


def export_run(execution, out, db=None, repo=REPO_WORKFLOWS, packs=None):
    """WFL-23: a run of n8n as one zip, from the run register (ops/runreg.py), the stack's record of it: each step in
    order with its request, whole answer and times, its task's record (from the tasks table, when db is given), the
    files it made by artifact id and hash, the tracker writes with their shadow or live references, and the pull
    request; from n8n only the workflow's shape (shape_of). -> the zip's path."""
    import runreg as RR
    r = RR.run(execution)
    if not r:
        raise ValueError(f"the run register holds no run {execution!r}")
    steps = sorted(r["steps"], key=lambda s: s["started"] or "")
    nodes, writes, prs, files = [], [], [], []
    for s in steps:
        a = s.get("answer") or {}
        n = {"id": s["rid"], "title": s.get("title") or s.get("node") or s["kind"], "block": s["kind"], "agent": (s.get("request") or {}).get("agent") or "",
             "status": a.get("status") or "waiting", "started": s["started"], "ended": s.get("ended") or "", "answer": _view(s["kind"], a),
             "request": s.get("request") or {}, "result": a, "error": a.get("error") or ""}
        if db is not None and a.get("task"):
            t = db.execute("select id, title, status, created, updated from tasks where id=?", (a["task"],)).fetchone()
            n["task_record"] = {"task": dict(t) if t else None, "steps": [dict(x) for x in db.execute(
                "select idx, title, agent, harness, status, output, error from task_steps where task=? order by occ, idx", (a["task"],)).fetchall()]}
        if s["kind"] == "tracker" and a.get("ref"):
            writes.append({"write": a.get("write"), "tracker": a.get("tracker"), "key": a.get("key"), "ref": a["ref"], "shadow": a.get("shadow")})
        if a.get("pr"):
            prs.append({"url": a["pr"], "number": a.get("pr_number"), "branch": a.get("branch"), "draft": a.get("draft", True), "build": a.get("build")})
        for x in a.get("artifact_ids") or []:
            files.append({"id": x, "sha256": x.removeprefix("artifact:"), "made_by": AR.records(x.removeprefix("artifact:"))})
        nodes.append(n)
    it = RR.item(**r["item"]) if r.get("item") else None
    done = all(s.get("answer") for s in steps)
    run = {"id": (it or {}).get("run") or f"{r.get('name') or r.get('workflow')}#{execution}", "execution": execution,
           "task": f"{r['item']['tracker']}/{r['item']['key']}" if r.get("item") else "", "workflow": r.get("name") or r.get("workflow") or "",
           "status": (nodes[-1]["status"] if done and nodes else "running"), "started": steps[0]["started"] if steps else "",
           "ended": (steps[-1].get("ended") or "") if done and steps else "", "nodes": nodes, "tracker_writes": writes,
           "pull_requests": prs, "files": files, "item": it}
    return export(run, out, shape=shape_of(r.get("workflow"), r.get("name"), repo, packs))


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

"""Morning digest on Telegram: what the stack did in the last 24 h, in a few lines. No model calls.
Runs from digest.timer (07:30, catches up after the PC was off). Usage: python3 ops/digest.py [--print]
"""
import json, subprocess, sys, time, urllib.request
from datetime import datetime
from pathlib import Path

import deployment as DEPLOY                        # this deployment's hosts and paths (deployments/<name>/deployment.env)

STATE = Path("/srv/ai/state")
DAY = time.time() - 86400
OPS = Path(__file__).resolve().parent


def jsonl(name):
    try:
        return [json.loads(l) for l in (STATE / name).read_text().splitlines() if l.strip()]
    except FileNotFoundError:
        return []


def sql(q):
    p = subprocess.run(["docker", "exec", "aistack-postgres-1", "psql", "-U", "litellm", "-d", "litellm", "-tAc", q],
                       capture_output=True, text=True)
    return [r.split("|") for r in p.stdout.split("\n") if r]


def ago(ts):
    h = (time.time() - ts) / 3600
    return f"{h:.0f} h ago" if h < 48 else f"{h / 24:.0f} days ago"


lines = [f"Good morning. AI stack, last 24 h ({datetime.now():%a %d %b}):"]

# Model use: subscription calls are free; paid spend is what counts against the $10 budget.
use = sql('select coalesce(k.key_alias, \'other\'), count(*), coalesce(sum(s.spend),0) from "LiteLLM_SpendLogs" s '
          'left join "LiteLLM_VerificationToken" k on k.token = s.api_key '
          "where s.\"startTime\" > now() - interval '1 day' group by 1 order by 2 desc")
total = sql('select coalesce(sum(spend),0) from "LiteLLM_SpendLogs"')
calls = ", ".join(f"{a.removeprefix('vk-')} {n}" for a, n, _ in use[:5]) or "none"
day_spend = sum(float(s) for *_, s in use)
lines.append(f"- Model calls: {calls}. Paid today ${day_spend:.4f}, all-time ${float(total[0][0]) if total else 0:.4f} of $10.")

b = [r for r in jsonl("backups.jsonl") if r["kind"] == "backup"]
d = [r for r in jsonl("backups.jsonl") if r["kind"] == "restore-drill"]
lines.append(f"- Backup: {b[-1]['file']} ({b[-1]['size']}, {ago(b[-1]['ts'])})" if b else "- Backup: none yet!")
if d:
    lines.append(f"- Restore drill: {d[-1]['result']} ({ago(d[-1]['ts'])})")
if b and time.time() - b[-1]["ts"] > 2 * 86400:
    lines.append("  ! last backup is older than 2 days")

ap = [r for r in jsonl("approvals.jsonl") if r["ts"] > DAY]
skills = [r for r in ap if r["kind"] == "skill"]
cur = [r for r in ap if r["kind"] == "curator"]
mem = [r for r in ap if r["kind"] == "memory"]
if skills:
    lines.append(f"- Skills learned or changed: {', '.join(sorted({r['item_id'] for r in skills}))}")
for r in cur:
    lines.append(f"- Curator: {r['decision']} (gate {r.get('old', '?')} -> {r.get('new', '?')}/{r.get('n', '?')})")
if mem:
    lines.append(f"- Memory: {len(mem)} decision(s): " + ", ".join(f"{r['decision']}" for r in mem))
hs = subprocess.run(["docker", "exec", "aistack-hindsight-db-1", "psql", "-U", "hindsight", "-d", "hindsight", "-tAc",
                     "select count(*) filter (where fact_type <> 'observation'), "
                     "count(*) filter (where fact_type = 'observation'), "
                     "count(*) filter (where created_at > now() - interval '1 day') from memory_units"],
                    capture_output=True, text=True).stdout.strip().split("|")
if len(hs) == 3:
    lines.append(f"- Long-term memory: {hs[0]} facts, {hs[1]} observations ({hs[2]} new today)")
pending = subprocess.run(["docker", "exec", "aistack-hermes-1", "sh", "-c", "ls /opt/data/pending/memory 2>/dev/null | wc -l"],
                         capture_output=True, text=True).stdout.strip()
if pending not in ("", "0"):
    lines.append(f"- {pending} memory change(s) wait for you: /memory pending")

try:
    ing = [l for l in (STATE / "vault-ingest.log").read_text().splitlines()
           if "ingest done" in l and datetime.strptime(l[:19], "%Y-%m-%d %H:%M:%S").timestamp() > DAY]
except FileNotFoundError:
    ing = []
if ing:
    lines.append(f"- Vault: {len(ing)} source(s) ingested: " + "; ".join(l.split("ingest done: ")[1].split(" (")[0] for l in ing[:4]))

graphs = subprocess.run(["journalctl", "--user", "-u", "graphify-sync", "--since", "-1day", "-o", "cat", "--no-pager"],
                        capture_output=True, text=True).stdout
upd = sorted({l.split("graph updated: ")[1].split(" @")[0] for l in graphs.splitlines() if "graph updated: " in l})
if upd:
    lines.append(f"- Code graph updated: {', '.join(upd)}")

tok = ""
for key in ("FORGEJO_TOKEN", "FORGEJO_STATUS_TOKEN"):        # one token is enough: the write token, else the read-only one
    tok = tok or subprocess.run(["sops", "-d", "--extract", f'["{key}"]', str(OPS.parent / "secrets/secrets.enc.yaml")],
                                capture_output=True, text=True).stdout.strip()
ci = []
for repo in ("ai-stack", "TestRepo", "vault", "hermes-skills"):
    try:
        req = urllib.request.Request(f"{DEPLOY.FORGEJO_URL}/api/v1/repos/{DEPLOY.FORGEJO_OWNER}/{repo}/actions/tasks?limit=1",
                                     headers={"Authorization": f"token {tok}"})
        runs = json.load(urllib.request.urlopen(req, timeout=10)).get("workflow_runs") or []
        if runs:
            ci.append(f"{repo} {'ok' if runs[0]['status'] == 'success' else runs[0]['status'].upper()}")
    except Exception:
        ci.append(f"{repo} ?")
if ci:
    lines.append("- CI: " + ", ".join(ci))

failed = subprocess.run(["systemctl", "--user", "list-units", "--failed", "--plain", "--no-legend"],
                        capture_output=True, text=True).stdout.split()
failed = [u for u in failed if u.endswith((".service", ".timer"))]
lines.append(f"- Problems: failed jobs {', '.join(failed)}" if failed else "- No failed jobs.")

try:                                                     # the Agent health board (ops/crew.py health, in state.json)
    import json as _json
    _h = _json.loads(Path("/srv/ai/missions/public/state.json").read_text()).get("health") or {}
    _bad = [i for i in _h.get("items", []) if i.get("issues")]
    lines.append(f"- Agent health: {len(_bad)} with issues: " + "; ".join(f"{i['name']} ({i['issues'][0]['text']})" for i in _bad[:5])
                 if _bad else f"- Agent health: all {len(_h.get('items', []))} agents fine." if _h else "- Agent health: not available.")
except Exception:
    lines.append("- Agent health: not available.")
msg = "\n".join(lines)
print(msg)
if "--print" not in sys.argv:
    import notify as N                            # the one notification path (OBS-16)
    N.send(msg, "result", by="stack")

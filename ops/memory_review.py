"""Memory auto-review: decide staged Hermes memory writes by rule, so only real decisions reach the owner.

Runs every 10 min (systemd user timer) with secrets in the environment:
  sops exec-env secrets/secrets.enc.yaml 'sops exec-env secrets/agent-keys.enc.yaml "python3 ops/memory_review.py"'
Auto-approve: no secret, at most 300 chars, judge says not sensitive (health/finance/IDs) and no contradiction
with current USER.md/MEMORY.md. Anything else stays staged and is announced on Telegram once.
Every decision is appended to /srv/ai/state/approvals.jsonl (actor auto|manual is filled by the later report).
"""
import json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import prompts as P  # noqa: E402
import textcap as TC                              # visible caps (AGENTS.md, truncation)

C = "aistack-hermes-1"
STATE = Path("/srv/ai/state"); LOG = STATE / "approvals.jsonl"; SEEN = STATE / "memory-notified.json"
SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|xox[bp]-[A-Za-z0-9-]{10,}"
                    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|\b\d{8,10}:[A-Za-z0-9_-]{30,}\b|password\s*[:=]\s*\S+)", re.I)


def sh(*cmd):
    return subprocess.run(["docker", "exec", "-u", "hermes", C, *cmd], capture_output=True, text=True).stdout


def judge(entry, known):
    prompt = P.text("curator", "GATEKEEPER").format(known=known or "(none)", entry=entry)   # MEM-11: prompts/curator.md
    body = json.dumps({"model": "gpt-sub-fast", "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("http://127.0.0.1:4000/v1/chat/completions", data=body, headers={
        "Authorization": f"Bearer {os.environ['VK_CURATOR']}", "Content-Type": "application/json"})
    text = TC.answer(json.load(urllib.request.urlopen(req, timeout=120)), "the memory judge")
    return json.loads(re.search(r"\{.*\}", text, re.S).group(0))


def record(**kw):
    STATE.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps({"ts": int(time.time()), "kind": "memory", **kw}, ensure_ascii=False) + "\n")


def notify(text):
    import notify as N                            # the one notification path (OBS-16); a memory waiting for the owner's OK
    N.send(text, "approval", by="memory")


def main():
    seen = set(json.loads(SEEN.read_text())) if SEEN.exists() else set()
    ids = sh("sh", "-c", "ls /opt/data/pending/memory 2>/dev/null").split()
    if not ids:
        return
    known = sh("sh", "-c", "cat /opt/data/memories/USER.md /opt/data/memories/MEMORY.md 2>/dev/null")
    for fn in ids:
        item = json.loads(sh("cat", f"/opt/data/pending/memory/{fn}") or "{}")
        pid, entry = item.get("id"), (item.get("payload") or {}).get("content") or item.get("summary", "")
        if not pid:
            continue
        if SECRET.search(entry):
            sh("hermes", "-z", f"/memory reject {pid}")
            record(item_id=pid, rule="secret", decision="rejected", actor="auto")
            notify(f"Memory {pid}: blocked, it looked like a secret. Nothing was saved.")
            continue
        verdict = {"contradicts": False, "sensitive": False, "reason": ""}
        if len(entry) <= 300:
            try:
                verdict = judge(entry, known)
            except Exception as e:
                verdict = {"contradicts": True, "sensitive": False, "reason": f"judge failed: {e.__class__.__name__}"}
        if len(entry) <= 300 and not verdict.get("contradicts") and not verdict.get("sensitive"):
            out = sh("hermes", "-z", f"/memory approve {pid}")
            record(item_id=pid, rule="clean", decision="approved" if "Approved" in out else "approve-failed", actor="auto")
            known += "\n" + entry
            continue
        rule = "too-long" if len(entry) > 300 else ("contradiction" if verdict.get("contradicts") else "sensitive")
        if pid not in seen:
            record(item_id=pid, rule=rule, decision="staged", actor="auto")
            short = re.sub(r"\d{3,}", "###", entry)[:80]  # cap: id
            notify(f"Memory needs your OK ({rule}: {verdict.get('reason', '')}):\n\"{short}\"\n"
                   f"Approve: /memory approve {pid}   Reject: /memory reject {pid}\nOr tap it in Mission Control, System.")
            seen.add(pid)
    SEEN.write_text(json.dumps(sorted(seen)))


if __name__ == "__main__":
    main()

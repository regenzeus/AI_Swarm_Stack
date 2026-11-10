"""Weekly learning run: curator pass on Hermes's skills, behind the benchmark gate, then the vault lint.

  python3 ops/curate.py                    weekly run (its n8n workflow, Sundays 04:00)
  python3 ops/curate.py --apply "CMD"      gate an arbitrary skills change instead of the curator (tests/demo)
  python3 ops/curate.py --no-lint          skip the vault lint
Run with secrets: sops exec-env secrets/secrets.enc.yaml 'sops exec-env secrets/agent-keys.enc.yaml "python3 ops/curate.py"'

Gate: the fast benchmark subset (gate: true in eval/bench-v1.yaml) runs before and after the change. Cases that
flip pass -> fail are re-run once (LLM answers vary); if any still fail, or the score drops, the change is rolled
back to the snapshot taken just before it (`hermes curator rollback`) and the rollback is committed to
hermes-skills. Every decision lands in /srv/ai/state/approvals.jsonl and on Telegram.
"""
import argparse, json, shlex, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval")); sys.path.insert(0, str(ROOT / "ops"))
import bench  # noqa: E402
import skills_sync  # noqa: E402
import deployment as DEPLOY  # noqa: E402

LOG = Path("/srv/ai/state/approvals.jsonl")


def hermes(cmd):
    p = subprocess.run(["docker", "exec", "-u", "hermes", "aistack-hermes-1", "sh", "-c", cmd],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return (p.stdout + p.stderr).strip()


def reload_hermes():
    """The gateway caches its skills index in memory; changes made outside the agent (curator CLI, rollback,
    git restore) only take effect after a restart."""
    subprocess.run(["docker", "restart", "aistack-hermes-1"], capture_output=True)
    subprocess.run(["docker", "restart", "aistack-hermes-dashboard-1", "aistack-gate-hermes-dashboard-1"], capture_output=True)   # they share Hermes' network namespace
    for _ in range(60):
        h = subprocess.run(["curl", "-s", "http://127.0.0.1:8642/health"], capture_output=True, text=True).stdout
        if '"ok"' in h:
            return
        time.sleep(3)


def gate(label, only=None):
    return bench.run(argparse.Namespace(gate=True, label=label, only=only))


def record(**kw):
    with LOG.open("a") as f:
        f.write(json.dumps({"ts": int(time.time()), "kind": "curator", **kw}, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply"); ap.add_argument("--no-lint", action="store_true")
    a = ap.parse_args()
    what = "test change" if a.apply else "curator"

    skills_sync.main()                                  # commit whatever was learned during the week
    before = gate("pre-" + ("change" if a.apply else "curate"))
    if before.get("errors", 0) > 2:                     # cannot measure (usually the subscription's rate limit)
        msg = (f"Weekly {what} run skipped: {before['errors']} of {before['total']} test answers were not measurable "
               "(model rate limit). Nothing changed; it runs again next week, or start it with `make curate`.")
        print(msg); skills_sync.notify(msg); record(item_id="-", rule="eval-gate", decision="skipped", actor="auto")
        return 2
    snap = hermes(f"hermes curator backup --reason eval-gate-{what.replace(' ', '-')}")  # the rollback point
    snap_id = snap.rstrip().rsplit("/", 1)[-1]
    print("snapshot:", snap_id)
    if a.apply:
        out = subprocess.run(a.apply, shell=True, capture_output=True, text=True)  # nosemgrep: subprocess-shell-true -- operator-typed test hook (make curate ARGS=--apply)
        print("applied:", shlex.quote(a.apply), out.returncode)
    else:
        # Skills restored from git lose the curator's provenance marker; hand every eligible one back first
        # (bundled and hub skills are never eligible).
        out = hermes("hermes curator adopt --all-unmanaged --yes >/dev/null; hermes curator resume >/dev/null; "
                     "hermes curator run --sync --consolidate; hermes curator pause >/dev/null")
        print("\n".join(out.splitlines()[-12:]))
    skills_sync.main()
    reload_hermes()
    changed = subprocess.run(["git", "-C", str(skills_sync.REPO), "log", "-1", "--format=%h %s"],
                             capture_output=True, text=True).stdout.strip()

    try:
        after = gate("post-" + ("change" if a.apply else "curate"))
        cmp = bench.compare_results(before, after)
        if cmp["lost"]:                                 # re-check flips once before calling it a regression
            retry = gate("recheck", only=",".join(cmp["lost"]))
            still = [r["id"] for r in retry["results"] if not r["pass"]]
            cmp["noise"] = [i for i in cmp["lost"] if i not in still]
            cmp["lost"] = still
            cmp["new"] += len(cmp["noise"])
        inconclusive = after.get("errors", 0) > 2
    except Exception as e:                              # no verdict means no change: roll back
        print("gate failed:", e)
        cmp = {"old": before["passed"], "new": 0, "n": before["total"], "lost": [], "gained": []}
        inconclusive = True
    regressed = inconclusive or bool(cmp["lost"]) or cmp["new"] < cmp["old"]

    if regressed:
        rb = hermes(f"hermes curator rollback --id {snap_id} -y")
        print("rollback:", rb.splitlines()[-1] if rb else "?")
        reload_hermes()
        skills_sync.main()
        verdict = ("ROLLED BACK (the result could not be measured). " if inconclusive else
                   f"ROLLED BACK. Gate {cmp['old']}/{cmp['n']} -> {cmp['new']}/{cmp['n']}; "
                   f"broke: {', '.join(cmp['lost']) or '-'}. ") + f"Skills restored to the snapshot before the {what}."
    else:
        verdict = (f"KEPT. Gate {cmp['old']}/{cmp['n']} -> {cmp['new']}/{cmp['n']}"
                   + (f" (gained: {', '.join(cmp['gained'])})" if cmp["gained"] else "") + ".")
    record(item_id=changed, rule="eval-gate", decision="rolled-back" if regressed else "kept", actor="auto", **cmp)
    head = subprocess.run(["git", "-C", str(skills_sync.REPO), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    msg = (f"Weekly {what} run: {verdict}\nSkills history: "
           f"{DEPLOY.FORGEJO_URL}/{DEPLOY.FORGEJO_OWNER}/hermes-skills/commit/{head}")
    print(msg)
    skills_sync.notify(msg)

    if not a.no_lint and not a.apply:
        subprocess.run(["bash", str(ROOT / "ops" / "vault-lint.sh")])
    return 1 if regressed else 0


if __name__ == "__main__":
    sys.exit(main())

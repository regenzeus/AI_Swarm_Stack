"""Skills -> git: mirror Hermes's skills folder into the hermes-skills repo, tag capabilities, park risky skills.

Runs every 5 min (systemd user timer); needs no secrets. Every change becomes one commit in
forgejo:regenzeus/hermes-skills, so a learned skill is a reviewable diff and `git revert` undoes it.

Capability tags come from Hermes's own skill scanner (tools/skills_guard.py): execution/persistence/privilege
-> cap:shell, destructive/traversal -> cap:fs-write, network/exfiltration -> cap:net. An agent-written skill
with any cap tag is parked (archived, so it is not loaded) until the owner approves it once:
    make skill-approve NAME=<skill>
Dangerous skills never get this far: skills.guard_agent_created blocks them when the agent writes them.
"""
import hashlib, io, json, subprocess, sys, tarfile, tempfile, time
from pathlib import Path
from textcap import cut                    # visible caps and input limits (AGENTS.md, truncation)
import textcap as TC

C = "aistack-hermes-1"
REPO = Path.home() / "hermes-skills"
STATE = Path("/srv/ai/state"); APPROVED = STATE / "skills-approved.json"; LOG = STATE / "approvals.jsonl"
EXCLUDE = {".usage.json", ".usage.json.lock", ".curator_state", ".curator_backups"}
CAPS = {"execution": "cap:shell", "persistence": "cap:shell", "privilege_escalation": "cap:shell",
        "destructive": "cap:fs-write", "traversal": "cap:fs-write",
        "network": "cap:net", "exfiltration": "cap:net"}

SCAN = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, "/opt/hermes")
from tools.skills_guard import scan_skill
out = {}
for p in json.load(sys.stdin):
    r = scan_skill(Path("/opt/data/skills") / p, source="agent-created")
    out[p] = {"verdict": r.verdict, "categories": sorted({f.category for f in r.findings}),
              "findings": [f"{f.severity} {f.category} {f.file}:{f.line}" for f in r.findings][:8]}  # cap: top
print(json.dumps(out))
'''


def run(*cmd, cwd=None, inp=None):
    return subprocess.run(cmd, cwd=cwd, input=inp or "", capture_output=True, text=True)


def hermes(*cmd, inp=None):
    return run("docker", "exec", "-i", "-u", "hermes", C, *cmd, inp=inp)


def notify(text, category="system"):
    import notify as N                            # the one notification path (OBS-16)
    N.send(text, category, by="stack")


def record(**kw):
    with LOG.open("a") as f:
        f.write(json.dumps({"ts": int(time.time()), "kind": "skill", **kw}, ensure_ascii=False) + "\n")


def snapshot(dest: Path):
    """Copy /opt/data/skills (minus usage counters) to dest/skills."""
    tar = subprocess.run(["docker", "exec", C, "tar", "-C", "/opt/data", "-cf", "-", "skills"], capture_output=True)
    with tarfile.open(fileobj=io.BytesIO(tar.stdout)) as t:
        t.extractall(dest, filter="data", members=[m for m in t.getmembers()
                                                   if not EXCLUDE & set(Path(m.name).parts)])


def skill_dirs(root: Path):
    """{relative dir: name} for every SKILL.md under root (archived ones included)."""
    return {str(p.parent.relative_to(root)): p.parent.name for p in root.rglob("SKILL.md")}


def digest(d: Path):
    h = hashlib.sha256()
    for f in sorted(d.rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(d)).encode()); h.update(f.read_bytes())
    return h.hexdigest()[:16]


def main(note=()):
    STATE.mkdir(parents=True, exist_ok=True)
    approved = json.loads(APPROVED.read_text()) if APPROVED.exists() else {}
    with tempfile.TemporaryDirectory() as tmp:
        snapshot(Path(tmp))
        new = Path(tmp) / "skills"
        if not (new / ".bundled_manifest").exists():
            sys.exit("skills snapshot failed (is hermes running?)")
        bundled = dict(l.split(":", 1) for l in (new / ".bundled_manifest").read_text().split() if ":" in l)
        run("rsync", "-a", "--delete", "--exclude=.git", f"{new}/", f"{REPO}/skills/")

    dirs = skill_dirs(REPO / "skills")
    status = run("git", "status", "--porcelain", "-uall", "--", "skills", cwd=REPO).stdout.splitlines()
    if not status:
        return
    touched = sorted({d for d in dirs if any(l[3:].startswith(f"skills/{d}/") for l in status)})
    live = [d for d in touched if not d.startswith(".archive")]
    scans = json.loads(hermes("/opt/hermes/.venv/bin/python", "-", inp=SCAN.replace("json.load(sys.stdin)",
                                                                                     repr(live))).stdout or "{}")
    lines, parked = [f"{n} [learned; parked]" for n in note], []
    for d in live:
        name = dirs[d]
        s = scans.get(d, {"verdict": "unknown", "categories": [], "findings": []})
        caps = sorted({CAPS[c] for c in s["categories"] if c in CAPS})
        origin = "bundled-edit" if name in bundled else "learned"
        lines.append(f"{name} [{origin}; {s['verdict']}{'; ' + ' '.join(caps) if caps else ''}]")
        h = digest(REPO / "skills" / d)
        if origin == "learned" and caps and approved.get(name) != h:
            r = hermes("hermes", "curator", "archive", name)
            parked.append(f"{name}; {' '.join(caps)}")
            record(item_id=name, rule=",".join(caps), decision="parked", actor="auto", findings=s["findings"])
            notify(category="approval", text=f"Skill '{name}' needs your OK ({', '.join(caps)}). It is parked and not used until you approve.\n"
                   f"Approve: tell Claude \"approve skill {name}\"  (or: make skill-approve NAME={name})")
            if r.returncode:
                print(f"archive {name} failed: {r.stderr.strip()}")
        elif origin == "learned":
            record(item_id=name, rule="no-caps" if not caps else "approved", decision="kept", actor="auto")
    gone = [l[3:] for l in status if l.startswith(" D")]
    if parked:  # re-mirror so the commit shows the skill under .archive/
        return main(note=parked)
    run("git", "add", "-A", "skills", cwd=REPO)
    msg = "skills: " + ("; ".join(lines) if lines else f"{len(status)} file(s) changed") + \
          ("".join(f"\n- removed {g}" for g in gone[:10]))
    run("git", "commit", "-q", "-m", TC.fit(msg, 3000), cwd=REPO)  # cap: api
    push = run("git", "push", "-q", "origin", "HEAD", cwd=REPO)
    sha = run("git", "rev-parse", "--short", "HEAD", cwd=REPO).stdout.strip()
    print(f"committed {sha}: {msg.splitlines()[0]}" + ("" if push.returncode == 0 else " (push failed)"))
    learned = [l for l in lines if "[learned" in l]
    if learned:
        notify("Hermes learned/changed skills: " + cut("; ".join(learned), 3000, "the full list is in the skills repo") +  # cap: api
               f"\nDiff: http://192.168.1.10:3000/regenzeus/hermes-skills/commit/{sha}")


def approve(name):
    """Restore a parked skill and remember its exact content as approved (any later edit asks again)."""
    r = hermes("hermes", "curator", "restore", name)
    print(r.stdout.strip() or r.stderr.strip())
    main()
    dirs = {n: d for d, n in skill_dirs(REPO / "skills").items() if not d.startswith(".archive")}
    if name not in dirs:
        sys.exit(f"{name} is not active after restore")
    approved = json.loads(APPROVED.read_text()) if APPROVED.exists() else {}
    approved[name] = digest(REPO / "skills" / dirs[name])
    APPROVED.write_text(json.dumps(approved, indent=1))
    record(item_id=name, rule="manual", decision="approved", actor="manual")
    print(f"approved {name} ({approved[name]})")


if __name__ == "__main__":
    approve(sys.argv[2]) if sys.argv[1:2] == ["approve"] else main()

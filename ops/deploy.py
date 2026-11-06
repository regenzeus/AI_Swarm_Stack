"""Deploy a change of ~/ai-stack that is already pulled: rebuild what changed, apply it, then check the stack.
  python3 ops/deploy.py <old-commit> <new-commit>      (run by ops/builds.py with the runner's secrets in the env)
Exit 0 = deployed and healthy; 1 = a step or the checks failed (builds.py then reverts and deploys the revert).
Prints RESTART_RUNNER when the Mission Control runner's own code changed (builds.py restarts it a little later).
What changed -> what happens:
  images/<x>/...            build the image tag that compose/versions.env use for it
  compose/, images          docker compose up -d (recreates only services whose config or image changed)
  config/litellm/           restart LiteLLM          config/hermes/configure*.sh   re-run that profile's configure script
  prompts/<main|mission|builder>.md                  re-run the configure script that writes that SOUL text (SOUL_OF)
  ops/systemd/              install units, daemon-reload, restart changed services/timers
  ops/keys.sh, agents.yaml  swarm identities (swarm_setup.py agents), key models/budgets/grants (update-keys.py), restart Hermes
  ops/missions.py etc.      restart the runner (RESTART_RUNNER)
Then: smoke test (smoke/smoke.sh) and health of Hermes, LiteLLM and Mission Control.
One deploy at a time (PLT-10): every deploy, from the builder or a session, holds ~/.aistack-deploy.lock; a second one
waits up to LOCK_WAIT seconds and then gives up without touching the stack (exit 1). Sessions also hold
~/.aistack-land.lock around merge + deploy; that is a different file, so the two never deadlock.
"""
import fcntl, json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path

R = Path(__file__).resolve().parent.parent
COMPOSE = ["docker", "compose", "--env-file", "versions.env", "-f", "compose/core.yaml", "-f", "compose/apps.yaml"]
LOCK = Path.home() / ".aistack-deploy.lock"
LOCK_WAIT = 2400                      # 40 min: longer than a deploy with image builds; builds.py waits 60 min in total
ok = True
# MEM-11: the configure scripts that write a Hermes SOUL text, which prompts file it comes from, and the variable each
# section is handed in as (by name, so run() never prints the text)
SOUL_OF = {"config/hermes/configure.sh": ("main", {f"SOUL_{r}": f"{r}_RULE" for r in ("WEB", "MISSIONS", "SHOPPING", "LANGUAGE", "PHONE", "CLAUDE")}),
           "config/hermes/configure-mission.sh": ("mission", {"SOUL_TEXT": "SOUL"}),
           "config/hermes/configure-builder.sh": ("builder", {"SOUL_TEXT": "SOUL"})}


def soul(script):
    """(`-e NAME` arguments, env) that hand a configure script its SOUL text from prompts/<owner>.md."""
    owner, names = SOUL_OF.get(script, (None, {}))
    if not owner:
        return [], {}
    sys.path.insert(0, str(R / "ops"))
    import prompts as P
    env = {var: str(P.text(owner, name)) for var, name in names.items()}
    return [a for var in env for a in ("-e", var)], env


def configure_scripts(changed):
    """The configure scripts to re-run: those that changed, and those whose prompts file changed."""
    return [s for s in ["config/hermes/configure.sh", "config/hermes/configure-scout.sh", "config/hermes/configure-curator.sh",
                        "config/hermes/configure-mission.sh", "config/hermes/configure-builder.sh"]
            if s in changed or (s in SOUL_OF and f"prompts/{SOUL_OF[s][0]}.md" in changed)]


def lock(path=LOCK, wait=LOCK_WAIT):
    """The open lock file once this process holds the deploy lock, or None after `wait` seconds."""
    f = open(path, "a")
    deadline, said = time.monotonic() + wait, False
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except BlockingIOError:
            if time.monotonic() >= deadline:
                f.close()
                return None
            if not said:
                print(f"waiting for another deploy ({path})", flush=True)
                said = True
            time.sleep(min(2, wait))


def run(*cmd, timeout=1800, **kw):
    global ok
    print("$", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=R, capture_output=True, text=True, timeout=timeout, **kw)
    tail = (p.stdout + p.stderr).strip().splitlines()[-12:]
    if tail:
        print("  " + "\n  ".join(tail), flush=True)
    if p.returncode:
        ok = False
        print(f"  FAILED (exit {p.returncode})", flush=True)
    return p.returncode == 0


def runner_changed(changed):
    """Whether the runner must restart: any ops/ Python module (it imports most of them, many only through another, like
    crew.py -> observe.py) or obs_core.py, which ops/observe.py loads from the app's folder (FND-49), or its unit."""
    return any((f.startswith("ops/") and f.count("/") == 1 and f.endswith(".py")) or f == "images/mission-control/obs_core.py"
               or f == "ops/systemd/missions.service" for f in changed)


def image_tag(name):
    """The tag compose, versions.env, the Makefile or an ops/ script that runs the image uses (the desk runs from
    ops/desk.sh and the runner, not from compose: FND-46)."""
    files = ["compose/core.yaml", "compose/apps.yaml", "versions.env", "Makefile",
             *sorted(str(p.relative_to(R)) for p in (R / "ops").glob("*.sh")), *sorted(str(p.relative_to(R)) for p in (R / "ops").glob("*.py"))]
    text = "\n".join((R / f).read_text() for f in files)
    m = re.search(rf"aistack/{re.escape(name)}:[A-Za-z0-9._-]+", text)
    return m.group(0) if m else None


def healthy(url, n=100):            # up to 5 min: a recreated Hermes takes a few minutes to answer
    for _ in range(n):
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(3)
    return False


def new_timers(units, dest):
    """The timers this deploy brings for the first time (no copy installed yet): enabled and started after it. A timer the
    owner switched off keeps its state, because its file is already installed."""
    return [Path(f).name for f in units if f.endswith(".timer") and not (Path(dest) / Path(f).name).exists()]


def unit_target(f, dest):
    """Where a file of ops/systemd goes: docker-<name>.conf is a drop-in for Docker (it takes effect at Docker's next start;
    a deploy never restarts Docker), the rest are units."""
    name = Path(f).name
    if name.startswith("docker-") and name.endswith(".conf"):
        return Path(dest) / "docker.service.d" / name.removeprefix("docker-")
    return Path(dest) / name


def swarm_restart(changed):
    """FND-37: the swarm service reads the agent cards when it starts, through a single-file bind mount that keeps the
    file git replaced. A changed config/agents.yaml (an agent change, a new card) needs a restart to reach the agents."""
    return "config/agents.yaml" in changed


def main(old, new):
    global ok
    changed = subprocess.run(["git", "diff", "--name-only", old, new], cwd=R, capture_output=True, text=True).stdout.split()
    print(f"{len(changed)} files changed {old[:8]}..{new[:8]}", flush=True)
    images = sorted({f.split("/")[1] for f in changed if f.startswith("images/") and f.count("/") >= 2})
    for name in images:
        tag = image_tag(name)
        if tag and (R / "images" / name / "Dockerfile").exists():
            args = ["docker", "build", "-q", "-t", tag]
            pins = dict(re.findall(r"^([A-Z_]+_IMAGE)=(\S+)$", (R / "versions.env").read_text(), re.M))
            for arg in re.findall(r"^ARG ([A-Z_]+_IMAGE)\b", (R / "images" / name / "Dockerfile").read_text(), re.M):
                if arg in pins:                          # base images come from versions.env (builder, litellm)
                    args += ["--build-arg", f"{arg}={pins[arg]}"]
            run(*args, f"images/{name}", timeout=3600)
    if images or any(f.startswith(("compose/", "versions.env")) for f in changed):
        run(*COMPOSE, "up", "-d", "--remove-orphans")
    if any(f.startswith("config/litellm/") for f in changed):
        run("docker", "restart", "aistack-litellm-1")
    hermes_restart = False
    for f in configure_scripts(changed):
        args, env = soul(f)
        if f == "config/hermes/configure.sh":
            run("docker", "exec", *args, "-u", "hermes", "aistack-hermes-1", "sh", "/config/configure.sh", env={**os.environ, **env}); hermes_restart = True
        elif f == "config/hermes/configure-scout.sh":
            run("docker", "exec", "-u", "hermes", "aistack-hermes-1", "sh", "/config/configure-scout.sh"); hermes_restart = True
        elif f == "config/hermes/configure-curator.sh":
            run("docker", "exec", "-u", "hermes", "aistack-hermes-1", "sh", "/config/configure-curator.sh"); hermes_restart = True
        elif f == "config/hermes/configure-mission.sh":
            run("docker", "exec", "-e", "LITELLM_MISSION_KEY", *args, "-u", "hermes", "aistack-hermes-1",      # by name: run() prints the command
                "sh", "/config/configure-mission.sh", env={**os.environ, **env, "LITELLM_MISSION_KEY": os.environ.get("VK_MISSION", "")}); hermes_restart = True
        elif f == "config/hermes/configure-builder.sh":
            run("docker", "exec", *args, "aistack-builder-1", "sh", "/config/configure-builder.sh", env={**os.environ, **env})
    if any(f.startswith("config/hermes/plugins/") or f == "config/hermes/install-runtime-plugin.sh" for f in changed):
        for prof in ("", "mission", "scout", "curator"):     # the runtime plugin, every Hermes profile (+ the builder's home)
            run("docker", "exec", "-u", "hermes", "aistack-hermes-1", "sh", "/config/install-runtime-plugin.sh", *([prof] if prof else []))
        run("docker", "exec", "-u", "hermes", "aistack-builder-1", "sh", "/config/install-runtime-plugin.sh")
        hermes_restart = True
    if swarm_restart(changed):
        run("docker", "restart", "aistack-swarm-1")
    if any(f in ("ops/keys.sh", "config/agents.yaml", "ops/swarm_setup.py", "ops/update-keys.py") for f in changed):
        healthy("http://127.0.0.1:4000/health/liveliness")      # a LiteLLM restart above may still be starting
        run("python3", "ops/swarm_setup.py", "agents")            # swarm identities first: a grant of an unknown server is dropped
        run("python3", "ops/update-keys.py")
        hermes_restart = True                                     # Hermes reads its MCP tool list at start
    if hermes_restart:
        run("docker", "restart", "aistack-hermes-1")
        # the dashboard and its gate live in Hermes' network namespace: a restarted Hermes leaves them without network
        run("docker", "restart", "aistack-hermes-dashboard-1", "aistack-gate-hermes-dashboard-1")
    units = [f for f in changed if f.startswith("ops/systemd/") and (R / f).exists()]
    if units:
        dest = Path.home() / ".config/systemd/user"
        fresh = new_timers(units, dest)
        for f in units:
            target = unit_target(f, dest)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text((R / f).read_text())
        run("systemctl", "--user", "daemon-reload")
        for n in fresh:                                           # a new scheduled job runs without a hand step
            run("systemctl", "--user", "enable", "--now", n)
        for f in units:
            n = Path(f).name
            if n != "missions.service" and subprocess.run(["systemctl", "--user", "is-active", "-q", n]).returncode == 0:
                run("systemctl", "--user", "restart", n)
    if runner_changed(changed):
        print("RESTART_RUNNER", flush=True)       # every module the runner may import (builds, cleanup, telemetry, ...)
    if any(f.startswith("ops/windows/") for f in changed):
        print("note: Windows scripts changed; they are copied to C:\\AI\\ops by hand (WSL has no access to Windows)", flush=True)
    # checks: the stack must still be whole. Health first: `compose up` may have just recreated a service, and the
    # smoke test against a gateway that is still starting would fail a good deploy (and trigger a rollback).
    for name, url in (("LiteLLM", "http://127.0.0.1:4000/health/liveliness"), ("Hermes", "http://127.0.0.1:8642/health"),
                      ("Mission Control", "http://127.0.0.1:8090/healthz")):
        h = healthy(url)
        print(f"health {name}: {'ok' if h else 'NOT RESPONDING'}", flush=True)
        ok = ok and h
    run("bash", "smoke/smoke.sh", timeout=900)
    if any(f.startswith(("images/litellm/", "config/litellm/", "versions.env")) for f in changed):
        run("python3", "ops/probe_tool_calls.py", timeout=600)   # the gateway changed: tool calls must keep their arguments
    print("DEPLOY OK" if ok else "DEPLOY FAILED", flush=True)
    record(old, new, ok, len(changed))
    return 0 if ok else 1


def record(old, new, ok, files, path=None):
    """One line per deploy, with where it came from (builder or session; FND-04): /srv/ai/state/deploys.jsonl."""
    path = Path(path or os.environ.get("DEPLOY_RECORD", "/srv/ai/state/deploys.jsonl"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps({"ts": time.time(), "old": old, "new": new, "ok": ok, "files": files,
                                "source": os.environ.get("DEPLOY_SOURCE", "unknown")}) + "\n")
    except OSError as e:
        print(f"deploy record: {e}", flush=True)


if __name__ == "__main__":
    held = lock()
    if not held:
        print(f"DEPLOY FAILED: another deploy held {LOCK} for {LOCK_WAIT} s; nothing was changed", flush=True)
        sys.exit(1)
    sys.exit(main(sys.argv[1], sys.argv[2]))

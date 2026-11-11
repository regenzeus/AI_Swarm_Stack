"""Deploy a change of ~/ai-stack that is already pulled: rebuild what changed, apply it, then check the stack.
  python3 ops/deploy.py <old-commit> <new-commit>      (run by ops/builds.py with the runner's secrets in the env)
Exit 0 = deployed and healthy; 1 = a step or the checks failed (builds.py then reverts and deploys the revert).
Prints RESTART_RUNNER when the Mission Control runner's own code changed (builds.py restarts it a little later).
What changed -> what happens:
  images/<x>/...            build the image tag that compose/versions.env use for it
  compose/, images, deployments/   docker compose up -d (recreates only services whose config or image changed)
  config/litellm/           restart LiteLLM          config/hermes/configure*.sh   re-run that profile's configure script
  prompts/<main|mission|builder|tax>.md              re-run the configure script that writes that SOUL text (SOUL_OF)
  ops/systemd/              install units, daemon-reload, restart changed services/timers; after the checks a good
                            deploy enables its new timers and takes off the dropped units, and a failed deploy or a
                            rollback leaves the diff's timers enabled as it found them (PLT-43)
  ops/keys.sh, agents.yaml  swarm identities (swarm_setup.py agents), key models/budgets/grants (update-keys.py), restart Hermes
  ops/missions.py etc., deployments/   restart the runner (RESTART_RUNNER)
Then: smoke test (smoke/smoke.sh) and health of Hermes, LiteLLM and Mission Control, and last the site's doctor
(python3 ops/deployment.py doctor, PLT-46): a missing or unapproved pack, a workflow no factory owns, a dead runner or a
workflow not imported or published as the deployment says fails the deploy instead of leaving the site half-published.
Before any step: a machine that names no deployment, or switches on a factory it refuses, is refused (PLT-44, PLT-47).
One deploy at a time (PLT-10): every deploy, from the builder or a session, holds ~/.aistack-deploy.lock; a second one
waits up to LOCK_WAIT seconds and then gives up without touching the stack (exit 1). Sessions also hold
~/.aistack-land.lock around merge + deploy; that is a different file, so the two never deadlock.
"""
import fcntl, json, os, re, shutil, subprocess, sys, time, urllib.request
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "ops"))
import deployment as DEPLOY                        # this deployment's file and features (deployments/<name>/deployment.env)
COMPOSE = ["docker", "compose", "--env-file", "versions.env", "--env-file", str(DEPLOY.FILE), "-f", "compose/core.yaml", "-f", "compose/apps.yaml"]
COMPOSE_INPUTS = ("compose/", "versions.env", "deployments/")      # a change in one of them: compose up
LOCK = Path.home() / ".aistack-deploy.lock"
LOCK_WAIT = 2400                      # 40 min: longer than a deploy with image builds; builds.py waits 60 min in total
ok = True
# MEM-11: the configure scripts that write a Hermes SOUL text, which prompts file it comes from, and the variable each
# section is handed in as (by name, so run() never prints the text)
SOUL_OF = {"config/hermes/configure.sh": ("main", {f"SOUL_{r}": f"{r}_RULE" for r in ("WEB", "MISSIONS", "SHOPPING", "LANGUAGE", "PHONE", "CLAUDE")}),
           "config/hermes/configure-mission.sh": ("mission", {"SOUL_TEXT": "SOUL"}),
           "config/hermes/configure-builder.sh": ("builder", {"SOUL_TEXT": "SOUL"}),
           "config/hermes/configure-tax.sh": ("tax", {"SOUL_TEXT": "SOUL"})}


RULE_FEATURE = {"PHONE_RULE": "phone"}      # PHN-28: a rule of a feature that is off goes in empty, so its block is removed


def soul(script, on=None):
    """(`-e NAME` arguments, env) that hand a configure script its SOUL text from prompts/<owner>.md; a rule of a feature
    that is off is handed in empty (GEN-13: the assistant's prompt says nothing of a switched-off AI phone)."""
    owner, names = SOUL_OF.get(script, (None, {}))
    if not owner:
        return [], {}
    sys.path.insert(0, str(R / "ops"))
    import prompts as P
    on = DEPLOY.ON if on is None else on
    env = {var: "" if RULE_FEATURE.get(name, "core") not in on else str(P.text(owner, name)) for var, name in names.items()}
    return [a for var in env for a in ("-e", var)], env


def features_changed(changed):
    """GEN-13: whether this deploy changes the deployment's own file (its FEATURES): its profile and its keys follow."""
    try:
        return str(DEPLOY.FILE.resolve().relative_to(R)) in changed
    except ValueError:                                    # a deployment folder outside the repository changes by hand
        return False


def off_services():
    """GEN-13, PHN-28: the compose services of the features that are off (each names its feature as its profile). A
    container of one left from before the feature went off is stopped and removed: compose up starts only the switched-on
    profiles and leaves the others' containers running."""
    import yaml
    out = []
    for f in ("compose/core.yaml", "compose/apps.yaml"):
        text = (R / f).read_text()
        doc = yaml.safe_load(text.replace("!reset ", "").replace("!override ", ""))
        out += [n for n, s in (doc.get("services") or {}).items() if (s.get("profiles") or ["core"])[0] not in DEPLOY.ON]
    return sorted(out)


def configure_scripts(changed):
    """The configure scripts to re-run: those that changed, those whose prompts file changed, and all of them when the
    agents' keys changed (a new or rotated key reaches its profile only through its script: on 10 Nov 2026 the tax
    desk's new vk-tax landed without reaching the tax profile, and its first run was refused for want of a key)."""
    keys = KEYS_FILE in changed
    feats = features_changed(changed)                      # GEN-13: a feature switched on or off changes main's rules (PHN-28)
    return [s for s in ["config/hermes/configure.sh", "config/hermes/configure-scout.sh", "config/hermes/configure-curator.sh",
                        "config/hermes/configure-mission.sh", "config/hermes/configure-builder.sh", "config/hermes/configure-tax.sh"]
            if keys or s in changed or (s in SOUL_OF and f"prompts/{SOUL_OF[s][0]}.md" in changed) or (feats and s in SOUL_OF and s.endswith("/configure.sh"))]


KEYS_FILE = "secrets/agent-keys.enc.yaml"            # the agents' gateway keys, sops-encrypted; made by `make keys`


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
    try:
        p = subprocess.run(cmd, cwd=R, capture_output=True, text=True, timeout=timeout, **kw)
    except subprocess.TimeoutExpired:                    # review RUN-R28: a failed step like any other, so the deploy is recorded
        ok = False
        print(f"  FAILED (no answer within {timeout} s)", flush=True)
        return False
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
    # review 10 Nov (RUNNER2-R3): ops/domain/ is the runner's too (flows.py alone imports it 21 times), and the runner's
    # own environment (RUNNER2-R2) is rebuilt and then restarted into
    return any((f.startswith("ops/") and f.endswith(".py") and not f.startswith(("ops/windows/", "ops/swarm-probes/")))
               or f in ("images/mission-control/obs_core.py", "ops/systemd/missions.service", "ops/runner-requirements.lock",
                        "ops/runner_env.sh") or f.startswith("deployments/") for f in changed)


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
    return [Path(f).name for f in units if f.endswith(".timer") and not (Path(dest) / Path(f).name).exists()
            and DEPLOY.unit_feature(R / f) in DEPLOY.ON]          # a timer of a feature that is off is not started (GEN-13)


def gone_units(changed, root=R):
    """The files of ops/systemd this deploy removes from the repository."""
    return [f for f in changed if f.startswith("ops/systemd/") and not (Path(root) / f).exists()]


def remove_units(gone, dest, sh=None):
    """A unit the repository no longer has goes from this machine too: stopped and disabled, its installed file and its
    drop-ins deleted (WFL-12: a timer removed from the repository would otherwise fire on). The caller reloads systemd.
    -> the names removed."""
    sh = sh or run
    out = []
    for f in gone:
        target = unit_target(f, dest)
        if not target.exists():
            continue
        if target.parent == Path(dest) and target.suffix in (".timer", ".service"):
            sh("systemctl", "--user", "disable", "--now", target.name)
        target.unlink()
        shutil.rmtree(target.with_name(target.name + ".d"), ignore_errors=True)    # its drop-ins (a schedule the app once set)
        out.append(target.name)
    return out


def enabled_timers():
    """PLT-43: -> the names of the user timers enabled on this machine, or None when systemctl cannot say."""
    try:
        p = subprocess.run(["systemctl", "--user", "list-unit-files", "--type=timer", "--state=enabled", "--no-legend"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode:
        return None
    return {w[0] for w in (ln.split() for ln in p.stdout.splitlines()) if w and w[0].endswith(".timer")}


def rolls_back(old, new, env=os.environ):
    """PLT-43: whether this deploy goes back: its caller says so (DEPLOY_ROLLBACK=1: ops/update.py's `deploy.py <new> <old>`
    after a failed update, also when a site's own commit makes the two diverge), or new is an ancestor of old."""
    return env.get("DEPLOY_ROLLBACK") == "1" or (old != new and subprocess.run(
        ["git", "merge-base", "--is-ancestor", new, old], cwd=R, capture_output=True).returncode == 0)


def put_back_timers(before, touched, dest, sh=None, now=None):
    """PLT-43: the timers of the deploy's diff (touched) enabled again as the deploy found them (before): one it left
    enabled is disabled and stopped, one it found enabled is enabled and started while its unit is installed. Timers
    outside the diff are the owner's and stay as they are. -> the lines the deploy prints."""
    sh = sh or run
    now = enabled_timers() if now is None else now
    if before is None or now is None:
        return ["the enabled timers could not be read (systemctl --user list-unit-files): none put back"]
    out = []
    for n in sorted((now - before) & set(touched)):
        sh("systemctl", "--user", "disable", "--now", n)
        out.append(f"timer {n}: disabled again, as this deploy found it")
    for n in sorted((before - now) & set(touched)):
        if (Path(dest) / n).exists():
            sh("systemctl", "--user", "enable", "--now", n)
            out.append(f"timer {n}: enabled again, as this deploy found it")
        else:
            out.append(f"timer {n}: enabled when this deploy began, but its unit is gone: not enabled")
    return out


def settle_units(back, gone, fresh, before, touched, dest):
    """PLT-43, after the checks. A good deploy and a rollback take the units the repository dropped off this machine
    (WFL-12); only a good deploy that is no rollback enables the timers it brings first (PLT-08). A failed deploy and a
    rollback then leave the timers of the diff enabled as the deploy found them. 10 Nov 2026: a site's rollback
    (`deploy.py <new> <old>` after a failed update) enabled a timer of its diff that the site never had."""
    if ok and not back:
        for n in fresh:                                   # a new scheduled job runs without a hand step
            run("systemctl", "--user", "enable", "--now", n)
    if ok or back:                                        # after the enabling: one that failed keeps the dropped units
        removed = remove_units(gone, dest)
        for n in removed:
            print(f"unit {n} removed: the repository no longer has it", flush=True)
        if removed:
            run("systemctl", "--user", "daemon-reload")
    if back or not ok:
        for line in put_back_timers(before, touched, dest):
            print(line, flush=True)


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


def build_proxy(values=None):
    """PLT-42: the deployment's build proxy (BUILD_HTTP_PROXY, BUILD_NO_PROXY in its deployment.env) as Docker's own proxy
    build arguments -> {name: value}, {} without one. Docker hands these to every RUN of the build and keeps them out of
    the image and its history, so no container ever runs with them; ~/.docker/config.json's proxies would reach every
    container instead."""
    v = DEPLOY.VALUES if values is None else values
    proxy, skip = (str(v.get(k) or "").strip() for k in ("BUILD_HTTP_PROXY", "BUILD_NO_PROXY"))
    if not proxy:
        return {}
    names = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY") + (("no_proxy", "NO_PROXY") if skip else ())
    return {n: (skip if n.lower() == "no_proxy" else proxy) for n in names}


def build_args(name, values=None):
    """The docker build of one image, its base pins from versions.env (builder, litellm, pricewatch), or None. The build
    proxy's arguments are named without their values, which docker takes from build()'s environment: the proxy may carry
    an account, and run() prints the command."""
    tag = image_tag(name)
    if not tag or not (R / "images" / name / "Dockerfile").exists():
        return None
    args = ["docker", "build", "-q", "-t", tag]
    pins = dict(re.findall(r"^([A-Z_]+_IMAGE)=(\S+)$", (R / "versions.env").read_text(), re.M))
    for arg in re.findall(r"^ARG ([A-Z_]+_IMAGE)\b", (R / "images" / name / "Dockerfile").read_text(), re.M):
        if arg in pins:                                  # base images come from versions.env
            args += ["--build-arg", f"{arg}={pins[arg]}"]
    for arg in build_proxy(values):
        args += ["--build-arg", arg]
    return args + [f"images/{name}"]


def build(name):
    """Build one image as a deploy does, with the build proxy -> True when it built, False when it failed, None when the
    image has no tag or no Dockerfile."""
    args = build_args(name)
    return run(*args, timeout=3600, env={**os.environ, **build_proxy()}) if args else None


def build_all(names):
    """A new machine's images (ops/new-machine.sh): in FROM order, each like a deploy builds it. -> 0, or 1 on the first failure."""
    for name in build_order(sorted(names)):
        if build(name) is False:
            print(f"image {name} did not build: stopped (review OPS-R6: a failed build once read as built)", flush=True)
            return 1
    return 0


def build_order(images):
    """An image built FROM another of this deploy comes after it (review IMG-R4: the builder, FROM the Hermes image, was
    built first in alphabetical order, so Docker looked for the new Hermes tag on Docker Hub)."""
    def needs(a, b):
        df = R / "images" / a / "Dockerfile"
        text = df.read_text() if df.exists() else ""
        return f"{b.upper()}_IMAGE" in text or f"aistack/{b}:" in text
    order, left = [], list(images)
    while left:
        ready = [a for a in left if not any(needs(a, b) for b in left if b != a)]
        nxt = (ready or left)[0]                          # a cycle cannot build anyway: as listed
        order.append(nxt)
        left.remove(nxt)
    return order


def pins(rev):
    """The *_IMAGE pins of versions.env at a commit."""
    return dict(re.findall(r"^([A-Z0-9_]+_IMAGE)=(\S+)$", subprocess.run(["git", "show", f"{rev}:versions.env"], cwd=R,
                                                                      capture_output=True, text=True).stdout, re.M))


def moved_pins(changed, old, new):
    """The *_IMAGE pins of versions.env this deploy changes."""
    if "versions.env" not in changed:
        return set()
    before, after = pins(old), pins(new)
    return {k for k in after if before.get(k) != after[k]}


# n8n answers /healthz as soon as its port is open, before its database migrations, before its workflows are active and
# before its start-up recovery; /healthz/readiness answers 200 only after all three (docs/N8N-MIGRATION.md §11).
N8N_READY = "http://127.0.0.1:5678/healthz/readiness"


def n8n_upgrade(changed, old, new):
    """PLT-39: n8n's image changes (N8N_IMAGE). The deploy goes ahead while runs wait in n8n: n8n keeps a waiting
    execution in its database across a new image and its migrations, and resumes it when its answer comes (tested
    2.44.7 -> 2.45.4, 10 Nov 2026). -> the lines the deploy prints, or [] when the image stays."""
    if "N8N_IMAGE" not in moved_pins(changed, old, new):
        return []
    before, after = pins(old).get("N8N_IMAGE", "?"), pins(new).get("N8N_IMAGE", "?")
    return [f"n8n's image changes: {before.split('@')[0]} -> {after.split('@')[0]}; runs that wait in n8n resume on the "
            "new one once it is ready (docs/N8N-MIGRATION.md §11)"]


def pinned_by(changed, old, new):
    """The images whose base pin (an *_IMAGE in versions.env) changed: rebuilt though their own folder did not."""
    moved = moved_pins(changed, old, new)
    if not moved:
        return set()
    return {d.parent.name for d in (R / "images").glob("*/Dockerfile")
            if moved & set(re.findall(r"^ARG ([A-Z_]+_IMAGE)\b", d.read_text(), re.M))}


def main(old, new):
    global ok
    refused = DEPLOY.deploy_refusals()                    # PLT-44, PLT-47: before anything changes
    if refused:
        print("\n".join(f"refused: {x}" for x in refused) + "\nDEPLOY FAILED: nothing was changed", flush=True)
        record(old, new, False, 0)
        return 1
    try:                                                  # SEC-22: the stack's repository keeps its never-in-git hooks, every deploy
        subprocess.run([sys.executable, str(R / "ops/termguard.py"), "install", str(R)], cwd=R, capture_output=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"the never-in-git hooks were not installed: {e}", flush=True)
    if (R / "ops/stack_cli.py").is_file():                # the `stack` command line in ~/.local/bin, every deploy (its doctor: PLT-46)
        try:
            subprocess.run([sys.executable, str(R / "ops/stack_cli.py"), "install"], cwd=R, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"the stack command line was not installed: {e}", flush=True)
    changed = subprocess.run(["git", "diff", "--name-only", old, new], cwd=R, capture_output=True, text=True).stdout.split()
    print(f"{len(changed)} files changed {old[:8]}..{new[:8]}", flush=True)
    before, back = enabled_timers(), rolls_back(old, new)          # PLT-43: what a failed deploy or a rollback leaves enabled
    if back:
        print(f"a rollback to {new[:8]}: it enables no timer and leaves the enabled ones as it found them", flush=True)
    images = sorted({f.split("/")[1] for f in changed if f.startswith("images/") and f.count("/") >= 2} | pinned_by(changed, old, new))
    for name in build_order(images):
        build(name)
    if images or any(f.startswith(COMPOSE_INPUTS) for f in changed):
        run(*COMPOSE, "up", "-d", "--remove-orphans")
        off = off_services()
        if off:                                           # GEN-13: a feature switched off stops its containers (the AI phone, PHN-28)
            run(*COMPOSE, "rm", "--stop", "--force", *off)
    upgrade = n8n_upgrade(changed, old, new)
    if upgrade:                                           # compose up recreated n8n on the new image: it migrates, then starts
        print("\n".join(upgrade), flush=True)
        ready = healthy(N8N_READY, n=200)                 # limit: waits, up to 10 min: a new image migrates n8n's database first
        print(f"n8n on its new image: {'ready' if ready else 'NOT READY'}", flush=True)
        ok = ok and ready
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
        elif f == "config/hermes/configure-tax.sh":                  # TAX-02: the tax desk's reader, ChatGPT only, no tools
            run("docker", "exec", "-e", "LITELLM_TAX_KEY", *args, "-u", "hermes", "aistack-hermes-1",
                "sh", "/config/configure-tax.sh", env={**os.environ, **env, "LITELLM_TAX_KEY": os.environ.get("VK_TAX", "")}); hermes_restart = True
    if any(f.startswith("config/hermes/plugins/") or f == "config/hermes/install-runtime-plugin.sh" for f in changed):
        for prof in ("", "mission", "scout", "curator", "tax"):     # the runtime plugin, every Hermes profile (+ the builder's home)
            run("docker", "exec", "-u", "hermes", "aistack-hermes-1", "sh", "/config/install-runtime-plugin.sh", *([prof] if prof else []))
        run("docker", "exec", "-u", "hermes", "aistack-builder-1", "sh", "/config/install-runtime-plugin.sh")
        hermes_restart = True
    if swarm_restart(changed):
        run("docker", "restart", "aistack-swarm-1")
    if any(f in ("ops/keys.sh", "config/agents.yaml", "ops/swarm_setup.py", "ops/update-keys.py") for f in changed) or features_changed(changed):
        healthy("http://127.0.0.1:4000/health/liveliness")      # a LiteLLM restart above may still be starting
        run("python3", "ops/swarm_setup.py", "agents")            # swarm identities first: a grant of an unknown server is dropped
        run("python3", "ops/update-keys.py")
        hermes_restart = True                                     # Hermes reads its MCP tool list at start
    if hermes_restart:
        run("docker", "restart", "aistack-hermes-1")
        # the dashboard and its gate live in Hermes' network namespace: a restarted Hermes leaves them without network
        run("docker", "restart", "aistack-hermes-dashboard-1", "aistack-gate-hermes-dashboard-1")
    dest = Path.home() / ".config/systemd/user"
    gone = gone_units(changed)                            # taken off after the checks (settle_units), so a failed deploy keeps them
    units = [f for f in changed if f.startswith("ops/systemd/") and (R / f).exists()]
    fresh = new_timers(units, dest)                       # enabled after the checks, by a good deploy only
    if units:
        for f in units:
            target = unit_target(f, dest)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text((R / f).read_text())
        run("systemctl", "--user", "daemon-reload")
        for f in units:
            n = Path(f).name
            if n != "missions.service" and subprocess.run(["systemctl", "--user", "is-active", "-q", n]).returncode == 0:
                run("systemctl", "--user", "restart", n)
    if any(f.startswith(("n8n/workflows/", "compose/", "deployments/")) for f in changed):   # WFL-08, PLT-38: the deployment's workflows into n8n
        healthy(N8N_READY)                                # not /healthz: it answers before the migrations and the workflows
        run("python3", "ops/n8n_sync.py", "import")
    if any(f in ("ops/runner-requirements.lock", "ops/runner_env.sh") for f in changed):
        run("bash", "ops/runner_env.sh", timeout=1800)   # the runner restarts into the environment its lock names (PLT-37); a failure is a failed deploy
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
    if ok:                                                # PLT-46: a site left half-published fails the deploy, loud
        healthy(N8N_READY)                                # an import above restarted n8n
        if not run("python3", "ops/deployment.py", "doctor", timeout=900):   # limit: stops, a doctor that hangs fails the deploy
            print("the doctor named what is wrong: this deploy fails, and its caller reverts it", flush=True)
    settle_units(back, gone, fresh, before, {Path(f).name for f in changed if f.startswith("ops/systemd/") and f.endswith(".timer")}, dest)
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
    if sys.argv[1:2] == ["build"]:                       # python3 ops/deploy.py build <image> ... | all
        sys.exit(build_all([d.parent.name for d in (R / "images").glob("*/Dockerfile")] if sys.argv[2:] in ([], ["all"])
                           else [Path(x).name for x in sys.argv[2:]]))
    held = lock()
    if not held:
        print(f"DEPLOY FAILED: another deploy held {LOCK} for {LOCK_WAIT} s; nothing was changed", flush=True)
        sys.exit(1)
    sys.exit(main(sys.argv[1], sys.argv[2]))

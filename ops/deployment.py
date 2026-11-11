#!/usr/bin/env python3
"""This deployment's hosts, paths, accounts and features, as its deployments/<name>/deployment.env sets them (PLT-33, DEC-45).

    import deployment as DEPLOY; DEPLOY.NAS_HOST     in the host-side Python of ops/; DEPLOY.has("home") for a feature
    python3 ops/deployment.py CODE_DIR               one value (the Makefile)
    eval "$(python3 ops/deployment.py shell)"        every value as a shell variable (the scripts of ops/ and smoke/)
    python3 ops/deployment.py file                   the file compose is given as its second --env-file
    python3 ops/deployment.py need home || exit 0    a script of a feature: says "not configured" and stops when it is off
    python3 ops/deployment.py timers                 the timers of ops/systemd whose feature is on
    python3 ops/deployment.py workflows              the stack's own workflows (n8n/workflows/) it runs (PLT-38)
    python3 ops/deployment.py doctor [--json]        everything that keeps the site from running as its deployment says (PLT-46)
    python3 ops/deployment.py new <name|path>        a new deployment folder: the platform only, with the site's rule (PLT-48)

Which deployment: $AISTACK_DEPLOYMENT, else the first line of ~/.config/aistack/deployment, else platform: a machine that
names none runs the platform only (PLT-44), never home. A name is a folder of deployments/; a path is a folder anywhere
(a real work deployment's, kept off the repository). A variable of the same name in the environment wins over the file.
Containers do not import this: compose reads the same file."""
import json
import os
import re
import shlex
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Every feature a deployment may switch on (docs/PLATFORM.md §3). core is always on and is not listed in FEATURES.
KNOWN = {
    "builder": "the builder sandbox, OpenCode, the code graph and their package proxies",
    "forgejo-ci": "the Forgejo Actions runner, which needs a runner registration from the deployment's Forgejo (GEN-47)",
    "mission-control": "the app and the Hermes dashboard",
    "memory": "Hindsight, qmd and the memory agent",
    "home": "the NAS (backup, the restore drill, the skills mirror), Home Assistant and the router",
    "phone": "the AI phone service",
    "mail": "the mail connector, the postmaster and the inbox digest",
    "voice": "the NAS voice services",
    "telegram": "messages to Telegram",
    "tailnet": "the tailnet addresses",
    "web": "the scout, the page reader, the browser, the price watch and the Topic Desk",
    "publish": "the public GitHub snapshot",
    "offsite": "the off-site copy to OneDrive",
    "windows-desk": "the Windows desk (DEC-43)",
    "windows-worker": "the Windows worker (docs/PLATFORM.md §6)",
}


# The factories this repository holds (docs/PLATFORM.md §2): the platform's own upkeep, on at every site, and home, on
# where FEATURES names home and REFUSE does not. Every other factory is a pack the deployment's packs.txt names.
FACTORIES = {"platform": "the platform's own upkeep: on at every site",
             "home": "the household's work: on where FEATURES names home and REFUSE does not"}
DEFAULT = "platform"                        # PLT-44: a machine that names no deployment runs the platform only


def named(env=os.environ, home=None):
    """The deployment this machine names: $AISTACK_DEPLOYMENT, else the first line of ~/.config/aistack/deployment; ""
    when it names none (then it runs the platform only, and a deploy refuses until it names one)."""
    name = str(env.get("AISTACK_DEPLOYMENT") or "").strip()
    if not name:
        f = Path(home or Path.home()) / ".config" / "aistack" / "deployment"
        lines = f.read_text(encoding="utf-8").split() if f.is_file() else []
        name = lines[0] if lines else ""
    return name


def chosen(env=os.environ, home=None):
    """The folder of the deployment this machine runs: the one it names, else the platform only (PLT-44)."""
    name = named(env, home) or DEFAULT
    folder = Path(name).expanduser() if "/" in name else ROOT / "deployments" / name
    if not (folder / "deployment.env").is_file():
        raise SystemExit(f"deployment {name!r}: {folder}/deployment.env does not exist (docs/PLATFORM.md §2)")
    return folder


def load(path=None, env=os.environ):
    """-> {name: value} of the file, in its order. ${NAME} names a line above, else the environment (${HOME}), and
    ${NAME:-word} gives word when both leave it empty, as in a shell and in compose."""
    values = {}

    def sub(m):
        got = values[m.group(1)] if m.group(1) in values else str(env.get(m.group(1)) or "")
        return got or (m.group(2) or "")
    for line in Path(path or FILE).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and not line.startswith("#"):
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":   # a quoted value, as the shell and compose read it
                value = value[1:-1]
            values[name] = env[name] if name in env else re.sub(r"\$\{(\w+)(?::-([^}]*))?\}", sub, value)
    return values


def refused(values=None):
    """PLT-47: the factories the deployment refuses (REFUSE=home in its deployment.env): never switched on there,
    whatever its FEATURES or packs.txt say."""
    v = VALUES if values is None else values
    return {f for f in re.split(r"[\s,]+", str(v.get("REFUSE") or "")) if f}


def features(values):
    """The features a deployment's values switch on, core included; an unknown name stops it, with the known ones. A
    factory the deployment refuses (REFUSE) stays off, whatever FEATURES says (PLT-47)."""
    named = [f for f in re.split(r"[\s,]+", values.get("FEATURES", "")) if f]
    odd = sorted(set(named) - set(KNOWN))
    if odd:
        raise SystemExit(f"FEATURES names {', '.join(odd)}, which no part of the stack is (known: {', '.join(sorted(KNOWN))})")
    return {"core", *named} - refused(values)


def factories(values=None):
    """PLT-44: the factories of this repository that run here: the platform always, home where FEATURES switches it on."""
    v = VALUES if values is None else values
    return {"platform"} | ({"home"} & features(v))


def runs_factory(name, values=None):
    return name in factories(values)


def default_factory(values=None):
    """The factory a workflow made here belongs to (made on the canvas, or a schedule the runner gives): home where home
    runs, else the platform."""
    return "home" if runs_factory("home", values) else "platform"


def factory_of(wf):
    """The factory a workflow of n8n/workflows/ names ("factory": platform or home), or "" when it names none."""
    return str(wf.get("factory") or "") if isinstance(wf, dict) else ""


def owned(wf, values=None):
    """Whether a workflow file's factory runs here; a file that names no factory runs nowhere (the doctor names it)."""
    return runs_factory(factory_of(wf), values)


def unit_feature(path):
    """The feature a unit of ops/systemd belongs to, from its "# feature: <name>" line; core without one."""
    m = re.search(r"^# feature: ([a-z-]+)\s*$", Path(path).read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "core"


def unit_feature_of(unit, root=None):
    """The feature of a unit by its name (crew-phone-check: its .service, else its .timer); core when ops/systemd has none."""
    for suffix in (".service", ".timer"):
        p = Path(root or ROOT) / "ops" / "systemd" / f"{unit}{suffix}"
        if p.is_file():
            return unit_feature(p)
    return "core"


def workflow_feature(wf):
    """The feature a workflow file belongs to: its "feature" (n8n/workflows/*.json; ops/n8n_gen.py writes the feature of
    the crew job it runs), core without one. wf is the file's JSON or its path."""
    if not isinstance(wf, dict):
        try:
            wf = json.loads(Path(wf).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "core"
    return str(wf.get("feature") or "core")


NAMED = named()                             # "" when this machine names no deployment (PLT-44)
FOLDER = chosen()
FILE = FOLDER / "deployment.env"
VALUES = load()
globals().update(VALUES)
ON = features(VALUES)                       # the features switched on, core included (FEATURES is the line of the file)


def has(feature):
    if feature != "core" and feature not in KNOWN:
        raise ValueError(f"no feature {feature!r} (known: {', '.join(sorted(KNOWN))})")
    return feature in ON


def timers(root=ROOT):
    """The timers of ops/systemd whose feature this deployment switches on."""
    return sorted(t.name for t in (root / "ops" / "systemd").glob("*.timer") if unit_feature(t) in ON)


# The values a feature needs when it is on (compose takes them as optional, so a deployment without the feature needs
# none: a work site, 9 Nov 2026, had to write "off.invalid" for every home host). A host ending in .invalid counts as none.
NEEDS = {"home": ("NAS_HOST", "HA_URL", "ROUTER_URL"), "phone": ("PHONE_HOST",), "tailnet": ("PC_TAILNET_HOST",),
         "forgejo-ci": ("FORGEJO_URL",)}           # GEN-47: the runner registers with this Forgejo


def missing(values=None):
    """-> what the switched-on features need and the deployment file leaves empty, one line each."""
    v = VALUES if values is None else values
    on = features(v)
    need = [(f, n) for f, names in NEEDS.items() if f in on for n in names]
    if v.get("FORGE", "forgejo") == "forgejo" and "builder" in on:
        need += [("FORGE=forgejo", "FORGEJO_URL"), ("FORGE=forgejo", "FORGEJO_OWNER")]
    if v.get("FORGE") == "bitbucket-dc":
        need += [("FORGE=bitbucket-dc", "FORGE_URL")]
    empty = lambda x: not str(x or "").strip() or str(x).strip().endswith(".invalid")
    return [f"{n} is empty, and {f} needs it" for f, n in need if empty(v.get(n))]


def gate_problems(values=None):
    """WFL-15, WFL-16: -> what does not fit the deployment's tailnet, one line each. With the tailnet the app's gate is
    Tailscale's login (APP_GATE tailnet, the default); without it the gate is local (the app on this PC only) and n8n's
    editor and webhook addresses are on 127.0.0.1, so nothing of n8n is reached from elsewhere."""
    v = VALUES if values is None else values
    gate = v.get("APP_GATE") or "tailnet"
    if gate not in ("tailnet", "local"):
        return [f"APP_GATE is {gate!r}: tailnet or local"]
    if "tailnet" in features(v):
        return ["APP_GATE is local, and the tailnet is on: the app would take any request on this PC as the owner's"] if gate == "local" else []
    out = [] if gate == "local" else ["APP_GATE is not local, and the tailnet is off: the app would wait for a Tailscale login that never comes"]
    for name in ("N8N_EDITOR_URL", "N8N_WEBHOOK_URL"):
        host = urllib.parse.urlsplit(str(v.get(name) or "")).hostname
        if host not in ("127.0.0.1", "localhost"):
            out.append(f"{name} is not on 127.0.0.1, and the tailnet is off: n8n's addresses stay on this PC")
    return out


def app_name(values=None):
    """The app's name as the owner sees it (APP-61: "AI Stack" unless the deployment names it otherwise)."""
    return str((VALUES if values is None else values).get("APP_NAME") or "").strip() or "AI Stack"


def fill(text, values=None):
    """A file that names values as {{NAME}} -> with the values in it (the app's tools.json; app.js does the same)."""
    return re.sub(r"\{\{(\w+)\}\}", lambda m: (VALUES if values is None else values)[m.group(1)], text)


# ---------- the stack's own workflows (PLT-38) ----------
WORKFLOWS = ROOT / "n8n" / "workflows"
POLLER = "crew-tracker-poll"                 # the tracker poller (WFL-19): comes with the deployment's trackers


def _yaml(path):
    import yaml
    try:
        d = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return {}
    return d if isinstance(d, dict) else {}


def listed_names(folder=None):
    """The names the deployment's files choose, before any is left out: its workflows.yaml's, and with a tracker the
    tracker poller and each home/<name> tracker's item workflow."""
    folder = Path(folder or FOLDER)
    listed = [str(x).strip() for x in _yaml(folder / "workflows.yaml").get("workflows") or [] if str(x).strip()]
    trackers = [t for t in _yaml(folder / "trackers.yaml").get("trackers") or [] if isinstance(t, dict)]
    own = [f"item-{str(t['workflow']).replace('/', '-')}" for t in trackers if str(t.get("workflow") or "").startswith("home/")]
    return list(dict.fromkeys(listed + ([POLLER] if trackers else []) + own))


def _features_of(folder):
    """The features of a deployment folder: this one's ON, another's from its own deployment.env."""
    env = Path(folder) / "deployment.env"
    return features(load(env, env={})) if env.is_file() and Path(folder).resolve() != FOLDER.resolve() else ON


def workflow_names(folder=None):
    """PLT-38: the stack's own workflows the deployment runs, as names of n8n/workflows/ without .json (a name may be a
    pattern, task-* for the tasks the runner gives a schedule here): those its workflows.yaml lists, and, when its
    trackers.yaml lists a tracker, the tracker poller and each tracker's own item workflow (home/<name> ->
    item-home-<name>). A listed workflow of a feature that is off is left out (GEN-13, PHN-28: the AI phone's two crew
    jobs while FEATURES has no phone), so a deploy's import unpublishes it, and it is back once the feature is on again;
    so is one of a factory that does not run here (PLT-44: home's on a site without home, the doctor names it), and a
    pattern takes only the files of the factories that run (runs_workflow, n8n_jobs.workflows). The rest of
    n8n/workflows/ is never imported here."""
    folder = Path(folder or FOLDER)
    on = _features_of(folder)
    mine = {"platform"} | ({"home"} & on)

    def keep(n):
        if any(ch in n for ch in "*?["):
            return True
        try:
            wf = json.loads((WORKFLOWS / f"{n}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return True                           # a typo (workflow_problems names it) or a file not made yet
        return workflow_feature(wf) in on and factory_of(wf) in mine
    return [n for n in listed_names(folder) if keep(n)]


def runs_workflow(file, names=None, values=None, repo=None):
    """Whether the deployment runs the stack's workflow file (a file of n8n/workflows/, by its name): its lists choose
    it (PLT-38) and its factory runs here (PLT-44: home's workflows never run on a site without home). A name the
    repository has no file for yet is the lists' alone."""
    import fnmatch
    stem = Path(file).name.removesuffix(".json")
    if not any(fnmatch.fnmatchcase(stem, n) for n in (workflow_names() if names is None else names)):
        return False
    try:
        wf = json.loads((Path(repo or WORKFLOWS) / f"{stem}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    return owned(wf, values)


def add_workflow(file, folder=None):
    """A workflow made here (a crew job's by ops/n8n_gen.py, one made on the canvas and exported) joins the deployment's
    workflows.yaml, so the next import keeps it. -> True when it was added, False when the list has it already."""
    folder = Path(folder or FOLDER)
    if runs_workflow(file, workflow_names(folder)):
        return False
    p = folder / "workflows.yaml"
    text = p.read_text(encoding="utf-8") if p.is_file() else "workflows:\n"
    p.write_text(text + ("" if text.endswith("\n") else "\n") + f"  - {Path(file).name.removesuffix('.json')}\n", encoding="utf-8")
    return True


def workflow_problems(folder=None, repo=None):
    """-> each name of the deployment's workflows.yaml that matches no file of n8n/workflows/ (a typo runs nothing)."""
    import fnmatch
    stems = [p.stem for p in Path(repo or WORKFLOWS).glob("*.json")]
    listed = _yaml(Path(folder or FOLDER) / "workflows.yaml").get("workflows") or []
    return [f"workflows.yaml names {n}, which n8n/workflows/ does not have" for n in (str(x).strip() for x in listed)
            if n and not any(ch in n for ch in "*?[") and not fnmatch.filter(stems, n)]


# ---------- factories: tags, refusals, packs (PLT-44 to PLT-47) ----------
def tag_problems(repo=None):
    """PLT-45: -> each workflow file of n8n/workflows/ that no factory owns: its "factory" is missing or names none of
    FACTORIES. Such a file runs nowhere; on 11 Nov 2026 untagged home workflows showed on a work site."""
    out = []
    for p in sorted(Path(repo or WORKFLOWS).glob("*.json")):
        try:
            f = factory_of(json.loads(p.read_text(encoding="utf-8")))
        except ValueError:
            out.append(f"{p.name} is not JSON")
            continue
        if f not in FACTORIES:
            out.append(f"{p.name} names no factory (\"factory\": {' or '.join(FACTORIES)}{'; it says ' + repr(f) if f else ''}): it runs nowhere")
    return out


def off_problems(folder=None, values=None, repo=None):
    """PLT-44: -> each workflow the deployment's lists name exactly whose factory does not run here (a pattern such as
    task-* only takes the files of the factories that run)."""
    v = VALUES if values is None else values
    out = []
    for n in listed_names(folder):
        try:
            wf = json.loads((Path(repo or WORKFLOWS) / f"{n}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue                              # a pattern, or a typo (workflow_problems names that)
        f = factory_of(wf)
        if f in FACTORIES and not runs_factory(f, v):
            why = "this deployment refuses it (REFUSE)" if f in refused(v) else f"FEATURES does not switch {f} on"
            out.append(f"the deployment names {n}, a workflow of the factory {f}, and {why}: it does not run here")
    return out


def refusal_problems(values=None):
    """PLT-47: -> a refused factory the deployment switches on anyway, and a refusal of the platform itself."""
    v = VALUES if values is None else values
    on = {f for f in re.split(r"[\s,]+", v.get("FEATURES", "")) if f}
    out = [f"FEATURES switches on {f}, which this deployment refuses (REFUSE): it stays off" for f in sorted(refused(v) & on)]
    if "platform" in refused(v):
        out.append("REFUSE names platform: the platform runs at every site, only a factory can be refused")
    return out


def packs_named(folder=None):
    """The packs the deployment's files need: a tracker's workflow <pack>/<name> (home/ is the stack's own) and a tracker
    of record's records: <pack>."""
    out = set()
    for t in _yaml(Path(folder or FOLDER) / "trackers.yaml").get("trackers") or []:
        if isinstance(t, dict):
            w = str(t.get("workflow") or "")
            if "/" in w and not w.startswith("home/"):
                out.add(w.split("/", 1)[0])
            if t.get("records"):
                out.add(str(t["records"]))
    return sorted(out)


def pack_problems(folder=None, loaded=None, txt=None):
    """PLT-46: -> a pack the deployment needs and does not list (or no packs.txt at all), and each listed pack that does
    not run at its pinned commit: not approved there, refused, or with problems of its own. loaded: packs.load()."""
    from domain import packs as PK
    folder = Path(folder or FOLDER)
    txt = Path(txt or (PK.packs_txt() if folder == FOLDER else folder / "packs.txt"))
    need, listed = packs_named(folder), PK.entries(txt)
    out = []
    if need and not txt.is_file():
        out.append(f"no packs.txt beside the deployment.env, and trackers.yaml names the pack{'s' if len(need) > 1 else ''} "
                   f"{', '.join(need)}: nothing of {'them' if len(need) > 1 else 'it'} runs")
    else:
        out += [f"trackers.yaml names the pack {n}, which packs.txt does not list: nothing of it runs"
                for n in need if n not in {e["name"] for e in listed}]
    if not listed:
        return out
    loaded = PK.load(txt) if loaded is None else loaded
    for p in loaded.get("pending") or []:
        meanwhile = f"commit {p['runs'][:12]} runs meanwhile" if p.get("runs") else "nothing of it runs"
        out.append(f"pack {p['name']}: its pinned commit {p['commit'][:12]} is not approved ({meanwhile}); "
                   f"stack pack approve {p['name']} {p['commit'][:12]} asks for it")
    out += [r["why"] if str(r["why"]).startswith(f"pack {r['name']}") else f"pack {r['name']}: {r['why']}" for r in loaded.get("refused") or []]
    out += [f"pack {p['name']}: {x}" for p in loaded.get("packs") or [] for x in p.get("problems") or []]
    return out


TEMPLATES = ROOT / "n8n" / "templates"            # the platform's standard workflows, from phase B (none yet)


def override_problems(packs=(), templates=TEMPLATES):
    """PLT-46, prepared for phase B: a pack's workflow that overrides a standard workflow says so,
    "overrides": {"template": <name>, "checked": <the template's version it was last checked against>}. -> one line
    each whose template is gone or has a newer version since, with what the template says changed. Until the platform
    ships templates (n8n/templates/<name>.json with its "version" and "changes": {version: words}), nothing overrides."""
    out = []
    for p in packs or ():
        for w in p.get("workflows") or []:
            try:
                o = json.loads(Path(w["path"]).read_text(encoding="utf-8")).get("overrides")
            except (OSError, ValueError, KeyError):
                continue
            if not isinstance(o, dict):
                continue
            name, checked = str(o.get("template") or ""), str(o.get("checked") or "")
            try:
                t = json.loads((Path(templates) / f"{name}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                out.append(f"{w['name']} overrides the standard workflow {name or '(none named)'}, which the platform does not have")
                continue
            now = str(t.get("version") or "")
            if now != checked:
                said = str((t.get("changes") or {}).get(now) or "the template does not say what changed")
                out.append(f"{w['name']} overrides the standard workflow {name}, last checked against version {checked or 'none'}; "
                           f"it is now version {now}: {said}")
    return out


# ---------- the doctor (PLT-46): loud, naming each reason ----------
N8N = "aistack-n8n-1"
CI_RUNNER = "aistack-ci-runner-1"


def _sh(cmd, timeout=120):
    import subprocess
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, f"{type(e).__name__}: {e}"
    return p.returncode, (p.stdout or "") + (p.stderr if p.returncode else "")


def runner_problems(values=None, sh=_sh, now=None, cfg=None):
    """-> (problems, notes) of the site's runners: the stack's runner (missions.service), the CI runner where forgejo-ci
    is on, and each worker place whose status is stale (it writes one every 10 seconds): the wsl-host place when
    places.yaml sets it up, the Windows worker where windows-worker is on (never answered: a note, its setup is the
    owner's), and the runner's own wsl place when a request waits there and its worker does not answer."""
    import time
    from domain import places as PL
    on, now = features(VALUES if values is None else values), now or time.time()
    probs, notes = [], []
    _, state = sh(["systemctl", "--user", "is-active", "missions.service"])
    if state.strip() != "active":
        probs.append(f"the stack's runner (missions.service) is {state.strip() or 'not running'}: no workflow step runs")
    if "forgejo-ci" in on:
        _, state = sh(["docker", "inspect", "-f", "{{.State.Status}}", CI_RUNNER])
        if state.strip() != "running":
            probs.append(f"the CI runner ({CI_RUNNER}, the feature forgejo-ci) is {state.strip().splitlines()[-1] if state.strip() else 'missing'}: CI waits")
    cfg = PL.config() if cfg is None else cfg
    for name in [n for n in ("wsl-host",) if n in cfg] + (["windows"] if "windows-worker" in on else []):
        st = PL.place(name, cfg).last_status()
        if not st:
            (notes if name == "windows" else probs).append(f"the {name} worker has never answered (no status.json)"
                                                           + (": its setup on Windows is the owner's" if name == "windows" else ""))
        elif now - float(st.get("ts") or 0) > PL.ALIVE_S:
            probs.append(f"the {name} worker last answered {int(now - float(st.get('ts') or 0)) // 60} min ago (it answers every 10 s): it is dead or stuck")
    wsl = PL.place("wsl", cfg)
    waiting = [d for d in (wsl.requests.iterdir() if wsl.requests.is_dir() else ()) if d.is_dir() and not (wsl.answers / d.name).exists()]
    if waiting and not wsl.status(now):
        probs.append(f"{len(waiting)} request{'s wait' if len(waiting) > 1 else ' waits'} at the wsl place, and its worker (a thread of the runner) does not answer")
    return probs, notes


def drive_problems(root=Path("/mnt/c")):
    """DEC-43: -> /mnt/c mounted (automount on), or holding what something wrote there from WSL by mistake (it never
    reaches Windows, and the smoke test fails on it), named by its deepest path, owner and time. 11 Nov 2026: empty
    folders there failed a deploy, and nothing said who made them."""
    import datetime as dt
    import pwd
    root = Path(root)
    if os.path.ismount(root):
        return [f"{root} is a mounted Windows drive: automount is on (DEC-43)"]
    try:
        found = list(root.rglob("*"))
    except OSError:
        return []
    if not found:
        return []
    deepest = max(found, key=lambda p: (len(p.parts), str(p)))
    st = deepest.lstat()
    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        owner = str(st.st_uid)
    when = dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
    return [f"{root} holds {deepest} (made by {owner}, {when}), written there from WSL by mistake: it never reaches Windows "
            f"and fails the smoke test; remove {root / deepest.relative_to(root).parts[0]}"]


def n8n_problems(sh=_sh, loaded=None, mine=None, every=None):
    """-> the workflows n8n does not hold as the deployment says: one it runs that is not imported, one published or
    unpublished against its file (or the runner's newer word), one of the repository published though the deployment
    does not run it, and a running pack's workflow not imported or published against its file."""
    import n8n_jobs as NJ
    rc, ids = sh(["docker", "exec", "-u", "node", N8N, "n8n", "list:workflow", "--onlyId"], timeout=300)
    rc2, live = sh(["docker", "exec", "-u", "node", N8N, "n8n", "list:workflow", "--active=true", "--onlyId"], timeout=300)
    if rc or rc2:
        import textcap as TC
        why = TC.tail((ids if rc else live).strip(), 300) or "no answer"          # cap: preview, the end of n8n's reason
        return [f"n8n does not say which workflows it holds ({N8N}: {why}): nothing is known to run"]
    have, live = set(ids.split()), set(live.split())
    mine = NJ.workflows() if mine is None else mine
    want = {wid: (w["file"], bool(w["wf"].get("active"))) for wid, w in mine.items()}
    if loaded:
        import n8n_sync as NS
        want.update({wf["id"]: (name, wf["active"]) for p in loaded.get("packs") or [] for name, (_, wf) in NS._flows(p).items()})
    out = []
    for wid, (name, active) in sorted(want.items(), key=lambda x: x[1][0]):
        if wid not in have:
            out.append(f"{name} is not imported in n8n, and this deployment runs it")
        elif active != (wid in live):
            out.append(f"{name} is {'unpublished' if active else 'published'} in n8n, and the deployment says {'published' if active else 'unpublished'}")
    every = NJ.workflows(NJ.REPO, NJ.MADE, ["*"]) if every is None else every
    out += [f"n8n publishes {w['file']}, which this deployment does not run" for wid, w in sorted(every.items(), key=lambda x: x[1]["file"])
            if wid not in want and wid in live]
    return out


def doctor(values=None, folder=None, live=True, sh=_sh, loaded=None, now=None):
    """PLT-46: everything that keeps the site from running as its deployment says, each reason named. -> {"deployment",
    "ok", "problems", "notes"}; ok only without problems. live=False: the files alone (no n8n, no runners)."""
    v = VALUES if values is None else values
    folder = Path(folder or FOLDER)
    problems, notes = [], []
    if not NAMED and folder == FOLDER:
        notes.append("this machine names no deployment (~/.config/aistack/deployment): it runs the platform only")
    problems += missing(v) + gate_problems(v) + workflow_problems(folder) + refusal_problems(v) + tag_problems() + off_problems(folder, v)
    try:
        from domain import packs as PK
        txt = PK.packs_txt() if folder == FOLDER else folder / "packs.txt"
        loaded = loaded if loaded is not None else (PK.load(txt) if PK.entries(txt) else {"packs": [], "pending": [], "refused": []})
        problems += pack_problems(folder, loaded, txt) + override_problems(loaded["packs"])
    except Exception as e:                       # a pack's repository away, git missing: said, never a pass
        import textcap as TC
        loaded = None
        problems.append(f"the packs could not be read: {type(e).__name__}: {TC.cut(str(e), 300)}")   # cap: preview, the reason
    if live:
        problems += drive_problems() + n8n_problems(sh, loaded)
        p, n = runner_problems(v, sh, now)
        problems += p
        notes += n
    return {"deployment": v.get("DEPLOYMENT") or folder.name, "ok": not problems, "problems": problems, "notes": notes}


def deploy_refusals(values=None):
    """What stops a deploy before it changes anything: a machine that names no deployment (a deploy there would take a
    running site down to the platform only) and a refused factory switched on."""
    out = [] if NAMED else ["this machine names no deployment: write its name into ~/.config/aistack/deployment "
                            "(platform for the platform only); without one nothing is deployed"]
    return out + refusal_problems(values)


# ---------- a new deployment (PLT-48) ----------
RULE = ("**The rule of every site.** All work is a workflow run. People act through Asks; agents start and look at runs "
        "with `stack` (or its MCP tools). A change to a factory is a commit to its pack, approved before it is used. Never "
        "edit files on a site by hand: use `stack`.")


def new(where, root=ROOT):
    """A new deployment's folder from the platform's (the platform only: its features, model policy, data class and
    upkeep workflows), its AGENTS.md opening with the site's rule. A name makes deployments/<name>; a path a folder
    anywhere (a real site's, off the repository). -> the folder. Refuses a folder that holds anything."""
    folder = Path(where).expanduser() if "/" in where else Path(root) / "deployments" / where
    name = folder.name
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", name):
        raise SystemExit(f"a deployment's name is letters, digits and dashes, starting with a letter: not {name!r}")
    if folder.exists() and any(folder.iterdir()):
        raise SystemExit(f"{folder} holds files already: a new deployment starts in an empty folder")
    folder.mkdir(parents=True, exist_ok=True)
    base = Path(root) / "deployments" / DEFAULT
    for f in ("deployment.env", "workflows.yaml", "models.yaml", "data.yaml"):
        text = (base / f).read_text(encoding="utf-8").replace(f"deployments/{DEFAULT}/", f"{name}/")
        if f == "deployment.env":
            text = re.sub(r"^DEPLOYMENT=.*$", f"DEPLOYMENT={name}", text, flags=re.M)
        (folder / f).write_text(text, encoding="utf-8")
    import textwrap
    about = ("It runs the platform only (the app, the engine and the platform's upkeep) until its `FEATURES` switch a "
             "factory on or its `packs.txt` names one. What each file holds: deployments/AGENTS.md in the platform's repository.")
    (folder / "AGENTS.md").write_text(f"# {name}: a deployment of the platform\n\n{textwrap.fill(RULE, 120)}\n\n"
                                      f"{textwrap.fill(about, 120)}\n", encoding="utf-8")
    return folder


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["shell"]:
        print("\n".join(f"{k}={shlex.quote(v)}" for k, v in VALUES.items()))
    elif args == ["file"]:
        print(FILE)
    elif args == ["check"]:                      # make up: a switched-on feature with an empty value stops here, not in compose
        bad = missing() + gate_problems() + workflow_problems() + refusal_problems() + tag_problems() + off_problems()
        print("\n".join(bad) or f"   the deployment {VALUES.get('DEPLOYMENT') or FOLDER.name} has every value its features need")
        sys.exit(1 if bad else 0)
    elif args[:1] == ["doctor"] and set(args[1:]) <= {"--json"}:
        d = doctor()
        if "--json" in args:
            print(json.dumps(d, indent=1))
        else:
            n = len(d["problems"])
            print(f"doctor of the deployment {d['deployment']}: " + (f"{n} problem{'s' if n > 1 else ''}" if n else "nothing wrong"))
            print("\n".join([f"  FAIL  {p}" for p in d["problems"]] + [f"  note  {x}" for x in d["notes"]]))
        sys.exit(0 if d["ok"] else 1)
    elif len(args) == 2 and args[0] == "new":
        print(f"a new deployment in {new(args[1])}: name it in ~/.config/aistack/deployment on its machine")
    elif args == ["timers"]:
        print("\n".join(timers()))
    elif args == ["workflows"]:
        print("\n".join(sorted(p.name for p in WORKFLOWS.glob("*.json") if runs_workflow(p))))
    elif len(args) == 2 and args[0] == "need":
        if args[1] in refused():                 # PLT-47: the generic refusal, naming only the factory and the setting
            print(f"refused: the deployment {VALUES.get('DEPLOYMENT') or FOLDER.name} refuses {args[1]} (REFUSE in its deployment.env)")
            sys.exit(1)
        if not has(args[1]):
            print(f"not configured: the feature {args[1]} is off in the deployment {VALUES.get('DEPLOYMENT') or FOLDER.name}")
            sys.exit(1)
    elif len(args) == 1 and args[0] in VALUES:
        print(VALUES[args[0]])
    else:
        sys.exit(__doc__)

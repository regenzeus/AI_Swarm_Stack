#!/usr/bin/env python3
"""The data guard (GEN-14, DEC-45, docs/PLATFORM.md §5): customer data stays on the machine, by rules in code and by the
network.

    python3 ops/dataguard.py check            the data class fits the features, and a customer deployment has an egress list
    python3 ops/dataguard.py rules <user>     the outbound rule for the stack's user, for iptables-restore (ops/egress-host.sh)
    python3 ops/dataguard.py probe            from this side: every egress host answers, and a host off the list does not

deployments/<name>/data.yaml: class personal (home) or customer, and per repository a class of its own. Customer data
anywhere in a deployment means no feature that sends data out may be on (backup and the mail copy to the NAS, the off-site
copy, publish, the web tools, Telegram, the phone, mail, the tailnet) and the deployment has an egress list: the hosts the
work may reach (deployments/<name>/egress.txt, host or host:port, 443 by default).

Why one rule is enough: the stack runs rootless Docker, so every container's outbound connection is made by the stack's
user's own processes (rootlesskit, slirp4netns) on the host. A rule on the host for that user's outbound traffic covers the
runner, the scripts and every container at once. Home has no egress list, and none of this applies to it."""
import json
import re
import socket
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deployment as DEPLOY  # noqa: E402

CLASSES = ("personal", "customer")
# The features that send data out of the machine, and where to (a customer deployment switches every one off)
OUTBOUND = {"home": "the backup, the mail copy and the skills mirror go to the NAS", "offsite": "the backup goes to OneDrive",
            "publish": "a snapshot goes to GitHub", "web": "searches and page reads go to the web", "telegram": "messages go to Telegram",
            "phone": "the AI phone is driven over the tailnet", "mail": "mail is read from Gmail", "tailnet": "the app is reachable over the tailnet"}
HOST = re.compile(r"^([A-Za-z0-9.-]+\.[A-Za-z]{2,}|\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?$")
# WFL-17: the n8n nodes customer data allows: the logic nodes (triggers: schedule, webhook, manual; wait, if, switch,
# merge, loop, set, no-op, sticky note, execute workflow and its trigger, respond to webhook) and the AI Stack step. No
# node that reaches a system itself (HTTP Request, Code, Jira, Bitbucket, mail): the work reaches systems only through
# the stack's steps. The names are n8n 2.44.7's (n8n export:nodes); the deployment hands them to n8n as NODES_INCLUDE.
N8N_NODES = ("n8n-nodes-base.scheduleTrigger", "n8n-nodes-base.webhook", "n8n-nodes-base.manualTrigger", "n8n-nodes-base.wait",
             "n8n-nodes-base.if", "n8n-nodes-base.switch", "n8n-nodes-base.merge", "n8n-nodes-base.splitInBatches",
             "n8n-nodes-base.set", "n8n-nodes-base.noOp", "n8n-nodes-base.stickyNote", "n8n-nodes-base.executeWorkflow",
             "n8n-nodes-base.executeWorkflowTrigger", "n8n-nodes-base.respondToWebhook", "CUSTOM.aistackStep")
# WFL-18: where n8n keeps its executions (every node's output, an agent step's whole text among them): its database in
# the stack's Postgres (volume pgdata) and its home (volume n8n). They leave the PC only through the backup (feature
# home, ops/backup.sh) and its off-site copy (offsite), both in OUTBOUND, so a customer deployment has them off.
N8N_DATA = {"volumes": ("pgdata", "n8n"), "leaves_by": ("home", "offsite")}
COMPOSE = ("compose/core.yaml", "compose/apps.yaml")
CHAIN = "AISTACK_EGRESS"
PROBE = ("example.org", 443)             # a host no egress list names: it must not answer


def load(folder=None):
    f = Path(folder or DEPLOY.FOLDER) / "data.yaml"
    if not f.is_file():
        raise SystemExit(f"{f} does not exist: every deployment says its data class (docs/PLATFORM.md §5)")
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


def classes(d):
    """The deployment's class and every repository's."""
    return {d.get("class"), *(d.get("repos") or {}).values()}


def customer(d=None, repo=None):
    d = DATA if d is None else d
    if repo and repo in (d.get("repos") or {}):
        return d["repos"][repo] == "customer"
    return d.get("class") == "customer" or (repo is None and "customer" in classes(d))


def egress_hosts(folder=None):
    """-> [(host, port)] of the deployment's egress list, or None when it has none."""
    f = Path(folder or DEPLOY.FOLDER) / "egress.txt"
    if not f.is_file():
        return None
    out = []
    for ln in f.read_text(encoding="utf-8").splitlines():
        ln = ln.split("#", 1)[0].strip()
        if not ln:
            continue
        m = HOST.match(ln)
        if not m:
            raise SystemExit(f"{f}: {ln!r} is no host or host:port")
        out.append((m.group(1), int(m.group(2) or 443)))
    return out


def values_of(folder=None):
    """The deployment's values: this machine's, or those of the folder's deployment.env ({} without one)."""
    if folder is None:
        return DEPLOY.VALUES
    f = Path(folder) / "deployment.env"
    return DEPLOY.load(f, env={}) if f.is_file() else {}


def n8n_nodes(values=None):
    """WFL-17: -> the node types n8n loads in this deployment, a tuple from its N8N_NODES_INCLUDE (n8n's NODES_INCLUDE),
    or None when it loads every node but n8n's excluded ones (home). A pack's workflow with a node off the tuple is to
    be refused. A customer deployment's tuple is checked against N8N_NODES (problems)."""
    raw = str((DEPLOY.VALUES if values is None else values).get("N8N_NODES_INCLUDE") or "").strip()
    if not raw:
        return None
    try:
        got = json.loads(raw)
    except ValueError:
        got = None
    if not (isinstance(got, list) and got and all(isinstance(n, str) for n in got)):
        raise SystemExit(f"N8N_NODES_INCLUDE is no JSON list of node types: {raw!r}")
    return tuple(got)


def stays_local(root=None):
    """WFL-18, GEN-14: -> what in the compose files lets n8n's data or a service's port off the PC; [] when nothing does.
    Every published port is on 127.0.0.1; n8n's database volume and its home are local volumes (no driver, no options);
    n8n sends nothing home (no diagnostics, no version pings)."""
    root = Path(root or DEPLOY.ROOT)
    files = [yaml.safe_load((root / f).read_text(encoding="utf-8")) or {} for f in COMPOSE]
    out = []
    for doc in files:
        for name, svc in sorted((doc.get("services") or {}).items()):
            for port in svc.get("ports") or []:
                if not str(port.get("host_ip") if isinstance(port, dict) else port).startswith("127.0.0.1"):
                    out.append(f"{name} publishes {port}, not on 127.0.0.1 only")
        for vol in N8N_DATA["volumes"]:
            v = (doc.get("volumes") or {}).get(vol, False)
            if v is not False and ({k for k in (v or {})} & {"driver", "driver_opts", "external"}):
                out.append(f"the volume {vol} holds n8n's executions and is not a local volume of this PC")
    n8n = next((doc["services"]["n8n"] for doc in files if "n8n" in (doc.get("services") or {})), None)
    if n8n is None:
        return out + ["no n8n service in the compose files: nothing to check"]
    env = n8n.get("environment") or {}
    for k in ("N8N_DIAGNOSTICS_ENABLED", "N8N_VERSION_NOTIFICATIONS_ENABLED"):
        if str(env.get(k)).lower() != "false":
            out.append(f"n8n's {k} is not false: it sends to n8n's servers")
    return out


def problems(d=None, on=None, folder=None, values=None):
    """-> what is wrong with the data class against the features; [] when it fits."""
    d = DATA if d is None else d
    on = DEPLOY.ON if on is None else on
    out = [f"class {c!r} is none of {', '.join(CLASSES)}" for c in sorted(map(str, classes(d))) if c not in CLASSES]
    if customer(d):
        for f, why in sorted(OUTBOUND.items()):
            if f in on:
                out.append(f"customer data, and the feature {f} is on: {why}. Switch it off in this deployment")
        hosts = egress_hosts(folder)
        if not hosts:
            out.append("customer data and no egress list: deployments/<name>/egress.txt names the hosts the work may reach")
        nodes = n8n_nodes(values_of(folder) if values is None else values)
        if nodes is None:
            out.append("customer data, and n8n loads every node: N8N_NODES_INCLUDE lists its logic nodes (ops/dataguard.py N8N_NODES)")
        else:
            out += [f"customer data, and n8n loads {n}, which is not one of its logic nodes (ops/dataguard.py N8N_NODES)"
                    for n in nodes if n not in N8N_NODES]
        out += [f"customer data: {p}" for p in stays_local()]
    return out


def resolvers(path="/etc/resolv.conf"):
    try:
        return sorted({ln.split()[1] for ln in Path(path).read_text().splitlines() if ln.startswith("nameserver ") and "." in ln.split()[1]})
    except OSError:
        return []


def rules(user, hosts, resolve=None, dns=None, loopback=("127.0.0.0/8",)):
    """iptables-restore lines (filter table, without --flush of anything else): the stack's user may reach loopback, its DNS
    servers, and the egress hosts on their ports; everything else it starts is refused. Names resolve now: a host whose
    addresses change is resolved again when the rule is applied again (ops/egress-host.sh runs it at boot and hourly)."""
    resolve = resolve or (lambda h, p: sorted({a[4][0] for a in socket.getaddrinfo(h, p, socket.AF_INET, socket.SOCK_STREAM)}))
    lines = ["*filter", f":{CHAIN} - [0:0]"]
    lines += [f"-A {CHAIN} -d {lo} -j RETURN" for lo in loopback]
    lines.append(f"-A {CHAIN} -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN")
    for ns in (resolvers() if dns is None else dns):
        lines += [f"-A {CHAIN} -d {ns}/32 -p udp --dport 53 -j RETURN", f"-A {CHAIN} -d {ns}/32 -p tcp --dport 53 -j RETURN"]
    for host, port in hosts:
        try:
            ips = resolve(host, port)
        except OSError:                                  # fails closed: a host that does not resolve gets nothing allowed
            print(f"egress: {host} does not resolve, so nothing is allowed for it", file=sys.stderr)
            ips = []
        for ip in ips:
            lines.append(f"-A {CHAIN} -d {ip}/32 -p tcp --dport {port} -j RETURN")
    lines += [f"-A {CHAIN} -p tcp -j REJECT --reject-with tcp-reset", f"-A {CHAIN} -j REJECT --reject-with icmp-port-unreachable",
              f"-A OUTPUT -m owner --uid-owner {user} -j {CHAIN}", "COMMIT"]
    return lines


def connects(host, port, timeout=5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def status_only(text, by="stack", category="system"):
    """What a message may say when the data class is customer: that something happened, never its content."""
    return f"{by}: a {category} message (its content stays on the PC: customer data class). Open the app to read it."


DATA = load()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["check"]:
        bad = problems()
        print("\n".join(bad) or f"   the data class fits: {DATA.get('class')}, egress list: "
                                f"{'none' if egress_hosts() is None else f'{len(egress_hosts())} hosts'}")
        sys.exit(1 if bad else 0)
    if len(args) == 2 and args[0] == "rules":
        hosts = egress_hosts()
        if hosts is None:
            sys.exit("this deployment has no egress list (deployments/<name>/egress.txt): nothing to enforce")
        print("\n".join(rules(args[1], hosts)))
        sys.exit(0)
    if args == ["probe"]:
        hosts = egress_hosts()
        if hosts is None:
            print("no egress list in this deployment: nothing to probe")
            sys.exit(0)
        bad = [f"{h}:{p} on the list does not answer" for h, p in hosts if not connects(h, p)]
        if connects(*PROBE):
            bad.append(f"{PROBE[0]}:{PROBE[1]} is off the list and answers: the outbound rule is not in place (ops/egress-host.sh)")
        print("\n".join(bad) or f"   egress holds: {len(hosts)} hosts answer, a host off the list does not")
        sys.exit(1 if bad else 0)
    sys.exit(__doc__)

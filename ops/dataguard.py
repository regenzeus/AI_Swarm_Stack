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


def problems(d=None, on=None, folder=None):
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

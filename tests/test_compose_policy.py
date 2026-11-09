"""Every compose file, parsed (review SEC-R7: Semgrep's port rule read only flow-style lists, so nas/forgejo's block list
publishing 3000 and 2222 on every interface passed): ports on loopback, no Docker socket, no host namespaces, no privilege,
NET_ADMIN only on the five sealed images, and each exception named with its reason."""
import glob
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SEALED = {"fetch", "browser", "pricewatch", "phone", "mail"}       # they set their own firewall, then drop every capability
EXCEPTIONS = {                                                       # file, service, what -> why (each one the owner's to change)
    ("nas/forgejo/compose.yaml", "forgejo", "port 3000:3000"): "Forgejo on the NAS serves the LAN; the PC and CI reach it there",
    ("nas/forgejo/compose.yaml", "forgejo", "port 2222:2222"): "Forgejo's ssh on the NAS, for the LAN",
    ("nas/homeassistant/compose.yaml", "homeassistant", "network_mode: host"): "Home Assistant finds devices by broadcast",
}


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode)
                              else loader.construct_mapping(node) if isinstance(node, yaml.MappingNode) else loader.construct_scalar(node))


def findings():
    out = []
    files = sorted(glob.glob(str(ROOT / "compose/*.y*ml")) + glob.glob(str(ROOT / "nas/**/*.y*ml"), recursive=True))
    assert files, "no compose file found: nothing was checked"
    for f in files:
        rel = str(Path(f).relative_to(ROOT))
        for name, svc in ((yaml.load(open(f), Loader=_Loader) or {}).get("services") or {}).items():
            svc = svc or {}
            for p in svc.get("ports") or []:
                if isinstance(p, dict):
                    if str(p.get("host_ip")) != "127.0.0.1":
                        out.append((rel, name, f"port {p.get('host_ip')}:{p.get('published')}"))
                elif not str(p).startswith("127.0.0.1:"):
                    out.append((rel, name, f"port {p}"))
            for v in svc.get("volumes") or []:
                src = v.get("source") if isinstance(v, dict) else str(v).split(":")[0]
                if "docker.sock" in str(src):
                    out.append((rel, name, f"socket {src}"))
            for k in ("network_mode", "pid", "userns_mode", "ipc"):
                if str(svc.get(k) or "").startswith("host"):
                    out.append((rel, name, f"{k}: host"))
            if svc.get("privileged"):
                out.append((rel, name, "privileged"))
            caps = set(svc.get("cap_add") or [])
            if caps and not (caps == {"NET_ADMIN"} and name in SEALED):
                out.append((rel, name, f"cap_add {sorted(caps)}"))
    return out


def test_every_compose_service_stays_on_loopback_without_socket_namespaces_or_privilege():
    found = findings()
    assert [f for f in found if f not in EXCEPTIONS] == [], "a service is exposed or privileged; fix it or name it in EXCEPTIONS with why"
    assert set(EXCEPTIONS) <= set(found), "an exception no compose file needs any more: remove it"

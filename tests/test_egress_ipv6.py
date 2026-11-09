"""The mail and phone firewalls fail closed on IPv6 (review CNX-R13: `ip6tables ... || true` hid a missing IPv6 firewall).
The entrypoints' v6() runs with a stand-in ip6tables that fails, against a container with and without IPv6."""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LO = "00000000000000000000000000000001 01 80 10 80       lo\n"
ETH = "fd000000000000000000000000000002 02 40 00 80     eth0\n"


@pytest.mark.parametrize("image", ["mail", "phone"])
@pytest.mark.parametrize("addrs,starts", [(LO, True), (LO + ETH, False)])
def test_an_ipv6_rule_that_cannot_be_set_stops_a_container_that_has_ipv6(tmp_path, image, addrs, starts):
    text = (ROOT / f"images/{image}/entrypoint.sh").read_text()
    assert not re.search(r"^ip6tables .*\|\| true", text, re.M)
    fn = re.search(r"^v6\(\) \{.*?^\}$", text, re.M | re.S).group(0)
    (tmp_path / "ip6tables").write_text("#!/bin/sh\nexit 3\n")
    (tmp_path / "ip6tables").chmod(0o755)
    (tmp_path / "if_inet6").write_text(addrs)
    r = subprocess.run(["sh", "-c", fn + "\nv6 -A OUTPUT -j REJECT\necho STARTED"], capture_output=True, text=True,
                       env={"PATH": f"{tmp_path}:/usr/bin:/bin", "IF_INET6": str(tmp_path / "if_inet6")})
    assert ("STARTED" in r.stdout) is starts and (r.returncode == 0) is starts
    assert ("no IPv6 beyond loopback" if starts else "not starting") in r.stdout

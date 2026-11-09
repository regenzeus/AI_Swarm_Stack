"""The data guard (GEN-14): customer data and a feature that sends data out never meet, a customer deployment has an
egress list, its outbound rule refuses every host off the list (proven in a sandbox), and messages carry status only."""
import subprocess
from pathlib import Path

import pytest

import dataguard as DG
import deployment as DEPLOY

ROOT = Path(__file__).resolve().parents[1]
HOME, WORK = ROOT / "deployments/home", ROOT / "deployments/example-work"


def on(folder):
    return DEPLOY.features(DEPLOY.load(folder / "deployment.env", env={}))


def test_home_is_personal_with_no_egress_list_and_the_work_example_is_customer_with_one():
    assert DG.problems(DG.load(HOME), on(HOME), HOME) == [] and DG.egress_hosts(HOME) is None
    assert DG.problems(DG.load(WORK), on(WORK), WORK) == [] and DG.customer(DG.load(WORK))
    assert ("llm-gateway.example.com", 443) in DG.egress_hosts(WORK)


def test_customer_data_with_a_feature_that_sends_data_out_is_refused(tmp_path):
    said = "\n".join(DG.problems({"class": "customer"}, {"core", "builder", "web", "home"}, tmp_path))
    assert "the feature web is on" in said and "the feature home is on" in said and "no egress list" in said
    mixed = {"class": "personal", "repos": {"workrepo": "customer"}}           # one customer repository is enough
    assert DG.customer(mixed) and DG.customer(mixed, "workrepo") and not DG.customer(mixed, "click")
    assert any("the feature publish is on" in p for p in DG.problems(mixed, {"core", "publish"}, WORK))
    assert any("is none of personal, customer" in p for p in DG.problems({"class": "secret"}, {"core"}, WORK))


def test_the_outbound_rule_allows_loopback_dns_and_the_list_and_refuses_the_rest():
    lines = DG.rules("1000", [("gw.example.com", 443), ("forge.example.com", 7990)], resolve=lambda h, p: {"gw.example.com": ["10.0.0.5"], "forge.example.com": ["10.0.0.6", "10.0.0.7"]}[h],
                     dns=["10.0.0.53"])
    text = "\n".join(lines)
    assert "-A AISTACK_EGRESS -d 10.0.0.5/32 -p tcp --dport 443 -j RETURN" in text
    assert "-A AISTACK_EGRESS -d 10.0.0.7/32 -p tcp --dport 7990 -j RETURN" in text
    assert "-A AISTACK_EGRESS -d 10.0.0.53/32 -p udp --dport 53 -j RETURN" in text and "-d 127.0.0.0/8 -j RETURN" in text
    assert lines[-3:] == ["-A AISTACK_EGRESS -j REJECT --reject-with icmp-port-unreachable", "-A OUTPUT -m owner --uid-owner 1000 -j AISTACK_EGRESS", "COMMIT"]
    def gone(h, p):
        raise OSError("no such host")
    assert "10.0.0" not in "\n".join(DG.rules("1000", [("gone.example.com", 443)], resolve=gone, dns=[]))    # fails closed


def test_the_rule_holds_in_a_sandbox_namespace():
    p = subprocess.run(["bash", "ops/egress-selftest.sh"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    if p.returncode == 77:
        pytest.skip(p.stdout.strip())                    # the builder sandbox has no iptables; the host runs it (make egress-check)
    assert p.returncode == 0 and "with the rule:    listed open, unlisted refused" in p.stdout, p.stdout + p.stderr


def test_a_message_under_the_customer_class_carries_status_only():
    said = DG.status_only("Build #3 of workrepo: Parameter P_X failed against extract 4.2", by="builder", category="result")
    assert "P_X" not in said and "workrepo" not in said and "customer data class" in said and said.startswith("builder:")

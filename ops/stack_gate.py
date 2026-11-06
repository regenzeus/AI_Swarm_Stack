"""Is the stack up? One answer for the runner and every scheduled job (PLT-28, FND-119).

On 4 Nov a cold start of the PC made containerd miss Docker's 15 seconds three times, systemd gave Docker up, and for three
hours every job and mission that came due failed against a Docker that was not there, each with its own alert. Now a job
asks first: not up means it waits or is skipped (systemd's ExecCondition: exit 1 is "skipped", not "failed").

Up means: stack_ready.py has finished this boot (its restart of Hermes must not hit a run), Docker answers, the services
every job leans on are running and not paused (the backup pauses Hermes), and the gateway is live. The marker lives on
tmpfs, so each boot starts without it; once the PC has been on for SETTLED_S, a missing marker holds nothing back.

  stack_gate.py                       up now? exit 0, or 1 and the reason (jobs that run every few minutes)
  stack_gate.py --wait 1800           wait for it, then exit 0, or 1 and the reason
  stack_gate.py --wait 1800 --slot 15 the same, not before 15 minutes after boot: the jobs the PC slept through
                                      catch up one after the other, not all at once on a stack that has just started
"""
import argparse
import http.client
import json
import os
import socket
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

RUN = Path(f"/run/user/{os.getuid()}")
SOCK = RUN / "docker.sock"
READY = RUN / "aistack-ready"
LITELLM = "http://127.0.0.1:4000/health/liveliness"
NEEDED = ("postgres", "litellm", "swarm", "hermes", "hindsight-db", "mission-control")
SETTLED_S = 1200                                     # on this long: nothing holds back for the marker, alerts are believed
START_WAIT_S = 900                                   # the runner starts anyway after this, and says what is missing


class _Conn(http.client.HTTPConnection):
    def __init__(self, timeout):
        super().__init__("docker", timeout=timeout)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(str(SOCK))


def uptime():
    """Seconds since this boot of WSL."""
    return float(Path("/proc/uptime").read_text().split()[0])


def booted():
    """When this boot began (epoch seconds): what ran before it could not have run while the PC was off."""
    return time.time() - uptime()


def settled():
    """The boot is over: from now on a missing run or a failure means something."""
    return uptime() >= SETTLED_S


def states(timeout=5):
    """{service: state} of the stack's containers from Docker's API; raises OSError when Docker does not answer."""
    q = urllib.parse.urlencode({"all": "1", "filters": json.dumps({"label": ["com.docker.compose.project=aistack"]})})
    c = _Conn(timeout)
    try:
        c.request("GET", f"/containers/json?{q}")
        rows = json.loads(c.getresponse().read().decode())
    except http.client.HTTPException as e:
        raise OSError(str(e)) from e
    finally:
        c.close()
    return {r["Labels"].get("com.docker.compose.service", ""): r["State"] for r in rows}


def gateway(timeout=5):
    """The gateway answers."""
    try:
        with urllib.request.urlopen(LITELLM, timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def why_down():
    """What keeps the stack from being up, in words, or ""."""
    if not READY.exists() and not settled():
        return "the stack is still starting"
    try:
        st = states()
    except (OSError, ValueError):
        return "Docker is not running"
    off = [f"{s} is {st.get(s, 'missing')}" for s in NEEDED if st.get(s) != "running"]
    if off:
        return ", ".join(off)
    return "" if gateway() else "the gateway (LiteLLM) is not answering"


def wait(timeout, stop=None, every=5, sleep=time.sleep):
    """Until the stack is up. -> True, or False after `timeout` seconds (or when `stop`, an Event, is set)."""
    end = time.time() + timeout
    while why_down():
        if time.time() >= end or (stop is not None and stop.is_set()):
            return False
        sleep(every)
    return True


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("--wait", type=int, default=0, help="seconds to wait for the stack")
    a.add_argument("--slot", type=int, default=0, help="not before this many minutes after boot")
    a = a.parse_args(argv)
    t0 = time.time()
    while uptime() < a.slot * 60:
        time.sleep(min(30, a.slot * 60 - uptime()))
    if not wait(a.wait):
        print(f"stack gate: skipped: {why_down()}", flush=True)
        return 1
    if time.time() - t0 > 5:
        print(f"{READY_LINE} after {round(time.time() - t0)} s", flush=True)      # observe.crew_history starts the run's clock here
    return 0


READY_LINE = "stack gate: ready"

if __name__ == "__main__":
    sys.exit(main())

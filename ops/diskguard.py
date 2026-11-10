"""PLT-36: WSL keeps its whole disk in one file on Windows C: (ext4.vhdx). When C: fills, WSL cannot write and stops,
and the stack with it (10 Nov 2026, 03:36: a night of image builds grew the Docker build cache to 52 GB; C: had 0.2 GB
left and the distro would not start again). Every 20 s the runner reads C: free space from the host probe
(ops/windows/host-probe.ps1) and, when it runs low, prunes the Docker build cache (it only makes builds faster; images,
containers and volumes stay) and tells the owner; nearly full, it tells them at once what is left. The space the
cache leaves inside WSL is reused by WSL without growing its disk file, so the guard acts only when C: itself runs low.
  python3 ops/diskguard.py     the reading now and what the guard would do"""
import time

LOW_GB = 10                    # below this free on C:, the build cache goes (20 wiped it every hour: C: sits near 14 GB)
CLEAR_GB = 13                  # above this again, the next low is a new episode (no flapping alerts)
CRIT_GB = 5                    # below this, an urgent alert: WSL is close to stopping
RELIEF_EVERY_S = 3600          # limit: paces, at most one prune an hour (a second prune of an empty cache frees nothing)
ALERT_EVERY_S = 3600           # limit: drops, at most one urgent alert an hour (the reading repeats every 20 s)
PRUNE = (("docker", "builder", "prune", "-af"),   # cap: the whole unused build cache; the next build makes its layers again
         ("docker", "image", "prune", "-f"))      # dangling images only: tagged ones are the rollback

state = {"relief_at": 0.0, "crit_at": 0.0, "episode": False}


def free_gb(host):
    """C: free in GB from the host probe's reading, or None when there is no fresh one."""
    try:
        return float(host["disk_c_free_gb"])
    except (TypeError, KeyError, ValueError):
        return None


def freed(outputs):
    """The "Total reclaimed space" lines Docker printed, joined."""
    return " ".join(ln.strip() for o in outputs for ln in (o or "").splitlines() if ln.strip().startswith("Total"))


def check(host, sh, notify, now=None, st=None):
    """One reading. sh(*cmd, timeout=) runs a command and returns its output; notify(text, category) tells the owner.
    -> what was done: "", "pruned", "critical" or "pruned+critical"."""
    st = state if st is None else st
    now = time.time() if now is None else now
    gb = free_gb(host)
    if gb is None:
        return ""
    if gb > CLEAR_GB:
        st["episode"] = False
        return ""
    if gb >= LOW_GB:
        return ""
    done = []
    if now - st["relief_at"] >= RELIEF_EVERY_S:
        st["relief_at"] = now
        got = freed([sh(*cmd, timeout=600) for cmd in PRUNE])
        done.append("pruned")
        if not st["episode"]:
            st["episode"] = True
            notify(f"Disk C: has {gb:.1f} GB free, and WSL keeps its whole disk there. I pruned the Docker build cache "
                   f"({got or 'it was empty'}); the next build takes longer, nothing else was touched.", "system")
    if gb < CRIT_GB and now - st["crit_at"] >= ALERT_EVERY_S:
        st["crit_at"] = now
        done.append("critical")
        notify(f"⚠️ Disk C: has only {gb:.1f} GB free. When it is full, WSL stops and the whole stack with it. "
               "Free space on C: soon.", "system")
    return "+".join(done)


if __name__ == "__main__":
    import json
    from pathlib import Path
    h = json.loads(Path("/srv/win-exports/.host/host.json").read_text(encoding="utf-8-sig"))
    gb = free_gb(h)
    print(f"C: {gb} GB free; the build cache goes below {LOW_GB} GB, an urgent alert below {CRIT_GB} GB:",
          "would prune" if gb is not None and gb < LOW_GB else "nothing to do")

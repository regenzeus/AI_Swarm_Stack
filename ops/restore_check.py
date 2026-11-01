"""Restore drill, step 3: every SQLite file in the restored volumes opens and passes integrity_check.
Runs inside the Hermes image (it has Python) with the drill volumes mounted read-only under /vol.
  python3 restore_check.py                                  the volumes under /vol
  python3 restore_check.py swarm <restored srv-ai folder>   the swarm's ledger snapshot opens, with its record counted
                                                            (SWM-36); exit 1 when it is missing or broken"""
import pathlib, sqlite3, sys


def volumes(root="/vol"):
    files = [p for p in pathlib.Path(root).rglob("*") if p.suffix in (".db", ".sqlite") and p.is_file()]
    bad = []
    for p in files:
        try:
            con = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)
            if con.execute("pragma integrity_check").fetchone()[0] != "ok":
                bad.append(str(p))
        except sqlite3.Error as e:
            bad.append(f"{p}: {e}")
    print(f"3/4 {len(files)} SQLite files open, integrity problems: {bad or 'none'}")
    for v in sorted(pathlib.Path(root).iterdir()):
        print(f"      {v.name}: {sum(1 for f in v.rglob('*') if f.is_file())} files")
    return not bad and bool(files)


def swarm(root):
    """-> (ok, line) for the swarm snapshot under a restored /srv/ai."""
    snap = pathlib.Path(root) / "swarm" / "swarm.snapshot.db"
    if not snap.is_file():
        return False, f"swarm ledger: no snapshot at {snap}"
    try:
        con = sqlite3.connect(f"file:{snap}?mode=ro&immutable=1", uri=True)
        ok = con.execute("pragma integrity_check").fetchone()[0] == "ok"
        n = {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in ("artifacts", "events", "messages")}
    except sqlite3.Error as e:
        return False, f"swarm ledger: {e}"
    return ok and n["events"] > 0, f"swarm ledger: {n['artifacts']} artifacts, {n['events']} events, {n['messages']} messages" + ("" if ok else ", integrity FAILED")


if __name__ == "__main__":
    if sys.argv[1:2] == ["swarm"]:
        good, line = swarm(sys.argv[2])
        print(f"    {line}")
    else:
        good = volumes()
    sys.exit(0 if good else 1)

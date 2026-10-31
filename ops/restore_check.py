"""Restore drill, step 3: every SQLite file in the restored volumes opens and passes integrity_check.
Runs inside the Hermes image (it has Python) with the drill volumes mounted read-only under /vol."""
import pathlib, sqlite3, sys

files = [p for p in pathlib.Path("/vol").rglob("*") if p.suffix in (".db", ".sqlite") and p.is_file()]
bad = []
for p in files:
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)
        if con.execute("pragma integrity_check").fetchone()[0] != "ok":
            bad.append(str(p))
    except sqlite3.Error as e:
        bad.append(f"{p}: {e}")
print(f"3/4 {len(files)} SQLite files open, integrity problems: {bad or 'none'}")
for v in sorted(pathlib.Path("/vol").iterdir()):
    print(f"      {v.name}: {sum(1 for f in v.rglob('*') if f.is_file())} files")
sys.exit(1 if bad or not files else 0)

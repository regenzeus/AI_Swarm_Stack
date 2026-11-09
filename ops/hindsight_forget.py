"""Remove conversations from long-term memory (Hindsight bank "owner") by text: every stored document whose text
contains one of the given snippets is deleted through the Hindsight API, together with the facts extracted
from it. Used by eval/bench.py after each run, so benchmark questions never become memories.
  python3 ops/hindsight_forget.py "snippet" ["snippet" ...]        prints what it deleted
Hindsight is reachable only on memnet, so the lookup runs in its database container and the delete in Hermes's."""
import json, subprocess, sys

BANK = "owner"


def find(snippets):
    if not snippets:
        return []
    like = " or ".join("original_text ilike '%' || $q$" + s.replace("$q$", "") + "$q$ || '%'" for s in snippets)
    q = f"select id from documents where bank_id = '{BANK}' and ({like})"
    out = subprocess.run(["docker", "exec", "aistack-hindsight-db-1", "psql", "-U", "hindsight", "-d", "hindsight",
                          "-tAc", q], capture_output=True, text=True)
    return [l.strip() for l in out.stdout.splitlines() if l.strip()]


def delete(ids):
    code = ("import json,sys,urllib.request as u\n"
            "n=0\n"
            "for i in json.loads(sys.argv[1]):\n"
            f"  r=u.Request('http://hindsight:8888/v1/default/banks/{BANK}/documents/'+i, method='DELETE')\n"
            "  n+=json.load(u.urlopen(r,timeout=60)).get('memory_units_deleted',0)\n"
            "print(n)")
    out = subprocess.run(["docker", "exec", "aistack-hermes-1", "/opt/hermes/.venv/bin/python", "-c", code,
                          json.dumps(ids)], capture_output=True, text=True)
    return int(out.stdout.strip() or 0) if out.returncode == 0 else -1


def forget(snippets):
    ids = find([s[:80] for s in snippets if s.strip()])  # cap: parse
    return (len(ids), delete(ids)) if ids else (0, 0)


if __name__ == "__main__":
    docs, units = forget(sys.argv[1:])
    print(f"forgot {docs} conversation(s), {units} fact(s)")

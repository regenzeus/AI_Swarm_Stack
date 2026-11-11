#!/usr/bin/env python3
"""APP-85: n8n's login for the app, typed once by the owner (the factory design v3, §4 B).

    make n8n-login        asks for the n8n account's email and password (nothing shows while you type), checks them
                          against n8n on this PC, and stores them in sops by name: N8N_LOGIN_EMAIL, N8N_LOGIN_PASSWORD

The app signs in to n8n with them for the owner's own session (images/mission-control/server.frames.py), so n8n's own
login never shows in the app. Nothing is printed, logged or written in clear: the values go to `sops set` on stdin. A
login n8n refuses is not stored. After storing: the next deploy hands them to the app (or restart Mission Control).
"""
import getpass
import json
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = "secrets/secrets.enc.yaml"
N8N = "http://127.0.0.1:5678"                         # n8n's port on this PC (compose/core.yaml), at its root
CHECK_TIMEOUT_S = 15                                  # limit: stops, n8n that does not answer the check within 15 s: nothing is stored


def accepted(email, password, url=N8N, opener=urllib.request.urlopen):
    """-> (True, "") when n8n takes the login, else (False, why); the password never goes into the why."""
    req = urllib.request.Request(f"{url}/rest/login", data=json.dumps({"emailOrLdapLoginId": email, "password": password}).encode(),
                                 headers={"Content-Type": "application/json", "browser-id": uuid.uuid4().hex}, method="POST")
    try:
        with opener(req, timeout=CHECK_TIMEOUT_S) as r:
            return r.status == 200, "" if r.status == 200 else f"n8n answered {r.status}"
    except urllib.error.HTTPError as e:
        return False, "n8n did not accept this email and password" if e.code in (400, 401, 403) else f"n8n answered {e.code}"
    except (urllib.error.URLError, OSError) as e:
        return False, f"n8n on this PC does not answer ({type(e).__name__}): is the stack up?"


def store(name, value, run=subprocess.run):
    """One secret into the sops file; the value goes on stdin, never on a command line."""
    p = run(["sops", "set", "--value-stdin", SECRETS, f'["{name}"]'], cwd=ROOT, input=json.dumps(value), capture_output=True, text=True)
    if p.returncode:
        raise SystemExit(f"could not store {name} in {SECRETS}: {(p.stderr or '').strip()}")


def main(ask=getpass.getpass, check=accepted, run=subprocess.run, say=print):
    say("n8n's login for the app: the account you sign in to n8n with. Nothing shows while you type.")
    email = ask("Email: ").strip()
    password = ask("Password: ")
    if not email or not password:
        say("Nothing was stored: both are needed.")
        return 1
    ok, why = check(email, password)
    if not ok:
        say(f"Nothing was stored: {why}.")
        return 1
    store("N8N_LOGIN_EMAIL", email, run=run)
    store("N8N_LOGIN_PASSWORD", password, run=run)
    say(f"Stored in {SECRETS} as N8N_LOGIN_EMAIL and N8N_LOGIN_PASSWORD. The next deploy hands them to the app; n8n's canvas then opens without its login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

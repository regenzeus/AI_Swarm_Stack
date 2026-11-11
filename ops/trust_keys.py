#!/usr/bin/env python3
"""The trust boundary's secrets (SEC-25, SEC-26, SEC-27; docs/SECURITY.md): made once, stored in sops, never printed.

    make trust-keys        (= sops exec-env secrets/secrets.enc.yaml 'python3 ops/trust_keys.py')

Each secret the environment lacks is made (32 random bytes, URL-safe) and stored with `sops set` in
secrets/secrets.enc.yaml; one that is there is kept, so it can run twice. The next deploy hands them out:
- AISTACK_STEP_TOKEN: Mission Control's step service (8099) and n8n's AI Stack step node (compose).
- MCP_TOKEN_<SERVER>: each of Mission Control's MCP servers and LiteLLM, which alone sends them (compose, config/litellm).
- N8N_HOOK_TOKEN: the header every n8n webhook asks for (ops/n8n_sync.py writes n8n's credential) and the runner sends.
After a new one: deploy (the services read them at start), then restart the runner (`systemctl --user restart missions`).
"""
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = "secrets/secrets.enc.yaml"
NAMES = ("AISTACK_STEP_TOKEN", "N8N_HOOK_TOKEN", "MCP_TOKEN_MISSIONS", "MCP_TOKEN_CLAUDE", "MCP_TOKEN_HOUSE", "MCP_TOKEN_FILES",
         "MCP_TOKEN_MEMORY", "MCP_TOKEN_MEMORYPUBLIC")


def missing(env=None):
    env = os.environ if env is None else env
    return [n for n in NAMES if not env.get(n)]


def store(name, value, run=subprocess.run):
    """One secret into the sops file; the value goes on stdin, never on a command line."""
    p = run(["sops", "set", "--value-stdin", SECRETS, f'["{name}"]'], cwd=ROOT, input=json.dumps(value), capture_output=True, text=True)
    if p.returncode:
        raise SystemExit(f"could not store {name} in {SECRETS}: {(p.stderr or '').strip()}")


def main(env=None, run=subprocess.run):
    made = missing(env)
    for name in made:
        store(name, secrets.token_urlsafe(32), run=run)
        print(f"made {name} (stored in {SECRETS})")
    kept = [n for n in NAMES if n not in made]
    if kept:
        print(f"kept {', '.join(kept)}")
    if made:
        print("next: a deploy hands them out; then restart the runner (systemctl --user restart missions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

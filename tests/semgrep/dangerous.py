"""Semgrep rule fixture (ops/semgrep_selftest.py): each `ruleid:` line must be flagged, each `ok:` line must not."""
import os, pickle, ssl, subprocess, tempfile
import requests, yaml

# ruleid: subprocess-shell-true
subprocess.run("ls " + name, shell=True)
# ok: subprocess-shell-true
subprocess.run(["ls", name])
# ruleid: os-system
os.system("rm -rf " + path)
# ruleid: python-eval-exec
eval(user_input)
# ruleid: yaml-unsafe-load
yaml.load(text)
# ok: yaml-unsafe-load
yaml.safe_load(text)
# ruleid: pickle-load
pickle.loads(blob)
# ruleid: tls-verify-off
requests.get(url, verify=False)
# ruleid: tls-verify-off
ssl._create_unverified_context()
# ruleid: tempfile-mktemp
tempfile.mktemp()

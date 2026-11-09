# config/: configuration applied to running services

| Path | Applies to | Applied by |
|---|---|---|
| `hermes/` | The Hermes profiles (main, scout, curator, mission) and the builder | `ops/deploy.py` and `make up` run the scripts inside the containers |
| `litellm/` | The model gateway | mounted into the `litellm` container; `make restart` or a deploy reloads it |
| `agents.yaml` | The agent registry: one card per agent (job, harness, model, key, roles, rooms, policies) | checked by `ops/registry.py`; mounted read-only into the `swarm` container |
| `gate/` | The sign-in gates (Caddy) for the Hermes dashboard and the code map | mounted read-only into the gate containers |

Configuration here is **declarative and idempotent**: applying it twice gives the same result, and it is the only
place a setting is made. Don't change a setting by hand in a running container. Change it here and redeploy,
or the next deploy silently reverts it.

A host, path or account the code needs goes into the deployment's `deployment.env` (`deployments/`, DEC-45; home's is
`deployments/home/deployment.env`) and is read from there: `tests/test_deployment.py` fails on the value hard-coded in
running code. A variable of the same name in the environment wins over the file.

No secrets in these files: they reference environment variables (`os.environ/NAME` in LiteLLM, `$NAME` in the
scripts) that sops provides at run time.

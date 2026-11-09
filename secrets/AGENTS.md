# secrets/: do not read, print or edit

sops + age encrypted files: `secrets.enc.yaml` (provider credentials, tokens, passwords) and `agent-keys.enc.yaml`
(the per-agent LiteLLM virtual keys, written by `ops/keys.sh`).

**Agents never open these files**, not even to "check a value". Code receives secrets only as environment variables
(`sops exec-env` in `make` and the systemd units). To add a secret, the owner runs `make secrets-edit`. In your
change, reference the new variable by name and say in the commit message which value the owner needs to add.

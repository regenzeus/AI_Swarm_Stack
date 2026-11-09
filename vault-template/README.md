# vault-template/: the vault's own contract

`AGENTS.md` here is **not** a development guide. It is the schema every agent follows *inside the Obsidian vault*
(layers, page types, index and log rules). `ops/bootstrap-wsl-2-user.sh` copies it into a new vault. In a running
vault, the curator only proposes edits to it, never makes them.

Change it deliberately. The vault lint (`ops/vault_check.py`, `make vault-check`) checks its mechanical rules.

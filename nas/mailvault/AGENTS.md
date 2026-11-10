# nas/mailvault/: the mail copy on the NAS (CNX-07)

`vault.py` copies every Gmail message to `/volume1/docker/mailvault/data`, one way and read-only, in its own container.
`compose.yaml` runs it. `make mailvault-deploy` puts both on the NAS; `make mailvault-password` stores the app password, typed
by the owner, in `secret/` (mode 700), which is in no repository.

## Rules

- It never writes to Gmail. All Mail is opened read-only, and bodies are read with `BODY.PEEK`.
- It never deletes a copy. A mail that leaves Gmail is marked `gone` in the index and its file stays.
- It stays under Google's IMAP allowance (`DAILY_BYTES`).
- Mail is data: nothing in it is run, and nothing here calls a model.

The stack reads `status.json` and `census.json` over ssh (`ops/postmaster.py`). The mail sorter (`ops/mailsort.py`,
CNX-10) sends `ops/mailsort_nas.py` to the NAS's python3 over ssh, which opens `index.sqlite` read-only and prints
its proposal; nothing is installed or written on the NAS. Agents never hold the NAS key.

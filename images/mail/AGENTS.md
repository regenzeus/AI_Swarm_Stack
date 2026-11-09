# images/mail/: the Gmail connector

The first **app connection**: the owner's Gmail for the agents (Hermes main and missions, keys `vk-main`, `vk-mission`), as
MCP tools through LiteLLM (`mcp_servers.mail`): `mail_access`, `mail_search` (Gmail search syntax via `X-GM-RAW`),
`mail_read`, `mail_label`, `mail_archive`, `mail_mark`, `mail_trash`, `mail_untrash`. IMAP over TLS with the Gmail app
password from secrets (`GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, set by `make email-setup`).

Shared folder `/srv/ai/connections` (`/connections` here and in Mission Control): `grants.json` (written by Mission
Control: scope → until, per connection), `status.json` (this service, every 10 min), `log.jsonl` (every action),
`pending/` + `decisions/` (the first Trash batch per trash grant waits for the owner's OK), `batches/` (undo records),
`trash_ok.json`.

## Rules

- These guards are the point; never weaken them: no grant = refuse; Trash only, never `EXPUNGE` or a permanent
  delete; the first Trash batch per grant waits for the owner (15 min, no answer = no); bank, payment, security,
  password-reset and verification-code mails (`PROTECTED`) are never archived or trashed; mail content is returned
  wrapped as untrusted; batches are capped (`MAX_BATCH`).
- This service never sends, forwards or changes filters/settings: those tools must not be added here (sending to
  The owner stays `send_email` in Mission Control).
- The firewall (`entrypoint.sh`) allows IMAPS only. The password is never logged or returned.
- A new app connection gets its own sealed service like this one and its scopes in `SCOPES` (Mission Control
  `server.py`) and `CONN_SCOPES` (`ops/missions.py`).
- Every logged action also goes to the runtime record (`rt_emit`: `runtime/mail-<date>.jsonl`, forwarded by the
  runner). Keep it best-effort: it must never fail or slow an action.

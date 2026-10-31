# config/litellm/: the model gateway

| File | Contents |
|---|---|
| `config.yaml` | models (`gpt-sub`, `gpt-sub-fast` on the ChatGPT subscription), router settings, MCP servers (qmd, fetch, research, missions, graphify, claude, mail, phone, house, browser), callbacks (Phoenix) |
| `chatgpt-models.yaml` | the ChatGPT model block that `ops/enable-chatgpt.py` inserts after `make chatgpt-login` |

Every model call of every agent passes through here, which is what makes per-agent keys, budgets, tool grants and
cost tracking possible. Keys and their grants live in `ops/keys.sh` (applied with `make keys` /
`ops/update-keys.py`), not here.

## Rules

- **Subscription only.** Never add a paid provider or model. This rule keeps the stack at $0.
- No fallbacks to other models. When the subscription pauses (usage limit), callers wait and retry.
- MCP servers are reachable only on internal networks. A new server also needs a grant per key in `ops/keys.sh`,
  a row in the guide's technology chapter, and a Hermes restart.
- Provider credentials only as `os.environ/NAME`.

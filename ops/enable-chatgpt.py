"""Insert the ChatGPT model block into the LiteLLM config (idempotent). Run after the device login."""
p = "config/litellm/config.yaml"
s = open(p).read()
if "chatgpt/" not in s:
    block = "".join(l for l in open("config/litellm/chatgpt-models.yaml") if not l.startswith("# Added"))
    marker = "  # ChatGPT models (gpt-sub, gpt-sub-fast) are added after `make chatgpt-login`; see chatgpt-models.yaml.\n\n"
    s = s.replace(marker, block)
    open(p, "w").write(s)
    print("ChatGPT models enabled")
else:
    print("ChatGPT models already enabled")

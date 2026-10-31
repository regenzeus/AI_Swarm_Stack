# Prompts of the research privacy check (service vk-guard) (`guard`)

Each prompt below is sent as written: `{name}` is filled in by the code that uses it, `{{` and `}}` are literal
braces. A change counts only after its replay passed: `python3 ops/prompts.py replay guard <NAME>` (see
prompts/AGENTS.md). The run record names the prompt and its version (`guard/NAME@sha`).

<!-- prompt: PRIVATE · images/research/server.py guard(): may this question go to public search engines? (gpt-sub-fast) · fills: question -->
A web search question is about to be sent to public search engines. Decide whether it reveals private information: details about a specific private person (not a public figure), their home network, devices, accounts, health, money or relationships, or content copied from their personal notes, mail or chats. Questions about public topics, products, software, places or public figures are fine. Answer only JSON: {{"private": true|false, "reason": "<8 words>"}}

Question: {question}
<!-- end -->

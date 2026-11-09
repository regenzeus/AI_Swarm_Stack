# Approvals before a work deployment

What the owner gets signed off at work before the stack runs there with the company's code or customer data. None of
these can be done by the stack or by its AI: each is a person's decision at the company. The stack's side is to make
each one easy to decide, so each item says what to show and what answer is needed. Design: [PLATFORM.md](PLATFORM.md).

| # | Who decides | The question | Show them | The answer the stack needs |
|---|---|---|---|---|
| 1 | IT security | May this software run on a company PC, in WSL, with the company's source code? | PLATFORM.md §1, §5, §6; docs/SECURITY.md; that it is open source (MIT) and the repository's address | yes / no, and any condition (an approved image, a scan) |
| 2 | IT security | May a separate local Windows account (`aiworker`, standard, not administrator) be created and run a scheduled task that builds code? | PLATFORM.md §6 (the parts, the account's folders, the threat table); ops/windows/worker-setup.ps1 | yes / no; whether a domain policy blocks local accounts or scheduled tasks |
| 3 | IT network | How can the `aiworker` account, and the WSL side, be limited to the repository server, the package mirrors and the model gateway? | PLATFORM.md §5 and the "network" row of §6's threat table; the host list the deployment needs (its egress.txt) | the mechanism (a firewall rule for the local user, the company proxy, a separate network) and who sets it |
| 4 | The model gateway's owners | Does the gateway offer an OpenAI-compatible and an Anthropic-compatible endpoint, which models, and may an automated agent use it with a token? | PLATFORM.md §4; how many tokens a change costs (§8: 0.2 to 1.6 million) | the endpoints, the model names, how a token is issued, any rate or cost limit |
| 5 | The model gateway's owners, or the Claude Code licence holder | May the Claude Code CLI run against the gateway (`ANTHROPIC_BASE_URL`) for the coder role? | PLATFORM.md §4 | yes / no; if no, the coder role uses the gateway's other models |
| 6 | Open-source compliance | Is each third-party part allowed? In particular the AGPL-3.0 and GPL-3.0 programs in `images/repointel` (repowise, CodeLore), run unmodified and never linked | the image list (`images/*/Dockerfile`, `versions.env`, `compose/*.yaml`) | per part: allowed, allowed if not modified, or not allowed (then the `repointel` part stays off) |
| 7 | The data owner (the project or customer contract) | May customer data (configurations, data extracts) be processed by the model gateway at all, and must it stay on the PC otherwise? | PLATFORM.md §5 (the data class `customer` and what it turns off) | yes / no; the data class to set; any folder that must never be read |
| 8 | The repository's owners | May an automated agent open draft pull requests on the repository, and under which account? | PLATFORM.md §7 (drafts only, never a merge) | the service account or the owner's own, and the repository's address |
| 9 | The owner's manager | Is the owner's time on running and checking the stack's work part of the job? | the measured change (§8) once it exists | yes / no |

**When all are answered:** the answers go into `deployments/<work>/` on the work PC (the endpoints, the hosts, the data
class), never into this repository. The first real change waits for 1, 2, 3, 4 and 7.

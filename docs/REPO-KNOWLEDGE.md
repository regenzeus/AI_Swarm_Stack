# What the stack knows about a repository

Written 7 November 2026. The owner: "How do we make a coherent system out of all of this?" We had Understand Anything, Graphify, Serena, a written analysis and a repository wiki, and we add CodeLore and repowise. Measured that day: of 77 coding builds, **none called the code graph**, though every one could.

## The idea

Different tools answer different questions. **They all feed one place per repository, onboarding produces it, the owner reads it on the repo page, and a coding agent gets what its task needs without having to ask.**

| The question | Answered by | How | Costs a model? |
|---|---|---|---|
| How do I run it? | Our profile | Runs its tests once | No |
| What depends on what? | Graphify | Code graph | No |
| Where does it break? What changes together? Who knows it? | **CodeLore** | Git history | No |
| How healthy is it? Dead code, bus factor, test reach? | **repowise** | Index of code and history | No |
| What is in it, for a person? | Understand Anything | Code map, tours | Yes |
| What is it, and should we use it? | Written analysis | Claude, read-only | Yes |
| What did we learn working on it? | Repository wiki | The Scribe, after each change | Yes |

**CodeLore and repowise overlap** on hotspots and ownership. We run both, and the exam decides whether both earn their place. Graphify stays until repowise's graph is shown to replace it.

## Onboarding

```
clone (full history) → graph → facts → map → explain → search → analysis → wiki
```

- **Full history.** Onboarding cloned with `--depth 1`, so each copy held one commit and no history tool could work. It now fetches the whole history.
- **Facts** is the new step: no model, and seconds to minutes. It writes `/srv/ai/code-docs/<name>.facts.json`.
- **The wiki is seeded from the facts too**, so "where it breaks" holds real evidence.
- **They stay current:** facts are rebuilt when a repository's main branch has moved.

## Keeping it safe

Both are third-party programs that read a repository, so:

| Rule | Why |
|---|---|
| A throwaway copy, never our clone | repowise writes `.claude`, editor files and hooks into a repository unless told not to |
| No network, no secrets, read-only tools, dropped capabilities | Their code is not ours, and repowise's telemetry is on by default |
| Pinned versions, with CodeLore's checksum checked at build | So an update is a decision |
| No model features (`--no-prose`) | Prose would need a key and is what Understand Anything already does |
| Run as separate programs, never bundled or imported | repowise is AGPL-3.0 and CodeLore GPL-3.0; the stack is MIT. Worth a proper look before anyone redistributes an image |

CodeLore is young: 5 stars and one owner. If it stops, repowise or `git log` cover most of what we use.

## The repo page

One long page becomes tabs, one question each:

| Tab | Holds |
|---|---|
| **Overview** | State, what waits for you, Request a change, what it is, builds |
| **Map** | The interactive code map and the code graph |
| **History** | Often changed and complex; what changes together; who knows it; how old it is |
| **Health** | repowise's findings: components, dead code, bus factor, test reach |
| **Analysis** | The written analysis |
| **Wiki** | The repository's wiki |

## Getting it to the agents

A tool an agent could call is not knowledge it has: 77 builds and no call. So the knowledge goes **in the brief**, chosen for the task, and the tools stay for follow-up questions.

For each coding step, from the request and the files it names:

1. **Which files:** those the specification names, else the best matches in the code map's digest.
2. **For those files:** how often they change, what changes with them, who depends on them, which tests cover them.
3. **For the repository:** the commands that work, and what failed here before.
4. **From the wiki:** only pages citing those files, not the same 12,000 characters every time.

It stays to a few thousand characters, marked as data, and it says the code wins.

## How we will know

The exam gains an arm with this brief, on `ai-stack` (640 files) and another large repository, measured by score, tokens and fix rounds. If it does not help there, the brief shrinks.

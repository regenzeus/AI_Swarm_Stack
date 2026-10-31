# The public copy

The stack is published at [github.com/regenzeus/AI_Swarm_Stack](https://github.com/regenzeus/AI_Swarm_Stack) as a
**snapshot**: the committed tree, rewritten so that it holds nothing personal, without the private history (every
private commit carries the owner's e-mail). `ops/publish.py` makes it, and nothing is pushed unless it is clean
(SEC-19).

```
make publish-check    # build the snapshot in /srv/ai/publish/tree, scan it, run its tests; pushes nothing
make publish          # the same, then one commit on top of the public history, pushed to GitHub
```

Each publish is the owner's call; nothing publishes by itself. Every run is logged in `/srv/ai/state/publish.jsonl`
(the commit it was made of, the file count, the result).

## What changes in the snapshot

| | In the private repository | In the snapshot |
|---|---|---|
| The owner's identifiers (name, e-mail, PC hostname, tailnet name, NAS user, addresses) | as they are | replaced from the private map, e.g. "the owner", `owner@example.com`, `pc.example.ts.net`, `192.168.1.x`, `/home/owner` |
| `secrets/secrets.enc.yaml`, `secrets/agent-keys.enc.yaml` | sops-encrypted values | left out; `secrets/*.example.yaml` name each value a new install needs, with no value |
| `.sops.yaml` | the owner's age recipient | a placeholder for your own age public key |
| `eval/FROZEN.sha256`, `prompts/replays.json` | hashes of the private texts | hashes of the public texts, which differ only by their placeholders |
| `requirements/REQUIREMENTS.md`, `docs/API.md` | generated | generated again from the public files |
| History | every commit | one snapshot commit per publish, authored by `regenzeus` with GitHub's no-reply address |

## The private files

The identifiers are in no repository. They live in `/srv/ai/private/` (mode 700, inside the nightly backup):

- `publish-map.tsv`: one `term<TAB>replacement` per line, applied in order with exact case. A term that starts or
  ends with a letter or digit matches only as a whole word. A capitalised term at the start of a sentence gets a
  capitalised replacement ("The owner approves"); a lowercase term keeps its case, because code compares it.
- `research-terms.txt`: what the research tool never sends to a web search. `ops/private-terms.sh` adds the vault's
  own projects and writes the list the research container reads; without this file it fails, so the guard keeps its
  last list rather than run without the owner's identifiers.

To keep something new out of the snapshot, add it to the map. The scan already stops a snapshot that still holds a
term from the map in any case, so a missing variant stops the publish instead of leaking.

## The checks before a push

1. **The scan** reads every file and every path of the snapshot and stops on: a term from the map in any case; an
   e-mail address outside the placeholders and test fixtures (`ALLOW_EMAILS`); a LAN address other than
   `192.168.1.x` and `192.168.0.0`; a Tailscale address other than `100.64.0.x`; a tailnet name other than `example`;
   a token pattern (OpenAI, GitHub, Slack, AWS, Google, Telegram) other than the fake ones in tests; a private key, an
   age secret key or recipient; a sops value. It names the file and line, never the private term itself, and a
   stopped snapshot is deleted from disk.
2. **The snapshot's own tests**: the whole suite runs on the rewritten tree in the builder sandbox. A rewrite that
   breaks code (a name the code compares, a hash) fails here, and nothing is pushed.

3. **Nothing dropped**: before the commit, the files git would commit must be exactly the snapshot's (an ignore
   rule once left out the secrets examples).

GitHub's own secret scanning and push protection then check the push once more.

## Setting it up on a new machine

The push uses a deploy key that can write to this one repository and nothing else:

```
ssh-keygen -t ed25519 -N "" -C "ai-stack publish" -f ~/.ssh/id_ed25519_github_publish
```

Add `~/.ssh/id_ed25519_github_publish.pub` on GitHub (the repository's Settings → Deploy keys → Add deploy key, with
"Allow write access"), and this to `~/.ssh/config`:

```
Host github-publish
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_ed25519_github_publish
  IdentitiesOnly yes
```

Then restore `/srv/ai/private/` from the backup, and run `make publish-check`.

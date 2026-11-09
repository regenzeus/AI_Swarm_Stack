# The stack as a platform

Written 8 November 2026. The owner decided: "The AI Swarm Stack shall be a platform to run AI systems like the one we
run in my home. My home stuff is an example deployment." It carries on from [GENERALISATION.md](GENERALISATION.md)
(core, domains, deployments) and makes its parked items real, because a second deployment now exists: a work PC where
the builds need Windows-only tools and customer data may not leave the machine. Decision DEC-45; requirements GEN-04
to GEN-08, GEN-11 and GEN-13 to GEN-16.

## 1. Three layers

| Layer | What it holds | Where |
|---|---|---|
| **Platform** (the core) | the Conductor, the change loop and its judge, memory, the run record, the app's frame, the Windows worker protocol, the egress proxy | `ops/`, `images/`, `compose/` |
| **Domains** | one kind of work: briefings, shopping, the phone, mail, change requests; later a work domain pack | their modules, each switched on by a feature |
| **Deployments** | one installation: its hosts, owner, features, model policy, data class, egress list, constraint values | `deployments/<name>/` |

`deployments/home/` is this house, and is one example among others. `deployments/example-work/` shows a work deployment
with placeholders. A real work deployment's folder lives only on its machine, and nothing of it is committed here.

**The test of the platform:** a deployment with only `core`, `builder` and `mission-control` starts from its folder,
every check is green or *not configured*, and nothing of a switched-off feature runs or is contacted. Home keeps
behaving exactly as before: every step below lands with home's whole check green and no change in what home does.

## 2. The deployment folder

```
deployments/<name>/
  deployment.env    hosts, paths, accounts (today's deployments/home/deployment.env); never a secret
  features.txt      the features switched on, one per line
  models.yaml       the model policy: subscription_only or gateway_only, the aliases each role uses
  data.yaml         the data class (personal | customer) and, per repository, an override
  egress.txt        the hosts the work may reach (the egress proxy's list), one per line
  constraints.yaml  this deployment's values for the constraints that are a deployment's choice (machine, memory, hosts)
```

Which deployment a machine runs is one line in `~/.config/aistack/deployment` (default `home`), outside the
repository, so a pull never switches it. `ops/deployment.py` reads the chosen folder; `deployments/home/deployment.env` stays as
the file compose and the scripts are given, written from the chosen folder by `ops/deployment.py write`, so no script
that reads it today changes.

## 3. Features (A)

A feature is a named part that a deployment switches on. Off means: its compose services are not started (a compose
profile of the same name), its timers are not enabled, its checks say *not configured* (never *failed*), its app pages
are hidden, its hosts are not on the egress list, and its scripts exit with "not configured" before any network call.

| Feature | What it switches |
|---|---|
| `core` | LiteLLM, Postgres, Phoenix, the runner (always on) |
| `builder` | the builder sandbox and its package proxy |
| `mission-control` | the app |
| `memory` | Hindsight, qmd, the memory agent |
| `home` | the NAS (backup, Forgejo on the NAS, the mail copy), Home Assistant, the router |
| `phone` | the AI phone service |
| `mail` | the mail connector and the postmaster |
| `voice` | the NAS voice services |
| `telegram` | messages to Telegram (status only when the data class is customer, F) |
| `tailnet` | the tailnet addresses and `tailscale serve` |
| `web` | the scout, the page reader, the browser, the desk: everything that reads the web |
| `publish` | the public GitHub snapshot |
| `offsite` | the off-site copy to OneDrive |
| `windows-desk` | the Windows desk (DEC-43) |
| `windows-worker` | the Windows worker (D, below) |

Home switches every one on. The minimal step (this change) brings the list, the compose profiles, the timers and the
checks; the app's pages follow the same list.

A feature that is off needs none of its values (GEN-19): compose takes the home's hosts as optional, and
`python3 ops/deployment.py check` (run by `make up`) names the empty value a switched-on feature needs. A host that ends
in `.invalid` counts as none. Other settings a deployment may give in its `deployment.env`:

| Setting | What it does | Default |
|---|---|---|
| `BUILD_REPOS=local` | every repository in the code folder but the stack is one the builder may change, where it is (GEN-18) | `forgejo`: only repositories on Forgejo |
| `FORGE_PUSH` | the push remote of a local repository's change (`{repo}` is its name), e.g. a fork; without it the change stays in Mission Control | none |
| `FORGE_PUSH_PREFIX` | the branch prefix on that remote | `ai/` |
| `OWN_FORGES` | hosts (comma separated) whose repositories are the owner's own work, besides Forgejo and `FORGE_URL` | none |
| `CODEMAP_GATE` | `tailnet` (the viewer needs a Tailscale login) or `local` (loopback only, no login) | `tailnet` |
| `UA_ENRICH_WORKERS` | explanation calls side by side (at most 8) | 1 |
| `UA_JSON_MODE` | `1`: the explanation calls ask the model for a JSON object | off |

## 4. The model policy (B)

`models.yaml` says which kind of model access the deployment allows and what each role's alias resolves to.

- `subscription_only` (home, unchanged): the subscription models, no metered API key anywhere (CST-02).
- `gateway_only` (work): every model through one configured gateway (an OpenAI-compatible and an Anthropic-compatible
  endpoint, a token from a secret file). No subscription model is configured; a request for any other model is refused
  by LiteLLM, because it is not in its list. The Claude CLI roles get `ANTHROPIC_BASE_URL` and a token instead of
  `CLAUDE_CODE_OAUTH_TOKEN`.

Roles name aliases (`fast`, `main`, `coder`, `judge`), never model names; the policy maps them. About thirty prompts are
replay-gated on today's models (MEM-11): a gateway deployment replays them on its own models before it trusts them.

## 5. The data guard and enforced egress (F)

A deployment, or one repository, has a data class: `personal` (home) or `customer`. For customer work:

- no web tool for any role on that work (`web` off for it), no memory or wiki export, no backup or off-site copy of its
  folders, no publish of anything;
- messages to Telegram, the phone or mail carry status only, never content.

These are rules in code, and code can have a hole. So the network enforces the same thing, with one rule:

- **One outbound rule for the stack's user.** The stack runs rootless Docker, so every container's outbound connection is
  made by the stack's user's own processes on the host (rootlesskit, slirp4netns). `ops/egress-host.sh`, run as root,
  gives that user one rule: loopback, its DNS servers and the hosts of `egress.txt` (on their ports) are allowed, and every
  other connection it starts, from the runner, a script or any container, is refused; IPv6 only on loopback. A host that
  does not resolve gets nothing allowed. The rule lives until WSL stops, so a work deployment runs the script from
  `/etc/wsl.conf`'s boot command and hourly (addresses change).
- **The checks.** `ops/dataguard.py check` (in every landing's checks) refuses customer data together with any feature that
  sends data out, and a customer deployment without an egress list. `make egress-check` proves the rule in a sandbox
  (`ops/egress-selftest.sh`: a private network namespace, where a listed address answers and an unlisted one is refused,
  and both answer without the rule, so the proof can fail) and probes the live machine: every egress host answers, a host
  off the list does not.
- **Windows:** the worker's account reaches what Windows lets it reach; limiting it is the company IT's
  (docs/WORK-APPROVALS.md, item 3).

Home has no egress list, so none of this changes home.

## 6. The Windows worker (D)

### What it is for

Some work needs Windows: a Maven build with a company's settings, a vendor toolchain that runs only there, a regression
run of a Windows GUI tool without its window. The stack runs in WSL, which by design cannot start anything on Windows
(interop and automount off, no port open; DEC-43). The worker lets the stack ask Windows to run a **declared job**, and
nothing else.

### The parts and who they run as

```
 WSL (the stack)                         Windows, the owner's account            Windows, account aiworker
 ─────────────────────────────           ───────────────────────────            ───────────────────────────
 ops/winworker.py                        worker-broker.ps1 (logon task)          worker.ps1 (scheduled task)
   writes requests/<id>/  ──────────►    reads them over \\wsl.localhost,       reads C:\AIWorker\inbox\<id>\
     request.json, patch.diff            checks their shape, copies them  ───►    validates against jobs.d +
                                         to C:\AIWorker\inbox\<id>\               approved.json, runs the job
   reads /srv/win-exports/.host/         copies C:\AIWorker\outbox\<id>\  ◄───  writes C:\AIWorker\outbox\<id>\
     worker/<id>/ (read-only)    ◄────   to C:\AI\exports\.host\worker\         claimed.json, progress.jsonl,
                                                                                 result.json, artifacts/
```

Why three parts: a WSL distribution belongs to the Windows user who installed it, and no other Windows account can
read `\\wsl.localhost`. The job must not run as the owner (it would have the owner's files, credentials, shares and
mail), so a broker under the owner's account (`ops/windows/worker-broker.ps1`, its own hidden task beside the desk's)
carries files between WSL and folders the worker account can read. The broker never runs anything from a request: it
checks a request's shape, names, sizes and age, copies it whole into the inbox, mirrors the worker's answers for WSL,
and empties the inbox of a request whose result came back. The worker may only read the inbox, so an answer folder is
what marks a request as taken.

### The worker's account

`aiworker` is a local, standard (not administrator) Windows account made for this alone, created by
`ops/windows/worker-setup.ps1`, which the owner runs once as administrator (`-DryRun` prints every step and changes
nothing). It owns `C:\AIWorker\` and nothing else:

| Folder | Owner may | aiworker may | Holds |
|---|---|---|---|
| `jobs.d\` | write | read | the job definitions |
| `approved.json` | write | read | each approved job kind with the hash of its definition |
| `inbox\` | write (the broker) | read | requests, as the broker copied them |
| `outbox\` | read | write | claims, progress, results, artifacts |
| `repos\` | read | write | the worker's own clones, which jobs copy, never change |
| `scratch\` | read | write | one folder per job, deleted after it |
| `home\` | none | write | the account's own settings (Maven's `settings.xml`, git's) |

The account has no access to the owner's profile (Windows profiles are private to their user), no mapped drives, no
stored credentials of the owner, and no administrator right. What it needs to reach a company's servers (a read token
for the forge, Maven's repository settings) is set up in its own profile, by the owner, from the setup script's notes.

### A job kind

A job kind is a JSON file in `jobs.d\`, written by the owner on Windows. The stack can name a kind; it can never send
one. For example:

```json
{
  "kind": "maven.build",
  "about": "Apply a patch to a clean copy of a repository at a commit, and build it with Maven",
  "params": {
    "repo":   {"type": "name", "from": "repos"},
    "commit": {"type": "hex40"},
    "patch":  {"type": "file", "max_kb": 512},
    "goal":   {"type": "enum", "values": ["package", "verify"]}
  },
  "patch_paths": {"allow": ["src/**"], "deny": ["**/pom.xml", ".mvn/**", "**/*.cmd", "**/*.bat", "**/*.ps1"]},
  "steps": [
    ["git", "clone", "--no-hardlinks", "--quiet", "{repos}\\{repo}", "{scratch}\\src"],
    ["git", "-C", "{scratch}\\src", "checkout", "--quiet", "--detach", "{commit}"],
    ["git", "-C", "{scratch}\\src", "apply", "--check", "{patch}"],
    ["git", "-C", "{scratch}\\src", "apply", "{patch}"],
    ["mvn.cmd", "-B", "-q", "-f", "{scratch}\\src\\pom.xml", "{goal}"]
  ],
  "collect": ["src\\target\\surefire-reports\\*.xml"],
  "minutes": 30,
  "needs_gb": 2,
  "lock": "maven"
}
```

- **Parameters are typed.** `enum` (one of the values), `hex40` (a commit), `int` (with a range), `name` (one of the
  names in a Windows-side list, here the folders of `repos\`), `file` (a file of the request's own folder, of at most
  that size). A value that does not fit refuses the request with which parameter and why.
- **Steps are argument lists, never a command line.** Each value goes in as one argument, after its type check; no
  shell sees it (`cmd.exe` only where a tool is a `.cmd`, and then with values that the types made safe). `{scratch}`,
  `{repos}` and `{patch}` are filled in by the worker, never by the request.
- **A patch's paths are checked before it is applied.** Every path it touches (renames on both sides) must match
  `allow` and none may match `deny`; a binary patch, a symbolic link, a submodule, an absolute path or `..` refuses it.
- **Limits:** the job's minutes (its process tree is stopped past them), the memory Windows must have free before it
  starts, one job at a time per lock (`maven`, a vendor tool).

### Approval: the owner's tap, once per kind

A job kind runs only when `approved.json` holds its name with the SHA-256 of its definition file.
`ops/windows/worker-approve.ps1` shows the definition and writes the hash after the owner says yes. Editing the
definition changes the hash, so the kind stops until it is approved again. The worker account can read the approvals
and cannot change them.

### What crosses, in each direction

| From | To | What | Checked by |
|---|---|---|---|
| the stack | the broker | `request.json` (id, kind, values) and at most one patch file | the broker: the id's shape, the file names, the sizes, the age |
| the broker | the worker | the same files, unchanged | the worker: the kind exists and is approved, every value by its type, the patch's paths |
| the worker | the broker | `claimed.json` (a lease with a heartbeat), `progress.jsonl`, `result.json`, the collected artifacts | the broker: sizes |
| the broker | the stack | the same, into `C:\AI\exports\.host\worker\` (read-only in WSL) | the stack: the shape; build output is untrusted text |

### What a hostile request or a hostile patch can do

| Threat | Result |
|---|---|
| A request names a kind that is not declared or not approved | refused, with the reason |
| A value carries shell syntax, a path or `..` | refused by its type before any step runs |
| A patch changes the build (`pom.xml`, `.mvn`, a script) | refused by the path check |
| A patch changes source or tests that run in the build | **runs**: building code is running it. It runs as `aiworker`: no access to the owner's files or credentials, no administrator, its own scratch folder, a time limit. This is the real boundary, and why the account exists |
| Code in the build tries to reach the network | it can reach what `aiworker` can reach. A company PC should limit that account to its repository server (a firewall rule for a local user, or the company's proxy); `worker-setup.ps1` sets the proxy settings and says that the outbound limit is the company IT's to set (an approval item) |
| Code in the build edits `approved.json` or `jobs.d` | it cannot: the account may only read them |
| The stack floods requests | the broker takes one per kind at a time and drops requests older than an hour; the worker runs one job per lock |
| Build output tries to instruct an agent | output is untrusted text: it reaches agents labelled as such, like web pages |

### Leases and capacity

The worker writes `claimed.json` when it takes a job and refreshes its heartbeat every 10 seconds. A job whose heartbeat
is older than a minute is *lost*; the stack retries it once when its kind says `"retry": true`, and otherwise reports
it. The worker writes `status.json` every 10 seconds: the approved kinds and their hashes, what each lock is doing, the
free memory, and the tool versions each kind's `probe` steps print. The stack schedules against that status: a step
waits while its lock is busy instead of failing.

### In the Conductor

A step kind gains an optional `where`: `wsl` (the default, today's behaviour) or `windows`. A `windows` step goes to the
worker as a job of its kind (`winworker.step_kind`), waits for it, and its answer is the job's result, with the artifacts as evidence. The
coder still edits code in the builder in WSL; only the build or the tool run goes to Windows.

### The fake worker

`ops/fakeworker.py` is the worker's protocol in plain Python over the same folder layout, with the rules of
`ops/winjobs.py`, so the stack's tests and CI never need Windows (`tests/test_winworker.py`). The real worker,
`ops/windows/worker.ps1`, is checked on Windows by `ops/windows/worker-selftest.ps1` against the same cases: a job runs
end to end and brings its evidence back; a value with shell syntax, a patch to a build file or with `..`, an undeclared
kind, a name not on the worker's list and a kind edited after its approval are refused; a job past its limit is stopped.
It passed on the home PC on 8 November 2026, run as the owner (the account separation is the setup's to prove).

## 7. The forge, the judge and updates (C, E, H)

- **Forge (C):** one interface (open a draft pull request, comment, read its state, read CI) with Forgejo as home's
  implementation and Bitbucket Data Center as the second. Whether the stack may merge is a deployment's setting: home
  merges on the owner's tap, as today; a work deployment opens drafts and never merges.
- **Repositories built where they are (GEN-18):** with `BUILD_REPOS=local` the builder changes the repositories in the
  code folder without Forgejo. Their builds clone from and push to a bare copy the stack keeps in
  `/srv/ai/workbench-origins/<repo>.git`, outside the sandbox; the code folder moves that copy's branches by fast-forward
  only. The stack never merges such a change. It reaches the forge only as a draft pull request, pushed to `FORGE_PUSH`
  (a fork's pull request names the fork as its source), and customer code is never copied to Forgejo.
- **Judge (E):** the judge keeps its steps (baseline, flaky re-runs, protected paths, tamper check, acceptance). A
  deployment adds checks for a repository in `deployments/<name>/checks/<repo>.yaml`, set by the owner (a repository's
  profile is a model's writing, and the judge is not the model's to change). Each runs in the sandbox (`wsl`) or as a
  job of the Windows worker (`windows`, with the change's base commit and its diff), and gives
  `{pass, problems[], evidence[]}` (a Windows job may write it as `artifacts/verdict.json`). A failing check reopens
  the change and its problems reach the coder's next prompt; a check that cannot run is no pass.
- **Updates (H):** a work deployment updates only to a release tag the owner signed, never to `main` or a bare commit.
  `make release TAG=vYYYY.MM.DD` (the owner, with their own ssh signing key) signs the public snapshot's newest commit and
  pushes the tag; `make update TAG=...` on the work machine (`ops/update.py`) verifies the signature against the keys in
  its `deployments/<name>/allowed_signers`, runs the whole check on the tag's tree, moves the stack to it and deploys,
  and goes back when the deploy fails. Tonight's landings ran without the privacy scan for hours; a signed tag is the
  point where a person has looked.

## 8. Measuring a change

A measured change runs one real change request twice on the same commit: once by one coder, once by the stack's loop,
and records tests passed, tokens, builds, minutes and memory used, as the click exam does (`ops/replay.py`). On a
metered gateway the tokens are money: on 8 November one coder used 223,000 to 343,000 tokens a case and the stack's
loop 475,000 to 1,600,000, at the same or slightly better result. `make measure-change REPO=<repo> CASE=<n>` runs it on
the deployment it is on (`ops/measure.py`; `python3 ops/measure.py report <repo>` shows every run so far).

## 9. Order

1. The approvals ([WORK-APPROVALS.md](WORK-APPROVALS.md)): none of the work deployment starts before them.
2. Features and the deployment folder (A, G), minimal.
3. The model policy (B).
4. The data guard with enforced egress (F).
5. The Windows worker (D): the fake worker and the protocol tests first, then worker.ps1, the broker and the setup.
6. The measurement harness, run at home on a stand-in repository.
7. The forge (C), the pluggable judge (E), updates from tags (H).

Each lands alone, between exam arms, with home's whole check green.

# ai-stack operations. Secrets are decrypted by sops into the environment of each command only.
SHELL := /bin/bash
SECRETS := secrets/secrets.enc.yaml
KEYS    := secrets/agent-keys.enc.yaml
COMPOSE := docker compose --env-file versions.env -f compose/core.yaml -f compose/apps.yaml $(COMPOSE_EXTRA)
# UP_SERVICES: start only these (new-PC rehearsal); empty = all
# Run a compose command with secrets in its environment: $(call dc,<args>)
dc = sops exec-env $(SECRETS) 'sops exec-env $(KEYS) "$(COMPOSE) $(1)"'

.PHONY: up down ps logs restart keys secrets-edit smoke claude-connect probe-tools req check lock pull-smoke-model chatgpt-login ingest-exports bench bench-gate retrieval curate vault-check skill-approve skills-restore-from-git backup restore-drill restore understand understand-dashboard upgrade-check digest forget hindsight-models desk email-setup wiki-rebuild ua-enrich publish-check publish tasks-gate conductor-gate journeys trial trial-check

up:               ## start core services
	$(call dc,up -d $(UP_SERVICES))

down:             ## stop core services (data kept)
	$(call dc,down)

ps:
	$(call dc,ps)

logs:             ## last 100 lines of every service
	$(call dc,logs --tail 100)

restart:
	$(call dc,up -d --force-recreate $(UP_SERVICES))

secrets-edit:     ## add or change provider keys (opens an editor; values never printed)
	EDITOR=nano sops edit $(SECRETS)

keys:             ## create per-agent LiteLLM virtual keys
	sops exec-env $(SECRETS) 'bash ops/keys.sh'

pull-smoke-model: ## fetch the tiny wiring-test model (Ollama gets internet only for the pull)
	docker network connect aistack_edge aistack-ollama-1
	$(call dc,exec -T ollama ollama pull $(shell grep ^SMOKE_MODEL versions.env | cut -d= -f2)); rc=$$?; docker network disconnect aistack_edge aistack-ollama-1; exit $$rc

chatgpt-login:    ## one-time ChatGPT device-code login, then enable gpt-sub models (you sign in)
	$(call dc,exec litellm python -c "from litellm.llms.chatgpt.authenticator import Authenticator; Authenticator().get_access_token()")
	python3 ops/enable-chatgpt.py
	$(call dc,restart litellm)

smoke:            ## wiring test: every pipe connected, no tokens spent
	sops exec-env $(SECRETS) 'sops exec-env $(KEYS) "bash smoke/smoke.sh"'

claude-connect:   ## one-time: connect the builder's Claude Code engine (you sign in, paste the token; saved encrypted)
	ops/claude-connect.sh

probe-tools:      ## do streamed parallel tool calls keep their arguments through LiteLLM? (a few subscription calls)
	sops exec-env $(KEYS) "python3 ops/probe_tool_calls.py"

req:              ## check the requirements and render requirements/REQUIREMENTS.md (also part of make check)
	python3 ops/req.py render && python3 ops/req.py check

check:            ## every automatic check, exactly as CI runs it (ops/check.sh in the CI runner image; no secrets)
	tar c --exclude=.git --exclude=__pycache__ . | docker run --rm -i --entrypoint sh aistack/ci-runner:13.2.0 -c \
	  'mkdir /tmp/w && cd /tmp/w && tar x && python -m venv /tmp/v && /tmp/v/bin/pip install -q --disable-pip-version-check -r tests/requirements.txt && PYTEST=/tmp/v/bin/pytest bash ops/check.sh'

lock:             ## record image digests of what is running into versions.lock
	$(call dc,images --format json) | python3 -c 'import sys,json; [print(i["ContainerName"], (i["Repository"]+":"+i["Tag"]) if i["Repository"] else "<untagged: not the build its tag names>", i["ID"]) for i in sorted(json.load(sys.stdin), key=lambda i: i["ContainerName"])]' > versions.lock
	@cat versions.lock

ingest-exports:   ## convert mail/chat exports from C:\AI\exports (offline) and index them in qmd
	docker run --rm --network none -v /srv/win-exports:/in:ro -v /srv/ai/bulk:/out -v $(CURDIR)/converters:/app:ro aistack/tools:1 python /app/bulk_convert.py
	docker exec aistack-qmd-1 sh -c 'qmd update && qmd embed'

ha-deploy:  ## deploy or upgrade Home Assistant on the NAS (nas/homeassistant; host-side, keeps its config)
	bash ops/deploy-ha.sh

voice-deploy:  ## deploy Hermes' voice services on the NAS (nas/voice: speech to text, Piper; host-side; docs/HOME-VOICE.md)
	bash ops/deploy-voice.sh

deploy-testrepo:  ## deploy the committed HEAD of ~/code/TestRepo to the NAS (host-side; the agent has no NAS key)
	ops/deploy-testrepo.sh

opencode-password: ## show the OpenCode web login (user: opencode) in your own terminal
	@sops -d $(SECRETS) | grep "^OPENCODE_SERVER_PASSWORD:" | sed "s/^OPENCODE_SERVER_PASSWORD: /OpenCode user: opencode   password: /"

# --- MVP 6: learning, measured -------------------------------------------------------------------------
SECRETS_ALL = sops exec-env $(SECRETS) 'sops exec-env $(KEYS) "$(1)"'
bench:            ## full frozen benchmark (40 cases, ~20 min, ChatGPT subscription only)
	$(call SECRETS_ALL,python3 eval/bench.py run --label manual)
bench-gate:       ## fast gate subset (14 cases)
	$(call SECRETS_ALL,python3 eval/bench.py run --gate --label manual-gate)
retrieval:        ## qmd recall@8 / nDCG@8 per collection (add ARGS=--rerank for the rerank comparison)
	python3 eval/retrieval.py $(ARGS)
curate:           ## the weekly learning run now: gated curator pass + vault lint
	$(call SECRETS_ALL,python3 ops/curate.py)
vault-check:      ## deterministic vault lint (add ARGS=--fix)
	docker exec -i -u hermes -e VAULT=/vault aistack-hermes-1 /opt/hermes/.venv/bin/python - $(ARGS) < ops/vault_check.py
skill-approve:    ## approve a parked skill: make skill-approve NAME=<skill>
	python3 ops/skills_sync.py approve $(NAME)
skills-restore-from-git: ## put the skills folder back as committed in ~/hermes-skills (REF=<sha>, default HEAD)
	ops/skills-restore.sh $(REF)

# --- MVP 7: backups ---
backup:           ## encrypted backup to the NAS now (nightly 03:30 by timer)
	bash ops/backup.sh

restore-drill:    ## prove the newest backup restores (changes nothing; weekly by timer)
	bash ops/restore.sh drill

restore:          ## put the newest (or FILE=) backup back on this machine
	bash ops/restore.sh apply $(FILE)

# --- MVP 9: understand code ---
understand:       ## clone + analyse a repo: make understand REPO=https://github.com/owner/name (or REPO=name)
	$(call SECRETS_ALL,bash ops/understand.sh $(REPO))

ua-enrich:        ## explain the files and functions of REPO's code map where Understand Anything left placeholders (resumes)
	$(call SECRETS_ALL,python3 ops/ua_enrich.py /home/owner/code/$(REPO) $(REPO))
	python3 ops/ua_digest.py /home/owner/code/$(REPO)/.ua/knowledge-graph.json $(REPO) > /srv/ai/code-docs/$(REPO).md

understand-dashboard: ## code map of REPO in the browser (tailnet :8446), link also on Telegram
	bash ops/understand-dashboard.sh $(REPO)

upgrade-check:    ## which pinned components have newer releases (changes nothing; see UPGRADE.md)
	python3 ops/upgrade_check.py

digest:           ## send the morning digest now
	python3 ops/digest.py

# --- long-term memory (Hindsight) ---
forget:           ## remove every stored conversation containing TEXT from long-term memory: make forget TEXT="..."
	python3 ops/hindsight_forget.py "$(TEXT)"

hindsight-models: ## one-time download of the multilingual memory models (new machine)
	bash ops/hindsight-models.sh

# --- Topic Desk ---
desk:             ## run the nightly briefing now (all topics, or TOPIC=slug)
	$(call SECRETS_ALL,bash ops/desk.sh $(TOPIC))

email-setup:      ## one-time: Gmail app password for report e-mails (asks you; stored encrypted; sends a test)
	bash ops/email-setup.sh

wiki-rebuild:     ## compile a mission's LLM wiki from all its results: make wiki-rebuild MISSION=slug
	$(call SECRETS_ALL,python3 ops/wiki_rebuild.py $(MISSION))

tasks-gate:      ## phase 1's gate: eval/tasks-v1.yaml's 20 one-sentence tasks through the intake (starts nothing)
	sops exec-env $(SECRETS) 'sops exec-env $(KEYS) "python3 ops/tasks.py gate"'

conductor-gate:  ## phase 2's gate: a five-step task on three harnesses, the runner restarted during it (uses the subscriptions)
	sops exec-env $(SECRETS) 'sops exec-env $(KEYS) "python3 ops/conductor.py gate"'

trial:            ## one trial run in the background: make trial NAME=semver (eval/trials; its report lands in the vault, trials/)
	systemd-run --user --collect --unit=trial-$(NAME)-$$(date +%H%M) --working-directory=$(CURDIR) -E DOCKER_HOST=unix:///run/user/1000/docker.sock /usr/local/bin/sops exec-env $(SECRETS) 'sops exec-env $(KEYS) "python3 ops/trials.py run $(NAME)"'

trial-check:      ## does a trial's answer key score its own reference fully: make trial-check NAME=semver (changes nothing)
	python3 ops/trials.py check $(NAME)

journeys:         ## the journey checks now: a task to its result (replayed), every screen at 375 px, the e-mail, every make target (no model; nightly by timer)
	python3 ops/journeys.py all

publish-check:    ## build the public snapshot, scan it and run its tests; pushes nothing (docs/PUBLISHING.md)
	python3 ops/publish.py check

publish:          ## push the public snapshot to GitHub when it is clean (the owner's call each time; docs/PUBLISHING.md)
	python3 ops/publish.py push

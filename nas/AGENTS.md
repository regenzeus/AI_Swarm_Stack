# nas/: what runs on the Synology NAS

`forgejo/compose.yaml` is Forgejo (git + Actions) on the NAS, deployed to `/volume1/docker/forgejo/compose.yaml`.
It hosts the canonical repos (ai-stack, vault, hermes-skills, TestRepo) and receives the encrypted backups.
`homeassistant/` is Home Assistant (the House: Echos, lights, plugs), deployed by `make ha-deploy` to
`/volume1/docker/homeassistant` (host networking for device discovery, LAN only, port 8123). The owner approved it
on 2026-10-29; `configuration.yaml` is only seeded once and then belongs to Home Assistant and the owner.
`voice/` is Hermes' voice ([docs/HOME-VOICE.md](../docs/HOME-VOICE.md)): speech to text (Parakeet) and Piper for Home
Assistant's voice pipeline, on 127.0.0.1 only, deployed by `make voice-deploy` to `/volume1/docker/voice`. The owner
approved it on 2026-11-01 ("Yes, start V0").

`mailvault/` is the copy of the owner's Gmail ([its AGENTS.md](mailvault/AGENTS.md)): one way and read-only, deployed by
`make mailvault-deploy` to `/volume1/docker/mailvault`. The owner approved it on 2026-11-06.

## Rules (hard)

Changes here are applied host-side (`make ha-deploy`, `make voice-deploy`, `make deploy-testrepo`) or by the owner, never by agents. Never delete NAS data or volumes, never touch
RAID/SHR, storage pools or unrelated shares, never open router ports, and never weaken NAS security to make a
deployment easier. Agents never hold the NAS SSH key.

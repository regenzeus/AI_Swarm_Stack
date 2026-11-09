# nas/voice/: Hermes' voice on the NAS

`compose.yaml` runs speech to text (Parakeet through the Wyoming Whisper server) and text to speech (Piper) for Home
Assistant's voice pipeline ([docs/HOME-VOICE.md](../../docs/HOME-VOICE.md), requirement VOI-01). Both listen on
127.0.0.1 only: Home Assistant (host networking) reaches them, nothing on the network does. No audio is stored; the
speech service logs each transcript, so the logs are capped at 1 MB. Images are pinned by digest; the models download
on first start into `/volume1/docker/voice/{whisper,piper}`.

Deploy or change a setting host-side: `make voice-deploy`, or `ops/deploy-voice.sh WHISPER_MODEL=... STT_LIBRARY=...
PIPER_VOICE=...` (written to the NAS's `.env`, because sudo drops the environment). Measure with
`ssh synology python3 - bench < ops/voice_bench.py` (VOI-02); it loads every candidate voice into Piper, so restart
`voice-piper` afterwards to free the memory. The NAS rules in [../AGENTS.md](../AGENTS.md) apply.

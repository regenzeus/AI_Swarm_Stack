# nas/homeassistant/: Home Assistant on the NAS (the House)

`compose.yaml` runs Home Assistant (pinned by digest) on the NAS with host networking, so it can discover devices
on the home network; LAN only, port 8123, no router forward. `configuration.yaml` is the first configuration: `make
ha-deploy` (ops/deploy-ha.sh) writes it only when the NAS has none, after that it belongs to Home Assistant and the owner.

The stack's side is ops/house.py (status, switching, Alexa commands, the Echo bridge) and the House page in Mission
Control; Hermes reaches it only through Mission Control's `house` MCP tools. The owner types every password (Home
Assistant account, Amazon, TP-Link) into Home Assistant himself; the stack only holds its long-lived token (HA_TOKEN,
sops). Upgrade: change the tag and digest here, then `make ha-deploy` (the config folder stays).

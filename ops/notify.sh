#!/bin/sh
# Send one message to the owner through the one notification path (ops/notify.py, OBS-16):  ops/notify.sh "text"
# NOTIFY_CATEGORY (result, alert, health, build, swarm, system; default system) decides what the owner's preferences
# and quiet hours do with it. NOTIFY_BY names the sender when it isn't the stack itself (SWM-113).
exec python3 "$(dirname "$0")/notify.py" send --category "${NOTIFY_CATEGORY:-system}" -- "$*"

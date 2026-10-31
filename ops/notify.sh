#!/bin/sh
# Send one Telegram message to the owner through Hermes:  ops/notify.sh "text"
export DOCKER_HOST=unix:///run/user/1000/docker.sock
docker exec -u hermes aistack-hermes-1 sh -c 'hermes send -t "telegram:$TELEGRAM_ALLOWED_USERS" "$0"' "$*"

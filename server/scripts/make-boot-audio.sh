#!/bin/bash
# One-time generation of the boot greeting audio via Kokoro (~110 characters).
cd "$(dirname "$0")/.."
mkdir -p hud/audio
BASE=$(grep 'base_url:' config/server.yaml | awk '{print $2}')
VOICE=$(grep '^  voice:' config/server.yaml | awk '{print $2}')
NAME=${1:-there}
gen() {
  curl -s -m 30 -X POST "$BASE/audio/speech" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"kokoro\",\"input\":\"$2\",\"voice\":\"$VOICE\",\"response_format\":\"mp3\",\"stream\":false}" \
    -o "hud/audio/boot_$1.mp3"
}
gen morning   "Systems online. Good morning, $NAME."
gen afternoon "Systems online. Good afternoon, $NAME."
gen evening   "Systems online. Good evening, $NAME."
ls -la hud/audio/

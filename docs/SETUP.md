# Full Setup Guide

Tested on macOS (Apple Silicon) with Hermes Agent v0.16. Allow ~1 hour.

## 1. Hermes Agent (the brain)

Install Hermes Agent and give it an LLM provider — follow the
[official quickstart](https://hermes-agent.nousresearch.com/docs/getting-started/quickstart).
Verify `hermes` works in your terminal before continuing.

Enable its API server in `~/.hermes/.env`:

```bash
API_SERVER_ENABLED=true
API_SERVER_KEY=<long random secret>      # required — full toolset incl. terminal!
```

Start the gateway (`hermes gateway`) and verify:

```bash
KEY=$(grep '^API_SERVER_KEY=' ~/.hermes/.env | cut -d= -f2)
curl -H "Authorization: Bearer $KEY" http://127.0.0.1:8642/health
# {"status": "ok", ...}
```

Recommended: add voice-behavior rules to your global `~/.hermes/SOUL.md`
(short spoken sentences, no markdown aloud, never speak secrets, announce risky
actions and wait for approval). The agent — not the voice server — should own
its personality.

Jarvis (API server) uses Hermes `platform_toolsets.api_server` with **web + pc_apps**
(no live `browser` toolset — find/research stays in chat via `web_search` / `web_find`).
PC Chrome opens only when the user explicitly asks (`open_pc_app`, gated chrome_* tools).
Restart `hermes gateway` after changing toolsets.

## 2. Kokoro TTS (the voice)

Kokoro runs locally via Docker — no API key needed. From the repo root:

```bash
cd worker
docker compose -f docker-compose.kokoro.yml up -d
curl http://127.0.0.1:8880/health   # {"status":"healthy"} when ready
```

On Windows, run `worker\run-kokoro.bat` (local Python Kokoro server on port 8880 —
no Docker required). Optional Docker alternative: `docker compose -f docker-compose.kokoro.yml up -d`.

First start downloads ~100 MB of model weights. Browse voices at
`http://127.0.0.1:8880/v1/models` and set `voice.voice` in `server/config/server.yaml`
(default: `af_heart`).

## 3. The voice pipeline server (this repo)

```bash
cd server
python3 -m venv .venv
.venv/bin/pip install fastapi uvicorn requests pyyaml numpy anthropic \
    RealtimeSTT faster-whisper silero-vad websockets psutil
cp config/server.example.yaml config/server.yaml
```

Note: `faster-whisper` and `silero-vad` are REQUIRED — recent RealtimeSTT
releases treat them as optional extras and fail at runtime without them
(silently for VAD, loudly for the engine). The first start takes 60–90 s
(torch import + model download); subsequent starts are faster.

Edit `config/server.yaml`: set `voice.voice` (Kokoro voice id), and adjust the
`machines:` list (or delete it). The first run downloads the Whisper model
(~460 MB for `small.en`).

### TLS certificates (required for browser microphone)

Browsers only expose the mic to secure origins:

```bash
scripts/make-certs.sh            # auto-detects your LAN IP for the SAN
```

Trust `certs/cert.pem` on each device (macOS: Keychain; Windows:
`certutil -user -addstore Root cert.pem`; iPhone: download
`https://host:8765/hud/jarvis.cer`, install profile, then enable in
Settings → General → About → Certificate Trust Settings).

Optional but nice: rename your host's mDNS name (`sudo scutil --set
LocalHostName jarvis` on macOS) so the HUD lives at `https://jarvis.local/hud/`.
Port 443 needs the wildcard bind already set in the example config.

### HUD access token

```bash
echo "JARVIS_HUD_TOKEN=jarvis-$(python3 -c 'import secrets;print(secrets.token_hex(3))')" >> ~/.hermes/.env
```

The HUD asks for this once per device. Omit the variable entirely to disable
auth (not recommended).

### Boot greeting (one-time)

```bash
scripts/make-boot-audio.sh YourFirstName
```

Requires Kokoro running on port 8880.

### Run it

```bash
.venv/bin/python server.py
```

Wait ~40 s for the STT model to warm, then open `https://YOUR_HOST/hud/`.
Run `scripts/jarvis-health.sh` to check all six services.

## 4. Auto-start on boot (macOS)

Copy the two plists from `launchd/`, edit the `/PATH/TO` and `YOUR_USER`
placeholders, then:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jarvis.voice.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jarvis.dashboard.plist
```

**Read the comments in the plists** — there are two macOS traps (external-drive
TCC permissions and log-path location) that produce silent hangs or `EX_CONFIG`
errors if ignored. Day-to-day management: `scripts/jarvis-{start,stop,restart,health}.sh`.

## 5. Optional extras

**Push-to-talk client** (Windows/Linux box with a mic):

```bash
cd client
python -m venv .venv && .venv/Scripts/pip install sounddevice websockets numpy openwakeword
python client.py --push-to-talk --server ws://YOUR_HOST:8765/ws --list-devices
```

**GPU worker stats** (shows in the Machines panel): copy
`worker/worker_stats.py` to the worker machine, `pip install psutil`, run it,
and point a `machines:` entry's `stats_url` at `http://worker-ip:8767/stats`.

**GPU speech recognition** — the single biggest quality upgrade if you own any
NVIDIA machine on the LAN. On that machine:

```
cd worker
python -m venv .venv
.venv/Scripts/pip install faster-whisper fastapi uvicorn nvidia-cublas-cu12 nvidia-cudnn-cu12
copy run-stt.example.bat run-stt.bat    # fill in your JARVIS_HUD_TOKEN value
run-stt.bat
```

Then uncomment the `stt.remote:` block in the server's `server.yaml` (point
`url` at the GPU machine) and restart the voice server. Result: `large-v3-turbo`
accuracy at ~0.2 s per utterance, with automatic fallback to the local model
whenever the GPU machine is off. For auto-start at Windows logon, drop a
`JarvisSTT.vbs` in `shell:startup` (template in the .bat comments).

**Phone app feel**: open the HUD in Safari/Chrome on your phone →
Share → Add to Home Screen.

**Let the agent put things on your screen** (the showstopper): install the
bundled Hermes plugin so "show me a video of X on screen" makes holographic
media panels materialize on every open HUD:

```bash
cp -R hermes-plugin/hud_display ~/.hermes/plugins/hud_display
# edit ~/.hermes/plugins/hud_display/schemas.py: replace YOUR_HOST
hermes plugins enable hud_display     # repeat with -p <profile> if you use profiles
# restart your hermes gateway
```

The plugin needs `JARVIS_HUD_TOKEN` in `~/.hermes/.env` (same token as the
HUD). Directory name must stay a valid Python module name — hyphens silently
break plugin discovery. The agent then has `hud_display` / `hud_dismiss`
tools; YouTube links play as embedded video, `position` left/right lets it
fly in multiple panels from different vectors.

### PC apps on the visible Chrome (allowlisted)

Install `hermes-plugin/pc_apps` the same way (`pc_apps` toolset). Jarvis can
open only allowlisted targets (default: Chrome, YouTube, WhatsApp Web) and
**only while Chrome CDP is live** after you run `/browser connect` in the
Hermes CLI on the PC. Edit `D:\jarvis_kokoro\pc_apps_allowlist.yaml` to add
more sites later, then restart the Hermes gateway.

## 6. Verify everything

```bash
scripts/jarvis-health.sh   # all six rows OK
scripts/jarvis-smoke.sh    # synthesized voice turn through the full stack (macOS)
```

Then the real test: click the ring and ask "what's in your memory file?" —
a real agent answers with real file contents.

# Troubleshooting

**HUD loads but mic is blocked** — you're on plain http or an untrusted cert.
Browsers require a secure context for `getUserMedia`. Trust `certs/cert.pem`
on the device (see SETUP §3) and use `https://`.

**Chrome: "Your connection is not private" / `ERR_CERT_AUTHORITY_INVALID`** —
the HUD uses a self-signed cert. On the PC, double-click
`server/scripts/trust-cert.bat` (or open `certs/cert.pem` / the Certificate
window → Install Certificate → Current User → Trusted Root Certification
Authorities). Fully quit and reopen Chrome, then open
`https://192.168.1.57/hud/`. On iPhone: download `jarvis.cer` from the HUD,
install the profile, then enable trust under Settings → General → About →
Certificate Trust Settings. Regenerate SANs anytime with
`server/.venv/Scripts/python.exe server/scripts/make-certs.py`.

**First connection after server start times out** — the Whisper model warms at
startup (~40 s). `scripts/jarvis-health.sh` until all rows are OK.

**"Agent backend offline. Running in basic mode."** — the Hermes API server
isn't reachable. Check `API_SERVER_ENABLED/KEY` in `~/.hermes/.env` and that
`hermes gateway` is running; verify with `curl -H "Authorization: Bearer $KEY"
http://127.0.0.1:8642/health`.

**Transcripts are wrong/garbled words** — make sure you're on the current HUD
(hard refresh): mic must capture at 16 kHz natively. Upgrading `stt.model` to
`small.en` helps. Loud rooms: get closer to the mic; echo cancellation is on.

**Replies show â€™ / â€œ style garbage** — you're running an old server.py;
current code forces UTF-8 on the Hermes SSE stream.

**401 everywhere / ACCESS CODE loop** — the token you entered doesn't match
`JARVIS_HUD_TOKEN` in `~/.hermes/.env`. Clear the `jarvis_token` cookie and
retry; restart the voice server after changing the env var.

**LaunchAgent exits with EX_CONFIG** — your log paths point at an external
volume. Keep `StandardOutPath`/`StandardErrorPath` on the internal disk.

**LaunchAgent "running" but nothing listens, log empty** — TCC is blocking the
process from your external drive: it hangs inside `getcwd()`/`open()`. Grant
Full Disk Access to `Python.app` inside your Python framework (see the plist
comments), and invoke the **venv** python directly — no `bash -c 'cd ...'`
wrapper.

**Port 443 "address already in use" or permission denied** — bind `0.0.0.0`
(macOS only exempts wildcard binds for non-root low ports) and make sure a
previous instance fully released the port before restarting.

**Kokoro shows "offline" in the HUD** — the Kokoro Docker container isn't
running. Start it with `docker compose -f worker/docker-compose.kokoro.yml up -d`
and verify with `curl http://127.0.0.1:8880/health`.

**No speech / TTS errors in the HUD** — check that Kokoro is healthy and that
`voice.base_url` in `server/config/server.yaml` points at
`http://127.0.0.1:8880/v1`. Test directly:
```bash
curl -X POST http://127.0.0.1:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"Hello","voice":"af_heart","response_format":"pcm","stream":false}' \
  --output /tmp/test.pcm
```

**Stop button says stopped but Hermes kept working briefly** — on Hermes
v0.16, session runs aren't registered in the runs store (`/stop` 404s); the
halt works by dropping the SSE stream. Newer Hermes builds may fix this.

**"No clip timestamps found. Set 'vad_filter'..." error** — old build; current
code treats silent/unintelligible audio as an empty transcript on both the
local and GPU STT paths.

**GPU STT: "Library cublas64_12.dll is not found"** — the NVIDIA pip wheels
aren't on the DLL search path. Use the shipped `worker/stt_server.py` (it
resolves them via `sys.prefix`) and install `nvidia-cublas-cu12
nvidia-cudnn-cu12` into the same venv.

**HUD unreachable for ~15 s after a restart** — normal: launchd's respawn
throttle. If it lasts longer, run `scripts/jarvis-health.sh` on the host.

**HTTPS dead but the plain ws port still answers** — two known causes, both
fixed in current files but worth knowing: (1) file-descriptor exhaustion
(launchd default is 256; the shipped plist raises it to 8192), and (2) an
orphaned STT child process holding a port from a previous run, which makes the
next spawn fail its first bind and silently cancel all the TLS listeners. Use
`scripts/jarvis-stop.sh` — it kills by port ownership — never a bare pkill.

**Slow page loads from Windows (10s+), instant by IP** — Windows mDNS is
flaky with `.local` names. Add a hosts-file entry (admin):
`<server-ip> jarvis.local jarvis` (give the server a DHCP reservation first).

**Agent replies are empty (content null, 0 input tokens)** — your LLM
provider is out of quota/credits, not a bug here. Check the Hermes gateway
log for 429/402 errors and configure a `fallback_providers` entry in Hermes'
config.yaml.

**Agent "shows" things in its own browser instead of the HUD** — install and
enable the bundled `hermes-plugin/hud_display` (see SETUP). Prose
instructions don't beat tool schemas; the plugin does.

**Phone can't reach jarvis.local** — some Android versions lack mDNS; use the
raw IP (and add it to `security.extra_origin_hosts` in server.yaml so the
WebSocket origin check accepts it).

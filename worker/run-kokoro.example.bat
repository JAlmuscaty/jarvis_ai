@echo off
rem Jarvis Kokoro TTS sidecar (Windows). Copy to run-kokoro.bat.
rem Requires Docker Desktop. First start downloads ~100 MB model weights.
rem Verify: curl http://127.0.0.1:8880/health
cd /d %~dp0
docker compose -f docker-compose.kokoro.yml up -d

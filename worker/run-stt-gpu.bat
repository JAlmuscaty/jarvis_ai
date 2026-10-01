@echo off
rem Jarvis GPU STT worker (same PC as Jarvis) — keeps Whisper on the RTX
set HF_HOME=D:\jarvis_kokoro\hf
set HUGGINGFACE_HUB_CACHE=D:\jarvis_kokoro\hf\hub
set TRANSFORMERS_CACHE=D:\jarvis_kokoro\hf\transformers
set JARVIS_STT_MODEL=medium
set JARVIS_STT_BEAM=5
set JARVIS_STT_COMPUTE=int8
set JARVIS_STT_DEVICE=cuda
set JARVIS_STT_LANGUAGE=auto
rem Match HUD token if auth is enabled
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b "JARVIS_HUD_TOKEN=" "%USERPROFILE%\.hermes\.env"`) do set JARVIS_STT_TOKEN=%%B
cd /d C:\Users\Jasem\Desktop\jarvis_ai\worker
echo Starting GPU STT on http://127.0.0.1:8768 ...
D:\jarvis_kokoro\jarvis-venv\Scripts\python.exe stt_server.py

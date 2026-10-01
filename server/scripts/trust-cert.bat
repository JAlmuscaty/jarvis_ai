@echo off
title Trust Jarvis HTTPS Certificate
cd /d "%~dp0.."
echo.
echo === Trust Jarvis HUD certificate ===
echo This removes the Chrome "Your connection is not private" warning
echo for https://192.168.1.57/hud/ and https://127.0.0.1/hud/
echo.
echo A Windows security dialog may appear — click Yes / Allow.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0trust-cert.ps1"
echo.
pause

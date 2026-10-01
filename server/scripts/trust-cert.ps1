# Trust Jarvis self-signed cert in the current user's Trusted Root store.
$ErrorActionPreference = "Stop"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not (Test-Path (Join-Path $PSScriptRoot "..\certs\cert.pem"))) {
  $root = Resolve-Path (Join-Path $PSScriptRoot "..")
} else {
  $root = Resolve-Path (Join-Path $PSScriptRoot "..")
}
$pem = Join-Path $root "certs\cert.pem"
$der = Join-Path $env:TEMP "jarvis_hud_trust.cer"

if (-not (Test-Path $pem)) {
  Write-Host "Missing $pem — run make-certs.py first." -ForegroundColor Red
  exit 1
}

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  Write-Host "Missing venv python at $py" -ForegroundColor Red
  exit 1
}

& $py -c "from cryptography import x509; from cryptography.hazmat.primitives.serialization import Encoding; from pathlib import Path; c=x509.load_pem_x509_certificate(Path(r'$pem').read_bytes()); Path(r'$der').write_bytes(c.public_bytes(Encoding.DER)); print('ok')"
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "Installing certificate into Trusted Root (Current User)..."
# Visible certutil so Windows can show the confirmation UI
$result = Start-Process -FilePath "certutil.exe" -ArgumentList @("-user","-addstore","Root",$der) -Wait -PassThru
if ($result.ExitCode -eq 0) {
  Write-Host "SUCCESS — certificate trusted." -ForegroundColor Green
  Write-Host "1) Fully quit Chrome (all windows) and reopen it."
  Write-Host "2) Open https://127.0.0.1/hud/ or https://YOUR_LAN_IP/hud/ (run make-certs.py after IP changes)"
  Write-Host "3) Phone: see instructions printed below."
} else {
  Write-Host "certutil exit code $($result.ExitCode). Trying certificate UI..." -ForegroundColor Yellow
  Start-Process $der
  Write-Host "In the Certificate window: Install Certificate -> Current User ->"
  Write-Host "Place all certificates in the following store -> Trusted Root Certification Authorities -> Finish."
}

Write-Host ""
Write-Host "If Chrome still warns: use http://127.0.0.1:8765/hud/ on this PC (no cert needed)."
Write-Host "After your PC LAN IP changes, re-run: python server/scripts/make-certs.py then trust-cert.ps1"

Write-Host ""
Write-Host "=== iPhone / iPad ==="
Write-Host "1. On the phone (same Wi-Fi), open Safari:"
Write-Host "   http://192.168.1.57:8765/hud/jarvis.cer"
Write-Host "   (or https://192.168.1.57/hud/jarvis.cer after accepting once)"
Write-Host "2. Allow the profile download."
Write-Host "3. Settings -> Profile Downloaded -> Install."
Write-Host "4. Settings -> General -> About -> Certificate Trust Settings"
Write-Host "   -> enable full trust for 'Jarvis HUD'."
Write-Host "5. Open https://192.168.1.57/hud/"

Write-Host ""
Write-Host "=== Android Chrome ==="
Write-Host "Android often still warns for user-installed CAs. Prefer:"
Write-Host "  - Open the site -> Advanced -> Proceed (unsafe) once, OR"
Write-Host "  - Install the .cer and use a browser that respects user CAs."
Write-Host "Mic still needs HTTPS; proceeding past the warning is OK on LAN."

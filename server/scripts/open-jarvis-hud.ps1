# Open Jarvis HUD in the default browser (PC).
$ErrorActionPreference = "Stop"
$urls = @(
  "https://127.0.0.1/hud/",
  "http://127.0.0.1:8765/hud/"
)
# Prefer current LAN HTTPS if available
try {
  $lan = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -like '192.168.*' -or $_.IPAddress -like '10.*'
  } | Select-Object -First 1).IPAddress
  if ($lan) { $urls = @("https://$lan/hud/") + $urls }
} catch {}

$opened = $false
foreach ($u in $urls) {
  try {
    Start-Process $u
    Write-Host "Opened $u"
    $opened = $true
    break
  } catch {
    Write-Host "Could not open $u : $_"
  }
}
if (-not $opened) {
  Write-Host "Open manually: https://127.0.0.1/hud/  or  http://127.0.0.1:8765/hud/"
}

# Scarica gli annunci da tutti i portali (lo stesso che fa il pulsante "Aggiorna ora").
# Esempi:
#   .\aggiorna.ps1
#   .\aggiorna.ps1 --source subito --contract affitto
#
# Aggiornamento automatico ogni notte alle 3:00 (Utilità di pianificazione di Windows):
#   schtasks /Create /SC DAILY /ST 03:00 /TN "MorgantiCercaCase" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"$PSScriptRoot\aggiorna.ps1\""
# Per rimuoverlo:  schtasks /Delete /TN "MorgantiCercaCase" /F

$root = $PSScriptRoot
$py = Join-Path $root 'backend\.venv\Scripts\python.exe'
New-Item -ItemType Directory -Force (Join-Path $root 'data') | Out-Null
Push-Location (Join-Path $root 'backend')
& $py cli.py scrape @args 2>&1 | Tee-Object -Append -FilePath (Join-Path $root 'data\scrape.log')
Pop-Location

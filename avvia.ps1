# Avvia Morganti Cerca Case su http://localhost:8000
# Uso:  .\avvia.ps1          (compila il frontend se serve e avvia il server)
#       .\avvia.ps1 -Dev     (modalità sviluppo: backend :8000 + Vite :5173 con hot reload)
param([switch]$Dev)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$py = Join-Path $root 'backend\.venv\Scripts\python.exe'

if (-not (Test-Path $py)) {
    Write-Host 'Prima installazione: creo l''ambiente Python...'
    python -m venv (Join-Path $root 'backend\.venv')
    & $py -m pip install --quiet -r (Join-Path $root 'backend\requirements.txt')
    & $py -m playwright install chromium
}
if (-not (Test-Path (Join-Path $root 'frontend\node_modules'))) {
    Push-Location (Join-Path $root 'frontend'); npm install; Pop-Location
}

if ($Dev) {
    Start-Process -FilePath $py -ArgumentList '-m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000' -WorkingDirectory (Join-Path $root 'backend')
    Push-Location (Join-Path $root 'frontend'); npm run dev; Pop-Location
    return
}

if (-not (Test-Path (Join-Path $root 'frontend\dist\index.html'))) {
    Push-Location (Join-Path $root 'frontend'); npm run build; Pop-Location
}
Start-Process 'http://localhost:8000'
Push-Location (Join-Path $root 'backend')
& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Pop-Location

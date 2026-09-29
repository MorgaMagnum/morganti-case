# Avvia Morganti Cerca Case su http://localhost:8000
# Uso:  doppio clic su "Avvia Cerca Case.bat"   (il modo più semplice)
#       .\avvia.ps1               compila il frontend se serve, avvia il server e apre il browser
#       .\avvia.ps1 -Collegamento crea l'icona "Cerca Case" sul Desktop
#       .\avvia.ps1 -Dev          sviluppo: backend :8000 + Vite :5173 con hot reload
param([switch]$Dev, [switch]$Collegamento)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$py = Join-Path $root 'backend\.venv\Scripts\python.exe'
$frontend = Join-Path $root 'frontend'
$url = 'http://localhost:8000'

function Test-Server {
    try { Invoke-WebRequest "$url/api/facets" -UseBasicParsing -TimeoutSec 2 | Out-Null; return $true }
    catch { return $false }
}

if ($Collegamento) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Cerca Case.lnk'))
    $lnk.TargetPath = Join-Path $root 'Avvia Cerca Case.bat'
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation = "$env:SystemRoot\System32\imageres.dll,1"
    $lnk.Save()
    Write-Host 'Creato il collegamento "Cerca Case" sul Desktop.'
    return
}

if (-not (Test-Path $py)) {
    Write-Host 'Prima installazione: creo l''ambiente Python...'
    python -m venv (Join-Path $root 'backend\.venv')
    & $py -m pip install --quiet -r (Join-Path $root 'backend\requirements.txt')
    & $py -m playwright install chromium
}
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Push-Location $frontend; npm install; Pop-Location
}

if ($Dev) {
    Start-Process -FilePath $py -ArgumentList '-m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000' -WorkingDirectory (Join-Path $root 'backend')
    Push-Location $frontend; npm run dev; Pop-Location
    return
}

# Già in esecuzione (es. finestra lasciata aperta): apri solo il browser.
if (Test-Server) {
    Write-Host "Il sito è già avviato: apro $url"
    Start-Process $url
    return
}

# Ricompila il frontend se manca o se i sorgenti sono più recenti dell'ultima build.
$built = Join-Path $frontend 'dist\index.html'
$stale = -not (Test-Path $built)
if (-not $stale) {
    $builtAt = (Get-Item $built).LastWriteTime
    $stale = [bool](Get-ChildItem (Join-Path $frontend 'src'), (Join-Path $frontend 'index.html') -Recurse -File |
        Where-Object { $_.LastWriteTime -gt $builtAt } | Select-Object -First 1)
}
if ($stale) {
    Write-Host 'Compilo l''interfaccia...'
    Push-Location $frontend; npm run build; Pop-Location
}

# Apre il browser appena il server risponde (non prima, per evitare una pagina di errore).
Start-Job -ArgumentList $url -ScriptBlock {
    param($u)
    for ($i = 0; $i -lt 60; $i++) {
        try { Invoke-WebRequest "$u/api/facets" -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process $u; return }
        catch { Start-Sleep -Seconds 1 }
    }
} | Out-Null

Write-Host ''
Write-Host "Morganti Cerca Case: $url"
Write-Host 'Lascia aperta questa finestra finché usi il sito. Chiudila (o premi Ctrl+C) per spegnerlo.'
Write-Host ''
Push-Location (Join-Path $root 'backend')
try { & $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000 }
finally { Pop-Location; Get-Job | Remove-Job -Force }

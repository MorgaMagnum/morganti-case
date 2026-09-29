# Crea la versione "consultazione" di Cerca Case, da dare a chi deve solo guardare gli immobili.
# Sul suo PC non serve installare niente: il pacchetto contiene un Python portatile.
# Non cerca sui portali: mostra gli immobili dei file CSV che importa (pulsante "Esporta CSV" qui).
#
# Uso:       .\crea-versione-consultazione.ps1
# Risultato: consegna\Cerca Case - Consultazione.zip  (con dentro anche l'export di oggi)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venvPy = Join-Path $root 'backend\.venv\Scripts\python.exe'
$pyVersion = '3.12.10'  # ultima 3.12 con pacchetto "embeddable" ufficiale
$packages = 'fastapi', 'uvicorn', 'sqlmodel', 'httpx', 'selectolax', 'shapely', 'pillow', 'tzdata'
$cache = Join-Path $root '.cache'
$outDir = Join-Path $root 'consegna'
$name = 'Cerca Case - Consultazione'
$bundle = Join-Path $outDir $name
$prog = Join-Path $bundle 'programma'
$utf8Bom = New-Object System.Text.UTF8Encoding($true)

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

Step 'Compilo l''interfaccia'
Push-Location (Join-Path $root 'frontend')
npm run build
if ($LASTEXITCODE) { Pop-Location; throw 'Compilazione del frontend fallita' }
Pop-Location

Step 'Preparo la cartella'
if (Test-Path $bundle) { Remove-Item $bundle -Recurse -Force }
New-Item -ItemType Directory -Force $prog, $cache | Out-Null

Step "Python portatile $pyVersion"
$zip = Join-Path $cache "python-$pyVersion-embed-amd64.zip"
if (-not (Test-Path $zip)) {
    Invoke-WebRequest "https://www.python.org/ftp/python/$pyVersion/python-$pyVersion-embed-amd64.zip" -OutFile $zip -UseBasicParsing
}
$pyDir = Join-Path $prog 'python'
Expand-Archive $zip $pyDir
$pth = Get-ChildItem $pyDir -Filter 'python*._pth' | Select-Object -First 1
# Percorsi di ricerca: libreria standard, dipendenze, codice dell'app.
[IO.File]::WriteAllLines($pth.FullName, [string[]]@("$($pth.BaseName).zip", '.', 'Lib\site-packages', '..\backend', 'import site'))

Step 'Dipendenze (stesse versioni dell''ambiente di sviluppo)'
$constraints = Join-Path $cache 'constraints.txt'
& $venvPy -m pip freeze | Set-Content $constraints -Encoding ascii
& $venvPy -m pip install --quiet --disable-pip-version-check --target (Join-Path $pyDir 'Lib\site-packages') `
    --only-binary=:all: --platform win_amd64 --python-version 3.12 --implementation cp -c $constraints @packages
if ($LASTEXITCODE) { throw 'Installazione delle dipendenze fallita' }

Step 'Codice dell''app'
foreach ($dir in 'app', 'pipeline', 'scrapers') {
    Copy-Item (Join-Path $root "backend\$dir") (Join-Path $prog "backend\$dir") -Recurse
}
Copy-Item (Join-Path $root 'backend\consultazione.py') (Join-Path $prog 'backend')
Copy-Item (Join-Path $root 'config') (Join-Path $prog 'config') -Recurse
New-Item -ItemType Directory (Join-Path $prog 'frontend') | Out-Null
Copy-Item (Join-Path $root 'frontend\dist') (Join-Path $prog 'frontend\dist') -Recurse
Get-ChildItem $prog -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force

Step 'Controllo che parta'
$env:CC_MODE = 'consultazione'
$env:CC_DATA_DIR = Join-Path $cache 'check-data'
Push-Location (Join-Path $prog 'backend')
& (Join-Path $pyDir 'python.exe') -c "import app.main; from app import config; assert not config.CAN_SCRAPE; print('ok')"
$failed = $LASTEXITCODE
Pop-Location
Remove-Item Env:CC_MODE, Env:CC_DATA_DIR
if ($failed) { throw 'Il pacchetto non parte: vedi l''errore qui sopra' }

Step 'Avvio, istruzioni e dati di oggi'
# Solo caratteri ASCII: il prompt dei comandi non usa UTF-8.
$bat = @'
@echo off
title Cerca Case
if not exist "%~dp0programma\python\python.exe" (
  echo.
  echo   Prima bisogna estrarre la cartella dal file zip:
  echo   chiudi questa finestra, fai clic col tasto destro sul file zip
  echo   e scegli "Estrai tutto". Poi apri la cartella estratta
  echo   e fai doppio clic su "Apri Cerca Case".
  echo.
  pause
  exit /b 1
)
cd /d "%~dp0programma"
python\python.exe backend\consultazione.py
if errorlevel 1 pause
'@
[IO.File]::WriteAllText((Join-Path $bundle 'Apri Cerca Case.bat'), ($bat -replace "`r?`n", "`r`n"), [Text.Encoding]::ASCII)
# Stesso nome dei file di "Esporta CSV": all'avvio l'app lo trova e lo importa da sola.
$csvName = "cerca-case-$(Get-Date -Format 'yyyy-MM-dd').csv"
$exportPy = Join-Path $cache 'export.py'
[IO.File]::WriteAllText($exportPy, @'
import os
import sys

sys.path.insert(0, os.getcwd())  # the backend folder (the script itself lives in .cache)
from sqlmodel import Session
from app.db import engine
from pipeline.transfer import export_csv

with Session(engine) as s, open(sys.argv[1], "w", encoding="utf-8-sig", newline="") as f:
    f.write(export_csv(s))
'@)
Push-Location (Join-Path $root 'backend')
& $venvPy $exportPy (Join-Path $bundle $csvName)
$failed = $LASTEXITCODE
Pop-Location
if ($failed) { throw 'Esportazione dei dati fallita' }
$readme = @"
CERCA CASE
==========

PER APRIRLO
Fai doppio clic su "Apri Cerca Case".
Si apre una finestra nera e poi, da solo, il sito con tutte le case.
Lascia aperta la finestra nera mentre guardi le case; quando hai finito, chiudila.
Se Windows chiede conferma, premi "Esegui"
(oppure "Ulteriori informazioni" e poi "Esegui comunque").

Dalla seconda volta puoi usare l'icona "Cerca Case" che trovi sul Desktop.

QUANDO TI MANDO UN FILE NUOVO
1. Scaricalo (da WhatsApp o dalla mail): finisce nella cartella Download.
2. Apri Cerca Case come sempre: le case si aggiornano da sole.

Se non si aggiornano, premi "Importa file" in alto a destra
e scegli il file dalla cartella Download.

Serve Internet per vedere la mappa e le foto.
Non cancellare questa cartella: il programma è qui dentro.
"@
[IO.File]::WriteAllText((Join-Path $bundle 'LEGGIMI.txt'), ($readme -replace "`r?`n", "`r`n"), $utf8Bom)

Step 'Comprimo'
$zipOut = Join-Path $outDir "$name.zip"
if (Test-Path $zipOut) { Remove-Item $zipOut }
Compress-Archive -Path $bundle -DestinationPath $zipOut
$mb = [math]::Round((Get-Item $zipOut).Length / 1MB, 1)
Write-Host "`nFatto: $zipOut ($mb MB)" -ForegroundColor Green
Write-Host 'Mandalo a chi deve usarlo (es. con WeTransfer o Google Drive). Per gli aggiornamenti basta il file di "Esporta CSV".'

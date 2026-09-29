# Morganti Cerca Case

App locale, per uso personale, che raccoglie gli annunci di **vendita** e **affitto** del Comune di Cascina (PI) da tutti i principali portali. Li mostra su una mappa interattiva, in una lista con filtri e in una scheda di dettaglio con foto.

Fonti: **Immobiliare.it, Casa.it, Subito.it, Wikicasa, Idealista**. Coprono di fatto anche le agenzie locali, che pubblicano lì i loro immobili. Facebook è escluso di proposito: richiede login e i termini di Meta vietano lo scraping.

## Avvio

```powershell
.\avvia.ps1          # apre http://localhost:8000
.\avvia.ps1 -Dev     # sviluppo: API su :8000, frontend Vite su :5173
.\aggiorna.ps1       # scarica gli annunci (lo stesso fa il pulsante "Aggiorna ora")
```

Requisiti: Python 3.12, Node 20+, **Google Chrome installato**.

Il primo aggiornamento richiede circa 20-40 minuti. Il geocoding degli indirizzi è limitato a 1 richiesta al secondo (policy di OpenStreetMap), e tra una pagina e l'altra ci sono pause di 2-4 s per non sovraccaricare i siti. Gli aggiornamenti successivi sono molto più rapidi, perché gli indirizzi restano in cache.

Durante l'aggiornamento si apre Chrome **fuori dallo schermo**. Serve perché Immobiliare, Casa.it, Idealista e Wikicasa bloccano i client automatici "headless" (DataDome/Cloudflare). Il profilo del browser in `data/browser-profile` conserva i cookie tra un giro e l'altro.

Per un aggiornamento automatico notturno, il comando `schtasks` è descritto in `aggiorna.ps1`.

## Come funziona

```
backend/
  scrapers/      un parser per sito: pagina dei risultati -> RawListing (testato su HTML reale salvato)
  pipeline/
    geo.py       confine comunale (OSM) + assegnazione della frazione
    geocode.py   Nominatim, limitato al comune, con cache su DB
    dedup.py     riconosce lo stesso immobile su portali diversi
    store.py     inserisce, aggiorna, unisce i doppioni, disattiva gli annunci spariti
    runner.py    paginazione, errori isolati per fonte, registro dei run
  app/           API FastAPI (/api/listings, /markers, /facets, /images, /scrape)
frontend/        React + Vite + Leaflet
config/          confine del comune e frazioni (da OpenStreetMap)
data/            database SQLite, foto, log (non versionato)
```

- **Deduplica**: due annunci sono lo stesso immobile se hanno lo stesso contratto e una tipologia compatibile, e in più vale una di queste condizioni:
  - foto di copertina quasi identica (hash percettivo) e prezzo compatibile;
  - prezzo entro il ±3% e superficie entro l'±8%, con lo stesso indirizzo o con una distanza inferiore a 150 m.

  La scheda mostra tutti i siti su cui compare, ognuno col suo prezzo. Come prezzo principale usa il più basso.
- **Posizione**: coordinate del portale quando sono esatte, altrimenti geocoding dell'indirizzo, altrimenti il centro della frazione. Sulla mappa i marker tratteggiati indicano una posizione approssimativa. Gli annunci con coordinate esatte fuori dal confine comunale vengono scartati.
- **Annunci rimossi**: un annuncio che non compare per 2 aggiornamenti completi consecutivi diventa "non più online".
- **Foto**: la copertina viene scaricata durante l'aggiornamento. Le altre foto vengono scaricate alla prima apertura della scheda e poi servite dal disco.
- **Data di pubblicazione**: Subito e Wikicasa la forniscono. Per gli altri portali si usa la data in cui l'annuncio è stato trovato la prima volta, indicata nell'interfaccia come "visto …".

## Test

```powershell
cd backend; .venv\Scripts\python.exe -m pytest --cov=pipeline --cov=app --cov=scrapers
cd frontend; npm run build
```

Se un sito cambia struttura, il relativo parser smette di funzionare e l'errore compare nel pannello "Stato delle fonti". Per aggiornare la fixture in `backend/tests/fixtures/`, salva la pagina dei risultati e correggi il parser finché i test tornano verdi.

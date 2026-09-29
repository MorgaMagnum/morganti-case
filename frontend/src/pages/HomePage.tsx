import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Contract, PositionCertainty } from '../api/types'
import { ImportCsv } from '../components/DataTransfer'
import ErrorBoundary from '../components/ErrorBoundary'
import FilterBar from '../components/FilterBar'
import ListingCard from '../components/ListingCard'
import ListingsMap from '../components/ListingsMap'
import Pagination from '../components/Pagination'
import { apiFilterQuery, useFilters } from '../hooks/useFilters'
import { formatNumber } from '../lib/format'

const PAGE_SIZE = 24

export default function HomePage() {
  const { filters, update, reset, activeCount } = useFilters()
  const [bbox, setBbox] = useState<string | null>(null)
  const [hovered, setHovered] = useState<number | null>(null)
  const listTop = useRef<HTMLDivElement>(null)

  const filterQuery = useMemo(() => apiFilterQuery(filters, bbox), [filters, bbox])
  // The map always shows the whole comune, so it ignores the visible-area filter.
  const markerQuery = useMemo(() => apiFilterQuery({ ...filters, onlyVisibleArea: false }, null), [filters])
  const listQuery = useMemo(() => {
    const q = new URLSearchParams(filterQuery)
    q.set('sort', filters.sort)
    q.set('page', String(filters.page))
    q.set('size', String(PAGE_SIZE))
    return q
  }, [filterQuery, filters.sort, filters.page])

  const facets = useQuery({ queryKey: ['facets'], queryFn: api.facets })
  const markers = useQuery({
    queryKey: ['markers', markerQuery.toString()],
    queryFn: () => api.markers(markerQuery),
    placeholderData: keepPreviousData,
  })
  const listings = useQuery({
    queryKey: ['listings', listQuery.toString()],
    queryFn: () => api.listings(listQuery),
    placeholderData: keepPreviousData,
    // With "only visible area" we must wait for the map to report its bounds.
    enabled: !filters.onlyVisibleArea || bbox !== null,
  })

  // Panning changes the result set: go back to page 1 instead of showing an empty page 3.
  const lastBbox = useRef(bbox)
  useEffect(() => {
    if (lastBbox.current !== null && bbox !== lastBbox.current && filters.onlyVisibleArea && filters.page > 1) {
      update({})
    }
    lastBbox.current = bbox
  }, [bbox, filters.onlyVisibleArea, filters.page, update])

  const counts = useMemo(() => {
    const c: Record<Contract, number> = { vendita: 0, affitto: 0 }
    for (const f of facets.data?.data?.contracts ?? []) {
      if (f.value === 'vendita' || f.value === 'affitto') c[f.value] = f.count
    }
    return c
  }, [facets.data])

  const positionCounts = useMemo(() => {
    const c: Record<PositionCertainty, number> = { certa: 0, incerta: 0 }
    for (const f of facets.data?.data?.positions ?? []) {
      if (f.value === 'certa' || f.value === 'incerta') c[f.value] = f.count
    }
    return c
  }, [facets.data])

  const togglePosition = useCallback(
    (p: PositionCertainty) => {
      const other: PositionCertainty = p === 'certa' ? 'incerta' : 'certa'
      update({ position: filters.position === null ? other : null })
    },
    [filters.position, update],
  )

  const toggleContract = useCallback(
    (c: Contract) => {
      const other: Contract = c === 'vendita' ? 'affitto' : 'vendita'
      update({ contract: filters.contract === null ? other : null })
    },
    [filters.contract, update],
  )

  const onBounds = useCallback((b: string) => setBbox(b), [])
  const onPage = (page: number) => {
    update({ page })
    listTop.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const total = listings.data?.meta?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const noData = facets.data?.data?.total_active === 0
  const info = useQuery({ queryKey: ['info'], queryFn: api.info, staleTime: Infinity })
  const canScrape = info.data?.data?.can_scrape === true
  const readOnly = info.data?.data?.can_scrape === false

  // A bookmarked page number can outlive the data: clamp it.
  useEffect(() => {
    if (listings.isSuccess && !listings.isPlaceholderData && total > 0 && filters.page > totalPages) {
      update({ page: totalPages })
    }
  }, [listings.isSuccess, listings.isPlaceholderData, total, totalPages, filters.page, update])

  return (
    <main className="home">
      <FilterBar filters={filters} facets={facets.data?.data ?? null} activeCount={activeCount} onChange={update} onReset={reset} />

      <ErrorBoundary fallback={<div className="notice notice-error">La mappa non è disponibile. La lista qui sotto funziona comunque.</div>}>
        <ListingsMap
          markers={markers.data?.data ?? []}
          highlightedId={hovered}
          contract={filters.contract}
          position={filters.position}
          counts={counts}
          positionCounts={positionCounts}
          loading={markers.isLoading}
          onContractToggle={toggleContract}
          onPositionToggle={togglePosition}
          onBoundsChange={onBounds}
        />
      </ErrorBoundary>

      <section className="results" ref={listTop}>
        <div className="results-head">
          <h2 aria-live="polite">
            {listings.isLoading ? 'Carico…' : `${formatNumber(total)} ${total === 1 ? 'immobile' : 'immobili'}`}
            {filters.onlyVisibleArea && <span className="muted"> nell’area visibile</span>}
          </h2>
          {markers.data?.data && total > 0 && (
            <span className="muted">
              {formatNumber(markers.data.data.filter((m) => m.geo_precision !== 'comune').length)} sulla mappa
            </span>
          )}
        </div>

        {listings.error && <div className="notice notice-error">{(listings.error as Error).message}</div>}

        {noData && canScrape && (
          <div className="notice">
            <strong>Il database è vuoto.</strong> Premi “Completo” in alto per scaricare gli annunci da tutti i
            portali, oppure importa un file CSV esportato da un’altra copia.
          </div>
        )}
        {noData && readOnly && (
          <ImportCsv dropZone className="btn btn-primary btn-lg" label="Scegli il file…">
            <h3>Benvenuta!</h3>
            <p>
              Per vedere gli immobili trascina qui il file <strong>.csv</strong> che hai ricevuto, oppure premi il
              pulsante e sceglilo. Quando ne ricevi uno più recente, importalo allo stesso modo: gli immobili si
              aggiornano da soli.
            </p>
          </ImportCsv>
        )}

        {!listings.isLoading && total === 0 && !noData && !listings.error && (
          <div className="notice">
            Nessun immobile corrisponde ai filtri.{' '}
            <button type="button" className="link-btn" onClick={reset}>
              Azzera i filtri
            </button>
          </div>
        )}

        <div className={`grid ${listings.isPlaceholderData ? 'is-stale' : ''}`}>
          {(listings.data?.data ?? []).map((l) => (
            <ListingCard key={l.id} listing={l} onHover={setHovered} />
          ))}
        </div>

        <Pagination page={filters.page} totalPages={totalPages} onPage={onPage} />
      </section>
    </main>
  )
}

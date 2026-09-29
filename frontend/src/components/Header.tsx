import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { CONTRACT_LABEL, formatDateTime, timeAgo } from '../lib/format'

const POLL_RUNNING_MS = 5_000

export default function Header() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)

  const facets = useQuery({ queryKey: ['facets'], queryFn: api.facets })
  const status = useQuery({
    queryKey: ['scrape-status'],
    queryFn: api.scrapeStatus,
    refetchInterval: (q) => (q.state.data?.data?.running ? POLL_RUNNING_MS : false),
  })
  const running = status.data?.data?.running ?? false

  // When a crawl finishes, refresh everything that depends on the data.
  const wasRunning = useRef(running)
  useEffect(() => {
    if (wasRunning.current && !running) {
      queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'scrape-status' })
    }
    wasRunning.current = running
  }, [running, queryClient])

  const start = useMutation({
    mutationFn: api.startScrape,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['scrape-status'] }),
  })

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const lastUpdate = facets.data?.data?.last_update
  const runs = status.data?.data?.runs ?? []
  const lastFull = status.data?.data?.last_full_update
  const failed = runs.filter((r) => r.status === 'error').length

  return (
    <header className="topbar">
      <Link to="/" className="brand" aria-label="Morganti Cerca Case, torna alla ricerca">
        <span className="brand-mark" aria-hidden>
          <svg viewBox="0 0 32 32" width="28" height="28">
            <rect width="32" height="32" rx="8" fill="currentColor" />
            <path d="M8 16.5 16 9l8 7.5V24a1 1 0 0 1-1 1h-4.5v-5h-5v5H9a1 1 0 0 1-1-1z" fill="var(--bg)" />
          </svg>
        </span>
        <span>
          <span className="brand-name">Morganti Cerca Case</span>
          <span className="brand-sub">vendite e affitti a Cascina, da tutti i portali</span>
        </span>
      </Link>

      <div className="topbar-status" ref={panelRef}>
        <button type="button" className="status-pill" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          <span className={`dot ${running ? 'dot-running' : failed ? 'dot-warn' : 'dot-ok'}`} aria-hidden />
          {running
            ? 'Aggiornamento in corso…'
            : lastUpdate
              ? `Aggiornato ${timeAgo(lastUpdate)}`
              : 'Mai aggiornato'}
        </button>
        <div className="update-buttons" role="group" aria-label="Aggiorna gli annunci">
          <button
            type="button"
            className="btn btn-primary"
            disabled={running || start.isPending}
            onClick={() => start.mutate('rapido')}
            title="Solo gli annunci nuovi, circa 1 minuto"
          >
            {running ? 'In corso…' : 'Cerca novità'}
          </button>
          <button
            type="button"
            className="btn"
            disabled={running || start.isPending}
            onClick={() => start.mutate('completo')}
            title="Rilegge tutti gli annunci: rileva anche prezzi cambiati e annunci rimossi. Alcuni minuti."
          >
            Completo
          </button>
        </div>

        {open && (
          <div className="status-panel" role="dialog" aria-label="Stato delle fonti">
            <h3>Stato delle fonti</h3>
            <p className="muted small">
              <strong>Cerca novità</strong> legge solo gli annunci più recenti (circa 1 minuto).{' '}
              <strong>Completo</strong> rilegge tutto e rileva anche prezzi cambiati e annunci rimossi.
              {lastFull ? ` Ultimo completo: ${formatDateTime(lastFull)}.` : ' Nessun aggiornamento completo finora.'}
            </p>
            {start.error && <p className="error-text">{(start.error as Error).message}</p>}
            {runs.length === 0 && <p className="muted">Nessun aggiornamento eseguito finora.</p>}
            <ul>
              {runs.map((r) => (
                <li key={`${r.source}-${r.contract}`}>
                  <span className={`dot ${r.status === 'running' ? 'dot-running' : r.status === 'ok' ? 'dot-ok' : 'dot-warn'}`} />
                  <span className="run-name">
                    {r.label} · {CONTRACT_LABEL[r.contract]}
                    <span className={`run-mode run-mode-${r.mode}`}>{r.mode}</span>
                  </span>
                  <span className="run-meta">
                    {r.status === 'error' ? (
                      <span className="error-text" title={r.error ?? ''}>errore</span>
                    ) : (
                      <>
                        {r.found} annunci{r.new ? `, ${r.new} nuovi` : ''}
                      </>
                    )}
                    {' · '}
                    {formatDateTime(r.finished_at ?? r.started_at)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </header>
  )
}

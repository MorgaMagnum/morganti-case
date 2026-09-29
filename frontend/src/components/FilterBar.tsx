import { useEffect, useRef, useState } from 'react'
import type { Contract, Facets, PositionCertainty, SortKey } from '../api/types'
import type { Filters } from '../hooks/useFilters'
import { capitalize } from '../lib/format'
import { SOURCE_LABELS } from '../lib/sources'

interface Props {
  filters: Filters
  facets: Facets | null
  activeCount: number
  onChange: (patch: Partial<Filters>) => void
  onReset: () => void
}

const SORT_LABELS: Record<SortKey, string> = {
  published_desc: 'Più recenti',
  published_asc: 'Meno recenti',
  price_asc: 'Prezzo crescente',
  price_desc: 'Prezzo decrescente',
  m2_desc: 'Superficie maggiore',
  price_m2_asc: '€/m² più basso',
}

const TEXT_DEBOUNCE_MS = 350

/** Number input that commits on blur/Enter and after a short pause. */
function parseDraft(draft: string): number | null | undefined {
  if (draft.trim() === '') return null
  const n = Number(draft)
  return Number.isFinite(n) && n >= 0 ? Math.round(n) : undefined // undefined = invalid, don't commit
}

function NumberField(props: { label: string; value: number | null; onCommit: (v: number | null) => void; step?: number }) {
  const { value } = props
  const [draft, setDraft] = useState(value?.toString() ?? '')
  // Keep the latest callback in a ref so parent re-renders don't restart the debounce.
  const commitRef = useRef(props.onCommit)
  commitRef.current = props.onCommit
  useEffect(() => {
    setDraft((d) => (parseDraft(d) === value ? d : value?.toString() ?? ''))
  }, [value])
  useEffect(() => {
    const next = parseDraft(draft)
    if (next === undefined || next === value) return
    const t = setTimeout(() => commitRef.current(next), TEXT_DEBOUNCE_MS * 2)
    return () => clearTimeout(t)
  }, [draft, value])
  return (
    <label className="field">
      <span>{props.label}</span>
      <input
        type="number"
        inputMode="numeric"
        min={0}
        step={props.step}
        value={draft}
        aria-invalid={parseDraft(draft) === undefined}
        onChange={(e) => setDraft(e.target.value)}
      />
    </label>
  )
}

function MultiSelect(props: {
  label: string
  options: { value: string; count: number }[]
  selected: string[]
  onChange: (values: string[]) => void
  formatLabel?: (value: string) => string
  allLabel?: string
}) {
  const fmt = props.formatLabel ?? capitalize
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  const toggle = (v: string) =>
    props.onChange(props.selected.includes(v) ? props.selected.filter((x) => x !== v) : [...props.selected, v])
  const summary =
    props.selected.length === 0
      ? (props.allLabel ?? 'Tutte')
      : props.selected.length === 1
        ? fmt(props.selected[0])
        : `${props.selected.length} selezionate`
  return (
    <div className="field multiselect" ref={ref}>
      <span>{props.label}</span>
      <button type="button" className={`select-btn ${props.selected.length ? 'is-set' : ''}`} onClick={() => setOpen(!open)} aria-expanded={open}>
        {summary}
      </button>
      {open && (
        <div className="dropdown" role="group" aria-label={props.label}>
          {props.options.length === 0 && <p className="muted">Nessuna opzione</p>}
          {props.options.map((o) => (
            <label key={o.value} className="check-row">
              <input type="checkbox" checked={props.selected.includes(o.value)} onChange={() => toggle(o.value)} />
              <span>{fmt(o.value)}</span>
              <span className="count">{o.count}</span>
            </label>
          ))}
          {props.selected.length > 0 && (
            <button type="button" className="link-btn" onClick={() => props.onChange([])}>
              Deseleziona tutto
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export default function FilterBar({ filters, facets, activeCount, onChange, onReset }: Props) {
  const [expanded, setExpanded] = useState(false) // only matters on narrow screens
  const [q, setQ] = useState(filters.q)
  // Only adopt the URL value when it really differs (the URL stores the trimmed text,
  // so "via " must not be overwritten while the user is still typing).
  useEffect(() => setQ((cur) => (cur.trim() === filters.q ? cur : filters.q)), [filters.q])
  useEffect(() => {
    if (q.trim() === filters.q) return
    const t = setTimeout(() => onChange({ q }), TEXT_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [q, filters.q, onChange])

  const setContract = (c: Contract | null) => onChange({ contract: c })

  return (
    <section className="filterbar" aria-label="Filtri di ricerca">
      <div className="segmented" role="radiogroup" aria-label="Contratto">
        {([null, 'vendita', 'affitto'] as const).map((c) => (
          <button
            key={c ?? 'all'}
            type="button"
            role="radio"
            aria-checked={filters.contract === c}
            className={filters.contract === c ? 'active' : ''}
            onClick={() => setContract(c)}
          >
            {c === null ? 'Tutti' : c === 'vendita' ? 'Vendita' : 'Affitto'}
          </button>
        ))}
      </div>

      <label className="field field-search">
        <span>Cerca</span>
        <input type="search" placeholder="via, parola chiave, agenzia…" value={q} onChange={(e) => setQ(e.target.value)} />
      </label>

      <button
        type="button"
        className="btn more-filters"
        aria-expanded={expanded}
        aria-controls="more-filters"
        onClick={() => setExpanded((v) => !v)}
      >
        {expanded ? 'Nascondi filtri' : `Filtri${activeCount ? ` (${activeCount})` : ''}`}
      </button>

      <div id="more-filters" className={`filters-more ${expanded ? 'is-open' : ''}`}>
      <MultiSelect
        label="Tipologia"
        options={facets?.property_types ?? []}
        selected={filters.types}
        onChange={(types) => onChange({ types })}
      />
      <MultiSelect
        label="Frazione"
        options={(facets?.frazioni ?? []).slice().sort((a, b) => a.value.localeCompare(b.value))}
        selected={filters.frazioni}
        onChange={(frazioni) => onChange({ frazioni })}
      />
      <MultiSelect
        label="Fonte"
        allLabel="Tutti i siti"
        options={facets?.sources ?? []}
        selected={filters.sources}
        formatLabel={(s) => SOURCE_LABELS[s] ?? s}
        onChange={(sources) => onChange({ sources })}
      />

      <div className="field-pair">
        <NumberField label="Prezzo min €" value={filters.priceMin} step={filters.contract === 'affitto' ? 50 : 5000} onCommit={(v) => onChange({ priceMin: v })} />
        <NumberField label="Prezzo max €" value={filters.priceMax} step={filters.contract === 'affitto' ? 50 : 5000} onCommit={(v) => onChange({ priceMax: v })} />
      </div>
      <NumberField label="m² min" value={filters.m2Min} step={10} onCommit={(v) => onChange({ m2Min: v })} />
      <label className="field">
        <span>Locali</span>
        <select value={filters.roomsMin ?? ''} onChange={(e) => onChange({ roomsMin: e.target.value ? Number(e.target.value) : null })}>
          <option value="">Qualsiasi</option>
          {[1, 2, 3, 4, 5].map((n) => (
            <option key={n} value={n}>
              {n}+
            </option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>Posizione</span>
        <select
          value={filters.position ?? ''}
          onChange={(e) => onChange({ position: (e.target.value || null) as PositionCertainty | null })}
        >
          <option value="">Tutte</option>
          <option value="certa">Solo posizione certa</option>
          <option value="incerta">Solo posizione incerta</option>
        </select>
      </label>

      <div className="filter-toggles">
        <label className="check-row">
          <input type="checkbox" checked={filters.hasPrice} onChange={(e) => onChange({ hasPrice: e.target.checked })} />
          <span>Solo con prezzo</span>
        </label>
        <label className="check-row">
          <input type="checkbox" checked={filters.onlyVisibleArea} onChange={(e) => onChange({ onlyVisibleArea: e.target.checked })} />
          <span>Solo area visibile sulla mappa</span>
        </label>
      </div>

      <label className="field field-sort">
        <span>Ordina per</span>
        <select value={filters.sort} onChange={(e) => onChange({ sort: e.target.value as SortKey })}>
          {Object.entries(SORT_LABELS).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
      </label>

      {activeCount > 0 && (
        <button type="button" className="link-btn reset" onClick={onReset}>
          Azzera filtri ({activeCount})
        </button>
      )}
      </div>
    </section>
  )
}

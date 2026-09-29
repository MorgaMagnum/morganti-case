import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { Contract, PositionCertainty, SortKey } from '../api/types'

export interface Filters {
  contract: Contract | null
  types: string[]
  frazioni: string[]
  sources: string[]
  position: PositionCertainty | null
  priceMin: number | null
  priceMax: number | null
  m2Min: number | null
  roomsMin: number | null
  q: string
  hasPrice: boolean
  onlyVisibleArea: boolean
  sort: SortKey
  page: number
}

const SORTS: SortKey[] = ['published_desc', 'published_asc', 'price_asc', 'price_desc', 'm2_desc', 'price_m2_asc']

const num = (v: string | null) => {
  if (v == null || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) && n >= 0 ? n : null
}
const list = (v: string | null) => (v ? v.split(',').filter(Boolean) : [])

function parse(params: URLSearchParams): Filters {
  const contract = params.get('contract')
  const sort = params.get('sort') as SortKey | null
  const position = params.get('position')
  return {
    contract: contract === 'vendita' || contract === 'affitto' ? contract : null,
    types: list(params.get('types')),
    frazioni: list(params.get('frazioni')),
    sources: list(params.get('sources')),
    position: position === 'certa' || position === 'incerta' ? position : null,
    priceMin: num(params.get('price_min')),
    priceMax: num(params.get('price_max')),
    m2Min: num(params.get('m2_min')),
    roomsMin: num(params.get('rooms_min')),
    q: params.get('q') ?? '',
    hasPrice: params.get('has_price') === '1',
    onlyVisibleArea: params.get('area') === '1',
    sort: sort && SORTS.includes(sort) ? sort : 'published_desc',
    page: Math.max(1, num(params.get('page')) ?? 1),
  }
}

function serialize(f: Filters): URLSearchParams {
  const p = new URLSearchParams()
  if (f.contract) p.set('contract', f.contract)
  if (f.types.length) p.set('types', f.types.join(','))
  if (f.frazioni.length) p.set('frazioni', f.frazioni.join(','))
  if (f.sources.length) p.set('sources', f.sources.join(','))
  if (f.position) p.set('position', f.position)
  if (f.priceMin != null) p.set('price_min', String(f.priceMin))
  if (f.priceMax != null) p.set('price_max', String(f.priceMax))
  if (f.m2Min != null) p.set('m2_min', String(f.m2Min))
  if (f.roomsMin != null) p.set('rooms_min', String(f.roomsMin))
  if (f.q.trim()) p.set('q', f.q.trim())
  if (f.hasPrice) p.set('has_price', '1')
  if (f.onlyVisibleArea) p.set('area', '1')
  if (f.sort !== 'published_desc') p.set('sort', f.sort)
  if (f.page > 1) p.set('page', String(f.page))
  return p
}

/** Query string for the API (filters only, without paging/sorting). */
export function apiFilterQuery(f: Filters, bbox: string | null): URLSearchParams {
  const p = new URLSearchParams()
  if (f.contract) p.set('contract', f.contract)
  if (f.types.length) p.set('types', f.types.join(','))
  if (f.frazioni.length) p.set('frazioni', f.frazioni.join(','))
  if (f.sources.length) p.set('sources', f.sources.join(','))
  if (f.position) p.set('position', f.position)
  if (f.priceMin != null) p.set('price_min', String(f.priceMin))
  if (f.priceMax != null) p.set('price_max', String(f.priceMax))
  if (f.m2Min != null) p.set('m2_min', String(f.m2Min))
  if (f.roomsMin != null) p.set('rooms_min', String(f.roomsMin))
  if (f.q.trim()) p.set('q', f.q.trim())
  if (f.hasPrice) p.set('has_price', 'true')
  if (f.onlyVisibleArea && bbox) p.set('bbox', bbox)
  return p
}

export function useFilters() {
  const [params, setParams] = useSearchParams()
  const filters = useMemo(() => parse(params), [params])

  const update = useCallback(
    (patch: Partial<Filters>) => {
      setParams(
        (prev) => {
          const current = parse(prev)
          // Any change other than the page itself brings the user back to page 1.
          const next = { ...current, ...patch, page: patch.page ?? 1 }
          return serialize(next)
        },
        { replace: patch.page === undefined },
      )
    },
    [setParams],
  )

  const reset = useCallback(() => setParams(new URLSearchParams()), [setParams])

  const activeCount =
    (filters.contract ? 1 : 0) +
    filters.types.length +
    filters.frazioni.length +
    filters.sources.length +
    (filters.position ? 1 : 0) +
    (filters.priceMin != null ? 1 : 0) +
    (filters.priceMax != null ? 1 : 0) +
    (filters.m2Min != null ? 1 : 0) +
    (filters.roomsMin != null ? 1 : 0) +
    (filters.q ? 1 : 0) +
    (filters.hasPrice ? 1 : 0) +
    (filters.onlyVisibleArea ? 1 : 0)

  return { filters, update, reset, activeCount }
}

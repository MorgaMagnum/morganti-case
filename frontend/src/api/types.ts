export type Contract = 'vendita' | 'affitto'
export type GeoPrecision = 'esatta' | 'via' | 'approssimativa' | 'frazione' | 'comune'
export type PositionCertainty = 'certa' | 'incerta'
export type SortKey = 'published_desc' | 'published_asc' | 'price_asc' | 'price_desc' | 'm2_desc' | 'price_m2_asc'

export interface Envelope<T> {
  success: boolean
  data: T | null
  error: string | null
  meta: { total: number; page: number; size: number } | null
}

export interface ListingSummary {
  id: number
  contract: Contract
  property_type: string
  title: string
  price: number | null
  price_per_m2: number | null
  surface_m2: number | null
  rooms: number | null
  bathrooms: number | null
  address: string | null
  frazione: string | null
  lat: number | null
  lng: number | null
  geo_precision: GeoPrecision
  position_certain: boolean
  agency_name: string | null
  cover_url: string | null
  sources: string[]
  published_at: string
  published_is_estimate: boolean
  is_active: boolean
}

export interface SourceRef {
  source: string
  label: string
  url: string
  price: number | null
  agency_name: string | null
  last_seen_at: string
  is_active: boolean
}

export interface ListingDetail extends ListingSummary {
  description: string | null
  floor: string | null
  first_seen_at: string
  last_seen_at: string
  images: { id: number; url: string; caption: string | null }[]
  links: SourceRef[]
}

export interface MapMarker {
  id: number
  lat: number
  lng: number
  contract: Contract
  property_type: string
  price: number | null
  geo_precision: GeoPrecision
  position_certain: boolean
}

export interface FacetCount {
  value: string
  count: number
}

export interface Facets {
  property_types: FacetCount[]
  frazioni: FacetCount[]
  sources: FacetCount[]
  contracts: FacetCount[]
  positions: FacetCount[]
  total_active: number
  last_update: string | null
}

export interface RunInfo {
  source: string
  label: string
  contract: Contract
  status: 'running' | 'ok' | 'error'
  started_at: string
  finished_at: string | null
  pages: number
  found: number
  new: number
  updated: number
  skipped: number
  error: string | null
}

export interface ScrapeStatus {
  running: boolean
  runs: RunInfo[]
}

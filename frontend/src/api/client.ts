import type {
  Envelope,
  Facets,
  ListingDetail,
  ListingSummary,
  MapMarker,
  ScrapeMode,
  ScrapeStatus,
} from './types'

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<Envelope<T>> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch {
    throw new ApiError('Il server non risponde. È avviato il backend?')
  }
  let body: Envelope<T>
  try {
    body = (await res.json()) as Envelope<T>
  } catch {
    throw new ApiError(`Risposta non valida dal server (HTTP ${res.status})`)
  }
  if (!res.ok || !body.success) {
    throw new ApiError(body.error ?? `Errore HTTP ${res.status}`)
  }
  return body
}

export const api = {
  listings: (query: URLSearchParams) => request<ListingSummary[]>(`/api/listings?${query}`),
  markers: (query: URLSearchParams) => request<MapMarker[]>(`/api/listings/markers?${query}`),
  listing: (id: number) => request<ListingDetail>(`/api/listings/${id}`),
  facets: () => request<Facets>('/api/facets'),
  scrapeStatus: () => request<ScrapeStatus>('/api/scrape/status'),
  startScrape: (mode: ScrapeMode) => request<ScrapeStatus>(`/api/scrape?mode=${mode}`, { method: 'POST' }),
}

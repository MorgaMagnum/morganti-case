import type { Contract, GeoPrecision } from '../api/types'

const euro = new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })
const number = new Intl.NumberFormat('it-IT')
const relative = new Intl.RelativeTimeFormat('it-IT', { numeric: 'auto' })
const dateFmt = new Intl.DateTimeFormat('it-IT', { day: 'numeric', month: 'long', year: 'numeric' })
const dateTimeFmt = new Intl.DateTimeFormat('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

export function formatPrice(price: number | null, contract: Contract): string {
  if (price == null) return 'Prezzo su richiesta'
  return contract === 'affitto' ? `${euro.format(price)}/mese` : euro.format(price)
}

export function formatCompactPrice(price: number | null, contract: Contract): string {
  if (price == null) return '—'
  if (contract === 'affitto') return `${number.format(price)} €`
  if (price >= 1_000_000) return `${(price / 1_000_000).toLocaleString('it-IT', { maximumFractionDigits: 1 })} M€`
  return `${Math.round(price / 1000)} k€`
}

export const formatNumber = (n: number) => number.format(n)
export const formatDate = (iso: string) => dateFmt.format(new Date(iso))
export const formatDateTime = (iso: string) => dateTimeFmt.format(new Date(iso))

export function timeAgo(iso: string): string {
  const days = Math.round((new Date(iso).getTime() - Date.now()) / 86_400_000)
  if (Math.abs(days) < 1) return 'oggi'
  if (Math.abs(days) < 31) return relative.format(days, 'day')
  const months = Math.round(days / 30)
  if (Math.abs(months) < 12) return relative.format(months, 'month')
  return relative.format(Math.round(days / 365), 'year')
}

export const CONTRACT_LABEL: Record<Contract, string> = { vendita: 'Vendita', affitto: 'Affitto' }

export const PRECISION_LABEL: Record<GeoPrecision, string> = {
  esatta: 'Indirizzo esatto',
  via: 'Posizione della via',
  approssimativa: 'Posizione approssimativa',
  frazione: 'Solo frazione',
  comune: 'Posizione non indicata',
}

/** Scraped URLs are untrusted: only allow http(s) links. */
export function safeHttpUrl(url: string | null | undefined): string | null {
  if (!url) return null
  try {
    const parsed = new URL(url, window.location.origin)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null
  } catch {
    return null
  }
}

export function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

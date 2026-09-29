import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { Circle, MapContainer, Marker, TileLayer } from 'react-leaflet'
import L from 'leaflet'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import Gallery from '../components/Gallery'
import {
  capitalize,
  CONTRACT_LABEL,
  formatDate,
  formatNumber,
  formatPrice,
  PRECISION_LABEL,
  safeHttpUrl,
  timeAgo,
} from '../lib/format'

const APPROX_RADIUS_M = { approssimativa: 400, frazione: 700 } as const

export default function ListingPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const listingId = Number(id)
  const query = useQuery({
    queryKey: ['listing', listingId],
    queryFn: () => api.listing(listingId),
    enabled: Number.isInteger(listingId) && listingId > 0,
  })

  const back = () => (window.history.length > 1 ? navigate(-1) : navigate('/'))
  const detail = query.data?.data
  const markerIcon = useMemo(
    () =>
      detail
        ? L.divIcon({
            className: `mk mk-${detail.contract} mk-hl`,
            html: '<span></span>',
            iconSize: [28, 28],
            iconAnchor: [14, 14],
          })
        : null,
    [detail],
  )

  if (query.isLoading) return <main className="page-narrow muted">Carico l’annuncio…</main>
  if (query.error || !query.data?.data) {
    return (
      <main className="page-narrow">
        <div className="notice notice-error">{(query.error as Error | null)?.message ?? 'Annuncio non trovato'}</div>
        <Link to="/">← Torna alla ricerca</Link>
      </main>
    )
  }

  const l = query.data.data
  const approx = !l.position_certain
  const noPosition = l.geo_precision === 'comune'
  const facts: [string, string | null][] = [
    ['Prezzo', formatPrice(l.price, l.contract)],
    ['Prezzo al m²', l.price_per_m2 ? `${formatNumber(l.price_per_m2)} €/m²` : null],
    ['Superficie', l.surface_m2 ? `${formatNumber(l.surface_m2)} m²` : null],
    ['Locali', l.rooms ? String(l.rooms) : null],
    ['Bagni', l.bathrooms ? String(l.bathrooms) : null],
    ['Piano', l.floor],
    ['Tipologia', capitalize(l.property_type)],
    ['Frazione', l.frazione],
    ['Indirizzo', l.address],
  ]

  const privateLinks = l.links.filter((s) => s.is_active && s.is_private)
  const ownerAlsoAdvertises = privateLinks.length > 0 && l.links.some((s) => s.is_active && !s.is_private)

  return (
    <main className="detail">
      <button type="button" className="link-btn back" onClick={back}>
        ← Torna ai risultati
      </button>

      <div className="detail-head">
        <div>
          <div className="detail-badges">
            <span className={`badge badge-${l.contract}`}>{CONTRACT_LABEL[l.contract]}</span>
            <span className="badge badge-neutral">{capitalize(l.property_type)}</span>
            {l.has_private && <span className="badge badge-private">Privato</span>}
            {!l.is_active && <span className="badge badge-gone">Non più online</span>}
          </div>
          <h1>{l.title}</h1>
          <p className="muted">
            {[l.address, l.frazione, 'Cascina (PI)'].filter(Boolean).join(' · ')}
          </p>
        </div>
        <div className="detail-price">
          {formatPrice(l.price, l.contract)}
          {l.price_per_m2 && l.contract === 'vendita' && <span>{formatNumber(l.price_per_m2)} €/m²</span>}
        </div>
      </div>

      <div className="detail-grid">
        <div className="detail-main">
          <Gallery images={l.images} title={l.title} />

          <section className="panel">
            <h2>Caratteristiche</h2>
            <dl className="facts">
              {facts
                .filter(([, v]) => v)
                .map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
            </dl>
          </section>

          {l.description && (
            <section className="panel">
              <h2>Descrizione</h2>
              <p className="description">{l.description}</p>
            </section>
          )}
        </div>

        <aside className="detail-side">
          <section className="panel">
            <h2>{l.links.length > 1 ? `Pubblicato su ${l.links.length} siti` : 'Annuncio originale'}</h2>
            {ownerAlsoAdvertises && (
              <p className="owner-note">
                Il proprietario pubblica questo immobile anche direttamente su{' '}
                <strong>{privateLinks.map((s) => s.label).join(', ')}</strong>: puoi contattarlo da quell’annuncio,
                senza passare dall’agenzia.
              </p>
            )}
            <ul className="links">
              {l.links.map((s) => (
                <li key={s.url} className={s.is_active ? '' : 'is-inactive'}>
                  <div>
                    <strong>
                      {s.label}
                      {s.is_private && <span className="badge badge-private">Privato</span>}
                    </strong>
                    <span className="muted">
                      {s.agency_name ?? 'Inserzionista non indicato'}
                      {s.price != null && ` · ${formatPrice(s.price, l.contract)}`}
                    </span>
                    <span className="muted small">
                      {s.is_active ? `visto ${timeAgo(s.last_seen_at)}` : 'non più online'}
                    </span>
                  </div>
                  {safeHttpUrl(s.url) && (
                    <a className="btn btn-primary" href={safeHttpUrl(s.url)!} target="_blank" rel="noopener noreferrer">
                      Vedi annuncio ↗
                    </a>
                  )}
                </li>
              ))}
            </ul>
          </section>

          <section className="panel">
            <h2>Posizione</h2>
            <p className={`position-status ${l.position_certain ? 'is-certain' : 'is-uncertain'}`}>
              <span className={`swatch swatch-${l.position_certain ? 'certa' : 'incerta'}`} aria-hidden>
                {l.position_certain ? '' : '?'}
              </span>
              <span>
                <strong>{l.position_certain ? 'Posizione certa' : 'Posizione incerta'}</strong>
                <span className="muted small">
                  {noPosition
                    ? 'Il portale non indica dove si trova l’immobile: controlla l’annuncio originale o chiedi all’agenzia.'
                    : PRECISION_LABEL[l.geo_precision]}
                </span>
              </span>
            </p>
          {l.lat != null && l.lng != null && !noPosition && (
              <div className="mini-map">
                <MapContainer center={[l.lat, l.lng]} zoom={approx ? 14 : 16} scrollWheelZoom={false} className="map">
                  <TileLayer
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                  />
                  {approx ? (
                    <Circle
                      center={[l.lat, l.lng]}
                      radius={APPROX_RADIUS_M[l.geo_precision as keyof typeof APPROX_RADIUS_M] ?? 500}
                      pathOptions={{ color: l.contract === 'vendita' ? '#2457d6' : '#e0671f', dashArray: '6 6', weight: 2 }}
                    />
                  ) : (
                    markerIcon && <Marker position={[l.lat, l.lng]} icon={markerIcon} />
                  )}
                </MapContainer>
              </div>
          )}
          </section>

          <section className="panel dates">
            <div>
              <span className="muted">{l.published_is_estimate ? 'Trovato il' : 'Pubblicato il'}</span>
              <strong>{formatDate(l.published_at)}</strong>
            </div>
            <div>
              <span className="muted">Ultima verifica</span>
              <strong>{formatDate(l.last_seen_at)}</strong>
            </div>
          </section>
        </aside>
      </div>
    </main>
  )
}

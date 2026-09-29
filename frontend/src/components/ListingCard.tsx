import { memo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ListingSummary } from '../api/types'
import { SOURCE_LABELS } from '../lib/sources'
import { capitalize, formatNumber, formatPrice, PRECISION_LABEL, timeAgo } from '../lib/format'

interface Props {
  listing: ListingSummary
  onHover: (id: number | null) => void
}

function ListingCard({ listing: l, onHover }: Props) {
  const [imgFailed, setImgFailed] = useState(false)
  const facts = [
    l.surface_m2 ? `${formatNumber(l.surface_m2)} m²` : null,
    l.rooms ? `${l.rooms} ${l.rooms === 1 ? 'locale' : 'locali'}` : null,
    l.bathrooms ? `${l.bathrooms} ${l.bathrooms === 1 ? 'bagno' : 'bagni'}` : null,
  ].filter(Boolean)

  return (
    <Link
      to={`/immobile/${l.id}`}
      className={`card ${l.is_active ? '' : 'is-inactive'}`}
      onMouseEnter={() => onHover(l.id)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(l.id)}
      onBlur={() => onHover(null)}
    >
      <div className="card-media">
        {l.cover_url && !imgFailed ? (
          <img src={l.cover_url} alt="" loading="lazy" onError={() => setImgFailed(true)} />
        ) : (
          <div className="card-noimg">Nessuna foto</div>
        )}
        <span className={`badge badge-${l.contract}`}>{l.contract === 'vendita' ? 'Vendita' : 'Affitto'}</span>
        {!l.is_active && <span className="badge badge-gone">Non più online</span>}
        {!l.position_certain && (
          <span className="badge badge-uncertain" title={PRECISION_LABEL[l.geo_precision]}>
            ? Posizione incerta
          </span>
        )}
      </div>
      <div className="card-body">
        <div className="card-price">
          {formatPrice(l.price, l.contract)}
          {l.price_per_m2 && l.contract === 'vendita' && (
            <span className="card-ppm">{formatNumber(l.price_per_m2)} €/m²</span>
          )}
        </div>
        <div className="card-type">
          {capitalize(l.property_type)}
          {l.frazione && <> · {l.frazione}</>}
        </div>
        <h3 className="card-title">{l.title}</h3>
        {facts.length > 0 && <div className="card-facts">{facts.join(' · ')}</div>}
        <div className="card-foot">
          <span className="sources">
            {l.sources.map((s) => (
              <span key={s} className={`src src-${s}`}>
                {SOURCE_LABELS[s] ?? s}
              </span>
            ))}
          </span>
          <span className="muted" title={l.published_is_estimate ? 'Data in cui l’annuncio è stato trovato' : 'Data di pubblicazione'}>
            {l.published_is_estimate ? 'visto ' : ''}
            {timeAgo(l.published_at)}
          </span>
        </div>
      </div>
    </Link>
  )
}

export default memo(ListingCard)

import type { Contract, PositionCertainty } from '../api/types'
import { CONTRACT_LABEL } from '../lib/format'

interface Props {
  contract: Contract | null
  position: PositionCertainty | null
  counts: Record<Contract, number>
  positionCounts: Record<PositionCertainty, number>
  unplaced: number
  onToggle: (c: Contract) => void
  onPositionToggle: (p: PositionCertainty) => void
}

const POSITION_INFO: Record<PositionCertainty, { label: string; hint: string }> = {
  certa: { label: 'Posizione certa', hint: 'Indirizzo esatto o via indicata dal portale' },
  incerta: { label: 'Posizione incerta', hint: 'Solo zona, frazione o nessuna indicazione: il punto è indicativo' },
}

export default function Legend({ contract, position, counts, positionCounts, unplaced, onToggle, onPositionToggle }: Props) {
  return (
    <div className="legend" aria-label="Legenda">
      <div className="legend-row">
        {(['vendita', 'affitto'] as const).map((c) => {
          const visible = contract === null || contract === c
          return (
            <button
              key={c}
              type="button"
              className={`legend-item ${visible ? '' : 'is-off'}`}
              onClick={() => onToggle(c)}
              aria-pressed={visible}
              title={visible ? `Nascondi ${c}` : `Mostra ${c}`}
            >
              <span className={`swatch swatch-${c}`} aria-hidden />
              {CONTRACT_LABEL[c]}
              <span className="count">{counts[c]}</span>
            </button>
          )
        })}
      </div>
      <div className="legend-row">
        {(['certa', 'incerta'] as const).map((p) => {
          const visible = position === null || position === p
          return (
            <button
              key={p}
              type="button"
              className={`legend-item ${visible ? '' : 'is-off'}`}
              onClick={() => onPositionToggle(p)}
              aria-pressed={visible}
              title={POSITION_INFO[p].hint}
            >
              <span className={`swatch swatch-${p}`} aria-hidden>
                {p === 'incerta' ? '?' : ''}
              </span>
              {POSITION_INFO[p].label}
              <span className="count">{positionCounts[p]}</span>
            </button>
          )
        })}
      </div>
      {unplaced > 0 && (
        <p className="legend-note">
          {unplaced} {unplaced === 1 ? 'immobile' : 'immobili'} senza alcuna posizione: solo nella lista
        </p>
      )}
    </div>
  )
}

import { useCallback, useEffect, useRef, useState } from 'react'

interface Image {
  id: number
  url: string
  caption: string | null
}

export default function Gallery({ images, title }: { images: Image[]; title: string }) {
  const [index, setIndex] = useState(0)
  const [lightbox, setLightbox] = useState(false)
  const count = images.length

  const go = useCallback((delta: number) => setIndex((i) => (i + delta + count) % count), [count])

  const dialogRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!lightbox) return
    const opener = document.activeElement as HTMLElement | null
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setLightbox(false)
      if (e.key === 'ArrowRight') go(1)
      if (e.key === 'ArrowLeft') go(-1)
      if (e.key === 'Tab' && dialogRef.current) {
        // Keep keyboard focus inside the dialog.
        const buttons = [...dialogRef.current.querySelectorAll<HTMLButtonElement>('button')]
        const first = buttons[0]
        const last = buttons[buttons.length - 1]
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
      opener?.focus()
    }
  }, [lightbox, go])

  if (count === 0) return <div className="gallery-empty">Nessuna foto disponibile</div>

  const current = images[index]
  return (
    <div className="gallery">
      <div className="gallery-main">
        <button type="button" className="gallery-open" onClick={() => setLightbox(true)} aria-label="Apri a schermo intero">
          <img src={current.url} alt={current.caption ?? `${title}, foto ${index + 1}`} />
        </button>
        {count > 1 && (
          <>
            <button type="button" className="nav prev" onClick={() => go(-1)} aria-label="Foto precedente">‹</button>
            <button type="button" className="nav next" onClick={() => go(1)} aria-label="Foto successiva">›</button>
          </>
        )}
        <span className="gallery-counter">
          {index + 1} / {count}
        </span>
      </div>
      {count > 1 && (
        <div className="thumbs">
          {images.map((img, i) => (
            <button key={img.id} type="button" className={i === index ? 'active' : ''} onClick={() => setIndex(i)} aria-label={`Foto ${i + 1}`}>
              <img src={img.url} alt="" loading="lazy" />
            </button>
          ))}
        </div>
      )}

      {lightbox && (
        <div ref={dialogRef} className="lightbox" role="dialog" aria-modal="true" aria-label="Galleria foto" onClick={() => setLightbox(false)}>
          <img src={current.url} alt={current.caption ?? ''} onClick={(e) => e.stopPropagation()} />
          <button ref={closeRef} type="button" className="lb-close" onClick={() => setLightbox(false)} aria-label="Chiudi">×</button>
          {count > 1 && (
            <>
              <button type="button" className="nav prev" onClick={(e) => { e.stopPropagation(); go(-1) }} aria-label="Foto precedente">‹</button>
              <button type="button" className="nav next" onClick={(e) => { e.stopPropagation(); go(1) }} aria-label="Foto successiva">›</button>
            </>
          )}
          <span className="gallery-counter">
            {index + 1} / {count}
          </span>
        </div>
      )}
    </div>
  )
}

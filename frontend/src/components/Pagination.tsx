interface Props {
  page: number
  totalPages: number
  onPage: (page: number) => void
}

function pageWindow(page: number, total: number): (number | '…')[] {
  const pages = new Set([1, total, page - 1, page, page + 1].filter((p) => p >= 1 && p <= total))
  const sorted = [...pages].sort((a, b) => a - b)
  const out: (number | '…')[] = []
  sorted.forEach((p, i) => {
    if (i > 0 && p - sorted[i - 1] > 1) out.push('…')
    out.push(p)
  })
  return out
}

export default function Pagination({ page, totalPages, onPage }: Props) {
  if (totalPages <= 1) return null
  return (
    <nav className="pagination" aria-label="Pagine">
      <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        ← Precedente
      </button>
      {pageWindow(page, totalPages).map((p, i) =>
        p === '…' ? (
          <span key={`gap-${i}`} className="gap">
            …
          </span>
        ) : (
          <button key={p} type="button" className={p === page ? 'current' : ''} aria-current={p === page ? 'page' : undefined} onClick={() => onPage(p)}>
            {p}
          </button>
        ),
      )}
      <button type="button" disabled={page >= totalPages} onClick={() => onPage(page + 1)}>
        Successiva →
      </button>
    </nav>
  )
}

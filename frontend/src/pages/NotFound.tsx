import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <main className="page-narrow">
      <h1>Pagina non trovata</h1>
      <p>
        <Link to="/">Torna alla ricerca</Link>
      </p>
    </main>
  )
}

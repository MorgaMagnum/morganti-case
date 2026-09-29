import { Route, Routes } from 'react-router-dom'
import Header from './components/Header'
import HomePage from './pages/HomePage'
import ListingPage from './pages/ListingPage'
import NotFound from './pages/NotFound'

export default function App() {
  return (
    <div className="app">
      <Header />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/immobile/:id" element={<ListingPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </div>
  )
}

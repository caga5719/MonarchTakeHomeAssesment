import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import GLSpend from './pages/GLSpend'
import ItemsPerGL from './pages/ItemsPerGL'
import ItemsPerProperty from './pages/ItemsPerProperty'
import ErrorBoundary from './components/ErrorBoundary'

function Nav() {
  return (
    <nav className="top-nav">
      <span className="nav-brand">Monarch Invoices</span>
      <div className="nav-links">
        <NavLink to="/" end className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
          GL Spend
        </NavLink>
        <NavLink to="/items-per-gl" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
          Items Per GL
        </NavLink>
        <NavLink to="/items-per-property" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
          Items Per Property
        </NavLink>
        <NavLink to="/invoices" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
          Invoice Explorer
        </NavLink>
        <NavLink to="/mismatches" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
          Mismatches
        </NavLink>
      </div>
    </nav>
  )
}

function Placeholder({ title }: { title: string }) {
  return (
    <div className="page">
      <h1 className="page-title">{title}</h1>
      <p style={{ color: '#64748b' }}>Coming in Phase 6.</p>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Nav />
      <main className="main-content">
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<GLSpend />} />
            <Route path="/items-per-gl" element={<ItemsPerGL />} />
            <Route path="/items-per-property" element={<ItemsPerProperty />} />
            <Route path="/invoices" element={<Placeholder title="Invoice Explorer" />} />
            <Route path="/mismatches" element={<Placeholder title="GL Mismatches" />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </BrowserRouter>
  )
}

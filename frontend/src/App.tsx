import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'

function Placeholder({ title }: { title: string }) {
  return (
    <div style={{ padding: '2rem' }}>
      <h2>{title}</h2>
      <p>Coming in Phase 5.</p>
    </div>
  )
}

function Nav() {
  const linkStyle = ({ isActive }: { isActive: boolean }): React.CSSProperties => ({
    marginRight: '1rem',
    fontWeight: isActive ? 'bold' : 'normal',
    textDecoration: 'none',
    color: isActive ? '#0ea5e9' : '#334155',
  })
  return (
    <nav style={{ padding: '1rem 2rem', borderBottom: '1px solid #e2e8f0', display: 'flex', gap: '0.5rem' }}>
      <NavLink to="/" end style={linkStyle}>GL Spend</NavLink>
      <NavLink to="/items-per-gl" style={linkStyle}>Items Per GL</NavLink>
      <NavLink to="/items-per-property" style={linkStyle}>Items Per Property</NavLink>
      <NavLink to="/invoices" style={linkStyle}>Invoice Explorer</NavLink>
      <NavLink to="/mismatches" style={linkStyle}>Mismatches</NavLink>
    </nav>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Nav />
      <Routes>
        <Route path="/" element={<Placeholder title="GL Spend Breakdown" />} />
        <Route path="/items-per-gl" element={<Placeholder title="Items Per GL" />} />
        <Route path="/items-per-property" element={<Placeholder title="Items Per Property" />} />
        <Route path="/invoices" element={<Placeholder title="Invoice Explorer" />} />
        <Route path="/mismatches" element={<Placeholder title="GL Mismatches" />} />
      </Routes>
    </BrowserRouter>
  )
}

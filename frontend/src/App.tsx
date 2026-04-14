import { BrowserRouter, Routes, Route, NavLink, Navigate, Outlet } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import GLSpend from './pages/GLSpend'
import ItemsPerGL from './pages/ItemsPerGL'
import ItemsPerProperty from './pages/ItemsPerProperty'
import InvoiceExplorer from './pages/InvoiceExplorer'
import Mismatches from './pages/Mismatches'
import Login from './pages/Login'
import ErrorBoundary from './components/ErrorBoundary'

// ── Top navigation ─────────────────────────────────────────────────────────────

function Nav() {
  const { user, logout } = useAuth()
  const isAdmin = user?.role === 'admin'

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
        {isAdmin && (
          <NavLink to="/items-per-property" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            Items Per Property
          </NavLink>
        )}
        <NavLink to="/invoices" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
          Invoice Explorer
        </NavLink>
        <NavLink to="/mismatches" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
          Mismatches
        </NavLink>
      </div>
      {user && (
        <div className="nav-user">
          <span className="nav-user-name">{user.sub}</span>
          {user.role && <span className="nav-user-role">{user.role}</span>}
          <button className="nav-logout-btn" onClick={logout}>Sign out</button>
        </div>
      )}
    </nav>
  )
}

// ── Protected layout (renders Nav + Outlet, redirects to /login if unauthenticated) ──

function ProtectedLayout() {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  return (
    <>
      <Nav />
      <main className="main-content">
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
    </>
  )
}

// ── App ────────────────────────────────────────────────────────────────────────

function AppRoutes() {
  const { user } = useAuth()

  return (
    <Routes>
      {/* Public — redirect to dashboard if already logged in */}
      <Route
        path="/login"
        element={user ? <Navigate to="/" replace /> : <Login />}
      />

      {/* Protected — all dashboard pages share the Nav + main layout */}
      <Route element={<ProtectedLayout />}>
        <Route path="/" element={<GLSpend />} />
        <Route path="/items-per-gl" element={<ItemsPerGL />} />
        <Route path="/items-per-property" element={<ItemsPerProperty />} />
        <Route path="/invoices" element={<InvoiceExplorer />} />
        <Route path="/mismatches" element={<Mismatches />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}

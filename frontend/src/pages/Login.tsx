import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { loginUser, registerUser } from '../api'

type Mode = 'login' | 'register'

const ROLES = ['admin', 'manager', 'operations'] as const

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()

  const [mode, setMode] = useState<Mode>('login')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Shared fields
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  // Register-only fields
  const [name, setName] = useState('')
  const [role, setRole] = useState<string>('admin')
  const [propertyCode, setPropertyCode] = useState('')

  function switchMode(next: Mode) {
    setMode(next)
    setError(null)
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)

    if (mode === 'register') {
      const needsProperty = role === 'manager' || role === 'operations'
      if (needsProperty && !propertyCode.trim()) {
        setError('Property code is required for manager and operations roles.')
        return
      }
    }

    setLoading(true)
    try {
      if (mode === 'login') {
        const token = await loginUser(username, password)
        login(token)
        navigate('/', { replace: true })
      } else {
        await registerUser({
          username,
          password,
          name,
          role: role || null,
          property_code: propertyCode.trim() || null,
        })
        // Auto sign-in after registration
        const token = await loginUser(username, password)
        login(token)
        navigate('/', { replace: true })
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  const needsProperty = mode === 'register' && (role === 'manager' || role === 'operations')

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-header">
          <span className="login-brand">Monarch Invoice Classifier</span>
        </div>

        {/* Tab toggle */}
        <div className="login-tabs">
          <button
            type="button"
            className={`login-tab${mode === 'login' ? ' login-tab-active' : ''}`}
            onClick={() => switchMode('login')}
          >
            Sign in
          </button>
          <button
            type="button"
            className={`login-tab${mode === 'register' ? ' login-tab-active' : ''}`}
            onClick={() => switchMode('register')}
          >
            Create account
          </button>
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          {mode === 'register' && (
            <div className="login-field">
              <label className="login-label" htmlFor="name">Display name</label>
              <input
                id="name"
                type="text"
                className="filter-input"
                value={name}
                onChange={e => setName(e.target.value)}
                autoComplete="name"
                required
              />
            </div>
          )}

          <div className="login-field">
            <label className="login-label" htmlFor="username">Username</label>
            <input
              id="username"
              type="text"
              className="filter-input"
              value={username}
              onChange={e => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              required
            />
          </div>

          <div className="login-field">
            <label className="login-label" htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              className="filter-input"
              value={password}
              onChange={e => setPassword(e.target.value)}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              required
            />
          </div>

          {mode === 'register' && (
            <>
              <div className="login-field">
                <label className="login-label" htmlFor="role">Role</label>
                <select
                  id="role"
                  className="filter-input"
                  value={role}
                  onChange={e => setRole(e.target.value)}
                  required
                >
                  {ROLES.map(r => (
                    <option key={r} value={r}>
                      {r.charAt(0).toUpperCase() + r.slice(1)}
                    </option>
                  ))}
                </select>
              </div>

              <div className="login-field">
                <label className="login-label" htmlFor="propertyCode">
                  Property code{needsProperty ? '' : ' (optional)'}
                </label>
                <input
                  id="propertyCode"
                  type="text"
                  className="filter-input"
                  value={propertyCode}
                  onChange={e => setPropertyCode(e.target.value.toUpperCase())}
                  placeholder="e.g. BPOH"
                  required={needsProperty}
                />
                <span className="login-field-hint">
                  {needsProperty
                    ? 'Required — this user will only see data for this property.'
                    : 'Admins see all properties. Leave blank for full access.'}
                </span>
              </div>
            </>
          )}

          {error && <p className="login-error">{error}</p>}

          <button type="submit" className="login-btn" disabled={loading}>
            {loading
              ? (mode === 'login' ? 'Signing in…' : 'Creating account…')
              : (mode === 'login' ? 'Sign in' : 'Create account')}
          </button>
        </form>
      </div>
    </div>
  )
}

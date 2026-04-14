import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { jwtDecode } from 'jwt-decode'

const TOKEN_KEY = 'jwt_token'

export interface AuthUser {
  user_id: number
  sub: string        // username
  name?: string      // not in JWT payload, loaded separately if needed
  role: string | null
  property_code: string | null
  exp: number
}

interface AuthContextType {
  user: AuthUser | null
  token: string | null
  login: (token: string) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

function decodeToken(token: string): AuthUser | null {
  try {
    const decoded = jwtDecode<AuthUser>(token)
    // Reject if already expired
    if (decoded.exp * 1000 < Date.now()) return null
    return decoded
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState<AuthUser | null>(() => {
    const t = localStorage.getItem(TOKEN_KEY)
    return t ? decodeToken(t) : null
  })

  // If the stored token was already expired on mount, clear it
  useEffect(() => {
    if (token && !user) {
      localStorage.removeItem(TOKEN_KEY)
      setToken(null)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function login(newToken: string) {
    const decoded = decodeToken(newToken)
    if (!decoded) return
    localStorage.setItem(TOKEN_KEY, newToken)
    setToken(newToken)
    setUser(decoded)
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, token, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

export { TOKEN_KEY }

'use client'
import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from 'react'
import { api, storeToken, clearToken, ApiError } from '@/lib/api'
import type { User } from '@/lib/types'

interface AuthContextValue {
  user: User | null
  loading: boolean
  loginWithCredentials: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  loading: true,
  loginWithCredentials: async () => {},
  logout: () => {},
})

const TOKEN_KEY = 'ppc_os_token'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  // On mount: check if a stored token is still valid
  useEffect(() => {
    const stored = typeof window !== 'undefined' ? localStorage.getItem(TOKEN_KEY) : null
    if (!stored) {
      setLoading(false)
      return
    }
    api.me()
      .then(u => setUser(u))
      .catch(() => clearToken())          // token expired or invalid — clear it
      .finally(() => setLoading(false))
  }, [])

  const loginWithCredentials = useCallback(async (email: string, password: string) => {
    const { access_token } = await api.login(email, password)
    storeToken(access_token)             // store before calling me()
    const u = await api.me()
    setUser(u)
  }, [])

  const logout = useCallback(() => {
    clearToken()
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, loginWithCredentials, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}

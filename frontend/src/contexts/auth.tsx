import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { authApi } from '../lib/api'
import { SESSION_EXPIRED_EVENT, tokens } from '../lib/tokens'
import type { UserRead } from '../lib/types'

interface AuthContextValue {
  user: UserRead | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (data: {
    email: string
    password: string
    full_name?: string
  }) => Promise<void>
  logout: () => Promise<void>
  updateProfile: (data: { email?: string; full_name?: string }) => Promise<void>
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserRead | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    async function bootstrap() {
      if (!tokens.hasSession()) {
        setLoading(false)
        return
      }
      try {
        const me = await authApi.me()
        if (!cancelled) setUser(me)
      } catch {
        tokens.clear()
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void bootstrap()

    const onExpired = () => setUser(null)
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired)
    return () => {
      cancelled = true
      window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired)
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const pair = await authApi.login(email, password)
    tokens.set(pair)
    try {
      const me = await authApi.me()
      setUser(me)
    } catch (error) {
      tokens.clear()
      throw error
    }
  }, [])

  const register = useCallback(
    async (data: { email: string; password: string; full_name?: string }) => {
      await authApi.register(data)
      await login(data.email, data.password)
    },
    [login],
  )

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {
      tokens.clear()
    } finally {
      setUser(null)
    }
  }, [])

  const updateProfile = useCallback(async (data: { email?: string; full_name?: string }) => {
    const updated = await authApi.updateMe(data)
    setUser(updated)
  }, [])

  const refreshUser = useCallback(async () => {
    const me = await authApi.me()
    setUser(me)
  }, [])

  // Any 401 that survives the refresh retry tears the session down globally.
  useEffect(() => {
    const onExpired = () => setUser(null)
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired)
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({ user, loading, login, register, logout, updateProfile, refreshUser }),
    [user, loading, login, register, logout, updateProfile, refreshUser],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}

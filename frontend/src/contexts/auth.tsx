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
import type { TokenPair, UserRead } from '../lib/types'

export type LoginOutcome =
  | { mfaRequired: false }
  | { mfaRequired: true; mfaToken: string }

interface AuthContextValue {
  user: UserRead | null
  loading: boolean
  login: (email: string, password: string) => Promise<LoginOutcome>
  verifyMfa: (mfaToken: string, code: string) => Promise<void>
  loginWithOtp: (email: string, code: string) => Promise<void>
  completeOAuth: (code: string) => Promise<void>
  register: (data: {
    email: string
    password: string
    full_name?: string
    code: string
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

  // Stores a fresh token pair and hydrates the profile; any failure clears
  // the half-established session so the app never runs with stale identity.
  const applyTokens = useCallback(async (pair: TokenPair) => {
    tokens.set(pair)
    try {
      const me = await authApi.me()
      setUser(me)
    } catch (error) {
      tokens.clear()
      throw error
    }
  }, [])

  const login = useCallback(
    async (email: string, password: string): Promise<LoginOutcome> => {
      const response = await authApi.login(email, password)
      if ('mfa_required' in response) {
        return { mfaRequired: true, mfaToken: response.mfa_token }
      }
      await applyTokens(response)
      return { mfaRequired: false }
    },
    [applyTokens],
  )

  const verifyMfa = useCallback(
    async (mfaToken: string, code: string) => {
      await applyTokens(await authApi.verifyMfa(mfaToken, code))
    },
    [applyTokens],
  )

  const loginWithOtp = useCallback(
    async (email: string, code: string) => {
      await applyTokens(await authApi.verifyOtp(email, code))
    },
    [applyTokens],
  )

  const completeOAuth = useCallback(
    async (code: string) => {
      await applyTokens(await authApi.exchangeOAuthCode(code))
    },
    [applyTokens],
  )

  const register = useCallback(
    async (data: {
      email: string
      password: string
      full_name?: string
      code: string
    }) => {
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
    () => ({
      user,
      loading,
      login,
      verifyMfa,
      loginWithOtp,
      completeOAuth,
      register,
      logout,
      updateProfile,
      refreshUser,
    }),
    [
      user,
      loading,
      login,
      verifyMfa,
      loginWithOtp,
      completeOAuth,
      register,
      logout,
      updateProfile,
      refreshUser,
    ],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}

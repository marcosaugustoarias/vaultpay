import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, refreshAccessToken, setSessionExpiredHandler, tokenStore } from '../lib/api'
import type { LoginResult, User } from '../lib/types'

type Status = 'loading' | 'authenticated' | 'anonymous'

interface AuthState {
  status: Status
  user: User | null
  login: (email: string, password: string) => Promise<LoginResult>
  verifyMfa: (mfaToken: string, code: string) => Promise<void>
  logout: (reason?: string) => Promise<void>
  reloadUser: () => Promise<void>
  notice: string | null
  clearNotice: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading')
  const [user, setUser] = useState<User | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const reloadUser = useCallback(async () => {
    setUser(await api<User>('/auth/me'))
  }, [])

  const dropSession = useCallback((reason?: string) => {
    tokenStore.set(null)
    setUser(null)
    setStatus('anonymous')
    if (reason) setNotice(reason)
  }, [])

  // On load, try to resume the session from the HttpOnly refresh cookie.
  useEffect(() => {
    let cancelled = false
    setSessionExpiredHandler(() => dropSession('Tu sesión expiró. Volvé a iniciar sesión.'))
    ;(async () => {
      const token = await refreshAccessToken()
      if (cancelled) return
      if (!token) return setStatus('anonymous')
      try {
        await reloadUser()
        if (!cancelled) setStatus('authenticated')
      } catch {
        if (!cancelled) dropSession()
      }
    })()
    return () => {
      cancelled = true
      setSessionExpiredHandler(null)
    }
  }, [dropSession, reloadUser])

  const finish = useCallback(
    async (accessToken: string) => {
      tokenStore.set(accessToken)
      await reloadUser()
      setNotice(null)
      setStatus('authenticated')
    },
    [reloadUser],
  )

  const login = useCallback(
    async (email: string, password: string): Promise<LoginResult> => {
      const res = await api<{ access_token?: string; mfa_required?: boolean; mfa_token?: string }>('/auth/login', {
        method: 'POST',
        auth: false,
        body: { email, password },
      })
      if (res.mfa_required && res.mfa_token) return { kind: 'mfa', mfaToken: res.mfa_token }
      await finish(res.access_token as string)
      return { kind: 'ok' }
    },
    [finish],
  )

  const verifyMfa = useCallback(
    async (mfaToken: string, code: string) => {
      const res = await api<{ access_token: string }>('/auth/mfa/verify', {
        method: 'POST',
        auth: false,
        body: { mfa_token: mfaToken, code },
      })
      await finish(res.access_token)
    },
    [finish],
  )

  const logout = useCallback(
    async (reason?: string) => {
      try {
        await api('/auth/logout', { method: 'POST', auth: false }) // revokes the refresh-token family server-side
      } finally {
        dropSession(reason)
      }
    },
    [dropSession],
  )

  const value = useMemo(
    () => ({ status, user, login, verifyMfa, logout, reloadUser, notice, clearNotice: () => setNotice(null) }),
    [status, user, login, verifyMfa, logout, reloadUser, notice],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

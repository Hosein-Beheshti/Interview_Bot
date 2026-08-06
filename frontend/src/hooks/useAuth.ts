import { useCallback, useEffect, useState } from 'react'
import { User } from '../types'
import { describeError, fetchMe, loginWithGoogle, logoutRequest } from '../services/api'

interface AuthState {
  // 'loading' only while the initial /auth/me check is in flight.
  status: 'loading' | 'signed_in' | 'signed_out'
  user: User | null
  error: string | null
}

const initialState: AuthState = { status: 'loading', user: null, error: null }

export function useAuth() {
  const [state, setState] = useState<AuthState>(initialState)

  const refresh = useCallback(async () => {
    try {
      const user = await fetchMe()
      setState({ status: user ? 'signed_in' : 'signed_out', user, error: null })
    } catch {
      // A failed check (network blip) is treated as signed out rather than
      // stuck on a loading screen forever; the user can just try signing in.
      setState({ status: 'signed_out', user: null, error: null })
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const login = useCallback(async (idToken: string) => {
    try {
      const user = await loginWithGoogle(idToken)
      setState({ status: 'signed_in', user, error: null })
    } catch (err) {
      setState({ status: 'signed_out', user: null, error: describeError(err) })
    }
  }, [])

  const logout = useCallback(async () => {
    // Client state clears immediately regardless of whether the network call
    // succeeds — a failed logout request must not leave the UI stuck signed in.
    setState({ status: 'signed_out', user: null, error: null })
    await logoutRequest().catch(() => undefined)
  }, [])

  const dismissError = useCallback(
    () => setState((prev) => ({ ...prev, error: null })),
    [],
  )

  return { ...state, login, logout, refresh, dismissError }
}

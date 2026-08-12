import { useCallback, useEffect, useRef, useState } from 'react'
import { User } from '../types'
import { describeError, fetchMe, loginWithGoogle, logoutRequest } from '../services/api'

interface AuthState {
  // 'loading' only while the initial /auth/me check is in flight.
  status: 'loading' | 'signed_in' | 'signed_out'
  user: User | null
  error: string | null
}

/** A drop in the balance, observed between two `/auth/me` reads. */
export interface CreditSpend {
  amount: number
  /** Identity for the UI's "show this once" effect, not a display value. */
  at: number
}

const initialState: AuthState = { status: 'loading', user: null, error: null }

export function useAuth() {
  const [state, setState] = useState<AuthState>(initialState)
  const [lastSpend, setLastSpend] = useState<CreditSpend | null>(null)
  // The balance as of the previous read. Credits are spent server-side (a
  // session costs several, transcription and speech cost per use), and no
  // endpoint reports the charge — so the difference between two reads is the
  // only honest source for "what did that just cost me".
  const knownCredits = useRef<number | null>(null)

  const refresh = useCallback(async () => {
    try {
      const user = await fetchMe()
      if (user) {
        const before = knownCredits.current
        if (before !== null && user.credits < before) {
          setLastSpend({ amount: before - user.credits, at: Date.now() })
        }
        knownCredits.current = user.credits
      } else {
        knownCredits.current = null
      }
      setState({ status: user ? 'signed_in' : 'signed_out', user, error: null })
    } catch {
      // A failed check (network blip) is treated as signed out rather than
      // stuck on a loading screen forever; the user can just try signing in.
      setState({ status: 'signed_out', user: null, error: null })
    }
  }, [])

  const clearSpend = useCallback(() => setLastSpend(null), [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const login = useCallback(async (idToken: string) => {
    try {
      const user = await loginWithGoogle(idToken)
      knownCredits.current = user.credits
      setState({ status: 'signed_in', user, error: null })
    } catch (err) {
      setState({ status: 'signed_out', user: null, error: describeError(err) })
    }
  }, [])

  const logout = useCallback(async () => {
    // Client state clears immediately regardless of whether the network call
    // succeeds — a failed logout request must not leave the UI stuck signed in.
    setState({ status: 'signed_out', user: null, error: null })
    knownCredits.current = null
    setLastSpend(null)
    await logoutRequest().catch(() => undefined)
  }, [])

  const dismissError = useCallback(
    () => setState((prev) => ({ ...prev, error: null })),
    [],
  )

  return { ...state, login, logout, refresh, dismissError, lastSpend, clearSpend }
}

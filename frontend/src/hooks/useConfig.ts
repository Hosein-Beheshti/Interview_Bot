import { useCallback, useEffect, useState } from 'react'
import { fetchConfig } from '../services/api'
import { ClientConfig } from '../types'

type Status = 'loading' | 'ready' | 'failed'

/**
 * Load the server's limits once, at boot.
 *
 * `config` is null until it arrives and the app waits rather than rendering with
 * assumed numbers: any default here would reintroduce the duplicate copy of every
 * limit that `GET /api/config` exists to eliminate. A failure is surfaced, not
 * papered over — an input capped at a guessed length is worse than a retry.
 */
export function useConfig() {
  const [config, setConfig] = useState<ClientConfig | null>(null)
  const [status, setStatus] = useState<Status>('loading')

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      setConfig(await fetchConfig())
      setStatus('ready')
    } catch {
      setConfig(null)
      setStatus('failed')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return { config, status, retry: load }
}

/**
 * The upload limit as the copy should say it, derived from the one number the
 * server enforces. Floored, matching the server's own 413 message.
 */
export function maxUploadMB(config: ClientConfig): number {
  return Math.floor(config.cv_max_bytes / (1024 * 1024))
}

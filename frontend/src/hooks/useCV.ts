import { useCallback, useState } from 'react'
import { ClientConfig, CVInfo } from '../types'
import { ApiError, deleteCV, describeError, uploadCV } from '../services/api'
import { maxUploadMB } from './useConfig'

interface CVState {
  info: CVInfo | null
  uploading: boolean
  error: string | null
}

const initial: CVState = { info: null, uploading: false, error: null }

export function useCV(config: ClientConfig, onUnauthorized?: () => void) {
  const [state, setState] = useState<CVState>(initial)

  const upload = useCallback(
    async (
      file: File,
      role: string,
      sessionId?: string,
      jobContext?: string,
      numQuestions?: number,
    ): Promise<string | null> => {
      const validation = validate(file, config)
      if (validation) {
        setState((p) => ({ ...p, error: validation }))
        return null
      }

      setState((p) => ({ ...p, uploading: true, error: null }))
      try {
        const result = await uploadCV(file, role, sessionId, jobContext, numQuestions)
        setState({
          info: {
            filename: result.filename,
            sections: result.sections,
            chunk_count: result.chunk_count,
          },
          uploading: false,
          error: null,
        })
        return result.session_id
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          onUnauthorized?.()
          return null
        }
        // `describeError`, not the raw detail: uploading a CV is what creates
        // the session on this path, so it is a place a candidate meets "out of
        // credits", the rate limit, or the daily cap — each of which needs its
        // own sentence rather than whatever the server put in `detail`.
        setState({ info: null, uploading: false, error: describeError(err) })
        return null
      }
    },
    [config, onUnauthorized],
  )

  const remove = useCallback(async (sessionId: string) => {
    try {
      await deleteCV(sessionId)
    } finally {
      setState(initial)
    }
  }, [])

  const clear = useCallback(() => setState(initial), [])

  return { ...state, upload, remove, clear }
}

/**
 * Mirror the server's own upload checks, using the server's own numbers.
 *
 * Every bound and the accepted extension list come from `config`, so this can
 * only ever reject what `/cv/upload` would reject. It runs first purely to save a
 * round trip — the server re-checks all of it.
 *
 * Pasted CVs arrive here too, as a `.txt` File, so the size bound covers them
 * without a separate character cap.
 */
function validate(file: File, config: ClientConfig): string | null {
  if (file.size === 0) return 'File is empty'
  if (file.size > config.cv_max_bytes) {
    return `File exceeds ${maxUploadMB(config)} MB limit`
  }
  const name = file.name.toLowerCase()
  if (!config.cv_accepted_extensions.some((ext) => name.endsWith(ext))) {
    return `Only ${describeExtensions(config)} files are supported`
  }
  return null
}

/** ".pdf,.docx,.txt" -> "PDF, DOCX, or TXT", so the copy tracks the server list. */
function describeExtensions(config: ClientConfig): string {
  const names = config.cv_accepted_extensions.map((ext) => ext.replace('.', '').toUpperCase())
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')}, or ${names[names.length - 1]}`
}

/** The `accept` attribute for a file input, from the server's list. */
export function acceptedCVTypes(config: ClientConfig): string {
  return config.cv_accepted_extensions.join(',')
}

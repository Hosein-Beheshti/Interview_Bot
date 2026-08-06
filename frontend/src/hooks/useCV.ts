import { useCallback, useState } from 'react'
import { CVInfo } from '../types'
import { ApiError, deleteCV, uploadCV } from '../services/api'

export const ACCEPTED_CV_TYPES = '.pdf,.docx,.txt'
const MAX_BYTES = 5 * 1024 * 1024

interface CVState {
  info: CVInfo | null
  uploading: boolean
  error: string | null
}

const initial: CVState = { info: null, uploading: false, error: null }

export function useCV(onUnauthorized?: () => void) {
  const [state, setState] = useState<CVState>(initial)

  const upload = useCallback(
    async (file: File, role: string, sessionId?: string, jobContext?: string): Promise<string | null> => {
      const validation = validate(file)
      if (validation) {
        setState((p) => ({ ...p, error: validation }))
        return null
      }

      setState((p) => ({ ...p, uploading: true, error: null }))
      try {
        const result = await uploadCV(file, role, sessionId, jobContext)
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
        const message = err instanceof Error ? err.message : 'Upload failed'
        setState({ info: null, uploading: false, error: message })
        return null
      }
    },
    [onUnauthorized],
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

function validate(file: File): string | null {
  if (file.size === 0) return 'File is empty'
  if (file.size > MAX_BYTES) return 'File exceeds 5 MB limit'
  const name = file.name.toLowerCase()
  if (!name.endsWith('.pdf') && !name.endsWith('.docx') && !name.endsWith('.txt')) {
    return 'Only PDF, DOCX, or TXT files are supported'
  }
  return null
}

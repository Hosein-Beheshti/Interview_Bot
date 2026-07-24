import { ChatResponse, CVUploadResponse } from '../types'

const API_BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api`
  : '/api'

export async function sendMessage(
  message: string,
  sessionId?: string,
  role?: string,
  jobContext?: string
): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      role: role || 'Software Engineer',
      ...(jobContext ? { job_context: jobContext } : {}),
    }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Failed to send message')
  }

  return response.json()
}

export async function uploadCV(
  file: File,
  role: string,
  sessionId?: string,
  jobContext?: string,
): Promise<CVUploadResponse> {
  // Everything travels in the multipart body: a job description is too long for
  // a URL and would otherwise be logged in full by every proxy in the path.
  const form = new FormData()
  form.append('file', file)
  form.append('role', role)
  if (sessionId) form.append('session_id', sessionId)
  if (jobContext) form.append('job_context', jobContext)

  const response = await fetch(`${API_BASE}/cv/upload`, {
    method: 'POST',
    body: form,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Upload failed' }))
    throw new Error(error.detail || 'Failed to upload CV')
  }

  return response.json()
}

export async function deleteCV(sessionId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/cv/${sessionId}`, { method: 'DELETE' })
  if (!response.ok && response.status !== 404) {
    throw new Error('Failed to remove CV')
  }
}

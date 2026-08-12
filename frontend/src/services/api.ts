import { ChatResponse, CVUploadResponse, ScoreResult, TurnFailure, User } from '../types'

const API_BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api`
  : '/api'

/** An API failure that kept its HTTP status, so the UI can explain *why*. */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

/** Turns any failure into the sentence a candidate should actually read. */
export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return 'Please sign in to continue.'
    if (err.status === 402) return "You're out of credits."
    if (err.status === 429) {
      return 'Too many requests from your connection. Please wait a minute and try again.'
    }
    if (err.status === 503) {
      return 'This demo has hit its daily usage limit. Please try again tomorrow.'
    }
    if (err.status === 413) return 'That file is too large.'
    if (err.status >= 500) return 'The interviewer is unavailable right now. Please try again.'
    return err.message
  }
  if (err instanceof TypeError) return 'Cannot reach the server. Check your connection.'
  return err instanceof Error ? err.message : 'Something went wrong'
}

/**
 * The same failure, split into a headline and a detail line.
 *
 * The server already distinguishes "you are going too fast" from "the demo is
 * out of budget" from "the model is down"; leading with which of those it was
 * tells the candidate in one glance whether waiting, topping up, or retrying is
 * the thing to do.
 */
export function describeFailure(err: unknown): TurnFailure {
  const detail = describeError(err)
  if (err instanceof ApiError) {
    if (err.status === 401) return { title: 'Signed out', detail }
    if (err.status === 402) return { title: 'Out of credits', detail }
    if (err.status === 429) return { title: 'Slow down', detail }
    if (err.status === 503) return { title: 'Daily limit reached', detail }
    if (err.status === 413) return { title: 'File too large', detail }
    if (err.status === 502) return { title: 'Turn failed', detail }
    if (err.status >= 500) return { title: 'Interviewer unavailable', detail }
    return { title: 'Request failed', detail }
  }
  if (err instanceof TypeError) return { title: 'Offline', detail }
  return { title: 'Something went wrong', detail }
}

async function toApiError(response: Response, fallback: string): Promise<ApiError> {
  const body = await response.json().catch(() => null)
  return new ApiError(body?.detail || fallback, response.status)
}

export interface ChatStreamHandlers {
  /** The grade for the previous answer. Arrives before the next question exists. */
  onScore?: (score: ScoreResult | null) => void
  onDelta: (text: string) => void
  onDone: (response: ChatResponse) => void
}

/**
 * Run one interview turn over server-sent events.
 *
 * The stream is the source of truth for the reply text; the closing `done` event
 * carries the same full response the non-streaming endpoint would have returned.
 * A stream that ends without `done` is a failure — the server cannot change the
 * HTTP status once the body has started, so late errors arrive as an `error`
 * event instead.
 */
export async function streamMessage(
  message: string,
  sessionId: string | undefined,
  role: string | undefined,
  jobContext: string | undefined,
  handlers: ChatStreamHandlers,
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      role: role || 'Software Engineer',
      ...(jobContext ? { job_context: jobContext } : {}),
    }),
  })

  if (!response.ok) throw await toApiError(response, 'Failed to send message')
  if (!response.body) throw new ApiError('Streaming is not supported here', 500)

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completed = false

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // Frames are separated by a blank line; the last piece may be partial.
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''

    for (const frame of frames) {
      const parsed = parseFrame(frame)
      if (!parsed) continue
      if (parsed.event === 'error') {
        throw new ApiError(parsed.data.detail || 'The interviewer is unavailable', 502)
      }
      if (parsed.event === 'score') handlers.onScore?.(parsed.data.score ?? null)
      if (parsed.event === 'delta') handlers.onDelta(parsed.data.text ?? '')
      if (parsed.event === 'done') {
        completed = true
        handlers.onDone(parsed.data as ChatResponse)
      }
    }
  }

  if (!completed) {
    throw new ApiError('The connection dropped mid-answer. Please try again.', 502)
  }
}

function parseFrame(frame: string): { event: string; data: any } | null {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (dataLines.length === 0) return null
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) }
  } catch {
    return null
  }
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
    credentials: 'include',
    // A multipart body is a CORS "simple request" that browsers send without
    // a preflight check, so the server's origin whitelist is never consulted
    // before it's sent — a plain auto-submitting HTML form on another site
    // could otherwise trigger this while a victim is logged in (cookies are
    // SameSite=None in production, since frontend/backend are cross-site).
    // A custom header can't be set by a plain form, so adding one forces a
    // real preflight, and CORS then blocks any origin not on the whitelist.
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
    body: form,
  })

  if (!response.ok) throw await toApiError(response, 'Failed to upload CV')

  return response.json()
}

export async function deleteCV(sessionId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/cv/${sessionId}`, {
    method: 'DELETE',
    credentials: 'include',
  })
  if (!response.ok && response.status !== 404) {
    throw new ApiError('Failed to remove CV', response.status)
  }
}

/** Erase a session, its transcript, and any uploaded CV. */
export async function deleteSession(sessionId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    method: 'DELETE',
    credentials: 'include',
  })
  if (!response.ok && response.status !== 404) {
    throw new ApiError('Failed to delete session', response.status)
  }
}

// ── Auth ──────────────────────────────────────────────────────────────────

/** The logged-in user, or `null` if no session cookie is present/valid. */
export async function fetchMe(): Promise<User | null> {
  const response = await fetch(`${API_BASE}/auth/me`, { credentials: 'include' })
  if (response.status === 401) return null
  if (!response.ok) throw await toApiError(response, 'Failed to load your account')
  return response.json()
}

/** Exchange a Google ID token for a session cookie. */
export async function loginWithGoogle(idToken: string): Promise<User> {
  const response = await fetch(`${API_BASE}/auth/google`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id_token: idToken }),
  })
  if (!response.ok) throw await toApiError(response, 'Sign-in failed')
  return response.json()
}

export async function logoutRequest(): Promise<void> {
  await fetch(`${API_BASE}/auth/logout`, { method: 'POST', credentials: 'include' })
}

import { useState, useCallback, useEffect, useRef } from 'react'
import { ChatState, Message, ScoreResult } from '../types'
import { ApiError, deleteSession, describeFailure, streamMessage } from '../services/api'

const SESSION_STORAGE_KEY = 'interview_session_id'

const initialState: ChatState = {
  messages: [],
  session_id: null,
  status: 'created',
  question_number: 0,
  num_questions: 0,
  is_complete: false,
  summary: null,
  loading: false,
  streaming: false,
  stage: null,
  error: null,
}

/** The arguments of a turn, kept so a failed one can be sent again unchanged. */
interface Attempt {
  text: string
  role?: string
  jobContext?: string
}

/** Apply `change` to the trailing assistant message — the one being streamed. */
function updateStreamingMessage(
  state: ChatState,
  change: (message: Message) => Message,
): ChatState {
  const messages = [...state.messages]
  const last = messages.length - 1
  if (last < 0 || messages[last].role !== 'assistant') return state
  messages[last] = change(messages[last])
  return { ...state, messages }
}

export function useChat(onUnauthorized?: () => void) {
  const [state, setState] = useState<ChatState>(initialState)
  const lastAttempt = useRef<Attempt | null>(null)

  useEffect(() => {
    const saved = localStorage.getItem(SESSION_STORAGE_KEY)
    if (saved) {
      setState((prev) => ({ ...prev, session_id: saved }))
    }
  }, [])

  const send = useCallback(
    async (text: string, role?: string, jobContext?: string) => {
      if (!text.trim()) return

      lastAttempt.current = { text, role, jobContext }

      // The answer and an empty bubble go in immediately: the bubble is what the
      // reply streams into, so the candidate sees writing rather than a spinner.
      // Until the first chunk lands the bubble reports the stage instead.
      setState((prev) => ({
        ...prev,
        messages: [
          ...prev.messages,
          { role: 'user', content: text },
          { role: 'assistant', content: '' },
        ],
        loading: true,
        streaming: true,
        // Without a session the server must first extract the job profile and
        // build the interview blueprint, and that happens before the stream
        // opens; with one, the first thing it does is grade the answer.
        stage: state.session_id ? 'evaluating' : 'planning',
        error: null,
      }))

      try {
        await streamMessage(text, state.session_id || undefined, role, jobContext, {
          // The grade lands before the next question exists, so its arrival is
          // also the moment scoring stopped and writing began.
          onScore: (score: ScoreResult | null) =>
            setState((prev) => ({
              ...updateStreamingMessage(prev, (m) => ({ ...m, score: score ?? undefined })),
              stage: 'composing',
            })),

          onDelta: (chunk: string) =>
            setState((prev) => ({
              ...updateStreamingMessage(prev, (m) => ({ ...m, content: m.content + chunk })),
              stage: 'writing',
            })),

          onDone: (response) => {
            localStorage.setItem(SESSION_STORAGE_KEY, response.session_id)
            if (response.is_complete) {
              localStorage.removeItem(SESSION_STORAGE_KEY)
            }
            setState((prev) => ({
              // The server's copy of the reply is authoritative; the streamed
              // text should already equal it, and this makes that certain.
              ...updateStreamingMessage(prev, (m) => ({
                ...m,
                content: response.reply,
                score: response.score ?? m.score,
                mode: response.mode,
              })),
              session_id: response.session_id,
              status: response.status,
              question_number: response.question_number,
              num_questions: response.num_questions,
              is_complete: response.is_complete,
              summary: response.summary ?? prev.summary,
              loading: false,
              streaming: false,
              stage: null,
            }))
            lastAttempt.current = null
          },
        })
      } catch (err) {
        // A 401 means the session cookie expired or was revoked mid-use —
        // no amount of retrying fixes that, so send the user back to the
        // login screen instead of leaving them stuck on a dead error.
        if (err instanceof ApiError && err.status === 401) {
          onUnauthorized?.()
          return
        }
        // The turn did not commit server-side, so drop both messages rather than
        // leaving a half-turn the candidate cannot act on.
        setState((prev) => ({
          ...prev,
          messages: prev.messages.slice(0, -2),
          loading: false,
          streaming: false,
          stage: null,
          error: describeFailure(err),
        }))
      }
    },
    [state.session_id, onUnauthorized],
  )

  /**
   * Send the failed turn again, unchanged.
   *
   * Only offered once a session exists. A first turn that fails may still have
   * created and been charged for a session server-side, and the id never
   * reached us — resending would build a second one and charge again, so that
   * case gets no retry button.
   */
  const retry = useCallback(() => {
    const attempt = lastAttempt.current
    if (!attempt || !state.session_id) return
    send(attempt.text, attempt.role, attempt.jobContext)
  }, [send, state.session_id])

  const canRetry = Boolean(lastAttempt.current && state.session_id && state.error)

  const reset = useCallback(() => {
    localStorage.removeItem(SESSION_STORAGE_KEY)
    lastAttempt.current = null
    setState(initialState)
  }, [])

  /** Erase this session's data on the server, then start over. */
  const forget = useCallback(async () => {
    const sessionId = state.session_id
    localStorage.removeItem(SESSION_STORAGE_KEY)
    lastAttempt.current = null
    setState(initialState)
    if (sessionId) {
      await deleteSession(sessionId).catch(() => undefined)
    }
  }, [state.session_id])

  const adoptSession = useCallback((sessionId: string) => {
    localStorage.setItem(SESSION_STORAGE_KEY, sessionId)
    setState((prev) => ({ ...prev, session_id: sessionId }))
  }, [])

  const dismissError = useCallback(() => setState((prev) => ({ ...prev, error: null })), [])

  return { ...state, send, retry, canRetry, reset, forget, adoptSession, dismissError }
}

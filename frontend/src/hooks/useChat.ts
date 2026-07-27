import { useState, useCallback, useEffect } from 'react'
import { ChatState, Message, ScoreResult } from '../types'
import { deleteSession, describeError, streamMessage } from '../services/api'

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
  error: null,
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

export function useChat() {
  const [state, setState] = useState<ChatState>(initialState)

  useEffect(() => {
    const saved = localStorage.getItem(SESSION_STORAGE_KEY)
    if (saved) {
      setState((prev) => ({ ...prev, session_id: saved }))
    }
  }, [])

  const send = useCallback(
    async (text: string, role?: string, jobContext?: string) => {
      if (!text.trim()) return

      // The answer and an empty bubble go in immediately: the bubble is what the
      // reply streams into, so the candidate sees writing rather than a spinner.
      setState((prev) => ({
        ...prev,
        messages: [
          ...prev.messages,
          { role: 'user', content: text },
          { role: 'assistant', content: '' },
        ],
        loading: true,
        streaming: true,
        error: null,
      }))

      try {
        await streamMessage(text, state.session_id || undefined, role, jobContext, {
          onScore: (score: ScoreResult | null) =>
            setState((prev) =>
              updateStreamingMessage(prev, (m) => ({ ...m, score: score ?? undefined })),
            ),

          onDelta: (chunk: string) =>
            setState((prev) =>
              updateStreamingMessage(prev, (m) => ({ ...m, content: m.content + chunk })),
            ),

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
            }))
          },
        })
      } catch (err) {
        // The turn did not commit server-side, so drop both messages rather than
        // leaving a half-turn the candidate cannot act on.
        setState((prev) => ({
          ...prev,
          messages: prev.messages.slice(0, -2),
          loading: false,
          streaming: false,
          error: describeError(err),
        }))
      }
    },
    [state.session_id],
  )

  const reset = useCallback(() => {
    localStorage.removeItem(SESSION_STORAGE_KEY)
    setState(initialState)
  }, [])

  /** Erase this session's data on the server, then start over. */
  const forget = useCallback(async () => {
    const sessionId = state.session_id
    localStorage.removeItem(SESSION_STORAGE_KEY)
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

  return { ...state, send, reset, forget, adoptSession, dismissError }
}

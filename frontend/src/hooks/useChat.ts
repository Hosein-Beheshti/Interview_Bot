import { useState, useCallback, useEffect } from 'react'
import { ChatState, Message } from '../types'
import { sendMessage } from '../services/api'

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
  error: null,
}

export function useChat() {
  const [state, setState] = useState<ChatState>(initialState)

  useEffect(() => {
    const saved = localStorage.getItem(SESSION_STORAGE_KEY)
    if (saved) {
      setState((prev) => ({ ...prev, session_id: saved }))
    }
  }, [])

  const send = useCallback(async (text: string, role?: string, jobContext?: string) => {
    if (!text.trim()) return

    setState((prev) => ({ ...prev, loading: true, error: null }))

    try {
      const response = await sendMessage(
        text,
        state.session_id || undefined,
        role || undefined,
        jobContext || undefined
      )

      localStorage.setItem(SESSION_STORAGE_KEY, response.session_id)
      if (response.is_complete) {
        localStorage.removeItem(SESSION_STORAGE_KEY)
      }

      const assistantMsg: Message = {
        role: 'assistant',
        content: response.reply,
        ...(response.score && { score: response.score }),
        ...(response.mode && { mode: response.mode }),
      }

      setState((prev) => ({
        ...prev,
        messages: [
          ...prev.messages,
          { role: 'user', content: text },
          assistantMsg,
        ],
        session_id: response.session_id,
        status: response.status,
        question_number: response.question_number,
        num_questions: response.num_questions,
        is_complete: response.is_complete,
        summary: response.summary ?? prev.summary,
        loading: false,
      }))
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Something went wrong'
      setState((prev) => ({ ...prev, loading: false, error: message }))
    }
  }, [state.session_id])

  const reset = useCallback(() => {
    localStorage.removeItem(SESSION_STORAGE_KEY)
    setState(initialState)
  }, [])

  const adoptSession = useCallback((sessionId: string) => {
    localStorage.setItem(SESSION_STORAGE_KEY, sessionId)
    setState((prev) => ({ ...prev, session_id: sessionId }))
  }, [])

  return { ...state, send, reset, adoptSession }
}

import { ChatResponse } from '../types'

const API_BASE = '/api'

export async function sendMessage(
  message: string,
  sessionId?: string,
  role?: string
): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      role: role || 'Software Engineer',
    }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Failed to send message')
  }

  return response.json()
}

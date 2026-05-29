export interface Message {
  role: 'user' | 'assistant'
  content: string
  score?: ScoreResult
}

export interface ScoreResult {
  score: number
  strengths: string[]
  improvements: string[]
}

export interface ChatResponse {
  reply: string
  session_id: string
  question_number: number
  is_complete: boolean
  score?: ScoreResult
}

export interface CVUploadResponse {
  session_id: string
  filename: string
  chunk_count: number
  sections: string[]
}

export interface CVInfo {
  filename: string
  sections: string[]
  chunk_count: number
}

export interface ChatState {
  messages: Message[]
  session_id: string | null
  question_number: number
  is_complete: boolean
  loading: boolean
  error: string | null
}

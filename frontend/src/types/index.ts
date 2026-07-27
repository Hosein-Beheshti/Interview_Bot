export type TurnMode = 'main_question' | 'follow_up' | 'closing'

export interface Message {
  role: 'user' | 'assistant'
  content: string
  score?: ScoreResult
  // Turn type of an assistant message: lets the UI distinguish a numbered
  // question from a follow-up probe.
  mode?: TurnMode
}

export interface DimensionScore {
  key: string
  label: string
  score: number
}

export interface ScoreResult {
  score: number
  dimensions?: DimensionScore[]
  strengths: string[]
  improvements: string[]
}

export interface QuestionScore {
  label: string
  score: number
}

// Server-computed interview result. The client renders this verbatim — no
// scoring or aggregation logic lives on the frontend.
export interface InterviewSummary {
  role: string
  overall: number
  breakdown: QuestionScore[]
  strengths: string[]
  improvements: string[]
  copy_text: string
}

export interface ChatResponse {
  reply: string
  session_id: string
  status: string
  question_number: number
  num_questions: number
  is_complete: boolean
  score?: ScoreResult
  mode?: TurnMode
  summary?: InterviewSummary
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
  status: string
  question_number: number
  num_questions: number
  is_complete: boolean
  summary: InterviewSummary | null
  loading: boolean
  // True while the current reply is still arriving. Distinct from `loading`,
  // which also covers the wait before the first chunk.
  streaming: boolean
  error: string | null
}

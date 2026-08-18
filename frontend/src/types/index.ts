export type TurnMode = 'main_question' | 'follow_up' | 'closing'

/**
 * Server-owned limits, from `GET /api/config`.
 *
 * The client keeps no copy of any of these — every input cap, picker length, and
 * size sentence in the UI reads from here, so the browser and the API can never
 * disagree about what is allowed. Field names match the backend settings that
 * produce them. Client-side checks derived from this are a courtesy; the server
 * re-validates everything.
 */
export interface ClientConfig {
  max_questions: number
  role_max_chars: number
  job_context_max_chars: number
  chat_message_max_chars: number
  cv_max_bytes: number
  cv_min_chars: number
  /** Dotted, lowercase, sorted — e.g. `['.docx', '.pdf', '.txt']`. */
  cv_accepted_extensions: string[]
}

export interface User {
  id: string
  email: string
  display_name: string | null
  picture_url: string | null
  credits: number
}

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

/**
 * What the server is working on right now.
 *
 * Derived entirely from where we are in the SSE stream — the protocol carries no
 * stage events, but the order of the ones it does carry pins each phase down:
 *
 *   no session yet     → `planning`   (profile extraction + interview blueprint,
 *                                      which run before the stream opens)
 *   stream opened      → `evaluating` (the previous answer is being scored)
 *   `score` received   → `composing`  (progression decided, question being written)
 *   first `delta`      → `writing`    (text is arriving; the bubble shows it)
 */
export type TurnStage = 'planning' | 'evaluating' | 'composing' | 'writing'

/** A failed turn, split so the UI can lead with what went wrong before the
 *  detail, and know whether offering a retry is safe. */
export interface TurnFailure {
  title: string
  detail: string
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
  // Non-null only while a turn is in flight.
  stage: TurnStage | null
  error: TurnFailure | null
}

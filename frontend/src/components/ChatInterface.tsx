import { useState, useRef, useEffect } from 'react'
import { useChat } from '../hooks/useChat'
import { useVoice } from '../hooks/useVoice'
import { useCV } from '../hooks/useCV'
import { CVUpload } from './CVUpload'
import { EXAMPLE_ROLES } from '../data/examples'
import { InterviewSummary, ScoreResult } from '../types'
import '../styles/chat.css'

const AUTO_SEND_DELAY_MS = 6000

export function ChatInterface() {
  const { messages, session_id, question_number, num_questions, is_complete, summary, loading, streaming, error, send, reset, forget, adoptSession, dismissError } = useChat()
  const {
    isListening, transcript, interimText, isSpeaking, micError,
    unlockAudio, startListening, stopListening, resetTranscript,
    speak, stopSpeaking,
  } = useVoice()
  const cv = useCV()
  const [input, setInput] = useState('')
  const [role, setRole] = useState('Software Engineer')
  const [jobDescription, setJobDescription] = useState('')
  const [copied, setCopied] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const lastSpokenIdxRef = useRef(-1)
  const autoSendTimerRef = useRef<ReturnType<typeof setTimeout>>()
  const sendRef = useRef(send)
  const stopListeningRef = useRef(stopListening)
  const resetTranscriptRef = useRef(resetTranscript)

  useEffect(() => { sendRef.current = send }, [send])
  useEffect(() => { stopListeningRef.current = stopListening }, [stopListening])
  useEffect(() => { resetTranscriptRef.current = resetTranscript }, [resetTranscript])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Speak each assistant message exactly once, identified by index. Waits for
  // the stream to finish: reading a half-written question aloud would cut off
  // mid-sentence, and the text is only final once `streaming` clears.
  useEffect(() => {
    if (loading || streaming || messages.length === 0) return
    const lastIdx = messages.length - 1
    const last = messages[lastIdx]
    if (last.role === 'assistant' && last.content && lastIdx !== lastSpokenIdxRef.current) {
      lastSpokenIdxRef.current = lastIdx
      speak(last.content, is_complete ? undefined : () => startListening())
    }
  }, [messages, loading, streaming, is_complete, speak, startListening])

  // Mirror live transcript into the input box for visibility (interim takes priority while user is talking)
  useEffect(() => {
    if (!isListening) return
    const display = (transcript + (interimText ? ' ' + interimText : '')).trim()
    if (display) setInput(display)
  }, [transcript, interimText, isListening])

  // Auto-send only after a confirmed pause AFTER a final transcript with no interim activity
  useEffect(() => {
    clearTimeout(autoSendTimerRef.current)
    if (!isListening) return
    if (interimText) return  // user is still talking
    const trimmed = transcript.trim()
    if (!trimmed) return

    autoSendTimerRef.current = setTimeout(() => {
      stopListeningRef.current()
      sendRef.current(trimmed, undefined)
      setInput('')
      resetTranscriptRef.current()
    }, AUTO_SEND_DELAY_MS)

    return () => clearTimeout(autoSendTimerRef.current)
  }, [transcript, interimText, isListening])

  const handleSend = () => {
    unlockAudio()
    clearTimeout(autoSendTimerRef.current)
    const text = input.trim()
    if (!text) return
    if (isListening) stopListening()
    resetTranscript()
    send(text, messages.length === 0 ? role : undefined)
    setInput('')
  }

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value)
    clearTimeout(autoSendTimerRef.current)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  const handleCopyResults = () => {
    if (!summary) return
    navigator.clipboard.writeText(summary.copy_text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className="chat-container">

      {/* ── Header ── */}
      <header className="chat-header">
        <div className="header-brand">
          <div className="brand-mark" />
          <h1>AI Interviewer</h1>
        </div>
        {messages.length > 0 && !is_complete && num_questions > 0 && (
          <div className="header-meta">
            <div className="progress-track">
              {Array.from({ length: num_questions }, (_, i) => i + 1).map((n) => (
                <div key={n} className={`pdot ${n < question_number ? 'done' : n === question_number ? 'active' : ''}`} />
              ))}
            </div>
            <span className="q-label">Q {question_number} / {num_questions}</span>
          </div>
        )}
      </header>

      {/* ── Messages ── */}
      <div className="chat-messages">
        {messages.length === 0 ? (

          <div className="welcome">
            <div className="welcome-orb"><span>🎯</span></div>
            <div className="welcome-copy">
              <h2>AI Interviewer</h2>
              <p>Practice technical interviews with real-time AI feedback and voice interaction</p>
            </div>

            {session_id ? (
              <div className="card">
                <p className="card-hint">You have a saved session</p>
                <button className="btn-primary" onClick={() => { unlockAudio(); send('Continue', role) }}>
                  Resume Interview
                </button>
                <button className="btn-ghost" onClick={() => { lastSpokenIdxRef.current = -1; stopSpeaking(); stopListening(); cv.clear(); reset() }}>Start Fresh</button>
              </div>
            ) : (
              <div className="card">
                <label className="field-label">Try an example</label>
                <div className="example-chips">
                  {EXAMPLE_ROLES.map((example) => (
                    <button
                      key={example.id}
                      type="button"
                      className={`chip${role === example.role && jobDescription === example.jobDescription ? ' chip-active' : ''}`}
                      onClick={() => { setRole(example.role); setJobDescription(example.jobDescription) }}
                    >
                      {example.label}
                    </button>
                  ))}
                </div>

                <label className="field-label" style={{ marginTop: 14 }}>Your role</label>
                <input
                  list="role-options"
                  className="field-input"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  placeholder="e.g. Software Engineer"
                />
                <datalist id="role-options">
                  <option value="Software Engineer" />
                  <option value="Full Stack Developer" />
                  <option value="Backend Engineer" />
                  <option value="Frontend Engineer" />
                  <option value="DevOps Engineer" />
                  <option value="Data Engineer" />
                  <option value="ML Engineer" />
                  <option value="Product Manager" />
                  <option value="QA Engineer" />
                  <option value="Mobile Engineer" />
                </datalist>

                <label className="field-label" style={{ marginTop: 14 }}>Job description (optional)</label>
                <textarea
                  className="field-input"
                  value={jobDescription}
                  onChange={(e) => setJobDescription(e.target.value)}
                  placeholder="Paste the full job description to get questions tailored to the role, seniority, and required skills."
                  rows={4}
                  maxLength={8000}
                  style={{ resize: 'vertical', fontFamily: 'inherit' }}
                />

                <CVUpload
                  info={cv.info}
                  uploading={cv.uploading}
                  error={cv.error}
                  onUpload={async (file) => {
                    const newSessionId = await cv.upload(file, role, session_id ?? undefined, jobDescription.trim() || undefined)
                    if (newSessionId) adoptSession(newSessionId)
                  }}
                  onRemove={async () => {
                    if (session_id) await cv.remove(session_id)
                    else cv.clear()
                  }}
                />

                <button
                  className="btn-primary btn-full"
                  onClick={() => { unlockAudio(); send('Hi, ready to start', role, jobDescription.trim() || undefined) }}
                  disabled={!role.trim() || cv.uploading}
                  style={{ marginTop: 14 }}
                >
                  {cv.info ? 'Start CV-Aware Interview' : 'Start Interview'}
                </button>

                <p className="privacy-note">
                  Your answers and any CV you upload are stored so the interview can
                  resume, and are deleted automatically after 30 days. You can erase
                  them at any time from the summary at the end.
                </p>
              </div>
            )}
          </div>

        ) : (
          <>
            {messages.map((msg, idx) => {
              const isLastBot = msg.role === 'assistant' && idx === messages.length - 1
              return (
                <div key={idx} className="msg-group">
                  <div className={`msg-row ${msg.role}`}>
                    <div className={`msg-av ${msg.role === 'assistant' ? (isSpeaking && isLastBot ? 'bot-speaking' : 'bot') : 'user'}`}>
                      {msg.role === 'assistant' ? '🎙' : null}
                    </div>
                    <div className="msg-body">
                      <div className="msg-bubble">
                        {msg.content}
                        {isLastBot && streaming && (
                          msg.content
                            ? <span className="stream-caret" />
                            : <span className="typing-dots inline"><span /><span /><span /></span>
                        )}
                      </div>
                      {isLastBot && isSpeaking && (
                        <div className="waveform">
                          {[0, 1, 2, 3, 4].map((i) => (
                            <span key={i} className="wbar" style={{ animationDelay: `${i * 0.1}s` }} />
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  {msg.score && <ScoreCard score={msg.score} />}
                </div>
              )
            })}

            {is_complete && summary && (
              <SummaryCard
                summary={summary}
                copied={copied}
                onCopy={handleCopyResults}
                onReset={() => { lastSpokenIdxRef.current = -1; stopSpeaking(); stopListening(); cv.clear(); reset() }}
                onForget={() => { lastSpokenIdxRef.current = -1; stopSpeaking(); stopListening(); cv.clear(); forget() }}
              />
            )}

            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* ── Voice strip ── */}
      {messages.length > 0 && !is_complete && (isSpeaking || isListening) && (
        <div className={`voice-strip ${isSpeaking ? 'strip-speaking' : 'strip-listening'}`}>
          {isSpeaking ? (
            <>
              <div className="waveform sm">
                {[0, 1, 2, 3, 4].map((i) => (
                  <span key={i} className="wbar" style={{ animationDelay: `${i * 0.1}s` }} />
                ))}
              </div>
              <span>Interviewer speaking</span>
              <button className="strip-btn" onClick={stopSpeaking}>Skip ›</button>
            </>
          ) : (
            <>
              <span className="rec-dot" />
              <span>Listening — speak your answer</span>
              <button className="strip-btn" onClick={stopListening}>Done ✓</button>
            </>
          )}
        </div>
      )}

      {/* The server distinguishes "you are going too fast" from "the demo is out
          of budget" from "the model is down"; showing that beats one generic line. */}
      {(error || micError) && (
        <div className="error-strip">
          <span>{error || micError}</span>
          {error && (
            <button className="strip-btn" onClick={dismissError}>Dismiss</button>
          )}
        </div>
      )}

      {/* ── Input ── */}
      {!is_complete && messages.length > 0 && (
        <div className="input-area">
          <div className="input-row">
            <textarea
              className="input-box"
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder={isListening ? 'Listening…' : 'Type your answer or use the mic'}
              disabled={loading}
              rows={2}
            />
            <button
              className={`mic-btn${isListening ? ' mic-active' : ''}`}
              onClick={() => {
                unlockAudio()
                clearTimeout(autoSendTimerRef.current)
                if (isListening) {
                  stopListening()
                } else {
                  setInput('')
                  resetTranscript()
                  startListening()
                }
              }}
              disabled={loading}
              title={isListening ? 'Stop recording' : 'Record answer'}
            >
              {isListening ? <StopIcon /> : <MicIcon />}
            </button>
            <button className="send-btn" onClick={handleSend} disabled={loading || !input.trim()}>
              Send
            </button>
          </div>
        </div>
      )}

    </div>
  )
}

function ScoreCard({ score }: { score: ScoreResult }) {
  return (
    <div className="score-card">
      <div className="score-top">
        <span className="score-num">{score.score}<sub>/10</sub></span>
        <div className="score-track">
          <div className="score-fill" style={{ width: `${score.score * 10}%` }} />
        </div>
      </div>
      {score.strengths.length > 0 && (
        <div className="score-block">
          <p className="sbt green">Strengths</p>
          <ul>{score.strengths.map((s, i) => <li key={i} className="si green-li">{s}</li>)}</ul>
        </div>
      )}
      {score.improvements.length > 0 && (
        <div className="score-block">
          <p className="sbt amber">To Improve</p>
          <ul>{score.improvements.map((s, i) => <li key={i} className="si amber-li">{s}</li>)}</ul>
        </div>
      )}
    </div>
  )
}

function SummaryCard({
  summary, copied, onCopy, onReset, onForget
}: {
  summary: InterviewSummary
  copied: boolean
  onCopy: () => void
  onReset: () => void
  onForget: () => void
}) {
  return (
    <div className="summary-card">
      <div className="summary-header">
        <div className="summary-orb">
          <span className="orb-score">{summary.overall}</span>
          <span className="orb-denom">/10</span>
        </div>
        <div className="summary-title">
          <h3>Interview Complete</h3>
          <p>{summary.role} — overall score</p>
        </div>
      </div>

      <div className="summary-bars">
        {summary.breakdown.map((b, i) => (
          <div key={i} className="summary-bar-row">
            <span className="summary-bar-label">{b.label}</span>
            <div className="score-track">
              <div className="score-fill" style={{ width: `${b.score * 10}%` }} />
            </div>
            <span className="summary-bar-val">{b.score}/10</span>
          </div>
        ))}
      </div>

      {summary.strengths.length > 0 && (
        <div className="score-block">
          <p className="sbt green">Top Strengths</p>
          <ul>{summary.strengths.map((s, i) => <li key={i} className="si green-li">{s}</li>)}</ul>
        </div>
      )}

      {summary.improvements.length > 0 && (
        <div className="score-block">
          <p className="sbt amber">Focus Areas</p>
          <ul>{summary.improvements.map((s, i) => <li key={i} className="si amber-li">{s}</li>)}</ul>
        </div>
      )}

      <div className="summary-actions">
        <button className={`copy-btn${copied ? ' copied' : ''}`} onClick={onCopy}>
          {copied ? 'Copied!' : 'Copy Results'}
        </button>
        <button className="btn-primary" style={{ flex: 1 }} onClick={onReset}>
          New Interview
        </button>
      </div>

      <button className="btn-link" onClick={onForget}>
        Delete my transcript and CV from the server
      </button>
    </div>
  )
}

function MicIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  )
}

function StopIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <rect x="3" y="3" width="18" height="18" rx="3" />
    </svg>
  )
}

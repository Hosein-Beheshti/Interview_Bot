import { useState, useRef, useEffect } from 'react'
import { useChat } from '../hooks/useChat'
import { useVoice } from '../hooks/useVoice'
import '../styles/chat.css'

export function ChatInterface() {
  const { messages, session_id, question_number, is_complete, loading, error, send, reset } = useChat()
  const { isListening, transcript, isSpeaking, micError, startListening, stopListening, speak, stopSpeaking } = useVoice()
  const [input, setInput] = useState('')
  const [role, setRole] = useState('Software Engineer')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const lastSpokenRef = useRef('')
  const autoSendTimerRef = useRef<ReturnType<typeof setTimeout>>()
  const sendRef = useRef(send)
  const [autoSendPending, setAutoSendPending] = useState(false)

  useEffect(() => { sendRef.current = send }, [send])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Auto-speak new assistant messages, then auto-start listening
  useEffect(() => {
    if (loading || messages.length === 0) return
    const last = messages[messages.length - 1]
    if (last.role === 'assistant' && last.content !== lastSpokenRef.current) {
      lastSpokenRef.current = last.content
      speak(last.content, is_complete ? undefined : () => startListening())
    }
  }, [messages, loading, is_complete, speak, startListening])

  // When transcript arrives: populate input and auto-send after 2s
  useEffect(() => {
    if (!transcript) return
    setInput(transcript)
    setAutoSendPending(true)
    clearTimeout(autoSendTimerRef.current)
    autoSendTimerRef.current = setTimeout(() => {
      setAutoSendPending(false)
      const trimmed = transcript.trim()
      if (trimmed) {
        sendRef.current(trimmed, undefined)
        setInput('')
      }
    }, 2000)
    return () => clearTimeout(autoSendTimerRef.current)
  }, [transcript])

  const handleSend = () => {
    clearTimeout(autoSendTimerRef.current)
    setAutoSendPending(false)
    if (!input.trim()) return
    send(input.trim(), messages.length === 0 ? role : undefined)
    setInput('')
  }

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value)
    clearTimeout(autoSendTimerRef.current)
    setAutoSendPending(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="chat-container">

      {/* ── Header ── */}
      <header className="chat-header">
        <div className="header-brand">
          <div className="brand-mark" />
          <h1>AI Interviewer</h1>
        </div>
        {messages.length > 0 && (
          <div className="header-meta">
            <div className="progress-track">
              {[1, 2, 3, 4, 5].map((n) => (
                <div
                  key={n}
                  className={`pdot ${n < question_number ? 'done' : n === question_number ? 'active' : ''}`}
                />
              ))}
            </div>
            <span className="q-label">Q {question_number} / 5</span>
          </div>
        )}
      </header>

      {/* ── Messages ── */}
      <div className="chat-messages">
        {messages.length === 0 ? (

          /* Welcome */
          <div className="welcome">
            <div className="welcome-orb"><span>🎯</span></div>
            <div className="welcome-copy">
              <h2>AI Interviewer</h2>
              <p>Practice technical interviews with real-time AI feedback and voice interaction</p>
            </div>

            {session_id ? (
              <div className="card">
                <p className="card-hint">You have a saved session</p>
                <button className="btn-primary" onClick={() => send('Continue', role)}>
                  Resume Interview
                </button>
                <button className="btn-ghost" onClick={reset}>Start Fresh</button>
              </div>
            ) : (
              <div className="card">
                <label className="field-label">Select role</label>
                <select className="field-select" value={role} onChange={(e) => setRole(e.target.value)}>
                  <option>Software Engineer</option>
                  <option>Full Stack Developer</option>
                  <option>Backend Engineer</option>
                  <option>Frontend Engineer</option>
                  <option>DevOps Engineer</option>
                </select>
                <button className="btn-primary btn-full" onClick={() => send('Hi, ready to start', role)}>
                  Start Interview
                </button>
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
                      <div className="msg-bubble">{msg.content}</div>
                      {isLastBot && isSpeaking && (
                        <div className="waveform">
                          {[0, 1, 2, 3, 4].map((i) => (
                            <span key={i} className="wbar" style={{ animationDelay: `${i * 0.1}s` }} />
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  {msg.score && (
                    <div className="score-card">
                      <div className="score-top">
                        <span className="score-num">{msg.score.score}<sub>/10</sub></span>
                        <div className="score-track">
                          <div className="score-fill" style={{ width: `${msg.score.score * 10}%` }} />
                        </div>
                      </div>
                      {msg.score.strengths.length > 0 && (
                        <div className="score-block">
                          <p className="sbt green">Strengths</p>
                          <ul>
                            {msg.score.strengths.map((s, i) => (
                              <li key={i} className="si green-li">{s}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {msg.score.improvements.length > 0 && (
                        <div className="score-block">
                          <p className="sbt amber">To Improve</p>
                          <ul>
                            {msg.score.improvements.map((s, i) => (
                              <li key={i} className="si amber-li">{s}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}

            {loading && (
              <div className="msg-row assistant">
                <div className="msg-av bot">🎙</div>
                <div className="typing-dots">
                  <span /><span /><span />
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* ── Voice state strip ── */}
      {messages.length > 0 && (isSpeaking || isListening) && (
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

      {(error || micError) && <div className="error-strip">{error || micError}</div>}

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
              onClick={isListening ? stopListening : startListening}
              disabled={loading}
              title={isListening ? 'Stop recording' : 'Record answer'}
            >
              {isListening ? <StopIcon /> : <MicIcon />}
            </button>
            <button className="send-btn" onClick={handleSend} disabled={loading || !input.trim()}>
              Send
            </button>
          </div>
          {autoSendPending && (
            <p className="auto-hint">Sending in 2 s — edit above to cancel</p>
          )}
        </div>
      )}

      {/* ── Completion ── */}
      {is_complete && (
        <div className="completion-strip">
          <span>🎉 Interview complete — great work!</span>
          <button className="btn-primary" onClick={reset}>Start New Interview</button>
        </div>
      )}

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

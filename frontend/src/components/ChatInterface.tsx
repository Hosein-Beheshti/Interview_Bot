import { useState, useRef, useEffect } from 'react'
import { useChat } from '../hooks/useChat'
import { useVoice } from '../hooks/useVoice'
import { useCV } from '../hooks/useCV'
import { CreditSpend } from '../hooks/useAuth'
import { CVUpload } from './CVUpload'
import { BrandMark, MicGlyph } from './icons'
import { EXAMPLE_ROLES } from '../data/examples'
import { ClientConfig, InterviewSummary, ScoreResult, TurnStage, User } from '../types'
import '../styles/chat.css'

const AUTO_SEND_DELAY_MS = 6000
/** How long a "−8 credits" flash stays up before it stops being news. */
const SPEND_FLASH_MS = 7000

/** What each phase of a turn is called in the UI. Wording is deliberately about
 *  what the server is doing, not a generic "loading". */
const STAGE_LABEL: Record<TurnStage, string> = {
  planning: 'Reading the role and planning your interview',
  evaluating: 'Evaluating your answer',
  composing: 'Preparing the next question',
  writing: 'Writing',
}

interface ChatInterfaceProps {
  user: User
  /** Server-owned limits. Every input cap and picker length below reads from
   *  this — the component holds no limit of its own. */
  config: ClientConfig
  onLogout: () => void
  /** Called whenever credits may have been spent, so the caller can refetch the
   * balance: starting a session costs several, and speech costs per use. */
  onCreditsChanged: () => void
  /** The most recent observed drop in the balance, for the spend flash. */
  lastSpend: CreditSpend | null
  onSpendShown: () => void
}

export function ChatInterface({
  user, config, onLogout, onCreditsChanged, lastSpend, onSpendShown,
}: ChatInterfaceProps) {
  const { messages, session_id, question_number, num_questions, is_complete, summary, loading, streaming, stage, error, send, retry, canRetry, reset, forget, adoptSession, dismissError } = useChat(onLogout)
  const {
    isListening, transcript, interimText, isSpeaking, micError,
    unlockAudio, startListening, stopListening, resetTranscript,
    beginSpeech, pushSpeech, endSpeech, stopSpeaking,
  } = useVoice()
  const cv = useCV(config, onLogout)
  const [input, setInput] = useState('')
  const [role, setRole] = useState('Software Engineer')
  const [jobDescription, setJobDescription] = useState('')
  // The interview length, always a valid choice because the control only offers
  // valid ones. Starts at the maximum: someone who ignores this field gets the
  // full interview, which is what they would have got before it existed.
  const [questionCount, setQuestionCount] = useState(config.max_questions)
  const [cvOpen, setCvOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  // What this interview has cost so far, accumulated from observed balance
  // drops. Reset with the session, since that is what the figure describes.
  const [sessionSpend, setSessionSpend] = useState(0)
  const countedSpendRef = useRef<number | null>(null)
  const wasLoadingRef = useRef(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const lastSpokenIdxRef = useRef(-1)
  const speechEndedRef = useRef(false)
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

  // Re-check the balance whenever a session appears (creating one is the big
  // charge) and again at the end of each turn, which is what catches the
  // smaller per-use charges for speech and transcription.
  useEffect(() => {
    if (session_id) onCreditsChanged()
  }, [session_id, onCreditsChanged])

  useEffect(() => {
    if (wasLoadingRef.current && !loading) onCreditsChanged()
    wasLoadingRef.current = loading
  }, [loading, onCreditsChanged])

  // Count each observed spend exactly once (the ref guards the double-invoked
  // effect in StrictMode), then let the flash expire on its own.
  useEffect(() => {
    if (!lastSpend) return
    if (countedSpendRef.current !== lastSpend.at) {
      countedSpendRef.current = lastSpend.at
      setSessionSpend((prev) => prev + lastSpend.amount)
    }
    const timer = setTimeout(onSpendShown, SPEND_FLASH_MS)
    return () => clearTimeout(timer)
  }, [lastSpend, onSpendShown])

  const handleSignOut = () => {
    stopSpeaking()
    stopListening()
    cv.clear()
    reset()
    onLogout()
  }

  /** Tear down the current interview. `forget` also erases it server-side. */
  const endSession = (mode: 'reset' | 'forget') => {
    lastSpokenIdxRef.current = -1
    stopSpeaking()
    stopListening()
    cv.clear()
    setSessionSpend(0)
    if (mode === 'forget') forget()
    else reset()
  }

  // Speak each assistant message exactly once, identified by index. The text is
  // fed in as it streams rather than after `streaming` clears: synthesis of the
  // first sentence then overlaps generation of the rest, instead of the whole
  // generation time sitting in front of the first sound. `useVoice` cuts the
  // text at sentence boundaries and plays the pieces in order, so nothing is
  // read out half-written.
  useEffect(() => {
    if (messages.length === 0) return
    const lastIdx = messages.length - 1
    const last = messages[lastIdx]
    if (last.role !== 'assistant') {
      // A failed send drops both messages of the turn; stop reading out a reply
      // the candidate can no longer act on.
      if (lastSpokenIdxRef.current > lastIdx) {
        lastSpokenIdxRef.current = -1
        stopSpeaking()
      }
      return
    }

    if (lastIdx !== lastSpokenIdxRef.current) {
      lastSpokenIdxRef.current = lastIdx
      speechEndedRef.current = false
      beginSpeech()
    }
    if (speechEndedRef.current) return

    pushSpeech(last.content)
    if (!loading && !streaming) {
      speechEndedRef.current = true
      // Handed over at the end, not the start: whether this was the last
      // question is only known once the turn lands.
      endSpeech(is_complete ? undefined : () => startListening())
    }
  }, [messages, loading, streaming, is_complete, beginSpeech, pushSpeech, endSpeech, stopSpeaking, startListening])

  // Mirror live transcript into the input box for visibility (interim takes priority while user is talking)
  // Clamped to the server's message limit by hand: this sets the value
  // programmatically, and `maxLength` bounds only typing and pasting, so a long
  // dictated answer would otherwise sail past the cap and come back a 422.
  useEffect(() => {
    if (!isListening) return
    const display = (transcript + (interimText ? ' ' + interimText : '')).trim()
    if (display) setInput(display.slice(0, config.chat_message_max_chars))
  }, [transcript, interimText, isListening, config.chat_message_max_chars])

  // Auto-send only after a confirmed pause AFTER a final transcript with no interim activity
  useEffect(() => {
    clearTimeout(autoSendTimerRef.current)
    if (!isListening) return
    if (interimText) return  // user is still talking
    const trimmed = transcript.trim()
    if (!trimmed) return

    autoSendTimerRef.current = setTimeout(() => {
      stopListeningRef.current()
      // Sends the transcript, not `input`, so it needs the same clamp.
      sendRef.current(trimmed.slice(0, config.chat_message_max_chars), undefined)
      setInput('')
      resetTranscriptRef.current()
    }, AUTO_SEND_DELAY_MS)

    return () => clearTimeout(autoSendTimerRef.current)
  }, [transcript, interimText, isListening, config.chat_message_max_chars])

  // A zero balance cannot pay for a session under any pricing, so this is safe
  // to assert without the frontend knowing what a session costs. A balance that
  // is merely too small is left to the server's 402, which names both numbers.
  const outOfCredits = user.credits <= 0

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
          <div className="brand-mark"><BrandMark /></div>
          <div className="brand-text">
            <h1>Warmup</h1>
            <span className="brand-sub">AI interview practice</span>
          </div>
        </div>
        {messages.length > 0 && !is_complete && num_questions > 0 && (
          <div className="header-meta">
            <div
              className="progress-track"
              role="progressbar"
              aria-valuemin={1}
              aria-valuemax={num_questions}
              aria-valuenow={question_number}
              aria-label="Interview progress"
            >
              {Array.from({ length: num_questions }, (_, i) => i + 1).map((n) => (
                <div key={n} className={`pdot ${n < question_number ? 'done' : n === question_number ? 'active' : ''}`} />
              ))}
            </div>
            <span className="q-label">Question {question_number} of {num_questions}</span>
          </div>
        )}
        <div className="header-user">
          {lastSpend && (
            <span className="spend-flash" role="status">
              −{lastSpend.amount} credit{lastSpend.amount === 1 ? '' : 's'}
            </span>
          )}
          <span
            className={`credits-badge${user.credits <= 0 ? ' low' : ''}`}
            title={`${user.credits} credits remaining${sessionSpend > 0 ? ` · ${sessionSpend} spent on this interview` : ''}`}
          >
            {user.credits} credit{user.credits === 1 ? '' : 's'}
          </span>
          {user.picture_url ? (
            <img className="user-avatar" src={user.picture_url} alt="" referrerPolicy="no-referrer" />
          ) : (
            <span className="user-avatar-fallback">
              {(user.display_name || user.email)[0]?.toUpperCase()}
            </span>
          )}
          <button className="sign-out-btn" onClick={handleSignOut}>Sign out</button>
        </div>
      </header>

      {/* ── Messages ── */}
      <div className="chat-messages">
        {messages.length === 0 ? (

          <div className="welcome">
            {/* One line, no orb: the brand mark is already in the header, and
                this screen's job is the form below it — which has to fit on a
                laptop without scrolling. The three-step explanation lives on
                the sign-in screen, where someone is still deciding. */}
            <div className="welcome-copy">
              <h2>Practice the interview before it counts</h2>
              <p>Spoken questions, a score after every answer, a summary at the end.</p>
            </div>

            {session_id ? (
              <div className="card">
                <p className="card-hint">You have an interview in progress</p>
                <button className="btn-primary" onClick={() => { unlockAudio(); send('Continue', role) }}>
                  Resume interview
                </button>
                <button className="btn-ghost" onClick={() => endSession('reset')}>Start fresh</button>
              </div>
            ) : (
              <div className="card">
                {/* Role and length sit on one row: together they are the whole
                    required part of the form, and stacking them pushed the
                    button below the fold on a laptop. */}
                <div className="field-row">
                  <div className="field">
                    <label className="field-label" htmlFor="role-input">
                      Role <Required />
                      <CharCount
                        id="role-count"
                        value={role.length}
                        max={config.role_max_chars}
                      />
                    </label>
                    <input
                      id="role-input"
                      list="role-options"
                      className="field-input"
                      value={role}
                      onChange={(e) => setRole(e.target.value)}
                      placeholder="e.g. Software Engineer"
                      maxLength={config.role_max_chars}
                      aria-describedby="role-count"
                    />
                  </div>

                  <div className="field">
                    <label className="field-label" id="questions-label">
                      Questions <Required />
                    </label>
                    <div className="seg" role="group" aria-labelledby="questions-label">
                      {Array.from({ length: config.max_questions }, (_, i) => i + 1).map((n) => (
                        <button
                          key={n}
                          type="button"
                          className={`seg-btn${n === questionCount ? ' seg-btn-active' : ''}`}
                          onClick={() => setQuestionCount(n)}
                          aria-pressed={n === questionCount}
                        >
                          {n}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="example-row">
                  <span className="example-lead">Or start from an example:</span>
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

                <div className="field">
                  <label className="field-label" htmlFor="jd-input">
                    Job description <Optional />
                    <CharCount
                      id="jd-count"
                      value={jobDescription.length}
                      max={config.job_context_max_chars}
                    />
                  </label>
                  <textarea
                    id="jd-input"
                    className="field-input"
                    value={jobDescription}
                    onChange={(e) => setJobDescription(e.target.value)}
                    placeholder="Paste the posting — questions then follow its seniority, stack, and skills."
                    rows={3}
                    maxLength={config.job_context_max_chars}
                    aria-describedby="jd-count"
                  />
                </div>

                {/* The CV picker is the tallest block on this screen and the
                    one fewest people use on a first run, so it opens on
                    request. Anything already attached shows itself. */}
                {!cvOpen && !cv.info ? (
                  <button
                    type="button"
                    className="field-reveal"
                    onClick={() => setCvOpen(true)}
                    aria-expanded={false}
                  >
                    <span className="field-reveal-plus" aria-hidden>+</span>
                    Add your CV
                    <span className="field-reveal-note">
                      for questions about your own experience
                    </span>
                  </button>
                ) : (
                <div className="field">
                  <label className="field-label">
                    Your CV <Optional />
                  </label>
                  <CVUpload
                    info={cv.info}
                    uploading={cv.uploading}
                    error={cv.error}
                    config={config}
                    onUpload={async (file) => {
                      const newSessionId = await cv.upload(file, role, session_id ?? undefined, jobDescription.trim() || undefined, questionCount)
                      if (newSessionId) adoptSession(newSessionId)
                    }}
                    onRemove={async () => {
                      if (session_id) await cv.remove(session_id)
                      else cv.clear()
                    }}
                  />
                </div>
                )}

                {/* Starting an interview is the one thing here that costs a
                    meaningful number of credits, so an empty balance is said
                    before the click rather than as a failed turn afterwards. */}
                {outOfCredits && (
                  <p className="field-hint field-hint-error" role="status">
                    You're out of credits, so a new interview can't be started.
                    Existing interviews can still be finished.
                  </p>
                )}

                <div className="field">
                  {/* What is about to happen, in the words of the choices above
                      it. It is the last thing read before the click, and it
                      catches a job description pasted for the wrong role. */}
                  <p className="start-recap">
                    {role.trim() || 'Your role'} · {questionCount} question
                    {questionCount === 1 ? '' : 's'}
                    {jobDescription.trim() ? ' · job description' : ''}
                    {cv.info ? ' · CV' : ''}
                  </p>
                  <button
                    className="btn-primary btn-full"
                    onClick={() => {
                      unlockAudio()
                      send('Hi, ready to start', role, jobDescription.trim() || undefined, questionCount)
                    }}
                    disabled={!role.trim() || cv.uploading || outOfCredits}
                  >
                    {outOfCredits ? 'Out of credits' : 'Start interview'}
                  </button>
                </div>

                <p className="privacy-note">
                  <span className="req-legend"><Required /> Required.</span>{' '}
                  Answers and any CV you upload are deleted after 30 days, or
                  whenever you erase them from the summary.
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
                    <div
                      className={`msg-av ${msg.role === 'assistant' ? (isSpeaking && isLastBot ? 'bot-speaking' : 'bot') : 'user'}`}
                      title={msg.role === 'assistant' ? 'Interviewer' : 'You'}
                    >
                      {msg.role === 'assistant'
                        ? <MicGlyph />
                        : (user.display_name || user.email)[0]?.toUpperCase()}
                    </div>
                    <div className="msg-body">
                      <div className="msg-bubble">
                        {msg.content}
                        {isLastBot && streaming && (
                          msg.content
                            ? <span className="stream-caret" />
                            : <StageReport stage={stage ?? 'planning'} />
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
                creditsSpent={sessionSpend}
                creditsLeft={user.credits}
                onCopy={handleCopyResults}
                onReset={() => endSession('reset')}
                onForget={() => endSession('forget')}
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
              <button className="strip-btn" onClick={stopSpeaking}>Skip</button>
            </>
          ) : (
            <>
              <span className="rec-dot" />
              <span>Listening — speak your answer</span>
              <button className="strip-btn" onClick={stopListening}>Done</button>
            </>
          )}
        </div>
      )}

      {/* The server distinguishes "you are going too fast" from "the demo is out
          of budget" from "the model is down"; showing that beats one generic
          line. A failed turn does not commit, so retrying it is safe — but only
          once a session exists (see `useChat.retry`). */}
      {error && (
        <div className="error-strip" role="alert">
          <AlertIcon />
          <div className="error-body">
            <strong>{error.title}</strong>
            <span>{error.detail}</span>
          </div>
          {canRetry && (
            <button className="strip-btn" onClick={retry}>Try again</button>
          )}
          <button className="strip-btn" onClick={dismissError}>Dismiss</button>
        </div>
      )}

      {micError && !error && (
        <div className="error-strip" role="alert">
          <AlertIcon />
          <div className="error-body">
            <strong>Microphone unavailable</strong>
            <span>{micError}</span>
          </div>
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
              placeholder={isListening ? 'Listening…' : 'Type your answer, or use the mic'}
              disabled={loading}
              rows={2}
              aria-label="Your answer"
              maxLength={config.chat_message_max_chars}
              aria-describedby="answer-count"
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
              aria-label={isListening ? 'Stop recording' : 'Record answer'}
              aria-pressed={isListening}
            >
              {isListening ? <StopIcon /> : <MicIcon />}
            </button>
            <button className="send-btn" onClick={handleSend} disabled={loading || !input.trim()}>
              Send
            </button>
          </div>
          <p className="input-hint">
            <span>
              <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> for a new line
            </span>
            <CharCount
              id="answer-count"
              value={input.length}
              max={config.chat_message_max_chars}
            />
          </p>
        </div>
      )}

    </div>
  )
}

/**
 * Field markers. Every label in the setup form carries exactly one of these, so
 * "no marker" never has to be read as a claim either way.
 *
 * The asterisk is the convention people already know, but it is a symbol, not a
 * word — screen readers get the word, and the legend under the form spells it
 * out for anyone who hasn't met the convention.
 */
function Required() {
  return (
    <>
      <span className="req" aria-hidden>*</span>
      <span className="sr-only">(required)</span>
    </>
  )
}

function Optional() {
  return <span className="opt">Optional</span>
}

/**
 * `used / limit` for a length-capped field.
 *
 * The cap is enforced by the input's own `maxLength`, which comes from the
 * server's config — this only makes it visible, so running out of room reads as a
 * known boundary rather than the keyboard having broken. Amber rather than red at
 * the limit, matching the CV counter: nothing typed is wrong, there is just no
 * more space.
 *
 * Announced through `aria-describedby` (the caller wires it) rather than a live
 * region, which on a per-keystroke counter would talk over the person typing. The
 * one thing worth interrupting for — hitting the limit — mounts a `role="status"`
 * only at that moment, so it is spoken once.
 */
function CharCount({ id, value, max }: { id: string; value: number; max: number }) {
  const full = value >= max
  const near = !full && value >= Math.floor(max * 0.9)
  return (
    <span
      id={id}
      className={`char-count${full ? ' char-count-full' : near ? ' char-count-near' : ''}`}
    >
      {value.toLocaleString()}/{max.toLocaleString()}
      {full && <span className="sr-only" role="status"> — character limit reached</span>}
    </span>
  )
}

/** Whole seconds since this component mounted — i.e. since the turn was sent,
 *  because the reporting line only exists while the reply bubble is empty. */
function useElapsed(): number {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const started = Date.now()
    const id = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => clearInterval(id)
  }, [])
  return seconds
}

/**
 * What the server is doing, shown inside the reply bubble it will write into.
 *
 * Planning a fresh interview means two model calls before a single token of the
 * first question exists, which is a long silence to sit through; naming the work
 * and counting the seconds is the difference between "thinking" and "stuck".
 */
function StageReport({ stage }: { stage: TurnStage }) {
  const seconds = useElapsed()
  return (
    <span className="stage-report" role="status" aria-live="polite">
      <span className="typing-dots inline" aria-hidden><span /><span /><span /></span>
      <span className="stage-label">{STAGE_LABEL[stage]}</span>
      {/* Only once the wait is long enough that a number is reassuring rather
          than another thing flickering on screen. */}
      {seconds >= 3 && <span className="stage-elapsed">{seconds}s</span>}
    </span>
  )
}

/** Colour band for a 0–10 score. Purely presentational — the number the server
 *  sent is what is displayed; this only decides how the bar reads at a glance. */
function band(score: number): string {
  if (score >= 7) return 'band-high'
  if (score >= 4) return 'band-mid'
  return 'band-low'
}

function ScoreCard({ score }: { score: ScoreResult }) {
  return (
    <div className="score-card">
      <div className="score-head">
        <span className="score-caption">Answer score</span>
        <span className="score-num">{score.score}<sub> / 10</sub></span>
      </div>
      <div className="score-track">
        <div className={`score-fill ${band(score.score)}`} style={{ width: `${score.score * 10}%` }} />
      </div>
      {score.strengths.length > 0 && (
        <div className="score-block">
          <p className="sbt">Strengths</p>
          <ul>{score.strengths.map((s, i) => <li key={i} className="si green-li">{s}</li>)}</ul>
        </div>
      )}
      {score.improvements.length > 0 && (
        <div className="score-block">
          <p className="sbt">To improve</p>
          <ul>{score.improvements.map((s, i) => <li key={i} className="si amber-li">{s}</li>)}</ul>
        </div>
      )}
    </div>
  )
}

function SummaryCard({
  summary, copied, creditsSpent, creditsLeft, onCopy, onReset, onForget
}: {
  summary: InterviewSummary
  copied: boolean
  /** Observed spend for this interview; 0 when nothing was seen to change. */
  creditsSpent: number
  creditsLeft: number
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
          <h3>Interview complete</h3>
          <p>{summary.role} — overall score</p>
        </div>
      </div>

      <div className="summary-section">
        <p className="sbt">Breakdown</p>
        <div className="summary-bars">
          {summary.breakdown.map((b, i) => (
            <div key={i} className="summary-bar-row">
              <span className="summary-bar-label" title={b.label}>{b.label}</span>
              <div className="score-track">
                <div className={`score-fill ${band(b.score)}`} style={{ width: `${b.score * 10}%` }} />
              </div>
              <span className="summary-bar-val">{b.score}/10</span>
            </div>
          ))}
        </div>
      </div>

      {summary.strengths.length > 0 && (
        <div className="score-block">
          <p className="sbt">Top strengths</p>
          <ul>{summary.strengths.map((s, i) => <li key={i} className="si green-li">{s}</li>)}</ul>
        </div>
      )}

      {summary.improvements.length > 0 && (
        <div className="score-block">
          <p className="sbt">Focus areas</p>
          <ul>{summary.improvements.map((s, i) => <li key={i} className="si amber-li">{s}</li>)}</ul>
        </div>
      )}

      <div className="summary-meta">
        <span>
          {summary.breakdown.length} question{summary.breakdown.length === 1 ? '' : 's'} scored
        </span>
        {creditsSpent > 0 && <span>{creditsSpent} credits used</span>}
        <span>{creditsLeft} credits left</span>
      </div>

      <div className="summary-actions">
        <button className={`copy-btn${copied ? ' copied' : ''}`} onClick={onCopy}>
          {copied ? 'Copied' : 'Copy results'}
        </button>
        <button className="btn-primary" style={{ flex: 1 }} onClick={onReset}>
          New interview
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

function AlertIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      className="error-icon" aria-hidden>
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="13" />
      <line x1="12" y1="16.5" x2="12" y2="16.5" />
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

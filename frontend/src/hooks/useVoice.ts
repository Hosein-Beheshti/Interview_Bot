import { useState, useCallback, useRef, useEffect } from 'react'

/** One unit of speech: the text, and the audio being fetched for it. */
type SpeechChunk = { text: string; audio: Promise<Blob | null> }

// Chunk sizes trade time-to-first-sound against request count. Only the first
// chunk is cut short — that is the one the candidate is actually waiting on —
// and everything after it is aggregated, because `/speak` bills per 1,000
// characters rounded up, so each extra request can cost an extra credit.
const FIRST_CHUNK_MIN_CHARS = 12
const CHUNK_MIN_CHARS = 240
const CHUNK_MAX_CHARS = 600
// `/speak` rejects text longer than 2,000 characters, so no single chunk may
// reach that even when the whole tail is flushed at once.
const SPEAK_MAX_CHARS = 1800

function cutAtSpace(text: string, max: number): number {
  const cut = text.lastIndexOf(' ', max)
  return cut > 0 ? cut + 1 : max
}

/** Length of the next chunk to cut from `buffer`, or 0 to keep accumulating.
 *
 * A sentence boundary is a terminator followed by whitespace — requiring the
 * whitespace is what keeps "3.5" and a terminator still being streamed from
 * splitting a chunk mid-token.
 */
function nextChunkLength(buffer: string, minChars: number): number {
  const boundary = /[.!?…]["')\]]*\s|\n+/g
  let match: RegExpExecArray | null
  while ((match = boundary.exec(buffer)) !== null) {
    const end = match.index + match[0].length
    if (end >= minChars) return end
  }
  // No boundary in a long run of text — cut at a word break rather than let the
  // queue starve waiting for a full stop that may never come.
  if (buffer.length >= CHUNK_MAX_CHARS) return cutAtSpace(buffer, CHUNK_MAX_CHARS)
  return 0
}

export function useVoice() {
  const [isListening, setIsListening] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [interimText, setInterimText] = useState('')
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [micError, setMicError] = useState<string | null>(null)

  const recognitionRef = useRef<any>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const isListeningRef = useRef(false)
  const speakSeqRef = useRef(0)
  const speechUtterRef = useRef<SpeechSynthesisUtterance | null>(null)
  const primedAudioRef = useRef<HTMLAudioElement | null>(null)
  const audioPrimedRef = useRef(false)
  const speechSynthPrimedRef = useRef(false)

  // Streaming-speech state, all reset by `beginSpeech`.
  const bufferRef = useRef('')          // text seen but not yet cut into a chunk
  const consumedLenRef = useRef(0)      // how much of the source text was taken
  const chunkCountRef = useRef(0)
  const queueRef = useRef<SpeechChunk[]>([])
  const drainingRef = useRef(false)
  const noMoreChunksRef = useRef(false)
  const onEndRef = useRef<(() => void) | undefined>(undefined)
  // Resolves whatever is playing right now, so a cancelled utterance never
  // leaves the drain loop suspended on a promise nobody will settle.
  const cancelPlaybackRef = useRef<(() => void) | null>(null)

  // 1×1 silent MP3 (~50 bytes) used to prime the <audio> element during a user tap.
  const SILENT_MP3 = 'data:audio/mpeg;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4Ljc2LjEwMAAAAAAAAAAAAAAA//tQwAAAAAAAAAAAAAAAAAAAAAAASW5mbwAAAA8AAAACAAACcQCAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgID/////////////////////////////////////AAAAAExhdmM1OC4xMwAAAAAAAAAAAAAAACQDgAAAAAAAAAJxa9rXmAAAAAAAAAAAAAAAAAAAAAAA'

  const unlockAudio = useCallback(() => {
    // Unlock Web Audio API
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext
      if (AudioCtx) {
        if (!audioContextRef.current) audioContextRef.current = new AudioCtx()
        const ctx = audioContextRef.current
        const buffer = ctx.createBuffer(1, 1, 22050)
        const source = ctx.createBufferSource()
        source.buffer = buffer
        source.connect(ctx.destination)
        source.start(0)
        ctx.resume()
      }
    } catch {}

    // Prime an HTMLAudioElement so it can be played later from non-gesture contexts (iOS Safari)
    if (!audioPrimedRef.current) {
      try {
        const audio = new Audio()
        audio.preload = 'auto'
        audio.src = SILENT_MP3
        const p = audio.play()
        if (p && typeof p.then === 'function') {
          p.then(() => {
            try { audio.pause() } catch {}
            audio.currentTime = 0
            audioPrimedRef.current = true
          }).catch(() => {})
        }
        primedAudioRef.current = audio
      } catch {}
    }

    // Prime speechSynthesis on iOS — speak an empty utterance inside the gesture
    if (!speechSynthPrimedRef.current && 'speechSynthesis' in window) {
      try {
        const u = new SpeechSynthesisUtterance('')
        u.volume = 0
        window.speechSynthesis.speak(u)
        speechSynthPrimedRef.current = true
      } catch {}
    }
  }, [])

  useEffect(() => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) return

    const r = new SR()
    r.continuous = true
    r.interimResults = true
    r.lang = 'en-US'

    r.onresult = (e: any) => {
      let final = ''
      let interim = ''
      for (let i = 0; i < e.results.length; i++) {
        const seg = e.results[i][0]?.transcript ?? ''
        if (e.results[i].isFinal) final += seg + ' '
        else interim += seg + ' '
      }
      setTranscript(final.trim())
      setInterimText(interim.trim())
    }

    r.onend = () => {
      if (isListeningRef.current) {
        try { r.start() } catch {}
      } else {
        setIsListening(false)
        setInterimText('')
      }
    }

    r.onerror = (e: any) => {
      if (e.error === 'not-allowed') {
        setMicError('Microphone access denied — allow microphone in your browser settings.')
        isListeningRef.current = false
        setIsListening(false)
      }
    }

    recognitionRef.current = r
    return () => {
      isListeningRef.current = false
      try { r.stop() } catch {}
    }
  }, [])

  const startListening = useCallback(() => {
    if (!recognitionRef.current) {
      setMicError('Speech recognition is not supported. Please use Chrome, Edge, or Safari.')
      return
    }
    setTranscript('')
    setInterimText('')
    setMicError(null)
    isListeningRef.current = true
    setIsListening(true)
    try {
      recognitionRef.current.start()
    } catch {
      // Already started — stop and restart to reset results buffer
      try {
        recognitionRef.current.stop()
        setTimeout(() => {
          if (isListeningRef.current) {
            try { recognitionRef.current.start() } catch {}
          }
        }, 100)
      } catch {}
    }
  }, [])

  const stopListening = useCallback(() => {
    isListeningRef.current = false
    try { recognitionRef.current?.stop() } catch {}
  }, [])

  const resetTranscript = useCallback(() => {
    setTranscript('')
    setInterimText('')
    if (isListeningRef.current && recognitionRef.current) {
      try {
        recognitionRef.current.stop()
      } catch {}
    }
  }, [])

  const stopAllAudio = useCallback(() => {
    cancelPlaybackRef.current?.()
    cancelPlaybackRef.current = null
    // The abandoned drain loop, if any, exits on its next sequence check; it no
    // longer owns the flag, so a new utterance can start draining immediately.
    drainingRef.current = false
    queueRef.current = []
    if (primedAudioRef.current) {
      const a = primedAudioRef.current
      a.onended = null
      a.onerror = null
      try { a.pause() } catch {}
    }
    if (speechUtterRef.current) {
      speechUtterRef.current.onend = null
      speechUtterRef.current.onerror = null
      speechUtterRef.current = null
    }
    try { window.speechSynthesis?.cancel() } catch {}
  }, [])

  /** Fetch synthesized audio for one chunk. Null means "use the browser voice". */
  const synthesize = useCallback(async (text: string): Promise<Blob | null> => {
    try {
      const apiBase = import.meta.env.VITE_API_URL
        ? `${import.meta.env.VITE_API_URL}/api`
        : '/api'
      const res = await fetch(`${apiBase}/speak`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // /speak requires a signed-in user and debits credits, so the session
        // cookie has to ride along. Without this the request 401s and the
        // browser-TTS fallback below silently takes over.
        credentials: 'include',
        body: JSON.stringify({ text }),
      })
      if (!res.ok) return null
      return await res.blob()
    } catch {
      return null
    }
  }, [])

  /** Play one chunk's audio to completion. False means it never played. */
  const playBlob = useCallback(
    (blob: Blob, myId: number) =>
      new Promise<boolean>((resolve) => {
        const url = URL.createObjectURL(blob)
        // Reuse the element primed during the user gesture: on iOS that is the
        // only one allowed to start playing outside of one.
        const audio = primedAudioRef.current ?? new Audio()
        if (!primedAudioRef.current) primedAudioRef.current = audio

        let settled = false
        const settle = (played: boolean) => {
          if (settled) return
          settled = true
          cancelPlaybackRef.current = null
          URL.revokeObjectURL(url)
          audio.onended = null
          audio.onerror = null
          resolve(played)
        }

        cancelPlaybackRef.current = () => {
          try { audio.pause() } catch {}
          settle(false)
        }
        audio.onended = () => settle(true)
        audio.onerror = () => settle(false)
        audio.src = url
        audio.play().then(
          () => { if (speakSeqRef.current === myId) setIsSpeaking(true) },
          () => settle(false),
        )
      }),
    [],
  )

  const speakViaBrowser = useCallback(
    (text: string, myId: number) =>
      new Promise<void>((resolve) => {
        if (!text || !('speechSynthesis' in window)) { resolve(); return }
        const u = new SpeechSynthesisUtterance(text)
        u.rate = 0.95
        u.pitch = 1
        speechUtterRef.current = u

        let settled = false
        const settle = () => {
          if (settled) return
          settled = true
          if (speechUtterRef.current === u) speechUtterRef.current = null
          cancelPlaybackRef.current = null
          resolve()
        }

        cancelPlaybackRef.current = () => {
          try { window.speechSynthesis.cancel() } catch {}
          settle()
        }
        u.onend = settle
        u.onerror = settle
        if (speakSeqRef.current === myId) setIsSpeaking(true)
        try { window.speechSynthesis.speak(u) } catch { settle() }
      }),
    [],
  )

  /** Play queued chunks in order. Re-entrant calls are no-ops; whichever call
   *  owns the loop picks up chunks queued while it was already running. */
  const drain = useCallback(
    async (myId: number) => {
      if (drainingRef.current) return
      drainingRef.current = true

      while (speakSeqRef.current === myId) {
        const chunk = queueRef.current.shift()
        if (!chunk) break
        const blob = await chunk.audio
        if (speakSeqRef.current !== myId) return
        const played = blob ? await playBlob(blob, myId) : false
        if (speakSeqRef.current !== myId) return
        if (!played) {
          await speakViaBrowser(chunk.text, myId)
          if (speakSeqRef.current !== myId) return
        }
      }
      if (speakSeqRef.current !== myId) return

      drainingRef.current = false
      if (noMoreChunksRef.current && queueRef.current.length === 0) {
        setIsSpeaking(false)
        // Nothing was ever queued for an empty reply, and an empty reply should
        // not hand the turn back as though it had been read out.
        if (chunkCountRef.current > 0) onEndRef.current?.()
        onEndRef.current = undefined
      }
    },
    [playBlob, speakViaBrowser],
  )

  const flushChunks = useCallback(
    (myId: number, final: boolean) => {
      for (;;) {
        const buffer = bufferRef.current
        if (!buffer) break
        const minChars = chunkCountRef.current === 0 ? FIRST_CHUNK_MIN_CHARS : CHUNK_MIN_CHARS
        const take = final
          ? (buffer.length > SPEAK_MAX_CHARS ? cutAtSpace(buffer, SPEAK_MAX_CHARS) : buffer.length)
          : nextChunkLength(buffer, minChars)
        if (take <= 0) break

        const text = buffer.slice(0, take).trim()
        bufferRef.current = buffer.slice(take)
        if (text) {
          chunkCountRef.current += 1
          queueRef.current.push({ text, audio: synthesize(text) })
        }
      }
      void drain(myId)
    },
    [drain, synthesize],
  )

  /** Start a new utterance, cancelling anything still speaking. */
  const beginSpeech = useCallback(() => {
    speakSeqRef.current++
    stopAllAudio()
    bufferRef.current = ''
    consumedLenRef.current = 0
    chunkCountRef.current = 0
    noMoreChunksRef.current = false
    onEndRef.current = undefined
    setIsSpeaking(false)
  }, [stopAllAudio])

  /** Feed the utterance's text so far; synthesis starts at each sentence. */
  const pushSpeech = useCallback(
    (textSoFar: string) => {
      if (textSoFar.length <= consumedLenRef.current) return
      bufferRef.current += textSoFar.slice(consumedLenRef.current)
      consumedLenRef.current = textSoFar.length
      flushChunks(speakSeqRef.current, false)
    },
    [flushChunks],
  )

  /** No more text is coming: speak the tail, then run `onEnd` once it all has. */
  const endSpeech = useCallback(
    (onEnd?: () => void) => {
      onEndRef.current = onEnd
      noMoreChunksRef.current = true
      flushChunks(speakSeqRef.current, true)
    },
    [flushChunks],
  )

  const stopSpeaking = useCallback(() => {
    speakSeqRef.current++
    noMoreChunksRef.current = false
    onEndRef.current = undefined
    stopAllAudio()
    setIsSpeaking(false)
  }, [stopAllAudio])

  return {
    isListening,
    transcript,
    interimText,
    isSpeaking,
    micError,
    unlockAudio,
    startListening,
    stopListening,
    resetTranscript,
    beginSpeech,
    pushSpeech,
    endSpeech,
    stopSpeaking,
  }
}

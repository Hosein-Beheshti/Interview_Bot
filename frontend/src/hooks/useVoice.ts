import { useState, useCallback, useRef, useEffect } from 'react'

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

  const speak = useCallback(async (text: string, onEnd?: () => void) => {
    const myId = ++speakSeqRef.current

    stopAllAudio()
    setIsSpeaking(true)

    const finishIfCurrent = () => {
      if (speakSeqRef.current !== myId) return
      setIsSpeaking(false)
      onEnd?.()
    }

    const browserTTS = () => {
      if (speakSeqRef.current !== myId) return
      if (!('speechSynthesis' in window)) { finishIfCurrent(); return }
      const u = new SpeechSynthesisUtterance(text)
      u.rate = 0.95
      u.pitch = 1
      speechUtterRef.current = u
      u.onend = () => {
        if (speechUtterRef.current === u) speechUtterRef.current = null
        finishIfCurrent()
      }
      u.onerror = () => {
        if (speechUtterRef.current === u) speechUtterRef.current = null
        if (speakSeqRef.current === myId) setIsSpeaking(false)
      }
      try { window.speechSynthesis.speak(u) } catch { finishIfCurrent() }
    }

    try {
      const apiBase = import.meta.env.VITE_API_URL
        ? `${import.meta.env.VITE_API_URL}/api`
        : '/api'
      const res = await fetch(`${apiBase}/speak`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })

      if (speakSeqRef.current !== myId) return

      if (res.ok) {
        const blob = await res.blob()
        if (speakSeqRef.current !== myId) return

        const url = URL.createObjectURL(blob)
        // Reuse the audio element that was primed during the user gesture
        const audio = primedAudioRef.current ?? new Audio()
        if (!primedAudioRef.current) primedAudioRef.current = audio

        const cleanup = () => {
          URL.revokeObjectURL(url)
          audio.onended = null
          audio.onerror = null
        }

        audio.onended = () => { cleanup(); finishIfCurrent() }
        audio.onerror = () => {
          cleanup()
          if (speakSeqRef.current === myId) browserTTS()
        }

        audio.src = url
        try {
          await audio.play()
        } catch {
          cleanup()
          if (speakSeqRef.current === myId) browserTTS()
        }
        return
      }
    } catch {}

    if (speakSeqRef.current === myId) browserTTS()
  }, [stopAllAudio])

  const stopSpeaking = useCallback(() => {
    speakSeqRef.current++
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
    speak,
    stopSpeaking,
  }
}

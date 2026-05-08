import { useState, useCallback, useRef, useEffect } from 'react'

export function useVoice() {
  const [isListening, setIsListening] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [micError, setMicError] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const recognitionRef = useRef<any>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const isListeningRef = useRef(false)

  const unlockAudio = useCallback(() => {
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext
      if (!AudioCtx) return
      if (!audioContextRef.current) {
        audioContextRef.current = new AudioCtx()
      }
      const ctx = audioContextRef.current
      const buffer = ctx.createBuffer(1, 1, 22050)
      const source = ctx.createBufferSource()
      source.buffer = buffer
      source.connect(ctx.destination)
      source.start(0)
      ctx.resume()
    } catch {}
  }, [])

  useEffect(() => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) return

    const r = new SR()
    r.continuous = true
    r.interimResults = false
    r.lang = 'en-US'

    r.onresult = (e: any) => {
      // Accumulate all results from this session, not just the first one
      let text = ''
      for (let i = 0; i < e.results.length; i++) {
        text += (e.results[i][0]?.transcript ?? '') + ' '
      }
      const trimmed = text.trim()
      if (trimmed) setTranscript(trimmed)
    }

    // Restart automatically if still supposed to be listening (handles browser timeouts)
    r.onend = () => {
      if (isListeningRef.current) {
        try { r.start() } catch {}
      } else {
        setIsListening(false)
      }
    }

    r.onerror = (e: any) => {
      if (e.error === 'not-allowed') {
        setMicError('Microphone access denied — click the 🔒 icon in the address bar and allow microphone.')
        isListeningRef.current = false
        setIsListening(false)
      }
      // For other errors (network, aborted) let onend handle the restart
    }

    recognitionRef.current = r
  }, [])

  const startListening = useCallback(() => {
    if (!recognitionRef.current) {
      setMicError('Speech recognition is not supported in this browser. Please use Chrome or Edge.')
      return
    }
    setTranscript('')
    setMicError(null)
    isListeningRef.current = true
    setIsListening(true)
    try {
      recognitionRef.current.start()
    } catch {
      isListeningRef.current = false
      setIsListening(false)
    }
  }, [])

  const stopListening = useCallback(() => {
    isListeningRef.current = false
    try { recognitionRef.current?.stop() } catch {}
  }, [])

  const speak = useCallback(async (text: string, onEnd?: () => void) => {
    if (audioRef.current) audioRef.current.pause()
    window.speechSynthesis?.cancel()
    setIsSpeaking(true)

    const browserTTS = () => {
      if (!('speechSynthesis' in window)) { setIsSpeaking(false); onEnd?.(); return }
      const u = new SpeechSynthesisUtterance(text)
      u.rate = 0.92
      u.pitch = 1
      u.onend = () => { setIsSpeaking(false); onEnd?.() }
      u.onerror = () => { setIsSpeaking(false) }
      window.speechSynthesis.speak(u)
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
      if (res.ok) {
        const blob = await res.blob()
        const url = URL.createObjectURL(blob)
        const audio = new Audio(url)
        audioRef.current = audio
        audio.onended = () => { setIsSpeaking(false); URL.revokeObjectURL(url); onEnd?.() }
        audio.onerror = () => { setIsSpeaking(false); URL.revokeObjectURL(url); browserTTS() }
        audio.play().catch(() => { setIsSpeaking(false); URL.revokeObjectURL(url); browserTTS() })
        return
      }
    } catch {}

    browserTTS()
  }, [])

  const stopSpeaking = useCallback(() => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current.currentTime = 0 }
    window.speechSynthesis?.cancel()
    setIsSpeaking(false)
  }, [])

  return {
    isListening,
    transcript,
    isSpeaking,
    micError,
    unlockAudio,
    startListening,
    stopListening,
    speak,
    stopSpeaking,
    clearTranscript: () => setTranscript(''),
  }
}

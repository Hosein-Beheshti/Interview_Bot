import { useState, useCallback, useRef, useEffect } from 'react'

export function useVoice() {
  const [isListening, setIsListening] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [micError, setMicError] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const recognitionRef = useRef<any>(null)
  const audioContextRef = useRef<AudioContext | null>(null)

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

  // Wire up Web Speech API for STT (works in Edge/Chrome with no API key)
  useEffect(() => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) return

    const r = new SR()
    r.continuous = false
    r.interimResults = false
    r.lang = 'en-US'

    r.onresult = (e: any) => {
      const text = e.results[0]?.[0]?.transcript ?? ''
      if (text) setTranscript(text.trim())
    }
    r.onend = () => setIsListening(false)
    r.onerror = (e: any) => {
      if (e.error === 'not-allowed') {
        setMicError('Microphone access denied — click the 🔒 icon in the address bar and allow microphone.')
      }
      setIsListening(false)
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
    setIsListening(true)
    try {
      recognitionRef.current.start()
    } catch {
      setIsListening(false)
    }
  }, [])

  const stopListening = useCallback(() => {
    try { recognitionRef.current?.stop() } catch {}
  }, [])

  // TTS: try Deepgram /api/speak first, fall back to browser speechSynthesis
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

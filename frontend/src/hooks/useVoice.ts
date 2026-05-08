import { useState, useCallback, useRef } from 'react'

const apiBase = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api`
  : '/api'

function pickMimeType(): string {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4;codecs=mp4a.40.2',
    'audio/mp4',
    'audio/aac',
  ]
  if (typeof MediaRecorder === 'undefined') return ''
  for (const t of candidates) {
    try { if (MediaRecorder.isTypeSupported(t)) return t } catch {}
  }
  return ''
}

export function useVoice() {
  const [isListening, setIsListening] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [micError, setMicError] = useState<string | null>(null)

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const audioStreamRef = useRef<MediaStream | null>(null)
  const recorderMimeRef = useRef<string>('')

  const audioContextRef = useRef<AudioContext | null>(null)
  const speakSeqRef = useRef(0)
  const speechUtterRef = useRef<SpeechSynthesisUtterance | null>(null)
  const primedAudioRef = useRef<HTMLAudioElement | null>(null)
  const audioPrimedRef = useRef(false)
  const speechSynthPrimedRef = useRef(false)

  const SILENT_MP3 = 'data:audio/mpeg;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4Ljc2LjEwMAAAAAAAAAAAAAAA//tQwAAAAAAAAAAAAAAAAAAAAAAASW5mbwAAAA8AAAACAAACcQCAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgID/////////////////////////////////////AAAAAExhdmM1OC4xMwAAAAAAAAAAAAAAACQDgAAAAAAAAAJxa9rXmAAAAAAAAAAAAAAAAAAAAAAA'

  const unlockAudio = useCallback(() => {
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

    if (!speechSynthPrimedRef.current && 'speechSynthesis' in window) {
      try {
        const u = new SpeechSynthesisUtterance('')
        u.volume = 0
        window.speechSynthesis.speak(u)
        speechSynthPrimedRef.current = true
      } catch {}
    }
  }, [])

  const cleanupRecorder = useCallback(() => {
    if (audioStreamRef.current) {
      try { audioStreamRef.current.getTracks().forEach(t => t.stop()) } catch {}
      audioStreamRef.current = null
    }
    mediaRecorderRef.current = null
    audioChunksRef.current = []
  }, [])

  const transcribeBlob = useCallback(async (blob: Blob, mime: string) => {
    setIsTranscribing(true)
    try {
      const ext = mime.includes('webm') ? 'webm' : mime.includes('mp4') ? 'mp4' : 'audio'
      const formData = new FormData()
      formData.append('audio', blob, `recording.${ext}`)
      const res = await fetch(`${apiBase}/transcribe`, { method: 'POST', body: formData })
      if (!res.ok) throw new Error('Transcription failed')
      const data = await res.json()
      const text = (data.transcript || '').trim()
      if (text) setTranscript(text)
      else setMicError('No speech detected — please try again.')
    } catch {
      setMicError('Transcription failed — please try typing your answer instead.')
    } finally {
      setIsTranscribing(false)
    }
  }, [])

  const startListening = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setMicError('Voice input is not supported in this browser.')
      return
    }
    setMicError(null)
    setTranscript('')
    audioChunksRef.current = []

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      audioStreamRef.current = stream

      const mime = pickMimeType()
      recorderMimeRef.current = mime
      const recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream)
      mediaRecorderRef.current = recorder

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) audioChunksRef.current.push(e.data)
      }

      recorder.onstop = async () => {
        const chunks = audioChunksRef.current
        const usedMime = recorder.mimeType || mime || 'audio/webm'
        cleanupRecorder()
        setIsListening(false)
        if (chunks.length === 0) return
        const blob = new Blob(chunks, { type: usedMime })
        if (blob.size < 500) {
          setMicError('Recording too short — please try again.')
          return
        }
        await transcribeBlob(blob, usedMime)
      }

      recorder.onerror = () => {
        cleanupRecorder()
        setIsListening(false)
        setMicError('Recording error — please try again.')
      }

      recorder.start()
      setIsListening(true)
    } catch (err: any) {
      cleanupRecorder()
      setIsListening(false)
      if (err?.name === 'NotAllowedError') {
        setMicError('Microphone access denied — allow microphone in your browser settings.')
      } else {
        setMicError('Could not access microphone.')
      }
    }
  }, [cleanupRecorder, transcribeBlob])

  const stopListening = useCallback(() => {
    const r = mediaRecorderRef.current
    if (r && r.state !== 'inactive') {
      try { r.stop() } catch {}
    } else {
      cleanupRecorder()
      setIsListening(false)
    }
  }, [cleanupRecorder])

  const resetTranscript = useCallback(() => {
    setTranscript('')
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
    isTranscribing,
    transcript,
    interimText: '',
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

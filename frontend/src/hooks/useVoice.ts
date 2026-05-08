import { useState, useCallback, useRef } from 'react'

const apiBase = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api`
  : '/api'

const wsBase = (() => {
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL.replace(/^http/, 'ws') + '/api'
  }
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/api`
})()

function pickMimeType(): string {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4;codecs=mp4a.40.2',
    'audio/mp4',
  ]
  if (typeof MediaRecorder === 'undefined') return ''
  for (const t of candidates) {
    try { if (MediaRecorder.isTypeSupported(t)) return t } catch {}
  }
  return ''
}

export function useVoice() {
  const [isListening, setIsListening] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [interimText, setInterimText] = useState('')
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [micError, setMicError] = useState<string | null>(null)

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioStreamRef = useRef<MediaStream | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const finalTranscriptRef = useRef('')

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

  const cleanup = useCallback(() => {
    if (mediaRecorderRef.current) {
      try {
        if (mediaRecorderRef.current.state !== 'inactive') {
          mediaRecorderRef.current.stop()
        }
      } catch {}
      mediaRecorderRef.current = null
    }
    if (audioStreamRef.current) {
      try { audioStreamRef.current.getTracks().forEach(t => t.stop()) } catch {}
      audioStreamRef.current = null
    }
    if (wsRef.current) {
      try {
        if (wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.send('close')
          wsRef.current.close()
        }
      } catch {}
      wsRef.current = null
    }
  }, [])

  const startListening = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setMicError('Voice input is not supported in this browser.')
      return
    }
    setMicError(null)
    setTranscript('')
    setInterimText('')
    finalTranscriptRef.current = ''

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      audioStreamRef.current = stream

      const ws = new WebSocket(`${wsBase}/transcribe-stream`)
      ws.binaryType = 'arraybuffer'
      wsRef.current = ws

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'Results') {
            const alt = data.channel?.alternatives?.[0]
            if (!alt) return
            const text = (alt.transcript || '').trim()
            if (!text) return
            if (data.is_final) {
              finalTranscriptRef.current = [
                finalTranscriptRef.current, text,
              ].filter(Boolean).join(' ').trim()
              setTranscript(finalTranscriptRef.current)
              setInterimText('')
            } else {
              setInterimText(text)
            }
          }
        } catch {}
      }

      ws.onerror = () => {
        setMicError('Connection error — please try again.')
      }

      ws.onopen = () => {
        const mime = pickMimeType()
        const recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream)
        mediaRecorderRef.current = recorder

        recorder.ondataavailable = (e) => {
          if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
            e.data.arrayBuffer().then(buf => {
              if (ws.readyState === WebSocket.OPEN) ws.send(buf)
            })
          }
        }

        recorder.onerror = () => {
          setMicError('Recording error — please try again.')
          cleanup()
          setIsListening(false)
        }

        recorder.start(250)
        setIsListening(true)
      }

      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null
      }

    } catch (err: any) {
      cleanup()
      setIsListening(false)
      if (err?.name === 'NotAllowedError') {
        setMicError('Microphone access denied — allow microphone in your browser settings.')
      } else {
        setMicError('Could not access microphone.')
      }
    }
  }, [cleanup])

  const stopListening = useCallback(() => {
    cleanup()
    setIsListening(false)
    setInterimText('')
  }, [cleanup])

  const resetTranscript = useCallback(() => {
    finalTranscriptRef.current = ''
    setTranscript('')
    setInterimText('')
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

        const cleanupAudio = () => {
          URL.revokeObjectURL(url)
          audio.onended = null
          audio.onerror = null
        }

        audio.onended = () => { cleanupAudio(); finishIfCurrent() }
        audio.onerror = () => {
          cleanupAudio()
          if (speakSeqRef.current === myId) browserTTS()
        }

        audio.src = url
        try {
          await audio.play()
        } catch {
          cleanupAudio()
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
    isTranscribing: false,
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

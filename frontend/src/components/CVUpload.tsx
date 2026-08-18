import { useCallback, useRef, useState } from 'react'
import { acceptedCVTypes } from '../hooks/useCV'
import { maxUploadMB } from '../hooks/useConfig'
import { ClientConfig, CVInfo } from '../types'

/** Pasted text is uploaded as a text file rather than through a second
 *  endpoint: `/cv/upload` already accepts `.txt` and decodes it as UTF-8, so
 *  the paste path reuses the parsing, indexing, and size limits the file path
 *  is already validated against — including the upload size bound, which is why
 *  the textarea needs no character cap of its own. */
const PASTED_CV_FILENAME = 'pasted-cv.txt'

type Mode = 'file' | 'text'

interface Props {
  info: CVInfo | null
  uploading: boolean
  error: string | null
  config: ClientConfig
  onUpload: (file: File) => void
  onRemove: () => void
}

export function CVUpload({ info, uploading, error, config, onUpload, onRemove }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [mode, setMode] = useState<Mode>('file')
  const [text, setText] = useState('')

  const handleFiles = useCallback(
    (files: FileList | null) => {
      const file = files?.[0]
      if (file) onUpload(file)
    },
    [onUpload],
  )

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    handleFiles(e.dataTransfer.files)
  }

  const trimmed = text.trim()
  // The server applies this same minimum to the text it extracts, and rejects
  // before it creates the session — catching it here saves the round trip, not
  // the charge.
  const tooShort = trimmed.length < config.cv_min_chars

  const submitText = () => {
    if (tooShort || uploading) return
    onUpload(new File([trimmed], PASTED_CV_FILENAME, { type: 'text/plain' }))
  }

  if (info) {
    return (
      <div className="cv-attached">
        <div className="cv-attached-info">
          <DocumentIcon />
          <div className="cv-attached-text">
            <span className="cv-filename">
              {info.filename === PASTED_CV_FILENAME ? 'Pasted CV' : info.filename}
            </span>
            <span className="cv-meta">
              {info.chunk_count} chunks
              {info.sections.length > 0 ? ` · ${info.sections.slice(0, 4).join(', ')}` : ''}
            </span>
          </div>
        </div>
        <button className="cv-remove" onClick={onRemove} aria-label="Remove CV">
          Remove
        </button>
      </div>
    )
  }

  return (
    <div className="cv-input">
      <div className="cv-tabs" role="tablist" aria-label="How to provide your CV">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'file'}
          className={`cv-tab${mode === 'file' ? ' cv-tab-active' : ''}`}
          onClick={() => setMode('file')}
          disabled={uploading}
        >
          Upload a file
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'text'}
          className={`cv-tab${mode === 'text' ? ' cv-tab-active' : ''}`}
          onClick={() => setMode('text')}
          disabled={uploading}
        >
          Paste the text
        </button>
      </div>

      {mode === 'file' ? (
        <div
          className={`cv-dropzone${dragging ? ' dragging' : ''}${uploading ? ' uploading' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => !uploading && inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept={acceptedCVTypes(config)}
            hidden
            onChange={(e) => handleFiles(e.target.files)}
          />

          {uploading ? (
            <div className="cv-status">
              <Spinner />
              <span>Reading and indexing your CV…</span>
            </div>
          ) : (
            <>
              <UploadIcon />
              <div className="cv-prompt">
                <strong>Drop your CV here, or click to browse</strong>
                <span>
                  {config.cv_accepted_extensions
                    .map((ext) => ext.replace('.', '').toUpperCase())
                    .join(', ')}{' '}
                  · up to {maxUploadMB(config)} MB · questions draw on your experience
                </span>
              </div>
            </>
          )}
        </div>
      ) : (
        <div className="cv-paste">
          <textarea
            className="cv-paste-box"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={
              'Paste or type your CV here.\n\nRoles and dates, what you actually built, the tools you used, education. Formatting is ignored — plain text is fine.'
            }
            disabled={uploading}
            rows={9}
            aria-label="Your CV as text"
          />
          <div className="cv-paste-foot">
            <span className={`cv-count${trimmed.length > 0 && tooShort ? ' cv-count-short' : ''}`}>
              {trimmed.length === 0
                ? 'Nothing pasted yet'
                : tooShort
                  ? `${trimmed.length} of ${config.cv_min_chars} characters minimum`
                  : `${trimmed.length.toLocaleString()} characters`}
            </span>
            <button
              type="button"
              className="btn-primary cv-paste-btn"
              onClick={submitText}
              disabled={tooShort || uploading}
            >
              {uploading ? (
                <>
                  <Spinner />
                  Indexing…
                </>
              ) : (
                'Use this CV'
              )}
            </button>
          </div>
        </div>
      )}

      {error && <div className="cv-error">{error}</div>}
    </div>
  )
}

function UploadIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  )
}

function DocumentIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  )
}

function Spinner() {
  return <span className="cv-spinner" aria-hidden />
}

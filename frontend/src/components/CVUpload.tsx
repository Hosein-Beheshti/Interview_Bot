import { useCallback, useRef, useState } from 'react'
import { ACCEPTED_CV_TYPES } from '../hooks/useCV'
import { CVInfo } from '../types'

interface Props {
  info: CVInfo | null
  uploading: boolean
  error: string | null
  onUpload: (file: File) => void
  onRemove: () => void
}

export function CVUpload({ info, uploading, error, onUpload, onRemove }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

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

  if (info) {
    return (
      <div className="cv-attached">
        <div className="cv-attached-info">
          <DocumentIcon />
          <div className="cv-attached-text">
            <span className="cv-filename">{info.filename}</span>
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
        accept={ACCEPTED_CV_TYPES}
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
            <span>PDF, DOCX or TXT · up to 5 MB · questions draw on your experience</span>
          </div>
        </>
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

import { useRef, useState } from 'react';
import { Upload, X } from 'lucide-react';

// ── DropZone sub-component ─────────────────────────────────────────────────

export interface DropZoneProps {
  accept: string;
  file: File | null;
  onFile: (f: File | null) => void;
  label: string;
  hint: string;
  icon: React.ElementType;
  disabled?: boolean;
  maxSizeMb?: number;
  onSizeError?: (msg: string) => void;
}

export default function DropZone({ accept, file, onFile, label, hint, icon: Icon, disabled, maxSizeMb, onSizeError }: DropZoneProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const validateAndSetFile = (f: File) => {
    if (maxSizeMb && f.size > maxSizeMb * 1024 * 1024) {
      const sizeMb = (f.size / (1024 * 1024)).toFixed(1);
      onSizeError?.(`File too large (${sizeMb} MB). Maximum allowed: ${maxSizeMb} MB`);
      return;
    }
    onFile(f);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (disabled) return;
    const f = e.dataTransfer.files[0];
    if (f) validateAndSetFile(f);
  };

  const classes = [
    'summarize-dropzone',
    dragging  ? 'dragging'  : '',
    disabled  ? 'disabled'  : '',
    file      ? 'has-file'  : '',
  ].filter(Boolean).join(' ');

  return (
    <div
      className={classes}
      onDragOver={(e) => { e.preventDefault(); if (!disabled) setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => { if (!disabled && !file) inputRef.current?.click(); }}
      role="button"
      tabIndex={disabled ? -1 : 0}
      onKeyDown={(e) => { if ((e.key === 'Enter' || e.key === ' ') && !disabled && !file) inputRef.current?.click(); }}
      aria-label={file ? `Selected file: ${file.name}` : label}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        style={{ display: 'none' }}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) validateAndSetFile(f); e.target.value = ''; }}
        disabled={disabled}
      />

      {file ? (
        <div className="summarize-dropzone-file">
          <Icon size={16} aria-hidden="true" />
          <span className="summarize-dropzone-name">{file.name}</span>
          <span className="summarize-dropzone-size">
            {(file.size / (1024 * 1024)).toFixed(1)} MB
          </span>
          {!disabled && (
            <button
              className="summarize-dropzone-remove"
              onClick={(e) => { e.stopPropagation(); onFile(null); }}
              aria-label="Remove file"
            >
              <X size={13} />
            </button>
          )}
        </div>
      ) : (
        <div className="summarize-dropzone-empty">
          <Upload size={22} className="summarize-dropzone-icon" aria-hidden="true" />
          <span className="summarize-dropzone-label">{label}</span>
          <span className="summarize-dropzone-hint">{hint}</span>
        </div>
      )}
    </div>
  );
}

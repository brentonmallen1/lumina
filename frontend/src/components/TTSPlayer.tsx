import { useState, useRef, useEffect } from 'react';
import { Volume2, Pause, Square, Loader } from 'lucide-react';
import * as api from '../api/client';
import './TTSPlayer.css';

interface TTSPlayerProps {
  text: string;
  /** Override the server default voice. */
  voice?: string;
  className?: string;
}

type PlayState = 'idle' | 'loading' | 'playing' | 'paused';

export default function TTSPlayer({ text, voice, className }: TTSPlayerProps) {
  const [state, setState]   = useState<PlayState>('idle');
  const [error, setError]   = useState<string | null>(null);
  const audioRef            = useRef<HTMLAudioElement | null>(null);
  const blobUrlRef          = useRef<string | null>(null);

  // Revoke blob URL on unmount to avoid memory leaks
  useEffect(() => {
    return () => {
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
      }
    };
  }, []);

  // Stop playback when the text changes (e.g. different result loaded)
  useEffect(() => {
    handleStop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  const handlePlay = async () => {
    setError(null);

    // Resume paused audio without re-fetching
    if (state === 'paused' && audioRef.current) {
      audioRef.current.play();
      setState('playing');
      return;
    }

    // Generate new audio
    setState('loading');
    try {
      const blob = await api.synthesizeSpeech(text, voice);

      // Revoke previous blob URL
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
      }
      const url = URL.createObjectURL(blob);
      blobUrlRef.current = url;

      const audio = new Audio(url);
      audio.onended = () => setState('idle');
      audio.onerror = () => {
        setError('Playback failed');
        setState('idle');
      };
      audioRef.current = audio;
      await audio.play();
      setState('playing');
    } catch (err) {
      setError((err as Error).message);
      setState('idle');
    }
  };

  const handlePause = () => {
    audioRef.current?.pause();
    setState('paused');
  };

  const handleStop = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
    setState('idle');
  };

  const disabled = !text?.trim();

  return (
    <div className={`tts-player${className ? ` ${className}` : ''}`}>
      {state === 'loading' ? (
        <button className="summarize-action-btn tts-loading-btn" disabled>
          <Loader size={13} className="tts-spin" aria-hidden="true" />
          Generating…
        </button>
      ) : state === 'playing' ? (
        <>
          <button className="summarize-action-btn tts-playing-btn" onClick={handlePause} title="Pause">
            <Pause size={13} aria-hidden="true" />
            Pause
          </button>
          <button className="summarize-action-btn tts-stop-btn" onClick={handleStop} title="Stop">
            <Square size={13} aria-hidden="true" />
          </button>
        </>
      ) : state === 'paused' ? (
        <>
          <button className="summarize-action-btn tts-playing-btn" onClick={handlePlay} title="Resume">
            <Volume2 size={13} aria-hidden="true" />
            Resume
          </button>
          <button className="summarize-action-btn tts-stop-btn" onClick={handleStop} title="Stop">
            <Square size={13} aria-hidden="true" />
          </button>
        </>
      ) : (
        <button
          className="summarize-action-btn"
          onClick={handlePlay}
          disabled={disabled}
          title="Read aloud"
        >
          <Volume2 size={13} aria-hidden="true" />
          Read Aloud
        </button>
      )}
      {error && <span className="tts-error" role="alert">{error}</span>}
    </div>
  );
}

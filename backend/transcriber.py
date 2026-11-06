import os
import threading

# One shared engine instance for the whole process. Loading Whisper/Canary
# models is slow and memory-hungry, so the API server and the job worker must
# share a single instance instead of loading one per job.
_shared_engine = None
_shared_lock = threading.Lock()


def load_engine():
    """Instantiate and return the configured transcription engine (always a new instance)."""
    name = os.getenv("TRANSCRIPTION_ENGINE", "faster-whisper").lower()

    if name == "whisper":
        from engines.whisper_engine import WhisperEngine
        return WhisperEngine()
    elif name == "faster-whisper":
        from engines.faster_whisper_engine import FasterWhisperEngine
        return FasterWhisperEngine()
    elif name == "canary":
        from engines.canary_engine import CanaryEngine
        return CanaryEngine()
    elif name == "qwen-audio":
        from engines.qwen_audio_engine import QwenAudioEngine
        return QwenAudioEngine()
    else:
        raise ValueError(
            f"Unknown TRANSCRIPTION_ENGINE '{name}'. "
            "Valid options: whisper, faster-whisper, canary, qwen-audio"
        )


def set_shared_engine(engine) -> None:
    """Register the process-wide engine (called by the server after (re)loading)."""
    global _shared_engine
    with _shared_lock:
        _shared_engine = engine


def get_engine():
    """Return the shared engine, loading it once if nobody has yet."""
    global _shared_engine
    if _shared_engine is not None:
        return _shared_engine
    with _shared_lock:
        if _shared_engine is None:
            _shared_engine = load_engine()
        return _shared_engine

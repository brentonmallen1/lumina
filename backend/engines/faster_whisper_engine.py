import os


class FasterWhisperEngine:
    """Faster-Whisper via CTranslate2 — supports CPU and CUDA GPU."""

    def __init__(self):
        import torch
        from faster_whisper import WhisperModel

        model_size = os.getenv("WHISPER_MODEL_SIZE", "large-v3")
        compute_type = os.getenv("COMPUTE_TYPE", "int8")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self.language = os.getenv("LANGUAGE", "en") or None

        print(f"[faster-whisper] Loading model '{model_size}' on {device} ({compute_type}) ...")
        self.model_name = f"faster-whisper/{model_size}"
        # HF_HOME env var controls where the CTranslate2 model is cached.
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
        print("[faster-whisper] Ready.")

    def transcribe(self, audio_path: str) -> dict:
        opts: dict = {"beam_size": 5, "word_timestamps": True}
        if self.language:
            opts["language"] = self.language
        segments, info = self._model.transcribe(audio_path, **opts)
        seg_list: list[dict] = []
        full_text: list[str] = []
        for seg in segments:
            seg_list.append({
                "start": seg.start,
                "end":   seg.end,
                "text":  seg.text.strip(),
                "words": [
                    {"word": w.word, "start": w.start, "end": w.end}
                    for w in (seg.words or [])
                ],
            })
            full_text.append(seg.text.strip())
        return {
            "text":     " ".join(full_text),
            "segments": seg_list,
            "language": info.language,
        }

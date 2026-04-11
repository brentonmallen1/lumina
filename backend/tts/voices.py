"""
Available Kokoro TTS voices (English only).

Voice IDs follow the pattern: {region}{gender}_{name}
  af_ = American Female
  am_ = American Male
  bf_ = British Female
  bm_ = British Male
"""

VOICES: dict[str, dict] = {
    # American Female
    "af_bella":   {"name": "Bella",   "gender": "female", "accent": "american"},
    "af_sarah":   {"name": "Sarah",   "gender": "female", "accent": "american"},
    "af_nova":    {"name": "Nova",    "gender": "female", "accent": "american"},
    "af_sky":     {"name": "Sky",     "gender": "female", "accent": "american"},
    "af_jessica": {"name": "Jessica", "gender": "female", "accent": "american"},
    "af_heart":   {"name": "Heart",   "gender": "female", "accent": "american"},
    # American Male
    "am_adam":    {"name": "Adam",    "gender": "male",   "accent": "american"},
    "am_michael": {"name": "Michael", "gender": "male",   "accent": "american"},
    "am_echo":    {"name": "Echo",    "gender": "male",   "accent": "american"},
    "am_eric":    {"name": "Eric",    "gender": "male",   "accent": "american"},
    # British Female
    "bf_emma":    {"name": "Emma",    "gender": "female", "accent": "british"},
    "bf_lily":    {"name": "Lily",    "gender": "female", "accent": "british"},
    "bf_alice":   {"name": "Alice",   "gender": "female", "accent": "british"},
    # British Male
    "bm_george":  {"name": "George",  "gender": "male",   "accent": "british"},
    "bm_lewis":   {"name": "Lewis",   "gender": "male",   "accent": "british"},
    "bm_daniel":  {"name": "Daniel",  "gender": "male",   "accent": "british"},
}

DEFAULT_VOICE = "af_bella"

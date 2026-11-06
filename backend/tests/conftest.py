"""Point every test at throwaway data/cache directories before app modules import."""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="lumina-tests-")
os.environ["DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["AUDIO_CACHE_DIR"] = os.path.join(_tmp, "audio")
os.makedirs(os.environ["AUDIO_CACHE_DIR"], exist_ok=True)

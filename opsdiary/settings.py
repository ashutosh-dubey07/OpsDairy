"""Local configuration. Importing this module never makes a network request."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "opsdiary.sqlite3"

# A local .env is optional and ignored by Git. Process environment values win.
load_dotenv(PROJECT_ROOT / ".env", override=False)

GNANI_API_KEY = os.getenv("GNANI_API_KEY", "").strip()
GNANI_STT_LANGUAGE_CODE = os.getenv("GNANI_STT_LANGUAGE_CODE", "hi-IN").strip()
GNANI_TTS_VOICE = os.getenv("GNANI_TTS_VOICE", "Poorvi").strip()
GNANI_TTS_LANGUAGE = os.getenv("GNANI_TTS_LANGUAGE", "hi-en").strip()

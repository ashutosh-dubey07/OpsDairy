"""Local configuration. Importing this module never makes a network request."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

# A local .env is optional and ignored by Git. Process environment values win.
load_dotenv(PROJECT_ROOT / ".env", override=False)


def resolve_database_path(configured_path: str | None = None) -> Path:
    """Resolve the configured SQLite path, defaulting to the local data folder."""
    if configured_path is None:
        configured_path = os.getenv("OPSDIARY_DATABASE_PATH", "")
    configured_path = configured_path.strip()
    if not configured_path:
        return DATA_DIR / "opsdiary.sqlite3"

    path = Path(configured_path).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


# Production-like deployments should mount persistent storage and set this path.
DATABASE_PATH = resolve_database_path()

GNANI_API_KEY = os.getenv("GNANI_API_KEY", "").strip()
GNANI_STT_LANGUAGE_CODE = os.getenv("GNANI_STT_LANGUAGE_CODE", "hi-IN").strip()
GNANI_TTS_VOICE = os.getenv("GNANI_TTS_VOICE", "Poorvi").strip()
GNANI_TTS_LANGUAGE = os.getenv("GNANI_TTS_LANGUAGE", "hi-en").strip()

"""Prepared Prisma v2.5 and Timbre v2.5 REST integrations.

Nothing in this module runs at import time. The local demo does not call these
functions; invoke them only after live API mode is explicitly wired and enabled.
"""

from io import BytesIO
import wave

import requests

from opsdiary.settings import (
    GNANI_API_KEY,
    GNANI_STT_LANGUAGE_CODE,
    GNANI_TTS_LANGUAGE,
    GNANI_TTS_VOICE,
)

STT_URL = "https://api.vachana.ai/stt/v3"
TTS_URL = "https://api.vachana.ai/api/v1/tts/inference"
SUPPORTED_WAV_SAMPLE_RATES = {8000, 16000, 22050, 24000, 44100, 48000}
SUPPORTED_WAV_SAMPLE_WIDTHS = {1, 2, 3, 4}


class GnaniConfigurationError(RuntimeError):
    """Raised when the API key is missing."""


class GnaniAPIError(RuntimeError):
    """Raised when a documented Gnani REST request fails."""


def wav_duration_seconds(audio_bytes: bytes) -> float:
    """Read the duration of a WAV clip using only the Python standard library."""
    if not audio_bytes:
        raise ValueError("Audio file is empty.")
    try:
        with wave.open(BytesIO(audio_bytes), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            if frame_rate <= 0 or frame_count <= 0:
                raise ValueError("WAV audio must contain at least one sample.")
            return frame_count / frame_rate
    except (wave.Error, EOFError) as exc:
        raise ValueError("Use a valid WAV recording for the live microphone/upload flow.") from exc


def validate_wav_duration(audio_bytes: bytes, max_seconds: int = 30) -> float:
    """Validate a WAV clip before it is sent to Prisma REST."""
    duration = wav_duration_seconds(audio_bytes)
    if duration > max_seconds:
        raise ValueError(f"Audio is {duration:.1f} seconds; the maximum is {max_seconds} seconds.")
    return duration


def _validate_timbre_wav(audio_bytes: bytes) -> None:
    """Reject malformed PCM or WAV headers that cannot be played reliably."""
    if not audio_bytes:
        raise GnaniAPIError("Timbre v2.5 returned an empty audio response.")
    try:
        with wave.open(BytesIO(audio_bytes), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
    except (wave.Error, EOFError, ValueError) as exc:
        raise GnaniAPIError(f"Timbre v2.5 returned an invalid WAV response: {exc}") from exc

    expected_audio_bytes = frame_count * channels * sample_width
    if (
        channels not in {1, 2}
        or sample_width not in SUPPORTED_WAV_SAMPLE_WIDTHS
        or sample_rate not in SUPPORTED_WAV_SAMPLE_RATES
        or frame_count <= 0
        or expected_audio_bytes > len(audio_bytes)
    ):
        raise GnaniAPIError(
            "Timbre v2.5 returned an unsupported or inconsistent WAV "
            f"(channels={channels}, sample_width={sample_width}, "
            f"sample_rate={sample_rate}, frames={frame_count}, "
            f"expected_audio_bytes={expected_audio_bytes}, "
            f"response_bytes={len(audio_bytes)})."
        )


def _headers(api_key: str | None = None) -> dict[str, str]:
    key = (api_key or GNANI_API_KEY).strip()
    if not key:
        raise GnaniConfigurationError(
            "Set GNANI_API_KEY in the process environment or local ignored .env file."
        )
    return {"X-API-Key-ID": key}


def transcribe_prisma_v25(
    audio_bytes: bytes,
    filename: str = "incident.wav",
    content_type: str = "audio/wav",
    language_code: str | None = None,
    api_key: str | None = None,
    timeout_seconds: int = 60,
) -> dict:
    """Send one short audio file to the Prisma v2.5 REST endpoint.

    `model` is intentionally omitted: the documented endpoint defaults to
    Prisma v2.5. `language_code` remains required by the API.
    """
    if not audio_bytes:
        raise ValueError("Audio file is empty.")
    language = (language_code or GNANI_STT_LANGUAGE_CODE).strip()
    if not language:
        raise ValueError("language_code is required by the Prisma REST endpoint.")
    try:
        response = requests.post(
            STT_URL,
            headers=_headers(api_key),
            files={"audio_file": (filename, BytesIO(audio_bytes), content_type)},
            data={"language_code": language},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
    except requests.RequestException as exc:
        raise GnaniAPIError(f"Prisma v2.5 request failed: {exc}") from exc
    except ValueError as exc:
        raise GnaniAPIError("Prisma v2.5 returned an invalid response.") from exc
    if not body.get("success", False):
        error = body.get("error", {})
        raise GnaniAPIError(error.get("message", "Prisma v2.5 transcription failed."))
    return body


def synthesize_timbre_v25(
    text: str,
    voice: str | None = None,
    language: str | None = None,
    api_key: str | None = None,
    timeout_seconds: int = 60,
) -> bytes:
    """Return WAV bytes from the documented Timbre v2.5 REST endpoint."""
    if not text.strip():
        raise ValueError("Text to synthesize cannot be empty.")
    payload = {
        "text": text,
        "model": "timbre-v2.5",
        "voice": (voice or GNANI_TTS_VOICE).strip(),
        "language": (language or GNANI_TTS_LANGUAGE).strip(),
        "audio_config": {
            "encoding": "linear_pcm",
            "container": "wav",
            "num_channels": 1,
            "sample_rate": 48000,
            "sample_width": 2,
        },
    }
    headers = {**_headers(api_key), "Content-Type": "application/json"}
    try:
        response = requests.post(
            TTS_URL, headers=headers, json=payload, timeout=timeout_seconds
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise GnaniAPIError(f"Timbre v2.5 request failed: {exc}") from exc
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type not in {"audio/wav", "audio/x-wav", "audio/vnd.wave"}:
        raise GnaniAPIError(
            f"Timbre v2.5 returned a non-WAV response ({content_type or 'empty'}); expected audio/wav."
        )
    audio_bytes = response.content
    _validate_timbre_wav(audio_bytes)
    return audio_bytes

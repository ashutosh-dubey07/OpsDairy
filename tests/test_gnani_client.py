"""Mocked contract checks for the prepared Gnani REST client."""

import io
import unittest
import wave
from unittest.mock import Mock, patch

import requests

from opsdiary import gnani_client


def make_wav(seconds: int, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * (seconds * sample_rate))
    return buffer.getvalue()


class GnaniClientContractTests(unittest.TestCase):
    @patch("opsdiary.gnani_client.requests.post")
    def test_prisma_v25_uses_documented_multipart_fields_and_default_model(self, post: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "success": True,
            "transcript": "checkout error",
            "model": "prisma-v2.5",
            "request_id": "mock-request",
        }
        post.return_value = response
        audio = make_wav(2)

        result = gnani_client.transcribe_prisma_v25(
            audio, "incident.wav", "audio/wav", "hi-IN", api_key="mock-key"
        )

        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], gnani_client.STT_URL)
        self.assertEqual(kwargs["headers"], {"X-API-Key-ID": "mock-key"})
        self.assertEqual(kwargs["data"], {"language_code": "hi-IN"})
        self.assertNotIn("model", kwargs["data"])
        uploaded = kwargs["files"]["audio_file"]
        self.assertEqual(uploaded[0], "incident.wav")
        self.assertEqual(uploaded[1].getvalue(), audio)
        self.assertEqual(uploaded[2], "audio/wav")
        self.assertEqual(result["transcript"], "checkout error")

    @patch("opsdiary.gnani_client.requests.post")
    def test_timbre_v25_uses_documented_json_and_returns_audio_bytes(self, post: Mock) -> None:
        response = Mock()
        response.content = make_wav(1, sample_rate=48000)
        response.headers = {"Content-Type": "audio/wav"}
        post.return_value = response

        audio = gnani_client.synthesize_timbre_v25(
            "Checkout mein latency hai.", api_key="mock-key"
        )

        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], gnani_client.TTS_URL)
        self.assertEqual(kwargs["headers"], {
            "X-API-Key-ID": "mock-key",
            "Content-Type": "application/json",
        })
        self.assertEqual(kwargs["json"], {
            "text": "Checkout mein latency hai.",
            "model": "timbre-v2.5",
            "voice": "Poorvi",
            "language": "hi-en",
            "audio_config": {
                "encoding": "linear_pcm",
                "container": "wav",
                "num_channels": 1,
                "sample_rate": 48000,
                "sample_width": 2,
            },
        })
        self.assertEqual(audio, response.content)

    @patch("opsdiary.gnani_client.requests.post")
    def test_timbre_repairs_streaming_wav_size_placeholders(self, post: Mock) -> None:
        response = Mock()
        streaming_wav = bytearray(make_wav(1, sample_rate=48000))
        streaming_wav[4:8] = (0xFFFFFFFF).to_bytes(4, "little")
        streaming_wav[40:44] = (0xFFFFFFFF).to_bytes(4, "little")
        response.content = bytes(streaming_wav)
        response.headers = {"Content-Type": "audio/wav"}
        post.return_value = response

        audio = gnani_client.synthesize_timbre_v25("Synthetic test", api_key="mock-key")

        self.assertEqual(int.from_bytes(audio[4:8], "little"), len(audio) - 8)
        self.assertEqual(int.from_bytes(audio[40:44], "little"), len(audio) - 44)
        self.assertEqual(gnani_client.wav_duration_seconds(audio), 1)

    @patch("opsdiary.gnani_client.requests.post")
    def test_timbre_rejects_non_wav_response(self, post: Mock) -> None:
        response = Mock()
        response.content = b'{"success":false}'
        response.headers = {"Content-Type": "application/json"}
        post.return_value = response

        with self.assertRaisesRegex(gnani_client.GnaniAPIError, "non-WAV response"):
            gnani_client.synthesize_timbre_v25("Synthetic test", api_key="mock-key")

    @patch("opsdiary.gnani_client.requests.post")
    def test_timbre_surfaces_bounded_provider_error_message(self, post: Mock) -> None:
        response = Mock()
        response.status_code = 400
        response.json.return_value = {
            "success": False,
            "message": "Invalid request: sample_rate must be one of the documented values",
        }
        response.raise_for_status.side_effect = requests.HTTPError(
            "HTTP 400", response=response
        )
        post.return_value = response

        with self.assertRaisesRegex(
            gnani_client.GnaniAPIError, "sample_rate must be one of the documented values"
        ):
            gnani_client.synthesize_timbre_v25("Synthetic test", api_key="mock-key")

    @patch("opsdiary.gnani_client.requests.post")
    def test_prisma_surfaces_documented_error_shape(self, post: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "success": False,
            "error": {"type": "INVALID_LANGUAGE", "message": "Unsupported language"},
        }
        post.return_value = response

        with self.assertRaisesRegex(gnani_client.GnaniAPIError, "Unsupported language"):
            gnani_client.transcribe_prisma_v25(make_wav(1), api_key="mock-key")
        post.assert_called_once()

    @patch("opsdiary.gnani_client.requests.post")
    def test_timbre_rejects_malformed_wav_response(self, post: Mock) -> None:
        response = Mock()
        response.content = b"not-a-wav"
        response.headers = {"Content-Type": "audio/wav"}
        post.return_value = response

        with self.assertRaisesRegex(gnani_client.GnaniAPIError, "invalid WAV response"):
            gnani_client.synthesize_timbre_v25("Synthetic test", api_key="mock-key")

    @patch("opsdiary.gnani_client.requests.post")
    def test_timbre_accepts_vendor_wave_content_type(self, post: Mock) -> None:
        response = Mock()
        response.content = make_wav(1, sample_rate=48000)
        response.headers = {"Content-Type": "audio/vnd.wave;codec=1"}
        post.return_value = response

        audio = gnani_client.synthesize_timbre_v25("Synthetic test", api_key="mock-key")
        self.assertEqual(audio, response.content)

    @patch("opsdiary.gnani_client.requests.post")
    def test_timbre_rejects_empty_audio_response(self, post: Mock) -> None:
        response = Mock()
        response.content = b""
        response.headers = {"Content-Type": "audio/wav"}
        post.return_value = response

        with self.assertRaisesRegex(gnani_client.GnaniAPIError, "empty audio response"):
            gnani_client.synthesize_timbre_v25("Synthetic test", api_key="mock-key")

    @patch("opsdiary.gnani_client.requests.post")
    def test_timbre_accepts_supported_wav_sample_rate(self, post: Mock) -> None:
        response = Mock()
        response.content = make_wav(1, sample_rate=16000)
        response.headers = {"Content-Type": "audio/wav"}
        post.return_value = response

        audio = gnani_client.synthesize_timbre_v25("Synthetic test", api_key="mock-key")
        self.assertEqual(audio, response.content)

    @patch("opsdiary.gnani_client.requests.post")
    def test_timbre_rejects_unsupported_wav_sample_rate(self, post: Mock) -> None:
        response = Mock()
        response.content = make_wav(1, sample_rate=2)
        response.headers = {"Content-Type": "audio/wav"}
        post.return_value = response

        with self.assertRaisesRegex(gnani_client.GnaniAPIError, "sample_rate=2"):
            gnani_client.synthesize_timbre_v25("Synthetic test", api_key="mock-key")

    @patch("opsdiary.gnani_client.requests.post")
    def test_timbre_rejects_frame_count_larger_than_wav_payload(self, post: Mock) -> None:
        response = Mock()
        malformed_wav = bytearray(make_wav(1, sample_rate=48000))
        malformed_wav[40:44] = (10_000_000).to_bytes(4, "little")
        response.content = bytes(malformed_wav)
        response.headers = {"Content-Type": "audio/wav"}
        post.return_value = response

        with self.assertRaisesRegex(gnani_client.GnaniAPIError, "expected_audio_bytes="):
            gnani_client.synthesize_timbre_v25("Synthetic test", api_key="mock-key")

    @patch("opsdiary.gnani_client.requests.post")
    @patch("opsdiary.gnani_client.GNANI_API_KEY", "")
    def test_missing_key_fails_before_any_request(self, post: Mock) -> None:
        with self.assertRaises(gnani_client.GnaniConfigurationError):
            gnani_client.transcribe_prisma_v25(make_wav(1))
        post.assert_not_called()

    def test_wav_duration_limit_is_enforced_before_request(self) -> None:
        self.assertEqual(gnani_client.validate_wav_duration(make_wav(30)), 30)
        with self.assertRaisesRegex(ValueError, "maximum is 30 seconds"):
            gnani_client.validate_wav_duration(make_wav(31))

    @patch("opsdiary.gnani_client.requests.post")
    def test_prisma_rejects_audio_over_30_seconds_before_request(self, post: Mock) -> None:
        with self.assertRaisesRegex(ValueError, "maximum is 30 seconds"):
            gnani_client.transcribe_prisma_v25(make_wav(31), api_key="mock-key")
        post.assert_not_called()

    @patch("opsdiary.gnani_client.requests.post")
    def test_audio_size_limit_is_enforced_before_wav_parsing_or_request(self, post: Mock) -> None:
        oversized = b"x" * (gnani_client.MAX_STT_AUDIO_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "10 MB limit"):
            gnani_client.transcribe_prisma_v25(oversized, api_key="mock-key")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""Mocked contract checks for the prepared Gnani REST client."""

import io
import unittest
import wave
from unittest.mock import Mock, patch

from opsdiary import gnani_client


def make_wav(seconds: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * (seconds * 16000))
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
        response.content = make_wav(1)
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
    def test_timbre_rejects_non_wav_response(self, post: Mock) -> None:
        response = Mock()
        response.content = b'{"success":false}'
        response.headers = {"Content-Type": "application/json"}
        post.return_value = response

        with self.assertRaisesRegex(gnani_client.GnaniAPIError, "non-WAV response"):
            gnani_client.synthesize_timbre_v25("Synthetic test", api_key="mock-key")

    @patch("opsdiary.gnani_client.requests.post")
    def test_timbre_rejects_malformed_wav_response(self, post: Mock) -> None:
        response = Mock()
        response.content = b"not-a-wav"
        response.headers = {"Content-Type": "audio/wav"}
        post.return_value = response

        with self.assertRaisesRegex(gnani_client.GnaniAPIError, "invalid WAV response"):
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


if __name__ == "__main__":
    unittest.main()

import io
import json
import logging
import unittest

from opsdiary.observability import observed_stage, trace_scope


class ObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stream = io.StringIO()
        self.logger = logging.getLogger("opsdiary.events")
        self.handler = logging.StreamHandler(self.stream)
        self.previous_level = self.logger.level
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.INFO)

    def tearDown(self) -> None:
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self.previous_level)
        self.handler.close()

    def test_stage_log_has_trace_and_latency_without_input_content(self) -> None:
        with trace_scope("trace-safe-1"):
            with observed_stage("incident.extract", metadata={"secret": "transcript text"}):
                pass

        line = self.stream.getvalue()
        event = json.loads(line)
        self.assertEqual(event["trace_id"], "trace-safe-1")
        self.assertEqual(event["stage"], "incident.extract")
        self.assertEqual(event["outcome"], "ok")
        self.assertGreaterEqual(event["duration_ms"], 0)
        self.assertNotIn("transcript text", line)
        self.assertNotIn("secret", event)

    def test_failure_log_records_type_without_error_message(self) -> None:
        with trace_scope("trace-safe-2"):
            with self.assertRaisesRegex(ValueError, "private text"):
                with observed_stage("voice.stt", provider="synthetic-provider"):
                    raise ValueError("private text")

        event = json.loads(self.stream.getvalue())
        self.assertEqual(event["outcome"], "error")
        self.assertEqual(event["error_type"], "ValueError")
        self.assertNotIn("private text", self.stream.getvalue())


if __name__ == "__main__":
    unittest.main()

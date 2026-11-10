import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opsdiary.assistant import answer_question
from opsdiary.auth import create_initial_user
from opsdiary.storage import (
    init_db,
    list_assistant_interactions,
    save_assistant_interaction,
)


class DeterministicAssistantTests(unittest.TestCase):
    def test_greetings_and_credit_questions_use_fixed_answers(self) -> None:
        with patch("opsdiary.assistant.retrieve_incidents") as retrieve:
            greeting = answer_question("Hii!!!")
            credits = answer_question("Will this use Gnani credits?")

        self.assertEqual(greeting.intent, "greeting")
        self.assertEqual(greeting.source, "local-faq")
        self.assertIn("ready hai", greeting.answer)
        self.assertEqual(credits.intent, "credit_usage")
        self.assertIn("credit use zero", credits.answer)
        self.assertNotIn("Live mode", credits.answer)
        retrieve.assert_not_called()

    def test_incident_workflow_faq_describes_live_capture_and_review(self) -> None:
        reply = answer_question("How do I record an incident?")

        self.assertEqual(reply.intent, "incident_workflow")
        self.assertIn("synthetic Hinglish clip", reply.answer)
        self.assertIn("transcript review", reply.answer)
        self.assertNotIn("synthetic note", reply.answer)

    def test_unmatched_question_gets_explicit_local_search_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "opsdiary.sqlite3"
            init_db(db_path)
            reply = answer_question("teleporting unicorn telemetry", db_path)

        self.assertEqual(reply.intent, "incident_search_no_match")
        self.assertEqual(reply.source, "sqlite-fts5")
        self.assertEqual(reply.evidence, [])
        self.assertIn("Koi matching local incident record nahi mila", reply.answer)

    def test_incident_search_includes_ids_and_supporting_terms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "opsdiary.sqlite3"
            init_db(db_path)
            reply = answer_question("Checkout production 5xx payments fail", db_path)

        self.assertEqual(reply.intent, "incident_search")
        self.assertTrue(reply.evidence)
        self.assertTrue(any("SYN-1041" in item for item in reply.answer.splitlines()))
        self.assertTrue(all(item["matched_terms"] for item in reply.evidence))
        self.assertTrue(all(item["incident_id"].startswith("SYN-") for item in reply.evidence))

    def test_question_and_answer_are_persisted_and_scoped_to_actor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "opsdiary.sqlite3"
            init_db(db_path)
            create_initial_user("operator", "TestOnlyPass8!", db_path)
            question = "x'); DROP TABLE incidents; --"
            interaction_id = save_assistant_interaction(
                actor_username="OPERATOR",
                query=question,
                answer="Stored as plain user text; no SQL executed.",
                intent="incident_search_no_match",
                source="sqlite-fts5",
                evidence=[],
                trace_id="trace-test-001",
                db_path=db_path,
            )

            saved = list_assistant_interactions("operator", db_path=db_path)
            other_user = list_assistant_interactions("other_user", db_path=db_path)

        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["interaction_id"], interaction_id)
        self.assertEqual(saved[0]["query"], question)
        self.assertEqual(saved[0]["answer"], "Stored as plain user text; no SQL executed.")
        self.assertEqual(saved[0]["actor_username"], "operator")
        self.assertEqual(other_user, [])

    def test_storage_rejects_oversized_query(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "opsdiary.sqlite3"
            init_db(db_path)
            create_initial_user("operator", "TestOnlyPass8!", db_path)
            with self.assertRaisesRegex(ValueError, "2,000 characters"):
                save_assistant_interaction(
                    actor_username="operator",
                    query="x" * 2001,
                    answer="bounded response",
                    intent="help",
                    source="local-faq",
                    evidence=[],
                    trace_id="trace-test-002",
                    db_path=db_path,
                )


if __name__ == "__main__":
    unittest.main()

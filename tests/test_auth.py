import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from opsdiary import auth
from opsdiary.storage import connect, init_db


class LocalAuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "opsdiary.sqlite3"
        init_db(self.db_path)
        self.password = "correct horse battery staple phrase"
        auth.create_initial_user("Operator_01", self.password, self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_database_stores_argon2id_hash_not_plaintext(self) -> None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE username = ?", ("operator_01",)
            ).fetchone()
        self.assertTrue(row["password_hash"].startswith("$argon2id$"))
        self.assertNotEqual(row["password_hash"], self.password)
        with self.assertRaises(sqlite3.OperationalError):
            with connect(self.db_path) as conn:
                conn.execute("SELECT password FROM users").fetchone()

    def test_login_success_and_failures_have_non_enumerating_result(self) -> None:
        success = auth.authenticate("OPERATOR_01", self.password, self.db_path)
        wrong_password = auth.authenticate("operator_01", "not the passphrase", self.db_path)
        unknown_user = auth.authenticate("somebody_else", self.password, self.db_path)

        self.assertTrue(success.authenticated)
        self.assertEqual(success.username, "operator_01")
        self.assertEqual(success.auth_version, 1)
        self.assertEqual(wrong_password, auth.AuthResult(False))
        self.assertEqual(unknown_user, auth.AuthResult(False))

    def test_sql_injection_username_is_rejected_before_lookup(self) -> None:
        result = auth.authenticate("' OR 1=1 --", self.password, self.db_path)
        self.assertEqual(result, auth.AuthResult(False))
        self.assertEqual(auth.get_auth_version("operator_01", self.db_path), 1)

    def test_failed_login_throttle_and_password_reset_revoke_session_version(self) -> None:
        fixed_now = 1_800_000_000.0
        with patch("opsdiary.auth._now", return_value=fixed_now):
            for _ in range(auth.MAX_LOGIN_FAILURES):
                self.assertFalse(
                    auth.authenticate("operator_01", "wrong passphrase", self.db_path).authenticated
                )
            self.assertFalse(
                auth.authenticate("operator_01", self.password, self.db_path).authenticated
            )

        auth.reset_password("operator_01", "a new safe passphrase for OpsDiary", self.db_path)
        self.assertEqual(auth.get_auth_version("operator_01", self.db_path), 2)
        self.assertTrue(
            auth.authenticate(
                "operator_01", "a new safe passphrase for OpsDiary", self.db_path
            ).authenticated
        )
        self.assertFalse(auth.authenticate("operator_01", self.password, self.db_path).authenticated)

    def test_passphrase_minimum_is_checked_only_for_account_management(self) -> None:
        with self.assertRaises(auth.AuthError):
            auth.create_initial_user("second_user", "short", self.db_path)
        # Login still handles old or malformed stored credentials generically.
        self.assertEqual(auth.authenticate("operator_01", "short", self.db_path), auth.AuthResult(False))

    def test_create_initial_user_is_one_time_only(self) -> None:
        with self.assertRaisesRegex(auth.AuthError, "already exists"):
            auth.create_initial_user("second_user", "a second account passphrase", self.db_path)
        self.assertTrue(auth.users_exist(self.db_path))

    def test_schema_upgrade_preserves_seeded_incident_records(self) -> None:
        with connect(self.db_path) as conn:
            incident_count = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
            conn.execute("DROP TABLE auth_login_attempts")
            conn.execute("DROP TABLE users")
            conn.execute("PRAGMA user_version = 1")

        init_db(self.db_path)
        with connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0], incident_count)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
            tables = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        self.assertIn("users", tables)
        self.assertIn("auth_login_attempts", tables)


if __name__ == "__main__":
    unittest.main()

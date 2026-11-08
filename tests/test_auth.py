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
        self.recovery_code = auth.create_initial_user("Operator_01", self.password, self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_database_stores_argon2id_hash_not_plaintext(self) -> None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT password_hash, recovery_code_hash
                   FROM users WHERE username = ?""",
                ("operator_01",),
            ).fetchone()
        self.assertTrue(row["password_hash"].startswith("$argon2id$"))
        self.assertNotEqual(row["password_hash"], self.password)
        self.assertEqual(row["recovery_code_hash"], auth._recovery_digest(self.recovery_code))
        self.assertNotIn(self.recovery_code, row["recovery_code_hash"])
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

    def test_recovery_code_is_one_time_and_rotates_on_password_reset(self) -> None:
        new_password = "replacement account passphrase for OpsDiary"
        rotated_code = auth.recover_password(
            "operator_01", self.recovery_code, new_password, self.db_path
        )

        self.assertIsNotNone(rotated_code)
        self.assertFalse(auth.authenticate("operator_01", self.password, self.db_path).authenticated)
        self.assertTrue(auth.authenticate("operator_01", new_password, self.db_path).authenticated)
        self.assertIsNone(
            auth.recover_password(
                "operator_01", self.recovery_code, "another replacement passphrase", self.db_path
            )
        )
        second_rotated_code = auth.recover_password(
            "operator_01", rotated_code or "", "another replacement passphrase", self.db_path
        )
        self.assertIsNotNone(second_rotated_code)

        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT recovery_code_hash FROM users WHERE username = ?", ("operator_01",)
            ).fetchone()
        self.assertEqual(len(row["recovery_code_hash"]), 64)
        self.assertEqual(row["recovery_code_hash"], auth._recovery_digest(second_rotated_code or ""))

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
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 4)
            tables = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        self.assertIn("users", tables)
        self.assertIn("auth_login_attempts", tables)
        self.assertIn("assistant_interactions", tables)

    def test_version_two_account_migrates_without_losing_login(self) -> None:
        legacy_password = "legacy account passphrase for migration"
        legacy_hash = auth._HASHER.hash(legacy_password)
        with connect(self.db_path) as conn:
            conn.execute("DROP TABLE auth_login_attempts")
            conn.execute("DROP TABLE users")
            conn.execute(
                """CREATE TABLE users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    auth_version INTEGER NOT NULL DEFAULT 1 CHECK(auth_version >= 1)
                )"""
            )
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                ("legacy_user", legacy_hash, "2026-11-08T00:00:00+00:00"),
            )
            conn.execute("PRAGMA user_version = 2")

        init_db(self.db_path)
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT recovery_code_hash FROM users WHERE username = ?", ("legacy_user",)
            ).fetchone()
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 4)
        self.assertIsNone(row["recovery_code_hash"])
        self.assertTrue(auth.authenticate("legacy_user", legacy_password, self.db_path).authenticated)


if __name__ == "__main__":
    unittest.main()

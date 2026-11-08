"""Local, single-operator account management and authentication."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from getpass import getpass
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import (
    HashingError,
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

from opsdiary.settings import DATABASE_PATH
from opsdiary.storage import connect, init_db

USERNAME_PATTERN = re.compile(r"\A[a-zA-Z0-9][a-zA-Z0-9._-]{2,63}\Z")
MIN_PASSWORD_LENGTH = 15
MAX_PASSWORD_LENGTH = 1024
MAX_LOGIN_FAILURES = 5
FAILURE_WINDOW_SECONDS = 15 * 60
LOCKOUT_SECONDS = 15 * 60

# PasswordHasher uses Argon2id, a random per-password salt and the library's
# RFC 9106 low-memory profile. The pinned library version keeps this choice
# stable until the dependency is deliberately updated.
_HASHER = PasswordHasher()
_DUMMY_HASH: str | None = None


class AuthError(ValueError):
    """A safe-to-display local account setup error."""


@dataclass(frozen=True)
class AuthResult:
    authenticated: bool
    username: str | None = None
    auth_version: int | None = None


def normalize_username(username: str) -> str:
    if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
        raise AuthError("Username must be 3–64 characters: letters, digits, dot, dash or underscore.")
    return username.casefold()


def validate_password(password: str) -> None:
    if not isinstance(password, str):
        raise AuthError("Password is required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Use a passphrase with at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AuthError(f"Password must be no more than {MAX_PASSWORD_LENGTH} characters.")


def users_exist(db_path: Path | str = DATABASE_PATH) -> bool:
    with connect(db_path) as conn:
        return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def get_auth_version(username: str, db_path: Path | str = DATABASE_PATH) -> int | None:
    try:
        normalized = normalize_username(username)
    except AuthError:
        return None
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT auth_version FROM users WHERE username = ?", (normalized,)
        ).fetchone()
    return int(row["auth_version"]) if row else None


def create_initial_user(
    username: str,
    password: str,
    db_path: Path | str = DATABASE_PATH,
) -> None:
    """Create the first local account; there is intentionally no web signup."""
    normalized = normalize_username(username)
    validate_password(password)
    password_hash = _HASHER.hash(password)
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise AuthError("A local account already exists. Use reset-password to change it.")
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (normalized, password_hash, created_at),
            )
    except sqlite3.IntegrityError as exc:
        raise AuthError("Could not create the local account.") from exc


def reset_password(
    username: str,
    password: str,
    db_path: Path | str = DATABASE_PATH,
) -> None:
    """Reset the local password and invalidate active browser sessions."""
    normalized = normalize_username(username)
    validate_password(password)
    password_hash = _HASHER.hash(password)
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """UPDATE users
               SET password_hash = ?, auth_version = auth_version + 1
               WHERE username = ?""",
            (password_hash, normalized),
        )
        if cursor.rowcount != 1:
            raise AuthError("No local account matches that username.")
        conn.execute("DELETE FROM auth_login_attempts WHERE username = ?", (normalized,))


def _get_dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = _HASHER.hash("OpsDiary unknown-account timing guard")
    return _DUMMY_HASH


def _now() -> float:
    return time.time()


def _blocked_until(username: str, now: float, db_path: Path | str) -> float | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT blocked_until FROM auth_login_attempts WHERE username = ?",
            (username,),
        ).fetchone()
    if row and row["blocked_until"] is not None and float(row["blocked_until"]) > now:
        return float(row["blocked_until"])
    return None


def _record_failure(username: str, now: float, db_path: Path | str) -> None:
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT failure_count, window_started_at, blocked_until
               FROM auth_login_attempts WHERE username = ?""",
            (username,),
        ).fetchone()
        if row and row["blocked_until"] is not None and float(row["blocked_until"]) > now:
            return

        if not row or now - float(row["window_started_at"]) >= FAILURE_WINDOW_SECONDS:
            failure_count = 1
            window_started_at = now
        else:
            failure_count = int(row["failure_count"]) + 1
            window_started_at = float(row["window_started_at"])

        blocked_until = now + LOCKOUT_SECONDS if failure_count >= MAX_LOGIN_FAILURES else None
        conn.execute(
            """INSERT INTO auth_login_attempts
                   (username, failure_count, window_started_at, blocked_until)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(username) DO UPDATE SET
                   failure_count = excluded.failure_count,
                   window_started_at = excluded.window_started_at,
                   blocked_until = excluded.blocked_until""",
            (username, failure_count, window_started_at, blocked_until),
        )


def authenticate(
    username: str,
    password: str,
    db_path: Path | str = DATABASE_PATH,
) -> AuthResult:
    """Authenticate with a generic failure result and persistent throttling."""
    try:
        normalized = normalize_username(username)
    except AuthError:
        return AuthResult(False)

    now = _now()
    if _blocked_until(normalized, now, db_path) is not None:
        return AuthResult(False)

    with connect(db_path) as conn:
        user = conn.execute(
            """SELECT username, password_hash, auth_version
               FROM users WHERE username = ?""",
            (normalized,),
        ).fetchone()

    if not isinstance(password, str) or len(password) > MAX_PASSWORD_LENGTH:
        _record_failure(normalized, now, db_path)
        return AuthResult(False)

    stored_hash = user["password_hash"] if user else _get_dummy_hash()
    try:
        _HASHER.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError, HashingError):
        _record_failure(normalized, now, db_path)
        return AuthResult(False)

    if not user:
        _record_failure(normalized, now, db_path)
        return AuthResult(False)

    # Recheck inside a write transaction so a concurrent terminal password reset
    # cannot let an in-flight login authenticate against a stale hash.
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            """SELECT password_hash, auth_version
               FROM users WHERE username = ?""",
            (normalized,),
        ).fetchone()
        if (
            not current
            or current["password_hash"] != stored_hash
            or int(current["auth_version"]) != int(user["auth_version"])
        ):
            return AuthResult(False)
        if _HASHER.check_needs_rehash(stored_hash):
            conn.execute(
                """UPDATE users SET password_hash = ?
                   WHERE username = ? AND auth_version = ?""",
                (_HASHER.hash(password), normalized, int(user["auth_version"])),
            )
        conn.execute("DELETE FROM auth_login_attempts WHERE username = ?", (normalized,))

    return AuthResult(True, normalized, int(user["auth_version"]))


def _prompt_for_password() -> str:
    password = getpass("New passphrase (input hidden): ")
    confirmation = getpass("Confirm passphrase: ")
    if password != confirmation:
        raise AuthError("The passphrases do not match.")
    validate_password(password)
    return password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage OpsDiary's local operator account.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("create-user", help="Create the initial local account")
    subparsers.add_parser("reset-password", help="Reset the local account password")
    args = parser.parse_args(argv)

    try:
        init_db()
        username = input("Username (3–64 letters, digits, dot, dash or underscore): ").strip()
        password = _prompt_for_password()
        if args.command == "create-user":
            create_initial_user(username, password)
            print("Local account created. Restart or refresh OpsDiary to sign in.")
        else:
            reset_password(username, password)
            print("Password changed. Existing browser sessions will be signed out.")
    except (AuthError, OSError, sqlite3.Error) as exc:
        print(f"Account setup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

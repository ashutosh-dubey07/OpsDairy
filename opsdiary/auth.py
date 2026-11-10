"""Local, single-operator account management and authentication."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import re
import secrets
import sqlite3
import sys
import time
import unicodedata
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
MIN_PASSWORD_LENGTH = 8
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
    unmet = [label for label, satisfied in password_requirement_status(password) if not satisfied]
    if unmet:
        raise AuthError("Password does not meet all requirements: " + "; ".join(unmet) + ".")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AuthError(f"Password must be no more than {MAX_PASSWORD_LENGTH} characters.")


def password_requirement_status(password: str) -> list[tuple[str, bool]]:
    """Return the account password rules in display order with live status."""
    value = password if isinstance(password, str) else ""
    categories = [unicodedata.category(character) for character in value]
    return [
        (f"At least {MIN_PASSWORD_LENGTH} characters", len(value) >= MIN_PASSWORD_LENGTH),
        ("One uppercase letter", "Lu" in categories),
        ("One lowercase letter", "Ll" in categories),
        ("One number", "Nd" in categories),
        (
            "One symbol",
            any(
                category[0] not in {"L", "N"} and not character.isspace()
                for character, category in zip(value, categories, strict=True)
            ),
        ),
    ]


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
) -> str:
    """Create the first local account and return its one-time recovery code."""
    normalized = normalize_username(username)
    validate_password(password)
    password_hash = _HASHER.hash(password)
    recovery_code = _new_recovery_code()
    recovery_code_hash = _recovery_digest(recovery_code)
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise AuthError("A local account already exists. Use reset-password to change it.")
            conn.execute(
                """INSERT INTO users
                   (username, password_hash, recovery_code_hash, created_at)
                   VALUES (?, ?, ?, ?)""",
                (normalized, password_hash, recovery_code_hash, created_at),
            )
    except sqlite3.IntegrityError as exc:
        raise AuthError("Could not create the local account.") from exc
    return recovery_code


def reset_password(
    username: str,
    password: str,
    db_path: Path | str = DATABASE_PATH,
) -> str:
    """Reset the local password and invalidate active browser sessions."""
    normalized = normalize_username(username)
    validate_password(password)
    password_hash = _HASHER.hash(password)
    recovery_code = _new_recovery_code()
    recovery_code_hash = _recovery_digest(recovery_code)
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """UPDATE users
               SET password_hash = ?, recovery_code_hash = ?, auth_version = auth_version + 1
               WHERE username = ?""",
            (password_hash, recovery_code_hash, normalized),
        )
        if cursor.rowcount != 1:
            raise AuthError("No local account matches that username.")
        conn.execute(
            "DELETE FROM auth_login_attempts WHERE username IN (?, ?)",
            (normalized, f"recovery:{normalized}"),
        )
    return recovery_code


def _new_recovery_code() -> str:
    """Generate a 256-bit offline recovery code for one-time use."""
    return secrets.token_urlsafe(32)


def _recovery_digest(recovery_code: str) -> str:
    return hashlib.sha256(recovery_code.strip().encode("utf-8")).hexdigest()


def recover_password(
    username: str,
    recovery_code: str,
    new_password: str,
    db_path: Path | str = DATABASE_PATH,
) -> str | None:
    """Redeem a one-time offline code, rotate it, and revoke all sessions."""
    try:
        normalized = normalize_username(username)
    except AuthError:
        return None
    validate_password(new_password)

    attempt_key = f"recovery:{normalized}"
    now = _now()
    if _blocked_until(attempt_key, now, db_path) is not None:
        return None

    if not isinstance(recovery_code, str) or len(recovery_code) > 256:
        _record_failure(attempt_key, now, db_path)
        return None
    provided_digest = _recovery_digest(recovery_code)

    with connect(db_path) as conn:
        user = conn.execute(
            "SELECT recovery_code_hash FROM users WHERE username = ?", (normalized,)
        ).fetchone()

    stored_digest = user["recovery_code_hash"] if user else None
    expected_digest = stored_digest or ("0" * 64)
    if not hmac.compare_digest(expected_digest, provided_digest):
        _record_failure(attempt_key, now, db_path)
        return None

    new_password_hash = _HASHER.hash(new_password)
    rotated_code = _new_recovery_code()
    rotated_digest = _recovery_digest(rotated_code)
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT recovery_code_hash FROM users WHERE username = ?", (normalized,)
        ).fetchone()
        if not current or current["recovery_code_hash"] != stored_digest:
            return None
        conn.execute(
            """UPDATE users
               SET password_hash = ?, recovery_code_hash = ?, auth_version = auth_version + 1
               WHERE username = ? AND recovery_code_hash = ?""",
            (new_password_hash, rotated_digest, normalized, stored_digest),
        )
        conn.execute(
            "DELETE FROM auth_login_attempts WHERE username IN (?, ?)",
            (normalized, attempt_key),
        )
    return rotated_code


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
    password = getpass("New password (input hidden): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise AuthError("The passwords do not match.")
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
            recovery_code = create_initial_user(username, password)
            print("Local account created. Save this one-time recovery code offline:")
            print(recovery_code)
        else:
            recovery_code = reset_password(username, password)
            print("Password changed. Existing browser sessions were signed out.")
            print("Save this new one-time recovery code offline:")
            print(recovery_code)
    except (AuthError, OSError, sqlite3.Error) as exc:
        print(f"Account setup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
